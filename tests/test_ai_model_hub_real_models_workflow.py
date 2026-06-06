import os
import tempfile
import unittest
from unittest import mock

import main


class AIModelHubRealModelsWorkflowTests(unittest.TestCase):
    def _write_file(self, path, content="x"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def test_real_models_status_requires_flares_and_mobility_artifacts(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as artifact_dir:
            self._write_file(os.path.join(source_dir, "models", "flares", "model.bin"))

            status = main._ai_model_hub_real_models_status(
                {
                    "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR": source_dir,
                    "AI_MODEL_HUB_REAL_MODELS_ARTIFACT_DIR": artifact_dir,
                }
            )

        self.assertEqual(status["flares_files"], 1)
        self.assertEqual(status["mobility_files"], 0)
        self.assertFalse(status["ready"])

    def test_promote_profile_writes_real_use_case_mode_only_when_models_are_ready(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as tmpdir:
            self._write_file(os.path.join(source_dir, "models", "flares", "model.bin"))
            self._write_file(os.path.join(source_dir, "models", "mobility", "model.joblib"))
            profile_path = os.path.join(tmpdir, "pionera.env")
            self._write_file(
                profile_path,
                "\n".join(
                    [
                        "PROFILE_TOPOLOGY=vm-distributed",
                        "PROFILE_ADAPTER=inesdata",
                        f"AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR={source_dir}",
                        "COMPONENTS_PUBLIC_BASE_URL=https://org1.example.test",
                        "",
                    ]
                ),
            )

            with mock.patch.object(
                main,
                "apply_environment_configuration_profile",
                return_value={"status": "applied"},
            ) as apply_profile:
                result = main._promote_ai_model_hub_real_models_profile(
                    profile_path,
                    {
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR": source_dir,
                        "COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test",
                    },
                )

            with open(profile_path, encoding="utf-8") as handle:
                content = handle.read()

        self.assertEqual(result["status"], "promoted")
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_MODE=use-cases", content)
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH=/models", content)
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL=https://org1.example.test/model-server", content)
        apply_profile.assert_called_once()

    def test_restore_profile_switches_back_to_controlled_mock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = os.path.join(tmpdir, "pionera.env")
            self._write_file(
                profile_path,
                "\n".join(
                    [
                        "AI_MODEL_HUB_MODEL_SERVER_MODE=use-cases",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR=adapters/inesdata/sources/AIModelHub-Use-Cases",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY=https://example.test/use-cases.git",
                        "",
                    ]
                ),
            )

            with mock.patch.object(
                main,
                "apply_environment_configuration_profile",
                return_value={"status": "applied"},
            ) as apply_profile:
                result = main._restore_ai_model_hub_mock_model_server_profile(profile_path)

            with open(profile_path, encoding="utf-8") as handle:
                content = handle.read()

        self.assertEqual(result["status"], "restored")
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_MODE=mock", content)
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR=", content)
        apply_profile.assert_called_once()


if __name__ == "__main__":
    unittest.main()
