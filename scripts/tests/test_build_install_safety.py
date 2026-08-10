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
            text.index('scripts/atomic_replace_app.py" "$STAGED_APP" "$APP"'),
        )

    def test_replacement_delegates_to_transaction_helper_and_preserves_failures(self) -> None:
        text = SCRIPT.read_text()
        self.assertIn('REPLACEMENT_STARTED=1', text)
        self.assertIn('scripts/atomic_replace_app.py" "$STAGED_APP" "$APP"', text)
        self.assertIn('KEEP_STAGE=1', text)
        self.assertIn('trap \'preserve_on_failure $?\' ERR', text)
        self.assertIn("trap 'preserve_on_failure 130' INT", text)
        self.assertIn("trap 'preserve_on_failure 143' TERM", text)
        self.assertIn("trap - ERR INT TERM", text)

    def test_staging_is_a_private_sibling_of_absolute_destination(self) -> None:
        text = SCRIPT.read_text()
        self.assertIn("umask 077", text)
        self.assertIn('APP_PARENT="$(dirname "$APP")"', text)
        self.assertIn('bundle destination must be absolute', text)
        self.assertIn('STAGE_ROOT="$(mktemp -d "$APP_PARENT/.Clicky.install.XXXXXX")"', text)
        self.assertIn('chmod 700 "$STAGE_ROOT"', text)


if __name__ == "__main__":
    unittest.main()
