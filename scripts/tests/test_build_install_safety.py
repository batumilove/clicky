import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build-and-install-local.sh"


class AtomicInstallContractTests(unittest.TestCase):
    def test_installed_bundle_is_not_removed_before_verified_stage_exists(self) -> None:
        text = SCRIPT.read_text()
        self.assertNotIn('rm -rf "$APP"\nmkdir -p "$APP/Contents', text)
        self.assertIn('STAGED_APP="$STAGE_ROOT/Clicky.app"', text)
        self.assertIn('codesign --verify --deep --strict --verbose=2 "$STAGED_APP"', text)
        self.assertLess(
            text.index('codesign --verify --deep --strict --verbose=2 "$STAGED_APP"'),
            text.index('mv "$STAGED_APP" "$APP"'),
        )

    def test_replacement_preserves_and_restores_previous_bundle_on_failure(self) -> None:
        text = SCRIPT.read_text()
        self.assertIn('BACKUP_APP="$STAGE_ROOT/Clicky.previous.app"', text)
        self.assertIn('atomic_swap "$STAGED_APP" "$APP"', text)
        self.assertIn('mv "$STAGED_APP" "$BACKUP_APP"', text)
        self.assertIn('atomic_swap "$BACKUP_APP" "$APP"', text)
        self.assertIn("trap 'rollback $?' ERR", text)
        self.assertIn("trap 'rollback 130' INT", text)
        self.assertIn("trap 'rollback 143' TERM", text)
        self.assertIn("trap - ERR INT TERM", text)

    def test_staging_and_backup_are_private_siblings_of_destination(self) -> None:
        text = SCRIPT.read_text()
        self.assertIn("umask 077", text)
        self.assertIn('APP_PARENT="$(dirname "$APP")"', text)
        self.assertIn('STAGE_ROOT="$(mktemp -d "$APP_PARENT/.Clicky.install.XXXXXX")"', text)
        self.assertIn('chmod 700 "$STAGE_ROOT"', text)


if __name__ == "__main__":
    unittest.main()
