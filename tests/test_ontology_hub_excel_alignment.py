import os
import unittest


VALIDATION_ROOT = os.path.dirname(os.path.dirname(__file__))
SPECS_ROOT = os.path.join(
    VALIDATION_ROOT,
    "validation",
    "components",
    "ontology_hub",
    "functional",
    "specs",
)


def _read_spec(name):
    with open(os.path.join(SPECS_ROOT, name), "r", encoding="utf-8") as handle:
        return handle.read()


def _read_support(name):
    support_root = os.path.join(
        VALIDATION_ROOT,
        "validation",
        "components",
        "ontology_hub",
        "functional",
        "support",
    )
    with open(os.path.join(support_root, name), "r", encoding="utf-8") as handle:
        return handle.read()


class OntologyHubExcelAlignmentTests(unittest.TestCase):
    def test_specs_do_not_use_file_scope_playwright_timeout_configuration(self):
        offenders = []
        for name in sorted(os.listdir(SPECS_ROOT)):
            if not name.endswith(".spec.js"):
                continue
            spec = _read_spec(name)
            for line in spec.splitlines():
                stripped = line.strip()
                if line.startswith("test.setTimeout(") or line.startswith("test.describe.configure("):
                    offenders.append(f"{name}: {stripped}")

        self.assertEqual(
            offenders,
            [],
            "Playwright rejects file-scope timeout configuration in these specs: "
            + ", ".join(offenders),
        )

    def test_case_05_uses_repository_vocabulary_and_persists_download_state(self):
        spec = _read_spec("oh_app_05_vocab_catalog_detail.spec.js")

        self.assertIn("loadRunState(REPOSITORY_VOCAB_STATE_KEY)", spec)
        self.assertIn("saveRunState(VISUALIZATION_N3_STATE_KEY", spec)

    def test_case_10_targets_the_uri_vocabulary_without_overwriting_title(self):
        spec = _read_spec("oh_app_10_vocab_management.spec.js")

        self.assertIn('test("OH-APP-10: edit ontology metadata and tags"', spec)
        self.assertIn("const created = loadRunState(URI_VOCAB_STATE_KEY);", spec)
        self.assertIn("review: updatedReview,", spec)
        self.assertIn("tag: updatedTag,", spec)
        self.assertNotIn("const updatedTitle =", spec)
        self.assertNotIn("title: updatedTitle", spec)

    def test_case_11_can_reuse_the_downloaded_n3_from_case_05(self):
        spec = _read_spec("oh_app_10_vocab_management.spec.js")
        support = _read_support("excel-flows.js")

        self.assertIn('const VISUALIZATION_N3_STATE_KEY = "oh-app-05-visualization-n3";', support)
        self.assertIn("resolveVersionSourceDownload()", spec)
        self.assertIn("loadRunState(VISUALIZATION_N3_STATE_KEY)", spec)
        self.assertIn('source: "oh-app-05"', spec)

    def test_case_24_uses_shared_themis_activation_without_requiring_visible_user_options(self):
        spec = _read_spec("oh_app_22_services.spec.js")

        self.assertIn("const themisActivation = await openThemisPanel(page);", spec)
        self.assertIn("await waitForThemisResults(page);", spec)
        self.assertIn('waitUntil: "commit"', spec)
        self.assertNotIn('await page.locator("#user-options").waitFor({ state: "visible"', spec)
        self.assertNotIn('await page.locator("#themis-results").waitFor({ state: "visible"', spec)


if __name__ == "__main__":
    unittest.main()
