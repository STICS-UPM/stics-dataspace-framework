from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InesdataBrandingConfigTests(unittest.TestCase):
    def test_deployer_example_declares_branding_keys_without_secret_values(self):
        text = (ROOT / "identity/branding.config.example").read_text(encoding="utf-8")

        for key in (
            "INESDATA_BRAND_NAME=PIONERA",
            "INESDATA_BRAND_SHOW_MENU_TEXT=false",
            "INESDATA_BRAND_THEME=theme-1",
            "INESDATA_BRAND_PRIMARY_COLOR=#025B77",
            "INESDATA_BRAND_SECONDARY_COLOR=#2FA0B5",
            "INESDATA_BRAND_ASSETS_DIR=identity",
            "INESDATA_BRAND_LOGO_FILES=pionera-logo.svg",
            "INESDATA_BRAND_LOGO_URLS=",
            "INESDATA_BRAND_FOOTER_LOGO_FILES=pionera-logo.svg,funding-logos.png",
            "INESDATA_BRAND_FOOTER_LOGO_URLS=",
            "INESDATA_BRAND_FOOTER_TEXT=",
            "INESDATA_BRAND_POWERED_BY_TEXT=Powered by:",
            "INESDATA_BRAND_POWERED_BY_LOGO_FILES=inesdata-logo.svg",
            "INESDATA_BRAND_POWERED_BY_LOGO_URLS=",
            "INESDATA_BRAND_CONNECTOR_ASSET_BASE_URL=/inesdata-connector-interface/assets/branding",
            "INESDATA_BRAND_PORTAL_ASSET_BASE_URL=/assets/branding",
            "INESDATA_LOCAL_STORE_LABEL=LocalStore",
        ):
            self.assertIn(key, text)

        self.assertNotIn("password", text.lower())
        self.assertNotIn("token=", text.lower())

    def test_connector_interface_receives_branding_environment(self):
        deployment = (
            ROOT
            / "deployers/inesdata/connector/templates/connector-interface-deployment.yaml"
        ).read_text(encoding="utf-8")
        values = (ROOT / "deployers/inesdata/connector/values.yaml.tpl").read_text(
            encoding="utf-8"
        )

        for key in (
            "APP_THEME",
            "APP_BRAND_NAME",
            "APP_PRIMARY_COLOR",
            "APP_SECONDARY_COLOR",
            "APP_SHOW_MENU_TEXT",
            "APP_BRANDING_ASSET_BASE_URL",
            "APP_LOGO_FILES",
            "APP_LOGO_URLS",
            "APP_FOOTER_LOGO_FILES",
            "APP_FOOTER_LOGO_URLS",
            "APP_POWERED_BY_TEXT",
            "APP_POWERED_BY_LOGO_FILES",
            "APP_POWERED_BY_LOGO_URLS",
            "APP_FOOTER_TEXT",
            "APP_LOCAL_STORE_LABEL",
        ):
            self.assertIn(key, deployment)
        self.assertIn("connectorInterface:", values)
        self.assertIn("branding:", values)
        self.assertIn("showMenuText", values)
        self.assertIn("localStoreLabel", values)
        self.assertIn("assetsConfigMapName", values)
        self.assertIn("assets:", values)

    def test_public_portal_receives_branding_environment(self):
        configmap = (
            ROOT
            / "deployers/inesdata/dataspace/public-portal/templates/public-portal-frontend-configmap.yaml"
        ).read_text(encoding="utf-8")
        values = (
            ROOT / "deployers/inesdata/dataspace/public-portal/values.yaml.tpl"
        ).read_text(encoding="utf-8")

        for key in (
            "APP_THEME",
            "APP_BRAND_NAME",
            "APP_PRIMARY_COLOR",
            "APP_SECONDARY_COLOR",
            "APP_SHOW_MENU_TEXT",
            "APP_BRANDING_ASSET_BASE_URL",
            "APP_LOGO_FILES",
            "APP_LOGO_URLS",
            "APP_FOOTER_LOGO_FILES",
            "APP_FOOTER_LOGO_URLS",
            "APP_POWERED_BY_TEXT",
            "APP_POWERED_BY_LOGO_FILES",
            "APP_POWERED_BY_LOGO_URLS",
            "APP_FOOTER_TEXT",
        ):
            self.assertIn(key, configmap)
        self.assertIn("frontend:", values)
        self.assertIn("branding:", values)
        self.assertIn("showMenuText", values)
        self.assertIn("assets:", values)


if __name__ == "__main__":
    unittest.main()
