import os
import tempfile
import unittest
from pathlib import Path

from validation.components.semantic_virtualization.automap_source import (
    REQUIRED_DIRECTORIES,
    REQUIRED_FILES,
    run_automap_source_validation,
    validate_automap_source,
)


class SemanticVirtualizationAutomapSourceTests(unittest.TestCase):
    def _create_minimal_automap_source(self, root: Path) -> None:
        for relative_path in REQUIRED_DIRECTORIES.values():
            (root / relative_path).mkdir(parents=True, exist_ok=True)
            (root / relative_path / "__init__.py").write_text("", encoding="utf-8")

        for relative_path in REQUIRED_FILES.values():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# placeholder\n", encoding="utf-8")

        (root / "README.md").write_text(
            "Automap uses LangGraph to generate RML and YARRRML mappings, "
            "materialise KGs with morph-kgc, validate SPARQL/SHACL and run evaluation.",
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text(
            "[project]\n"
            "dependencies = ['langgraph', 'morph-kgc', 'rdflib', 'pyshacl', 'yatter']\n",
            encoding="utf-8",
        )

    def test_validate_automap_source_passes_for_expected_repository_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "automap"
            source_dir.mkdir()
            self._create_minimal_automap_source(source_dir)

            result = validate_automap_source(source_dir)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["assertions"], [])
        self.assertIn("langgraph", result["capabilities"]["detected_from_readme"])
        self.assertIn("morph-kgc", result["capabilities"]["dependency_markers"])
        self.assertEqual(
            result["secret_policy"],
            "Environment files and API keys are not read or persisted by this validation.",
        )

    def test_validate_automap_source_fails_when_source_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_dir = Path(tmpdir) / "automap"
            result = validate_automap_source(missing_dir)

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("not available locally" in item for item in result["assertions"]))

    def test_run_automap_source_validation_writes_component_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "automap"
            source_dir.mkdir()
            self._create_minimal_automap_source(source_dir)
            experiment_dir = Path(tmpdir) / "experiment"

            report = run_automap_source_validation(experiment_dir=experiment_dir, source_dir=source_dir)

            artifact_path = report["artifacts"]["report_json"]
            self.assertTrue(os.path.exists(artifact_path))
            self.assertTrue(artifact_path.endswith("semantic_virtualization_automap_source.json"))
            self.assertEqual(report["summary"], {"total": 1, "passed": 1, "failed": 0, "skipped": 0})
            self.assertEqual(report["support_checks"][0]["test_case_id"], "SV-AUTOMAP-01")


if __name__ == "__main__":
    unittest.main()
