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
