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
                "  ✓ 01 login readiness: authentication and shell loaded",
                "  - 02 optional path",
                "  ✗ 03 failing path",
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

        self.assertEqual(completed.stdout, "\nSuite: Ontology Hub functional\n")

    def test_console_reporter_prints_logical_group_headers_when_suite_is_mixed(self):
        script = """
const Reporter = require('./validation/ui/reporters/console-test-name-reporter.cjs');
const reporter = new Reporter();
reporter.colors = false;
reporter.interactive = false;
process.env.PIONERA_PLAYWRIGHT_SUITE_NAME = 'INESData integration';
const coreTest = {
  title: '01 login readiness: authentication and shell loaded',
  location: { file: 'validation/ui/adapters/inesdata/specs/01-login-readiness.spec.ts' },
};
const ontologyTest = {
  title: '08 ontology hub: read-only INESData UI integration surfaces vocabularies and ontologies',
  location: { file: 'validation/ui/adapters/inesdata/specs/08-ontology-hub-inesdata-readonly.spec.ts' },
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
                "  ✓ 01 login readiness: authentication and shell loaded",
                "Group: Ontology Hub (1 test)",
                "  ✓ 08 ontology hub: read-only INESData UI integration surfaces vocabularies and ontologies",
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
                "  ✓ PT5-MH-01: model catalog view is reachable from the public UI",
                "  ✓ PT5-MH-02: provider can register a local model asset with valid metadata",
                "Group: AI Model Hub (1 test)",
                "  ✓ PT5-MH-03: provider publication becomes visible through the consumer catalog UI",
                "Group: Functional (2 tests)",
                "  ✓ PT5-MH-04: model listing view renders the discovery shell",
                "  ✓ PT5-MH-05: model discovery search input accepts free text queries",
            ],
        )

    def test_console_reporter_labels_ontology_hub_integration_specs_as_api_integration(self):
        script = """
const Reporter = require('./validation/ui/reporters/console-test-name-reporter.cjs');
const reporter = new Reporter();
reporter.colors = false;
reporter.interactive = false;
process.env.PIONERA_PLAYWRIGHT_SUITE_NAME = 'Ontology Hub API integration';
const functionalTest = {
  title: 'OH functional',
  location: { file: 'validation/components/ontology_hub/functional/specs/oh_app_00_home.spec.js' },
};
const integrationTest = {
  title: 'OH API integration',
  location: { file: 'validation/components/ontology_hub/integration/specs/pt5_oh_13_sparql.spec.js' },
};
reporter.onBegin(null, { allTests: () => [functionalTest, integrationTest] });
reporter.onTestEnd(functionalTest, { status: 'passed' });
reporter.onTestEnd(integrationTest, { status: 'passed' });
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
                "Suite: Ontology Hub API integration (2 tests)",
                "Group: Functional (1 test)",
                "  ✓ OH functional",
                "Group: API integration (1 test)",
                "  ✓ OH API integration",
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
    location: { file: 'validation/ui/adapters/inesdata/specs/01-login-readiness.spec.ts' },
  },
  {
    title: '04 consumer catalog: published asset is discoverable',
    location: { file: 'validation/ui/adapters/inesdata/specs/04-consumer-catalog.spec.ts' },
  },
  {
    title: 'MinIO browser: provider bucket visible by direct URL',
    location: { file: 'validation/ui/shared/specs/minio-bucket-visibility.ts' },
  },
  {
    title: '07 semantic virtualization: HTTP data is queryable',
    location: { file: 'validation/ui/adapters/inesdata/specs/07-semantic-virtualization-httpdata.spec.ts' },
  },
  {
    title: '08 ontology hub: read-only INESData UI integration surfaces vocabularies and ontologies',
    location: { file: 'validation/ui/adapters/inesdata/specs/08-ontology-hub-inesdata-readonly.spec.ts' },
  },
  {
    title: '09 AI Model Hub: HTTP data publication is discoverable',
    location: { file: 'validation/ui/adapters/inesdata/specs/09-ai-model-hub-httpdata.spec.ts' },
  },
  {
    title: '10 AI model observer: transfer events are visible',
    location: { file: 'validation/ui/adapters/inesdata/specs/10-ai-model-observer.spec.ts' },
  },
  {
    title: '11 AI Model Browser: controlled model discovery, filtering and detail from INESData UI',
    location: { file: 'validation/ui/adapters/inesdata/specs/11-ai-model-browser.spec.ts' },
  },
  {
    title: '12 AI Model Execution: local model-server inference from INESData UI',
    location: { file: 'validation/ui/adapters/inesdata/specs/12-ai-model-execution.spec.ts' },
  },
  {
    title: '13 AI Model Benchmarking: compare two local model-server endpoints from INESData UI',
    location: { file: 'validation/ui/adapters/inesdata/specs/13-ai-model-benchmarking.spec.ts' },
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
                "Suite: INESData integration (10 tests)",
                "Group: Core (2 tests)",
                "  ✓ 01 login readiness: authentication and shell loaded",
                "  ✓ 04 consumer catalog: published asset is discoverable",
                "Group: Operational Storage (1 test)",
                "  ✓ MinIO browser: provider bucket visible by direct URL",
                "Group: Semantic Virtualization (1 test)",
                "  ✓ 07 semantic virtualization: HTTP data is queryable",
                "Group: Ontology Hub (1 test)",
                "  ✓ 08 ontology hub: read-only INESData UI integration surfaces vocabularies and ontologies",
                "Group: AI Model Hub (5 tests)",
                "  ✓ 09 AI Model Hub: HTTP data publication is discoverable",
                "  ✓ 10 AI model observer: transfer events are visible",
                "  ✓ 11 AI Model Browser: controlled model discovery, filtering and detail from INESData UI",
                "  ✓ 12 AI Model Execution: local model-server inference from INESData UI",
                "  ✓ 13 AI Model Benchmarking: compare two local model-server endpoints from INESData UI",
            ],
        )

    def test_console_reporter_counts_edc_groups_from_suite_tree(self):
        script = """
const Reporter = require('./validation/ui/reporters/console-test-name-reporter.cjs');
const reporter = new Reporter();
reporter.colors = false;
reporter.interactive = false;
process.env.PIONERA_PLAYWRIGHT_SUITE_NAME = 'EDC UI';
const tests = [
  {
    title: '01 edc readiness: dashboard authentication and shell loaded',
    location: { file: 'validation/ui/adapters/edc/specs/01-login-readiness.spec.ts' },
  },
  {
    title: '04 edc catalog: provider asset is discoverable',
    location: { file: 'validation/ui/adapters/edc/specs/04-consumer-catalog.spec.ts' },
  },
  {
    title: 'MinIO browser: provider bucket visible by direct URL',
    location: { file: 'validation/ui/adapters/edc/specs/06b-minio-bucket-visibility.spec.ts' },
  },
  {
    title: '07 edc semantic virtualization: HTTP data asset is discoverable',
    location: { file: 'validation/ui/adapters/edc/specs/07-semantic-virtualization-httpdata.spec.ts' },
  },
  {
    title: '08 edc ontology hub: read-only dashboard integration surfaces ontology endpoint',
    location: { file: 'validation/ui/adapters/edc/specs/08-ontology-hub-edc-readonly.spec.ts' },
  },
  {
    title: '09 EDC AI Model Hub: HTTP data publication is discoverable',
    location: { file: 'validation/ui/adapters/edc/specs/09-ai-model-hub-httpdata.spec.ts' },
  },
  {
    title: '10 EDC AI model observer: transfer events are visible',
    location: { file: 'validation/ui/adapters/edc/specs/10-ai-model-observer.spec.ts' },
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
                "Suite: EDC UI (7 tests)",
                "Group: Core (2 tests)",
                "  ✓ 01 edc readiness: dashboard authentication and shell loaded",
                "  ✓ 04 edc catalog: provider asset is discoverable",
                "Group: Operational Storage (1 test)",
                "  ✓ MinIO browser: provider bucket visible by direct URL",
                "Group: Semantic Virtualization (1 test)",
                "  ✓ 07 edc semantic virtualization: HTTP data asset is discoverable",
                "Group: Ontology Hub (1 test)",
                "  ✓ 08 edc ontology hub: read-only dashboard integration surfaces ontology endpoint",
                "Group: AI Model Hub (2 tests)",
                "  ✓ 09 EDC AI Model Hub: HTTP data publication is discoverable",
                "  ✓ 10 EDC AI model observer: transfer events are visible",
            ],
        )

    def test_console_reporter_never_attaches_unknown_tests_to_previous_group(self):
        script = """
