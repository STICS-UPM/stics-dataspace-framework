import os
import tempfile
import types
import unittest
from unittest import mock

import runtime_dependencies


class RuntimeDependenciesTests(unittest.TestCase):
    def _requirements_file(self, tmpdir):
        path = os.path.join(tmpdir, "requirements.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("requests==2.32.3\n")
            handle.write("kafka-python==2.3.0\n")
            handle.write("PyYAML==6.0.2\n")
            handle.write("minio==7.2.7\n")
        return path

    def test_mapping_installs_only_missing_requirement_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements_path = self._requirements_file(tmpdir)

            with mock.patch.object(
                runtime_dependencies,
                "_missing_modules",
                side_effect=[["minio"], []],
            ), mock.patch.object(
                runtime_dependencies.subprocess,
                "run",
                return_value=types.SimpleNamespace(returncode=0),
            ) as runner:
                runtime_dependencies.ensure_runtime_dependencies(
                    requirements_path=requirements_path,
                    module_names=("yaml", "minio"),
                    label="test",
                    module_requirements={
                        "yaml": "PyYAML",
                        "minio": "minio",
                    },
                )

        command = runner.call_args.args[0]
        self.assertIn("minio==7.2.7", command)
        self.assertNotIn("-r", command)
        self.assertNotIn("PyYAML==6.0.2", command)

    def test_mapping_supports_module_names_that_differ_from_package_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements_path = self._requirements_file(tmpdir)

            with mock.patch.object(
                runtime_dependencies,
                "_missing_modules",
                side_effect=[["kafka"], []],
            ), mock.patch.object(
                runtime_dependencies.subprocess,
                "run",
                return_value=types.SimpleNamespace(returncode=0),
            ) as runner:
                runtime_dependencies.ensure_runtime_dependencies(
                    requirements_path=requirements_path,
                    module_names=("kafka",),
                    label="test",
                    module_requirements={
                        "kafka": "kafka-python",
                    },
                )

        command = runner.call_args.args[0]
        self.assertIn("kafka-python==2.3.0", command)
        self.assertNotIn("PyYAML==6.0.2", command)

    def test_default_behavior_keeps_full_requirements_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements_path = self._requirements_file(tmpdir)

            with mock.patch.object(
                runtime_dependencies,
                "_missing_modules",
                side_effect=[["minio"], []],
            ), mock.patch.object(
                runtime_dependencies.subprocess,
                "run",
                return_value=types.SimpleNamespace(returncode=0),
            ) as runner:
                runtime_dependencies.ensure_runtime_dependencies(
                    requirements_path=requirements_path,
                    module_names=("minio",),
                    label="test",
                )

        command = runner.call_args.args[0]
        self.assertIn("-r", command)
        self.assertIn(requirements_path, command)


if __name__ == "__main__":
    unittest.main()
