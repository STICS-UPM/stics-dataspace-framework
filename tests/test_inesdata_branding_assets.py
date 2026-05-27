import base64
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import click

from deployers.inesdata import bootstrap


class InesdataBrandingAssetsTests(unittest.TestCase):
    def test_branding_assets_are_loaded_from_configured_identity_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            identity = root / "identity"
            identity.mkdir()
            (identity / "custom-logo.svg").write_text("<svg></svg>", encoding="utf-8")
            (identity / "footer.png").write_bytes(b"footer")

            config = {
                "INESDATA_BRAND_ASSETS_DIR": "identity",
                "INESDATA_BRAND_LOGO_FILES": "custom-logo.svg",
                "INESDATA_BRAND_FOOTER_LOGO_FILES": "footer.png",
                "INESDATA_BRAND_POWERED_BY_LOGO_FILES": "powered.svg",
            }
            (identity / "powered.svg").write_text("<svg>powered</svg>", encoding="utf-8")

            with mock.patch.object(bootstrap, "ROOT_DIR", str(root)):
                keys = bootstrap._inesdata_branding_template_keys(config, "connector")
                assets = {
                    asset["name"]: asset["contentBase64"]
                    for asset in bootstrap._load_branding_assets(config, keys["inesdata_brand_asset_files"])
                }

        self.assertEqual(
            keys["inesdata_brand_logo_urls"],
            "/inesdata-connector-interface/assets/branding/custom-logo.svg",
        )
        self.assertEqual(
            keys["inesdata_brand_footer_logo_urls"],
            "/inesdata-connector-interface/assets/branding/footer.png",
        )
        self.assertEqual(
            keys["inesdata_brand_powered_by_logo_urls"],
            "/inesdata-connector-interface/assets/branding/powered.svg",
        )
        self.assertEqual(
            keys["inesdata_brand_asset_files"],
            ["custom-logo.svg", "footer.png", "powered.svg"],
        )
        self.assertEqual(keys["inesdata_brand_assets"], [])
        self.assertEqual(assets["custom-logo.svg"], base64.b64encode(b"<svg></svg>").decode("ascii"))
        self.assertEqual(assets["footer.png"], base64.b64encode(b"footer").decode("ascii"))
        self.assertEqual(assets["powered.svg"], base64.b64encode(b"<svg>powered</svg>").decode("ascii"))

    def test_explicit_branding_urls_override_derived_urls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            identity = root / "identity"
            identity.mkdir()
            (identity / "custom-logo.svg").write_text("<svg></svg>", encoding="utf-8")

            config = {
                "INESDATA_BRAND_ASSETS_DIR": "identity",
                "INESDATA_BRAND_LOGO_FILES": "custom-logo.svg",
                "INESDATA_BRAND_LOGO_URLS": "https://example.org/logo.svg",
            }

            with mock.patch.object(bootstrap, "ROOT_DIR", str(root)):
                keys = bootstrap._inesdata_branding_template_keys(config, "portal")

        self.assertEqual(keys["inesdata_brand_logo_urls"], "https://example.org/logo.svg")
        self.assertEqual(keys["inesdata_brand_asset_base_url"], "/assets/branding")

    def test_branding_assets_reject_path_traversal(self):
        config = {
            "INESDATA_BRAND_ASSETS_DIR": "identity",
            "INESDATA_BRAND_LOGO_FILES": "../secret.svg",
        }

        with self.assertRaises(click.ClickException):
            bootstrap._inesdata_branding_template_keys(config, "connector")


if __name__ == "__main__":
    unittest.main()