const Reporter = require('./validation/ui/reporters/console-test-name-reporter.cjs');
const reporter = new Reporter();
reporter.colors = false;
reporter.interactive = false;
process.env.PIONERA_PLAYWRIGHT_SUITE_NAME = 'Experimental UI';
const tests = [
  {
    title: 'known semantic virtualization check',
    location: { file: 'validation/ui/adapters/edc/specs/07-semantic-virtualization-httpdata.spec.ts' },
  },
  {
    title: 'unknown future integration check',
    location: { file: 'validation/ui/experimental/specs/99-future-component.spec.ts' },
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
                "Suite: Experimental UI (2 tests)",
                "Group: Semantic Virtualization (1 test)",
                "  ✓ known semantic virtualization check",
                "Group: Unclassified (1 test)",
                "  ✓ unknown future integration check",
            ],
        )

    def test_console_reporter_classifies_future_edc_adapter_specs_as_core(self):
        script = """
const Reporter = require('./validation/ui/reporters/console-test-name-reporter.cjs');
const reporter = new Reporter();
reporter.colors = false;
reporter.interactive = false;
process.env.PIONERA_PLAYWRIGHT_SUITE_NAME = 'EDC UI';
const tests = [
  {
    title: '01 edc readiness: dashboard authentication and shell loaded',
    location: { file: 'validation/ui/adapters/edc/specs/01-login-readiness.spec.ts' },
  },
  {
    title: '17 edc future adapter check',
    location: { file: 'validation/ui/adapters/edc/specs/17-future-adapter-check.spec.ts' },
  },
  {
    title: '07 edc semantic virtualization: HTTP data asset is discoverable',
    location: { file: 'validation/ui/adapters/edc/specs/07-semantic-virtualization-httpdata.spec.ts' },
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

        output = completed.stdout.strip().splitlines()
        self.assertIn("Group: Core (2 tests)", output)
        self.assertIn("  ✓ 17 edc future adapter check", output)
        self.assertNotIn("Group: Unclassified (1 test)", output)

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

        self.assertEqual(completed.stdout, "\u001b[31m  ✗ 03 failing path\u001b[0m\n")


if __name__ == "__main__":
    unittest.main()
