import unittest
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_ROOT / "docs"
REFERENCE_WORKBOOKS = [
    DOCS_DIR / "A5.2_Casos_Prueba_.xlsx",
    DOCS_DIR / "E5.2_Resultados_Validacion_Componentes.xlsx",
]
IGNORED_REFERENCE_PATTERNS = [
    "context/",
    "context\\",
    "deliverables/",
    "deliverables\\",
    "deployer.config",
    "validation/datasets/sources/",
    "validation/datasets/sources\\",
    "experiments/",
    "experiments\\",
    "artefactos de experiments",
    "logs.txt",
    "logs/",
    "runtime/",
    "runtime\\",
    "node_modules/",
    "playwright-report/",
    "test-results/",
    "blob-report/",
]
FORBIDDEN_SECRET_LITERALS = [
    "testing123",
    '"password"',
    "password fields",
    "password field",
    "secret key",
]
MALFORMED_SPANISH_PATTERNS = [
    "ciónes",
    "útiliz",
    "acciónes",
    "validaciónes",
    "integraciónes",
    "iteraciónes",
    "limitaciónes",
    "observaciónes",
]


class DocsPublicationHygieneTests(unittest.TestCase):
    def _workbook_strings(self):
        for workbook_path in REFERENCE_WORKBOOKS:
            workbook = load_workbook(workbook_path, data_only=False)
            for sheet in workbook.worksheets:
                for row in sheet.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str):
                            yield workbook_path, sheet.title, cell.coordinate, cell.value

    def test_reference_workbooks_do_not_point_to_ignored_local_paths(self):
        findings = []
        for workbook_path, sheet, coordinate, value in self._workbook_strings():
            normalized = value.lower()
            hits = [pattern for pattern in IGNORED_REFERENCE_PATTERNS if pattern.lower() in normalized]
            if hits:
                findings.append((workbook_path.name, sheet, coordinate, hits, value[:160]))

        self.assertEqual([], findings)

    def test_reference_workbooks_do_not_repeat_qa_actor(self):
        findings = []
        for workbook_path, sheet, coordinate, value in self._workbook_strings():
            parts = [part.strip().lower() for part in value.replace("\n", " / ").split("/") if part.strip()]
            seen = []
            for part in parts:
                if part in seen and part == "qa":
                    findings.append((workbook_path.name, sheet, coordinate, value[:160]))
                    break
                seen.append(part)

        self.assertEqual([], findings)

    def test_reference_workbooks_do_not_expose_literal_test_credentials(self):
        findings = []
        for workbook_path, sheet, coordinate, value in self._workbook_strings():
            normalized = value.lower()
            hits = [pattern for pattern in FORBIDDEN_SECRET_LITERALS if pattern.lower() in normalized]
            if hits:
                findings.append((workbook_path.name, sheet, coordinate, hits, value[:160]))

        self.assertEqual([], findings)

    def test_reference_workbooks_do_not_contain_malformed_spanish_after_normalization(self):
        findings = []
        for workbook_path, sheet, coordinate, value in self._workbook_strings():
            hits = [pattern for pattern in MALFORMED_SPANISH_PATTERNS if pattern in value]
            if hits:
                findings.append((workbook_path.name, sheet, coordinate, hits, value[:160]))

        self.assertEqual([], findings)

    def test_reference_workbook_sheet_names_are_polished(self):
        workbook = load_workbook(DOCS_DIR / "A5.2_Casos_Prueba_.xlsx", data_only=False)

        self.assertIn("A5.1_Funcionalidades_Ex.1", workbook.sheetnames)
        self.assertNotIn("A5.1_Funcionlidades_Ex.1", workbook.sheetnames)

    def test_a52_workbook_preserves_embedded_media(self):
        with ZipFile(DOCS_DIR / "A5.2_Casos_Prueba_.xlsx") as workbook_zip:
            media_entries = [name for name in workbook_zip.namelist() if name.startswith("xl/media/")]

        self.assertGreaterEqual(len(media_entries), 1)

    def test_markdown_docs_do_not_reference_context_directory(self):
        findings = []
        for markdown_path in DOCS_DIR.rglob("*.md"):
            content = markdown_path.read_text(encoding="utf-8")
            if "context/" in content:
                findings.append(markdown_path.relative_to(PROJECT_ROOT).as_posix())

        self.assertEqual([], findings)

    def test_markdown_docs_do_not_reference_old_workbook_sheet_typo(self):
        findings = []
        for markdown_path in DOCS_DIR.rglob("*.md"):
            content = markdown_path.read_text(encoding="utf-8")
            if "A5.1_Funcionlidades_Ex.1" in content:
                findings.append(markdown_path.relative_to(PROJECT_ROOT).as_posix())

        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
