import os
import tempfile
import unittest
from pathlib import Path

from validation.components.semantic_virtualization.morph_kgv_source import (
    REQUIRED_FILES,
    run_morph_kgv_source_validation,
    validate_morph_kgv_source,
)


class SemanticVirtualizationMorphKgvSourceTests(unittest.TestCase):
    def _create_minimal_morph_kgv_source(self, root: Path) -> None:
        for relative_path in REQUIRED_FILES.values():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# placeholder\n", encoding="utf-8")

        (root / "README.md").write_text(
            "pip install .\n"
            "python run_query.py config.ini query.sparql\n"
            "morph-kgv serve config.ini\n"
            "The endpoint is available at http://localhost:8000/sparql.\n",
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text(
            "[project]\n"
            "name = 'morph_kgc'\n"
            "dependencies = ['rdflib', 'fastapi', 'uvicorn', 'click']\n"
            "[project.scripts]\n"
            "morph-kgv = 'morph_kgc.__main__:cli'\n",
            encoding="utf-8",
        )
        (root / "src" / "morph_kgc" / "__main__.py").write_text(
            "def serve():\n"
            "    path = '/sparql'\n"
            "    import uvicorn\n"
            "    uvicorn.run(path)\n",
            encoding="utf-8",
        )
        (root / "run_query.py").write_text(
            "from rdflib import Graph\n"
            "from morph_kgc import VIRTStore\n"
            "graph = Graph(VIRTStore('config.ini'))\n"
            "graph.query('SELECT * WHERE {?s ?p ?o}')\n",
            encoding="utf-8",
        )

    def test_validate_morph_kgv_source_passes_for_expected_repository_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "morph-kgv"
            source_dir.mkdir()
            self._create_minimal_morph_kgv_source(source_dir)

            result = validate_morph_kgv_source(source_dir)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["assertions"], [])
        self.assertIn("serve", result["capabilities"]["readme_markers"])
        self.assertIn("console_script", result["capabilities"]["pyproject_markers"])
        self.assertEqual(
            result["secret_policy"],
            "Environment files, database credentials and API keys are not read or persisted by this validation.",
        )

    def test_validate_morph_kgv_source_fails_when_source_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_dir = Path(tmpdir) / "morph-kgv"
            result = validate_morph_kgv_source(missing_dir)

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("not available locally" in item for item in result["assertions"]))

    def test_run_morph_kgv_source_validation_writes_component_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "morph-kgv"
            source_dir.mkdir()
            self._create_minimal_morph_kgv_source(source_dir)
            experiment_dir = Path(tmpdir) / "experiment"

            report = run_morph_kgv_source_validation(experiment_dir=experiment_dir, source_dir=source_dir)

            artifact_path = report["artifacts"]["report_json"]
            self.assertTrue(os.path.exists(artifact_path))
            self.assertTrue(artifact_path.endswith("semantic_virtualization_morph_kgv_source.json"))
            self.assertEqual(report["summary"], {"total": 1, "passed": 1, "failed": 0, "skipped": 0})
            self.assertEqual(report["support_checks"][0]["test_case_id"], "SV-MORPH-KGV-01")


if __name__ == "__main__":
    unittest.main()
