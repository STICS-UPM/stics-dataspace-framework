from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "identity"


class IdentityAssetsTests(unittest.TestCase):
    def test_identity_assets_use_stable_public_filenames(self):
        expected = {
            "README.md",
            "branding.config.example",
            "pionera-logo.svg",
            "inesdta.png",
            "funding-logos.png",
            "oeg.png",
        }

        self.assertTrue(IDENTITY.is_dir())
        existing = {path.name for path in IDENTITY.iterdir() if path.is_file()}
        self.assertTrue(expected.issubset(existing))

    def test_identity_assets_do_not_include_local_metadata(self):
        names = [path.name for path in IDENTITY.iterdir() if path.is_file()]

        self.assertFalse(any("Zone.Identifier" in name for name in names))


if __name__ == "__main__":
    unittest.main()
