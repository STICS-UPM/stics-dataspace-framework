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

    def _write_use_case_demo_source(self, source_dir):
        self._write_file(os.path.join(source_dir, "src", "server.py"), "from fastapi import FastAPI\napp = FastAPI()\n")
        self._write_file(os.path.join(source_dir, "requirements.txt"), "fastapi\nuvicorn\n")
        self._write_file(os.path.join(source_dir, "data", "mobility-datasets", "segments_test.csv"), "x,y\n1,2\n")
        self._write_file(os.path.join(source_dir, "data", "flares-datasets", "5w1h_subtarea_1_test.json"), "{}\n")
        self._write_file(os.path.join(source_dir, "data", "flares-datasets", "5w1h_subtarea_2_test.json"), "{}\n")

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

    def test_use_case_demo_profile_uses_combined_mode_without_training_artifacts(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as tmpdir:
            self._write_use_case_demo_source(source_dir)
            profile_path = os.path.join(tmpdir, "pionera.env")
            self._write_file(
                profile_path,
                "\n".join(
                    [
                        "PROFILE_TOPOLOGY=vm-distributed",
                        "PROFILE_ADAPTER=inesdata",
                        f"AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR={source_dir}",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY=https://example.test/use-cases.git",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF=abc1234",
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
                result = main._promote_ai_model_hub_use_case_demo_profile(
                    profile_path,
                    {
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR": source_dir,
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY": "https://example.test/use-cases.git",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF": "abc1234",
                        "COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test",
                    },
                )

            with open(profile_path, encoding="utf-8") as handle:
                content = handle.read()

        self.assertEqual(result["status"], "promoted")
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_MODE=combined", content)
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_IMAGE=model-server:combined-abc1234", content)
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH=/models", content)
        self.assertIn("AI_MODEL_HUB_ENABLE_MODEL_SERVER_USE_CASES=true", content)
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_DISCOVERY_PATH=/models", content)
        apply_profile.assert_called_once()

    def test_use_case_demo_seed_commands_match_steps_9_and_10(self):
        values = {
            "DS_1_NAME": "pionera",
            "DS_1_CONNECTORS": "conn-org2-pionera,conn-org3-pionera",
            "COMPONENTS_NAMESPACE": "components",
            "ENVIRONMENT_NAME": "DEV",
            "PROFILE_TOPOLOGY": "vm-distributed",
            "KEYCLOAK_PUBLIC_URL": "https://org1.example.test/auth",
            "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL": "http://model-server.components.svc.cluster.local:8080",
        }

        datasets_cmd = main._ai_model_hub_use_case_demo_seed_command(values, step="datasets")
        models_cmd = main._ai_model_hub_use_case_demo_seed_command(values, step="models")

        self.assertIn("--seed-scope", datasets_cmd)
        self.assertIn("datasets", datasets_cmd)
        self.assertIn("--model-set", models_cmd)
        self.assertIn("use-cases", models_cmd)
        self.assertIn("--skip-inesdata-models", models_cmd)
        self.assertIn("--use-case-model-server-base-url", models_cmd)
        self.assertIn("conn-org2-pionera,conn-org3-pionera", models_cmd)
        self.assertTrue(
            any(
                os.path.join("deployers", "inesdata", "deployments", "DEV", "vm-distributed", "pionera")
                in arg
                for arg in datasets_cmd
            )
        )
        self.assertIn("--keycloak-token-url", datasets_cmd)
        self.assertIn(
            "https://org1.example.test/auth/realms/pionera/protocol/openid-connect/token",
            datasets_cmd,
        )

    def test_use_case_demo_flow_runs_profile_level5_and_seed_steps(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as tmpdir:
            self._write_use_case_demo_source(source_dir)
            profile_path = os.path.join(tmpdir, "pionera.env")
            self._write_file(
                profile_path,
                "\n".join(
                    [
                        "PROFILE_TOPOLOGY=vm-distributed",
                        "PROFILE_ADAPTER=inesdata",
                        "DS_1_NAME=pionera",
                        "DS_1_CONNECTORS=conn-org2-pionera,conn-org3-pionera",
                        f"AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR={source_dir}",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY=https://example.test/use-cases.git",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF=abc1234",
                        "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL=http://model-server.example.test",
                        "",
                    ]
                ),
            )

            completed = mock.Mock(returncode=0)
            with mock.patch.object(
                main,
                "apply_environment_configuration_profile",
                return_value={"status": "applied"},
            ), mock.patch.object(main.subprocess, "run", return_value=completed) as subprocess_run:
                result = main._run_ai_model_hub_use_case_demo_flow(
                    profile_path,
                    {
                        "DS_1_NAME": "pionera",
                        "DS_1_CONNECTORS": "conn-org2-pionera,conn-org3-pionera",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR": source_dir,
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY": "https://example.test/use-cases.git",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF": "abc1234",
                        "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL": "http://model-server.example.test",
                    },
                    adapter_name="inesdata",
                    run_level5=True,
                )

        self.assertEqual(result["status"], "passed")
        step_names = [step["name"] for step in result["steps"]]
        self.assertEqual(step_names, ["prepare-profile", "level5-components", "step9-datasets", "step10-models"])
        commands = [call.args[0] for call in subprocess_run.call_args_list]
        self.assertEqual(commands[0][1:], ["main.py", "inesdata", "level", "5", "--topology", "vm-distributed"])
        self.assertIn("--seed-scope", commands[1])
        self.assertIn("datasets", commands[1])
        self.assertIn("--model-set", commands[2])
        self.assertIn("use-cases", commands[2])

    def test_use_case_demo_flow_stops_when_level5_fails(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as tmpdir:
            self._write_use_case_demo_source(source_dir)
            profile_path = os.path.join(tmpdir, "pionera.env")
            self._write_file(
                profile_path,
                "\n".join(
                    [
                        "PROFILE_TOPOLOGY=vm-distributed",
                        "PROFILE_ADAPTER=inesdata",
                        f"AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR={source_dir}",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF=abc1234",
                        "",
                    ]
                ),
            )

            failed = mock.Mock(returncode=7)
            with mock.patch.object(
                main,
                "apply_environment_configuration_profile",
                return_value={"status": "applied"},
            ), mock.patch.object(main.subprocess, "run", return_value=failed) as subprocess_run:
                result = main._run_ai_model_hub_use_case_demo_flow(
                    profile_path,
                    {
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR": source_dir,
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF": "abc1234",
                    },
                    adapter_name="inesdata",
                    run_level5=True,
                )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "level5-failed")
        self.assertEqual([step["name"] for step in result["steps"]], ["prepare-profile", "level5-components"])
        self.assertEqual(subprocess_run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
