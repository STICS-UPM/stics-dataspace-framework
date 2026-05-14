import subprocess
import unittest
from pathlib import Path


class PlaywrightConsoleReporterTests(unittest.TestCase):
    def test_console_reporter_prints_suite_and_colored_status_names(self):
        script = """
const Reporter = require('./validation/ui/reporters/console-test-name-reporter.cjs');
const reporter = new Reporter();
reporter.colors = false;
reporter.interactive = false;
process.env.PIONERA_PLAYWRIGHT_SUITE_NAME = 'INESData integration';
reporter.onBegin(null, { allTests: () => [{}, {}, {}] });
reporter.onTestEnd({ title: '01 login readiness: authentication and shell loaded' }, { status: 'passed' });
reporter.onTestEnd({ title: '02 optional path' }, { status: 'skipped' });
reporter.onTestEnd({ title: '03 failing path' }, { status: 'failed' });
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        self.assertEqual(
            completed.stdout.strip().splitlines(),
            [
                "Suite: INESData integration (3 tests)",
                "✓ 01 login readiness: authentication and shell loaded",
                "- 02 optional path",
                "✗ 03 failing path",
            ],
        )

    def test_console_reporter_keeps_suite_label_when_count_is_unavailable(self):
        script = """
const Reporter = require('./validation/ui/reporters/console-test-name-reporter.cjs');
const reporter = new Reporter();
reporter.colors = false;
reporter.interactive = false;
process.env.PIONERA_PLAYWRIGHT_SUITE_NAME = 'Ontology Hub functional';
reporter.onBegin();
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        self.assertEqual(completed.stdout, "Suite: Ontology Hub functional\n")

    def test_console_reporter_prints_logical_group_headers_when_suite_is_mixed(self):
        script = """
const Reporter = require('./validation/ui/reporters/console-test-name-reporter.cjs');
const reporter = new Reporter();
reporter.colors = false;
reporter.interactive = false;
process.env.PIONERA_PLAYWRIGHT_SUITE_NAME = 'INESData integration';
const coreTest = {
  title: '01 login readiness: authentication and shell loaded',
  location: { file: 'validation/ui/core/01-login-readiness.spec.ts' },
};
const ontologyTest = {
  title: '08 ontology hub: read-only INESData UI integration surfaces vocabularies and ontologies',
  location: { file: 'validation/ui/core/08-ontology-hub-inesdata-readonly.spec.ts' },
};
reporter.onBegin(null, { allTests: () => [coreTest, ontologyTest] });
reporter.onTestEnd(coreTest, { status: 'passed' });
reporter.onTestEnd(ontologyTest, { status: 'passed' });
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        self.assertEqual(
            completed.stdout.strip().splitlines(),
            [
                "Suite: INESData integration (2 tests)",
                "Group: Core (1 test)",
                "✓ 01 login readiness: authentication and shell loaded",
                "Group: Ontology Hub (1 test)",
                "✓ 08 ontology hub: read-only INESData UI integration surfaces vocabularies and ontologies",
            ],
        )

    def test_console_reporter_counts_interleaved_group_blocks_dynamically(self):
        script = """
