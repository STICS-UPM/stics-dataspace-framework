import json
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

COMPONENT_MARKER_HELPERS = [
    PROJECT_ROOT / "validation" / "components" / "ontology_hub" / "ui" / "support" / "live-marker.js",
    PROJECT_ROOT / "validation" / "components" / "ai_model_hub" / "ui" / "support" / "live-marker.js",
    PROJECT_ROOT
    / "validation"
    / "components"
    / "semantic_virtualization"
    / "ui"
    / "support"
    / "live-marker.js",
]

ALL_MARKER_HELPERS = [
    *COMPONENT_MARKER_HELPERS,
    PROJECT_ROOT / "validation" / "ui" / "shared" / "utils" / "live-marker.ts",
]


class ComponentUiLiveMarkerTests(unittest.TestCase):
    def test_component_helpers_export_the_same_marked_actions(self):
        expected_exports = {
            "checkMarked",
            "clickMarked",
            "fillMarked",
            "highlightMarked",
            "pressMarked",
            "selectOptionMarked",
            "setInputFilesMarked",
        }

        for helper_path in COMPONENT_MARKER_HELPERS:
            with self.subTest(helper_path=helper_path):
                script = f"""
const helper = require({json.dumps(str(helper_path))});
console.log(JSON.stringify(Object.keys(helper).sort()));
"""
                result = subprocess.run(
                    ["node", "-e", script],
                    cwd=PROJECT_ROOT,
                    text=True,
                    capture_output=True,
                    check=True,
                )

                self.assertEqual(set(json.loads(result.stdout)), expected_exports)

    def test_component_helpers_apply_dom_marker_for_auditable_videos(self):
        for helper_path in ALL_MARKER_HELPERS:
            with self.subTest(helper_path=helper_path):
                source = helper_path.read_text(encoding="utf-8")

                self.assertIn("data-pionera-playwright-marker", source)
                self.assertIn("locator.scrollIntoViewIfNeeded", source)
                self.assertNotIn("locator.highlight", source)
                self.assertIn("PLAYWRIGHT_INTERACTION_MARKERS", source)
                self.assertIn("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", source)

    def test_semantic_virtualization_editor_uses_marked_ui_actions(self):
        spec_path = (
            PROJECT_ROOT
            / "validation"
            / "components"
            / "semantic_virtualization"
            / "ui"
            / "specs"
            / "sv_ui_02_mapping_editor.spec.js"
        )
        source = spec_path.read_text(encoding="utf-8")

        self.assertIn("clickMarked", source)
        self.assertIn("fillMarked", source)
        self.assertIn("pressMarked", source)
        self.assertIn("highlightMarked", source)
        self.assertNotIn("sidebarLink.click", source)
        self.assertNotIn("labelInput.fill", source)
        self.assertNotIn("labelInput.press", source)
        self.assertNotIn('getByRole("tab", { name: /Save Mapping/i }).click', source)

    def test_semantic_virtualization_sidebar_navigation_handles_streamlit_reconnects(self):
        spec_path = (
            PROJECT_ROOT
            / "validation"
            / "components"
            / "semantic_virtualization"
            / "ui"
            / "specs"
            / "sv_ui_02_mapping_editor.spec.js"
        )
        source = spec_path.read_text(encoding="utf-8")

        self.assertIn("streamlitConnectionState", source)
        self.assertIn("dismissStreamlitConnectionDialog", source)
        self.assertIn("Connection error|Connection timed out", source)
        self.assertIn(r"\bCONNECTING\b", source)
        self.assertIn("waitForSidebarNavigationWindow", source)
        self.assertIn("sidebarLinkState", source)
        self.assertIn("intercepts pointer events", source)
        self.assertIn("navigateSidebarLinkByHref", source)
        self.assertIn("stayed disabled", source)
        self.assertIn("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SIDEBAR_CLICK_TIMEOUT_MS", source)


if __name__ == "__main__":
    unittest.main()
