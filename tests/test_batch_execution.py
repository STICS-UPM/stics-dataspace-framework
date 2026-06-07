import os
import tempfile
import unittest
from unittest import mock

import yaml

import main


class BatchExecutionTests(unittest.TestCase):
    def _write_yaml(self, path, payload):
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False)

    def _write_text(self, path, content):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def test_batch_plan_matrix_expands_topologies_and_adapters(self):
        payload = {
            "defaults": {"levels": [2, 6], "local_minikube_tunnel": False},
            "matrix": {
                "topologies": ["local", "vm-single"],
                "adapters": ["inesdata", "edc"],
            },
        }

        plan = main._normalize_batch_plan(payload, adapter_registry={"inesdata": "x:y", "edc": "x:y"})

        self.assertEqual(len(plan["runs"]), 4)
        self.assertEqual(
            [(run["topology"], run["adapter"], run["levels"]) for run in plan["runs"]],
            [
                ("local", "inesdata", [2, 6]),
                ("local", "edc", [2, 6]),
                ("vm-single", "inesdata", [2, 6]),
                ("vm-single", "edc", [2, 6]),
            ],
        )
        self.assertFalse(plan["runs"][0]["local_minikube_tunnel"])

    def test_batch_plan_allows_levels_per_topology_adapter_run(self):
        payload = {
            "defaults": {"levels": [6]},
            "runs": [
                {
                    "name": "local-inesdata-full",
                    "topology": "local",
                    "adapter": "inesdata",
                    "levels": [1, 2, 3, 4, 5, 6],
                },
                {
                    "name": "vm-single-edc-validation-only",
                    "topology": "vm-single",
                    "adapter": "edc",
                    "levels": [5, 6],
                },
                {
                    "name": "vm-distributed-inesdata-report-only",
                    "topology": "vm-distributed",
                    "adapter": "inesdata",
                },
            ],
        }

        plan = main._normalize_batch_plan(payload, adapter_registry={"inesdata": "x:y", "edc": "x:y"})

        self.assertEqual(
            [(run["topology"], run["adapter"], run["levels"]) for run in plan["runs"]],
            [
                ("local", "inesdata", [1, 2, 3, 4, 5, 6]),
                ("vm-single", "edc", [5, 6]),
                ("vm-distributed", "inesdata", [6]),
            ],
        )

    def test_batch_run_loads_secrets_and_sets_non_interactive_level6_flags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = os.path.join(tmpdir, "plan.yaml")
            secrets_path = os.path.join(tmpdir, "secrets.env")
            self._write_yaml(
                plan_path,
                {
                    "defaults": {
                        "levels": [6],
                        "kafka": True,
                        "validation_mode": "fast",
                        "auto_confirm": True,
                        "confirm_default": True,
                        "open_report": False,
                    },
                    "runs": [
                        {
                            "name": "local-inesdata",
                            "topology": "local",
                            "adapter": "inesdata",
                            "env": {"CUSTOM_BATCH_FLAG": "enabled"},
                        }
                    ],
                },
            )
            self._write_text(secrets_path, "PIONERA_SUDO_PASSWORD=demo-secret\n")

            observed_env = {}

            def fake_run_batch_levels(run, **kwargs):
                observed_env.update(
                    {
                        "adapter": run["adapter"],
                        "levels": list(run["levels"]),
                        "topology": run["topology"],
                        "batch": os.environ.get("PIONERA_BATCH_MODE"),
                        "sudo": os.environ.get("PIONERA_SUDO_PASSWORD"),
                        "kafka_run": os.environ.get(main.KAFKA_LEVEL6_RUN_FLAG),
                        "kafka_skip": os.environ.get(main.KAFKA_LEVEL6_SKIP_FLAG),
                        "validation_mode": os.environ.get("LEVEL6_VALIDATION_MODE"),
                        "open_report": os.environ.get("PIONERA_LEVEL6_PROMPT_OPEN_REPORT"),
                        "custom": os.environ.get("CUSTOM_BATCH_FLAG"),
                    }
                )
                return {"status": "completed", "adapter": run["adapter"], "topology": run["topology"], "levels": []}

            with mock.patch.object(main, "_run_batch_levels", side_effect=fake_run_batch_levels):
                result = main.run_batch(
                    plan_path=plan_path,
                    secrets_path=secrets_path,
                    adapter_registry={"inesdata": "fake:Adapter"},
                )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(observed_env["adapter"], "inesdata")
        self.assertEqual(observed_env["levels"], [6])
        self.assertEqual(observed_env["topology"], "local")
        self.assertEqual(observed_env["batch"], "true")
        self.assertEqual(observed_env["sudo"], "demo-secret")
        self.assertEqual(observed_env["kafka_run"], "true")
        self.assertEqual(observed_env["kafka_skip"], "false")
        self.assertEqual(observed_env["validation_mode"], "fast")
        self.assertEqual(observed_env["open_report"], "false")
        self.assertEqual(observed_env["custom"], "enabled")

    def test_batch_runtime_env_marks_managed_local_minikube_tunnel(self):
        run = {
            "topology": "local",
            "adapter": "inesdata",
            "levels": [3],
            "local_minikube_tunnel": "auto",
        }

        env = main._batch_runtime_environment(run, secrets={})

        self.assertEqual(env["PIONERA_LOCAL_MINIKUBE_TUNNEL_MANAGED"], "true")

    def test_batch_runtime_env_sets_vm_single_edc_k3s_image_defaults(self):
        run = {
            "topology": "vm-single",
            "adapter": "edc",
            "levels": [4, 5, 6],
            "allow_vm_single_cluster_switch": True,
            "local_minikube_tunnel": "auto",
        }

        env = main._batch_runtime_environment(run, secrets={})

        self.assertEqual(env["PIONERA_EDC_LOCAL_IMAGES_MODE"], "auto")
        self.assertEqual(env["PIONERA_EDC_CONNECTOR_IMAGE_PULL_POLICY"], "IfNotPresent")
        self.assertEqual(env["PIONERA_EDC_DASHBOARD_IMAGE_PULL_POLICY"], "IfNotPresent")
        self.assertEqual(env["PIONERA_EDC_DASHBOARD_PROXY_IMAGE_PULL_POLICY"], "IfNotPresent")
        self.assertEqual(env["PIONERA_SKIP_EDC_LOCAL_CONNECTOR_IMAGE_BUILD"], "false")
        self.assertEqual(env["PIONERA_SKIP_EDC_LOCAL_DASHBOARD_IMAGE_BUILD"], "false")
        self.assertEqual(
            env["PIONERA_VM_SINGLE_CLUSTER_SWITCH_CONFIRM"],
            main._vm_single_cluster_switch_confirmation_token("k3s"),
        )
        self.assertNotIn("PIONERA_LOCAL_MINIKUBE_TUNNEL_MANAGED", env)

    def test_batch_runtime_env_preserves_vm_single_edc_image_overrides(self):
        run = {
            "topology": "vm-single",
            "adapter": "edc",
            "levels": [4],
            "env": {
                "PIONERA_EDC_LOCAL_IMAGES_MODE": "disabled",
                "PIONERA_EDC_CONNECTOR_IMAGE_PULL_POLICY": "Always",
                "PIONERA_SKIP_EDC_LOCAL_CONNECTOR_IMAGE_BUILD": "true",
            },
        }

        env = main._batch_runtime_environment(run, secrets={})

        self.assertEqual(env["PIONERA_EDC_LOCAL_IMAGES_MODE"], "disabled")
        self.assertEqual(env["PIONERA_EDC_CONNECTOR_IMAGE_PULL_POLICY"], "Always")
        self.assertEqual(env["PIONERA_SKIP_EDC_LOCAL_CONNECTOR_IMAGE_BUILD"], "true")

    def test_minikube_tunnel_process_filter_ignores_search_commands(self):
        command = "/bin/bash -c pgrep -af 'minikube.*tunnel' || true"

        self.assertFalse(main._is_minikube_tunnel_process_command(command))

    def test_minikube_tunnel_process_filter_detects_real_minikube_tunnel(self):
        self.assertTrue(main._is_minikube_tunnel_process_command("/usr/local/bin/minikube -p demo tunnel"))
        self.assertTrue(main._is_minikube_tunnel_process_command("sudo minikube --profile demo tunnel"))
        self.assertEqual(main._minikube_tunnel_process_profile("sudo minikube --profile demo tunnel"), "demo")
        self.assertEqual(main._minikube_tunnel_process_profile("minikube -p demo tunnel"), "demo")
        self.assertEqual(main._minikube_tunnel_process_profile("minikube tunnel"), "minikube")

    def test_batch_levels_override_applies_to_all_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = os.path.join(tmpdir, "plan.yaml")
            self._write_yaml(
                plan_path,
                {
                    "runs": [
                        {
                            "name": "local-inesdata",
                            "topology": "local",
                            "adapter": "inesdata",
                            "levels": [1, 2, 3, 4, 5, 6],
                        },
                        {
                            "name": "vm-single-edc",
                            "topology": "vm-single",
                            "adapter": "edc",
                            "levels": [5, 6],
                        },
                    ],
                },
            )

            observed_runs = []

            def fake_run_batch_levels(run, **kwargs):
                observed_runs.append((run["name"], list(run["levels"])))
                return {"status": "completed", "adapter": run["adapter"], "topology": run["topology"], "levels": []}

            with mock.patch.object(main, "_run_batch_levels", side_effect=fake_run_batch_levels):
                result = main.run_batch(
                    plan_path=plan_path,
                    levels_override="6",
                    adapter_registry={"inesdata": "fake:Adapter", "edc": "fake:Adapter"},
                )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            observed_runs,
            [
                ("local-inesdata", [6]),
                ("vm-single-edc", [6]),
            ],
        )

    def test_batch_levels_override_accepts_comma_separated_sequence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = os.path.join(tmpdir, "plan.yaml")
            self._write_yaml(
                plan_path,
                {
                    "runs": [
                        {
                            "name": "local-inesdata",
                            "topology": "local",
                            "adapter": "inesdata",
                            "levels": [1, 2, 3, 4, 5, 6],
                        }
                    ],
                },
            )

            observed = {}

            def fake_run_batch_levels(run, **kwargs):
                observed["levels"] = list(run["levels"])
                return {"status": "completed", "adapter": run["adapter"], "topology": run["topology"], "levels": []}

            with mock.patch.object(main, "_run_batch_levels", side_effect=fake_run_batch_levels):
                main.run_batch(
                    plan_path=plan_path,
                    levels_override="4,5,6",
                    adapter_registry={"inesdata": "fake:Adapter"},
                )

        self.assertEqual(observed["levels"], [4, 5, 6])

    def test_batch_run_filter_executes_only_matching_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = os.path.join(tmpdir, "plan.yaml")
            self._write_yaml(
                plan_path,
                {
                    "runs": [
                        {
                            "name": "local-edc",
                            "topology": "local",
                            "adapter": "edc",
                            "levels": [4],
                        },
                        {
                            "name": "vm-single-edc",
                            "topology": "vm-single",
                            "adapter": "edc",
                            "levels": [4],
                        },
                    ],
                },
            )

            observed_runs = []

            def fake_run_batch_levels(run, **kwargs):
                observed_runs.append(run["name"])
                return {"status": "completed", "adapter": run["adapter"], "topology": run["topology"], "levels": []}

            with mock.patch.object(main, "_run_batch_levels", side_effect=fake_run_batch_levels):
                result = main.run_batch(
                    plan_path=plan_path,
                    run_filter="vm-single-edc",
                    adapter_registry={"edc": "fake:Adapter"},
                )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(observed_runs, ["vm-single-edc"])
        self.assertEqual([run["name"] for run in result["runs"]], ["vm-single-edc"])

    def test_batch_run_filter_fails_when_no_run_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = os.path.join(tmpdir, "plan.yaml")
            self._write_yaml(
                plan_path,
                {
                    "runs": [
                        {
                            "name": "local-edc",
                            "topology": "local",
                            "adapter": "edc",
                            "levels": [4],
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(ValueError, "did not match any run"):
                main.run_batch(
                    plan_path=plan_path,
                    run_filter="vm-single-edc",
                    adapter_registry={"edc": "fake:Adapter"},
                )

    def test_batch_dry_run_does_not_execute_levels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = os.path.join(tmpdir, "plan.yaml")
            profile_path = os.path.join(tmpdir, "profile.env")
            self._write_text(profile_path, "PROFILE_TOPOLOGY=local\nPROFILE_ADAPTER=edc\n")
            self._write_yaml(
                plan_path,
                {
                    "runs": [
                        {
                            "name": "dry",
                            "topology": "local",
                            "adapter": "edc",
                            "levels": [1, 2],
                            "profile_path": profile_path,
                            "apply_profile": True,
                        }
                    ]
                },
            )

            with mock.patch.object(main, "_run_batch_levels", side_effect=AssertionError("must not run")), mock.patch.object(
                main,
                "apply_environment_configuration_profile",
                side_effect=AssertionError("profile must not be applied in dry-run"),
            ):
                result = main.run_batch(
                    plan_path=plan_path,
                    adapter_registry={"edc": "fake:Adapter"},
                    dry_run=True,
                )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["runs"][0]["status"], "planned")
        self.assertEqual(result["runs"][0]["profile"]["status"], "planned")

    def test_batch_init_creates_ignored_local_plan_and_secrets_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = os.path.join(tmpdir, ".profiles", "runs", "full-validation.yaml")
            secrets_path = os.path.join(tmpdir, ".secrets", "pionera.env")

            result = main._create_batch_template_files(plan_path=plan_path, secrets_path=secrets_path)

            self.assertEqual(result["status"], "created")
            self.assertTrue(os.path.exists(plan_path))
            self.assertTrue(os.path.exists(secrets_path))
            with open(plan_path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("validation/evidences", content)
            self.assertNotIn("validation/evidences/batch", content)
            self.assertIn("# Each run can override defaults.levels", content)
            self.assertIn("name: vm-distributed-edc", content)
            self.assertIn("levels: [1, 2, 3, 4, 5, 6]", content)
            self.assertIn("PIONERA_EDC_LOCAL_IMAGES_MODE: auto", content)
            mode = os.stat(secrets_path).st_mode & 0o077
            self.assertEqual(mode, 0)

    def test_local_batch_starts_minikube_tunnel_before_level_3(self):
        class FakeConfigAdapter:
            def load_deployer_config(self):
                return {"MINIKUBE_PROFILE": "demo-profile"}

        class FakeAdapter:
            config_adapter = FakeConfigAdapter()

        events = []
        run = {
            "adapter": "inesdata",
            "topology": "local",
            "levels": [1, 2, 3],
            "baseline": False,
            "local_minikube_tunnel": "auto",
        }

        def fake_run_level(adapter, level_id, **kwargs):
            events.append(f"level-{level_id}")
            return {"status": "completed", "level": level_id}

        def fake_start(profile):
            events.append(f"tunnel-{profile}")
            return {"status": "started", "profile": profile, "log": "/tmp/minikube-tunnel.log"}

        with mock.patch.object(main, "build_adapter", return_value=FakeAdapter()), mock.patch.object(
            main,
            "_start_batch_local_minikube_tunnel",
            side_effect=fake_start,
        ), mock.patch.object(main, "run_level", side_effect=fake_run_level):
            result = main._run_batch_levels(run)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(events, ["level-1", "level-2", "tunnel-demo-profile", "level-3"])
        self.assertEqual(result["minikube_tunnel"]["status"], "started")

    def test_local_batch_does_not_start_minikube_tunnel_when_not_needed(self):
        class FakeAdapter:
            config_adapter = None

        run = {
            "adapter": "edc",
            "topology": "local",
            "levels": [1, 2],
            "baseline": False,
            "local_minikube_tunnel": "auto",
        }

        with mock.patch.object(main, "build_adapter", return_value=FakeAdapter()), mock.patch.object(
            main,
            "_start_batch_local_minikube_tunnel",
            side_effect=AssertionError("tunnel must not start before Level 3"),
        ), mock.patch.object(
            main,
            "run_level",
            side_effect=lambda adapter, level_id, **kwargs: {"status": "completed", "level": level_id},
        ):
            result = main._run_batch_levels(run)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["minikube_tunnel"]["status"], "skipped")

    def test_local_batch_respects_disabled_minikube_tunnel(self):
        class FakeAdapter:
            config_adapter = None

        run = {
            "adapter": "edc",
            "topology": "local",
            "levels": [3],
            "baseline": False,
            "local_minikube_tunnel": False,
        }

        with mock.patch.object(main, "build_adapter", return_value=FakeAdapter()), mock.patch.object(
            main,
            "_start_batch_local_minikube_tunnel",
            side_effect=AssertionError("tunnel is disabled for this run"),
        ), mock.patch.object(
            main,
            "run_level",
            side_effect=lambda adapter, level_id, **kwargs: {"status": "completed", "level": level_id},
        ):
            result = main._run_batch_levels(run)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["minikube_tunnel"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
