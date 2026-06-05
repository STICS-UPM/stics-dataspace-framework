import os
import shutil
import subprocess
import tempfile
import unittest

import yaml


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CHART_DIR = os.path.join(REPO_ROOT, "deployers", "shared", "components", "semantic-virtualization")


@unittest.skipUnless(shutil.which("helm"), "helm binary is required for chart rendering tests")
class SemanticVirtualizationMappingEditorChartTests(unittest.TestCase):
    def _render_chart_with_values(self, values):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as handle:
            yaml.safe_dump(values, handle, sort_keys=False)
            values_file = handle.name

        try:
            rendered = subprocess.run(
                ["helm", "template", "sv-test", CHART_DIR, "-f", values_file],
                check=True,
                capture_output=True,
                text=True,
            )
        finally:
            os.unlink(values_file)

        return [doc for doc in yaml.safe_load_all(rendered.stdout) if doc]

    def _mapping_editor_deployment(self, documents):
        for document in documents:
            if document.get("kind") != "Deployment":
                continue
            labels = document.get("metadata", {}).get("labels", {})
            if labels.get("app.kubernetes.io/component") == "mapping-editor":
                return document
        self.fail("mapping-editor deployment was not rendered")

    def test_mapping_editor_host_port_uses_recreate_strategy(self):
        documents = self._render_chart_with_values(
            {
                "mappingEditor": {
                    "enabled": True,
                    "hostPort": {
                        "enabled": True,
                        "port": 5678,
                    },
                },
            }
        )

        deployment = self._mapping_editor_deployment(documents)

        self.assertEqual(deployment["spec"]["strategy"], {"type": "Recreate"})
        ports = deployment["spec"]["template"]["spec"]["containers"][0]["ports"]
        self.assertEqual(ports[0]["hostPort"], 5678)

    def test_mapping_editor_explicit_strategy_overrides_host_port_default(self):
        explicit_strategy = {
            "type": "RollingUpdate",
            "rollingUpdate": {
                "maxSurge": 0,
                "maxUnavailable": 1,
            },
        }
        documents = self._render_chart_with_values(
            {
                "mappingEditor": {
                    "enabled": True,
                    "hostPort": {
                        "enabled": True,
                        "port": 5678,
                    },
                    "strategy": explicit_strategy,
                },
            }
        )

        deployment = self._mapping_editor_deployment(documents)

        self.assertEqual(deployment["spec"]["strategy"], explicit_strategy)


if __name__ == "__main__":
    unittest.main()