const Reporter = require('./validation/ui/reporters/console-test-name-reporter.cjs');
const reporter = new Reporter();
reporter.colors = false;
reporter.interactive = false;
process.env.PIONERA_PLAYWRIGHT_SUITE_NAME = 'AI Model Hub functional';
const tests = [
  {
    title: 'PT5-MH-01: model catalog view is reachable from the public UI',
    location: { file: 'validation/components/ai_model_hub/ui/specs/pt5_mh_01_catalog_access.spec.js' },
  },
  {
    title: 'PT5-MH-02: provider can register a local model asset with valid metadata',
    location: { file: 'validation/components/ai_model_hub/ui/specs/pt5_mh_02_model_registration.spec.js' },
  },
  {
    title: 'PT5-MH-03: provider publication becomes visible through the consumer catalog UI',
    location: { file: 'validation/components/ai_model_hub/ui/specs/pt5_mh_03_catalog_publication.spec.js' },
  },
  {
    title: 'PT5-MH-04: model listing view renders the discovery shell',
    location: { file: 'validation/components/ai_model_hub/ui/specs/pt5_mh_04_model_listing.spec.js' },
  },
  {
    title: 'PT5-MH-05: model discovery search input accepts free text queries',
    location: { file: 'validation/components/ai_model_hub/ui/specs/pt5_mh_05_search.spec.js' },
  },
];
reporter.onBegin(null, { allTests: () => tests });
for (const test of tests) {
  reporter.onTestEnd(test, { status: 'passed' });
}
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        self.assertEqual(
            completed.stdout.strip().splitlines(),
            [
                "Suite: AI Model Hub functional (5 tests)",
                "Group: Functional (2 tests)",
                "✓ PT5-MH-01: model catalog view is reachable from the public UI",
                "✓ PT5-MH-02: provider can register a local model asset with valid metadata",
                "Group: AI Model Hub (1 test)",
                "✓ PT5-MH-03: provider publication becomes visible through the consumer catalog UI",
                "Group: Functional (2 tests)",
                "✓ PT5-MH-04: model listing view renders the discovery shell",
                "✓ PT5-MH-05: model discovery search input accepts free text queries",
            ],
        )

    def test_console_reporter_counts_inesdata_groups_from_suite_tree(self):
        script = """
const Reporter = require('./validation/ui/reporters/console-test-name-reporter.cjs');
const reporter = new Reporter();
reporter.colors = false;
reporter.interactive = false;
process.env.PIONERA_PLAYWRIGHT_SUITE_NAME = 'INESData integration';
const tests = [
  {
    title: '01 login readiness: authentication and shell loaded',
    location: { file: 'validation/ui/core/01-login-readiness.spec.ts' },
  },
  {
    title: '04 consumer catalog: published asset is discoverable',
    location: { file: 'validation/ui/core/04-consumer-catalog.spec.ts' },
  },
  {
    title: '07 semantic virtualization: HTTP data is queryable',
    location: { file: 'validation/ui/core/07-semantic-virtualization-httpdata.spec.ts' },
  },
  {
    title: '08 ontology hub: read-only INESData UI integration surfaces vocabularies and ontologies',
    location: { file: 'validation/ui/core/08-ontology-hub-inesdata-readonly.spec.ts' },
  },
  {
    title: '09 AI Model Hub: HTTP data publication is discoverable',
    location: { file: 'validation/ui/core/09-ai-model-hub-httpdata.spec.ts' },
  },
  {
    title: '10 AI model observer: transfer events are visible',
    location: { file: 'validation/ui/core/10-ai-model-observer.spec.ts' },
  },
];
reporter.onBegin(null, { allTests: () => tests });
for (const test of tests) {
  reporter.onTestEnd(test, { status: 'passed' });
}
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        self.assertEqual(
            completed.stdout.strip().splitlines(),
            [
                "Suite: INESData integration (6 tests)",
                "Group: Core (2 tests)",
                "✓ 01 login readiness: authentication and shell loaded",
                "✓ 04 consumer catalog: published asset is discoverable",
                "Group: Semantic Virtualization (1 test)",
                "✓ 07 semantic virtualization: HTTP data is queryable",
                "Group: Ontology Hub (1 test)",
                "✓ 08 ontology hub: read-only INESData UI integration surfaces vocabularies and ontologies",
                "Group: AI Model Hub (2 tests)",
                "✓ 09 AI Model Hub: HTTP data publication is discoverable",
                "✓ 10 AI model observer: transfer events are visible",
            ],
        )

    def test_console_reporter_colors_failed_test_name(self):
        script = """
const Reporter = require('./validation/ui/reporters/console-test-name-reporter.cjs');
const reporter = new Reporter();
reporter.colors = true;
reporter.interactive = false;
reporter.onTestEnd({ title: '03 failing path' }, { status: 'failed' });
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        self.assertEqual(completed.stdout, "\u001b[31m✗ 03 failing path\u001b[0m\n")


if __name__ == "__main__":
    unittest.main()
