import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("helm"), "helm binary is required for chart rendering tests")
class OntologyHubChartSampleDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validation_environment_dir = Path(__file__).resolve().parents[1]
        cls.chart_dir = (
            cls.validation_environment_dir
            / "deployers"
            / "shared"
            / "components"
            / "ontology-hub"
        )

    def _render_chart(self, values_file: str) -> str:
        rendered = subprocess.run(
            [
                "helm",
                "template",
                "ontology-hub-test",
                str(self.chart_dir),
                "-f",
                str(self.chart_dir / values_file),
            ],
            cwd=self.validation_environment_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        return rendered.stdout

    def _render_chart_with_values(self, values_yaml: str) -> str:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml") as handle:
            handle.write(values_yaml)
            handle.flush()
            rendered = subprocess.run(
                [
                    "helm",
                    "template",
                    "ontology-hub-test",
                    str(self.chart_dir),
                    "-f",
                    handle.name,
                ],
                cwd=self.validation_environment_dir,
                check=True,
                capture_output=True,
                text=True,
            )
        return rendered.stdout

    def test_demo_values_render_sample_data_resources(self):
        if not (self.chart_dir / "values-demo.yaml").exists():
            self.skipTest("values-demo.yaml is a local runtime values file")
        rendered = self._render_chart("values-demo.yaml")

        self.assertIn("name: ontology-hub-test-sample-data", rendered)
        self.assertIn("seed-ontology-hub-mongodb", rendered)
        self.assertIn("seed-ontology-hub-elasticsearch", rendered)
        self.assertIn("prepare-ontology-hub-version-files", rendered)
        self.assertIn("mongo-users.json", rendered)
        self.assertIn("mongo-languages.json", rendered)
        self.assertIn("mongo-vocabularies.json", rendered)
        self.assertIn("version-latest.n3", rendered)
        self.assertIn('"prefix": "s4gridpt5"', rendered)
        self.assertIn('"stats-s4gridpt5"', rendered)
        self.assertIn('"$oid": "6655df8c246d4eb07e1808ff"', rendered)
        self.assertIn('"$oid": "6655df9c246d4eb07e180900"', rendered)
        self.assertIn('"creatorIds": [', rendered)
        self.assertIn('"6655debc246d4eb07e1808fb"', rendered)
        self.assertIn('"languageIds": [', rendered)
        self.assertIn('"54b2be018433ca9ccf1c0e0c"', rendered)
        self.assertIn('"54b2be018433ca9ccf1c0e2d"', rendered)
        self.assertIn('"label": "English"', rendered)
        self.assertIn('"label": "Spanish"', rendered)
        self.assertIn('"langs":["English"]', rendered)
        self.assertIn('"langs":["English","Spanish"]', rendered)
        self.assertIn(
            "docker.elastic.co/elasticsearch/elasticsearch:7.17.26", rendered
        )
        self.assertIn('collection.deleteMany({ prefix: document.prefix });', rendered)
        self.assertIn("\"_index\":\"lov_class\"", rendered)
        self.assertIn("\"index.default_pipeline\": \"ontology-hub-sample-data\"", rendered)
        self.assertIn("ignore_unavailable=true", rendered)
        self.assertIn("${es_base}/${index_name}", rendered)
        self.assertIn("${es_base}/_index_template/${template_name}", rendered)

    def test_default_values_do_not_render_optional_sample_data_resources(self):
        rendered = self._render_chart("values.yaml")

        self.assertIn('value: "mongodb://mongodb:27017"', rendered)
        self.assertIn('value: "mongodb://mongodb:27017/lov"', rendered)
        self.assertNotIn("%!d", rendered)
        self.assertNotIn("name: ontology-hub-test-sample-data", rendered)
        self.assertNotIn("seed-ontology-hub-mongodb", rendered)
        self.assertNotIn("seed-ontology-hub-elasticsearch", rendered)
        self.assertNotIn("prepare-ontology-hub-version-files", rendered)
        self.assertIn('mountPath: "/app/versions"', rendered)
        self.assertIn("emptyDir: {}", rendered)
        self.assertNotIn("kind: PersistentVolumeClaim", rendered)
        self.assertIn("startupProbe:\n            tcpSocket:\n              port: http", rendered)
        self.assertIn("readinessProbe:\n            tcpSocket:\n              port: http", rendered)
        self.assertIn("timeoutSeconds: 2", rendered)

    def test_health_probe_can_be_rendered_as_http_when_explicitly_requested(self):
        rendered = self._render_chart_with_values(
            textwrap.dedent(
                """
                health:
                  probeType: http
                  path: /dataset
                  timeoutSeconds: 3
                  startupProbe:
                    timeoutSeconds: 3
                """
            )
        )

        self.assertIn("startupProbe:\n            httpGet:\n              path: \"/dataset\"", rendered)
        self.assertIn("readinessProbe:\n            httpGet:\n              path: \"/dataset\"", rendered)
        self.assertIn("timeoutSeconds: 3", rendered)

    def test_versions_persistence_renders_pvc_when_enabled(self):
        rendered = self._render_chart_with_values(
            textwrap.dedent(
                """
                versions:
                  persistence:
                    enabled: true
                    size: 2Gi
                """
            )
        )

        self.assertIn("name: ontology-hub-test-versions", rendered)
        self.assertIn("app.kubernetes.io/component: versions", rendered)
        self.assertIn("persistentVolumeClaim:", rendered)
        self.assertIn("claimName: ontology-hub-test-versions", rendered)
        self.assertIn('storage: "2Gi"', rendered)


if __name__ == "__main__":
    unittest.main()
