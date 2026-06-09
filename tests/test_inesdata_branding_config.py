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
            "INESDATA_BRAND_FOOTER_LOGO_FILES=pionera-logo.svg,funding-logos.png,oeg.png",
            "INESDATA_BRAND_FOOTER_LOGO_URLS=",
            "INESDATA_BRAND_FOOTER_TEXT=",
            "INESDATA_BRAND_POWERED_BY_TEXT=Powered by:",
            "INESDATA_BRAND_POWERED_BY_LOGO_FILES=inesdta.png",
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
            "APP_BASE_HREF",
        ):
            self.assertIn(key, deployment)
        self.assertIn("publicBasePath", deployment)
        self.assertIn("OAUTH2_REDIRECT_PATH", deployment)
        self.assertIn("$connectorInterfacePublicBaseHref := printf", deployment)
        self.assertIn("value: {{ $connectorInterfacePublicBaseHref | quote }}", deployment)
        self.assertIn("connectorInterface:", values)
        self.assertIn("branding:", values)
        self.assertIn("showMenuText", values)
        self.assertIn("localStoreLabel", values)
        self.assertIn("assetsConfigMapName", values)
        self.assertIn("assets:", values)

    def test_connector_interface_entrypoint_rewrites_base_href(self):
        entrypoint = (
            ROOT
            / "adapters/inesdata/sources/inesdata-connector-interface/docker/assets/scripts/docker-entrypoint.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("APP_BASE_HREF", entrypoint)
        self.assertIn("<base href=", entrypoint)
        self.assertIn("sed -i", entrypoint)

    def test_connector_interface_runtime_branding_colors_are_applied(self):
        template = (
            ROOT
            / "adapters/inesdata/sources/inesdata-connector-interface/src/assets/config/app.config.template.json"
        ).read_text(encoding="utf-8")
        main_ts = (
            ROOT
            / "adapters/inesdata/sources/inesdata-connector-interface/src/main.ts"
        ).read_text(encoding="utf-8")

        self.assertIn('"branding"', template)
        self.assertIn('"name": "$APP_BRAND_NAME"', template)
        self.assertIn('"showMenuText": "$APP_SHOW_MENU_TEXT"', template)
        self.assertIn('"primaryColor": "$APP_PRIMARY_COLOR"', template)
        self.assertIn('"secondaryColor": "$APP_SECONDARY_COLOR"', template)
        self.assertIn("applyRuntimeBranding(runtimeEnv)", main_ts)
        self.assertIn("root.style.setProperty('--brand-500', primaryColor)", main_ts)
        self.assertIn("root.style.setProperty('--secondary-500', secondaryColor)", main_ts)
        self.assertIn("root.style.setProperty('--secondary-600', secondaryColor)", main_ts)

    def test_connector_interface_branding_patch_keeps_balanced_footer_logos(self):
        source = (ROOT / "adapters/inesdata/connectors.py").read_text(encoding="utf-8")

        self.assertIn(".footer__logos {", source)
        self.assertIn("display: flex;", source)
        self.assertIn("gap: clamp(22px, 4vw, 64px);", source)
        self.assertIn(".footer__logo--funding", source)
        self.assertIn("max-height: 64px;", source)
        self.assertIn("max-width: min(52vw, 760px);", source)
        self.assertIn("flex-direction: column;", source)
        self.assertIn("gap: 2px;", source)
        self.assertIn(".footer__logo--pionera", source)
        self.assertIn(".footer__logo--oeg", source)
        self.assertIn("margin: 0;", source)

    def test_connector_interface_source_uses_fixed_menu_and_sticky_footer_layout(self):
        navigation_html = (
            ROOT
            / "adapters/inesdata/sources/inesdata-connector-interface/src/app/shared/components/navigation/navigation.component.html"
        ).read_text(encoding="utf-8")
        navigation_ts = (
            ROOT
            / "adapters/inesdata/sources/inesdata-connector-interface/src/app/shared/components/navigation/navigation.component.ts"
        ).read_text(encoding="utf-8")
        navigation_scss = (
            ROOT
            / "adapters/inesdata/sources/inesdata-connector-interface/src/app/shared/components/navigation/navigation.component.scss"
        ).read_text(encoding="utf-8")
        routing_ts = (
            ROOT
            / "adapters/inesdata/sources/inesdata-connector-interface/src/app/app-routing.module.ts"
        ).read_text(encoding="utf-8")

        self.assertIn('src="assets/branding/pionera-logo.svg"', navigation_html)
        self.assertIn('*ngIf="showBrandName"', navigation_html)
        self.assertIn("{{ brandName }}", navigation_html)
        self.assertNotIn('<span class="brand-name">PIONERA</span>', navigation_html)
        self.assertIn("environment.runtime", navigation_ts)
        self.assertIn("showBrandName", navigation_ts)
        self.assertIn("brandName", navigation_ts)
        self.assertNotIn("collapse-button", navigation_html)
        self.assertNotIn("isMenuCollapsed", navigation_html)
        self.assertNotIn("toggleMenu", navigation_ts)
        self.assertNotIn(".sidenav--collapsed", navigation_scss)
        self.assertIn("flex: 1 0 auto;", navigation_scss)
        self.assertIn("min-height: 0;", navigation_scss)
        self.assertIn("--mdc-list-list-item-one-line-container-height: 42px;", navigation_scss)
        self.assertIn("align-self: center;", navigation_scss)
        self.assertIn("display: inline-flex;", navigation_scss)
        self.assertIn("data: {title: 'AI Model Observer', icon: 'desktop_windows'}", routing_ts)
        self.assertNotIn("icon: 'monitoring'", routing_ts)

    def test_model_observer_home_inputs_stay_inside_cards(self):
        scss = (
            ROOT
            / "adapters/inesdata/sources/inesdata-connector-interface/src/app/pages/ai-model-observer/ai-model-observer-home/ai-model-observer-home.component.scss"
        ).read_text(encoding="utf-8")

        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));", scss)
        self.assertIn("min-width: 0;", scss)
        self.assertIn("box-sizing: border-box;", scss)
        self.assertIn("max-width: 100%;", scss)

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
