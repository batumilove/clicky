#!/usr/bin/env python3
"""Atomically replace a verified Clicky app bundle with rollback."""

from __future__ import annotations

import argparse
import ctypes
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional

AT_FDCWD = -2
RENAME_SWAP = 0x00000002
_SIGNAL_SET = {signal.SIGINT, signal.SIGTERM}


class ReplaceInterrupted(RuntimeError):
    """Replacement was interrupted and rolled back."""


class RollbackFailed(RuntimeError):
    """Replacement failed and the preserved prior bundle could not be restored."""


def atomic_swap(left: Path, right: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameatx_np = libc.renameatx_np
    renameatx_np.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameatx_np.restype = ctypes.c_int
    if renameatx_np(
        AT_FDCWD,
        os.fsencode(left),
        AT_FDCWD,
        os.fsencode(right),
        RENAME_SWAP,
    ) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _existing_components(path: Path) -> Iterable[Path]:
    current = Path(path.anchor)
    yield current
    for part in path.parts[1:]:
        current /= part
        if not os.path.lexists(current):
            break
        yield current


def _validate_path(path: Path, *, must_exist: bool) -> None:
    if not path.is_absolute():
        raise ValueError(f"bundle path must be absolute: {path}")
    for component in _existing_components(path):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"bundle path contains symlink: {component}")
    parent_info = path.parent.lstat()
    if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid():
        raise ValueError(f"bundle parent is not a current-uid-owned directory: {path.parent}")
    if must_exist:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"bundle path is not a directory: {path}")
        if info.st_uid != os.getuid():
            raise ValueError(f"bundle path is not owned by current uid: {path}")
    elif os.path.lexists(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"destination is not a directory: {path}")
        if info.st_uid != os.getuid():
            raise ValueError(f"destination is not owned by current uid: {path}")


def _fsync_directories(*paths: Path) -> None:
    for path in {item.parent for item in paths}:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def verify_clicky(app: Path) -> None:
    subprocess.run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    bundle_id = subprocess.check_output(
        [
            "/usr/libexec/PlistBuddy",
            "-c",
            "Print :CFBundleIdentifier",
            str(app / "Contents" / "Info.plist"),
        ],
        text=True,
    ).strip()
    if bundle_id != "so.clicky.gpt55.local":
        raise RuntimeError(f"unexpected Clicky bundle identifier: {bundle_id!r}")


def replace_app(
    staged: Path,
    destination: Path,
    *,
    verify: Callable[[Path], None] = verify_clicky,
) -> None:
    staged = Path(staged)
    destination = Path(destination)
    _validate_path(staged, must_exist=True)
    _validate_path(destination, must_exist=False)
    if staged == destination:
        raise ValueError("staged and destination paths must differ")
    if staged.stat().st_dev != destination.parent.stat().st_dev:
        raise ValueError("staged and destination bundles must be on the same filesystem")

    previous_handlers = {
        sig: signal.getsignal(sig)
        for sig in _SIGNAL_SET
    }

    def interrupt(signum: int, _frame: object) -> None:
        raise ReplaceInterrupted(f"received signal {signum}")

    for sig in _SIGNAL_SET:
        signal.signal(sig, interrupt)

    swapped = False
    installed_fresh = False
    mask: Optional[Iterable[int]] = None
    try:
        try:
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, _SIGNAL_SET)
            if os.path.lexists(destination):
                atomic_swap(staged, destination)
                swapped = True
            else:
                os.rename(staged, destination)
                installed_fresh = True
            _fsync_directories(staged, destination)
            restore_mask = mask
            mask = None
            signal.pthread_sigmask(signal.SIG_SETMASK, restore_mask)

            verify(destination)
        except BaseException as original:
            if mask is None:
                mask = signal.pthread_sigmask(signal.SIG_BLOCK, _SIGNAL_SET)
            rollback_failure: Optional[RollbackFailed] = None
            rollback_restored = False
            try:
                if swapped:
                    try:
                        atomic_swap(staged, destination)
                        rollback_restored = True
                    except BaseException as rollback_error:
                        rollback_failure = RollbackFailed(
                            "rollback swap failed; previous bundle is preserved at "
                            f"{staged} and replacement remains at {destination}: {rollback_error}"
                        )
                elif installed_fresh and os.path.lexists(destination):
                    try:
                        os.rename(destination, staged)
                        rollback_restored = True
                    except BaseException as rollback_error:
                        rollback_failure = RollbackFailed(
                            "fresh-install rollback failed; replacement may remain at "
                            f"{destination}: {rollback_error}"
                        )

                if rollback_failure is None:
                    try:
                        _fsync_directories(staged, destination)
                    except BaseException as durability_error:
                        if swapped and rollback_restored:
                            rollback_failure = RollbackFailed(
                                "previous bundle was restored at destination and replacement "
                                f"preserved at {staged}, but rollback durability sync failed: "
                                f"{durability_error}"
                            )
                        elif installed_fresh and rollback_restored:
                            rollback_failure = RollbackFailed(
                                "fresh-install replacement was moved back to staging, but "
                                f"rollback durability sync failed: {durability_error}"
                            )
                        else:
                            rollback_failure = RollbackFailed(
                                f"rollback durability sync failed: {durability_error}"
                            )
            finally:
                if mask is not None:
                    restore_mask = mask
                    mask = None
                    try:
                        signal.pthread_sigmask(signal.SIG_SETMASK, restore_mask)
                    except ReplaceInterrupted:
                        if rollback_failure is None:
                            raise
            if rollback_failure is not None:
                raise rollback_failure from original
            raise
    finally:
        try:
            if mask is not None:
                restore_mask = mask
                mask = None
                signal.pthread_sigmask(signal.SIG_SETMASK, restore_mask)
        finally:
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("staged", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        replace_app(args.staged, args.destination)
    except BaseException as error:
        print(f"atomic Clicky replacement failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
