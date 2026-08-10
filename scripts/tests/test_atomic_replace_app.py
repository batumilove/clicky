import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import atomic_replace_app


class AtomicReplaceAppTests(unittest.TestCase):
    def make_bundle(self, parent: Path, name: str, marker: str) -> Path:
        bundle = parent / name
        bundle.mkdir()
        (bundle / "marker").write_text(marker)
        return bundle

    def test_success_swaps_verified_new_bundle_and_preserves_old_at_stage(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            parent = Path(tmp)
            staged = self.make_bundle(parent, "staged.app", "new")
            destination = self.make_bundle(parent, "Clicky.app", "old")

            atomic_replace_app.replace_app(
                staged,
                destination,
                verify=lambda app: self.assertEqual((app / "marker").read_text(), "new"),
            )

            self.assertEqual((destination / "marker").read_text(), "new")
            self.assertEqual((staged / "marker").read_text(), "old")

    def test_verification_failure_restores_previous_bundle(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            parent = Path(tmp)
            staged = self.make_bundle(parent, "staged.app", "new")
            destination = self.make_bundle(parent, "Clicky.app", "old")

            with self.assertRaisesRegex(RuntimeError, "verify failed"):
                atomic_replace_app.replace_app(
                    staged,
                    destination,
                    verify=lambda _app: (_ for _ in ()).throw(RuntimeError("verify failed")),
                )

            self.assertEqual((destination / "marker").read_text(), "old")
            self.assertEqual((staged / "marker").read_text(), "new")

    def test_failed_rollback_preserves_previous_bundle_at_stage(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            parent = Path(tmp)
            staged = self.make_bundle(parent, "staged.app", "new")
            destination = self.make_bundle(parent, "Clicky.app", "old")
            real_swap = atomic_replace_app.atomic_swap
            calls = 0

            def fail_second_swap(left: Path, right: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("rollback swap failed")
                real_swap(left, right)

            with mock.patch.object(atomic_replace_app, "atomic_swap", side_effect=fail_second_swap):
                with self.assertRaises(atomic_replace_app.RollbackFailed) as caught:
                    atomic_replace_app.replace_app(
                        staged,
                        destination,
                        verify=lambda _app: (_ for _ in ()).throw(RuntimeError("verify failed")),
                    )

            self.assertIn(str(staged), str(caught.exception))
            self.assertEqual((staged / "marker").read_text(), "old")
            self.assertEqual((destination / "marker").read_text(), "new")

    def test_signal_during_verification_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            parent = Path(tmp)
            staged = self.make_bundle(parent, "staged.app", "new")
            destination = self.make_bundle(parent, "Clicky.app", "old")

            def interrupt(_app: Path) -> None:
                os.kill(os.getpid(), signal.SIGTERM)

            with self.assertRaises(atomic_replace_app.ReplaceInterrupted):
                atomic_replace_app.replace_app(staged, destination, verify=interrupt)

            self.assertEqual((destination / "marker").read_text(), "old")
            self.assertEqual((staged / "marker").read_text(), "new")

    def test_rejects_relative_destination(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute"):
            atomic_replace_app.replace_app(Path("staged.app"), Path("Clicky.app"), verify=lambda _app: None)

    def test_rejects_symlink_destination(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            parent = Path(tmp)
            staged = self.make_bundle(parent, "staged.app", "new")
            target = self.make_bundle(parent, "target.app", "old")
            destination = parent / "Clicky.app"
            destination.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                atomic_replace_app.replace_app(staged, destination, verify=lambda _app: None)


if __name__ == "__main__":
    unittest.main()
