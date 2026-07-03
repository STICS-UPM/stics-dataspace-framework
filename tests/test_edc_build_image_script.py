import os
import stat
import subprocess
import tempfile
import time
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT_PATH = os.path.join(PROJECT_ROOT, "adapters", "edc", "scripts", "build_image.sh")
DASHBOARD_SCRIPT_PATH = os.path.join(
    PROJECT_ROOT,
    "adapters",
    "edc",
    "scripts",
    "build_dashboard_image.sh",
)
SYNC_DASHBOARD_SCRIPT_PATH = os.path.join(
    PROJECT_ROOT,
    "adapters",
    "edc",
    "scripts",
    "sync_dashboard_sources.sh",
)
LOCAL_EDC_SERVICE_EXTENSIONS_PATH = os.path.join(
    PROJECT_ROOT,
    "adapters",
    "edc",
    "sources",
    "connector",
    "final-connector",
    "src",
    "main",
    "resources",
    "META-INF",
    "services",
    "org.eclipse.edc.spi.system.ServiceExtension",
)
EDC_DASHBOARD_ASSET_SERVICE_OVERLAY_PATH = os.path.join(
    PROJECT_ROOT,
    "adapters",
    "edc",
    "overlays",
    "dashboard",
    "projects",
    "dashboard-core",
    "assets",
    "src",
    "asset.service.ts",
)


def _touch(path, *, contents="", executable=False, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(contents)
    if executable:
        current = os.stat(path).st_mode
        os.chmod(path, current | stat.S_IXUSR)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class EdcBuildImageScriptTests(unittest.TestCase):
    def test_dashboard_image_script_invokes_sync_with_bash(self):
        with open(DASHBOARD_SCRIPT_PATH, "r", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn('bash "$SCRIPT_DIR/sync_dashboard_sources.sh" --apply --source "$DASHBOARD_REPO_URL" --ref "$DASHBOARD_REPO_REF"', script)
        self.assertIn('--dashboard-app-dir "$CONTEXT_DIR/app"', script)
        self.assertNotIn("if [[ ! -d \"$DASHBOARD_REPO_DIR/.git\" ]]", script)
        self.assertNotIn('bash "$APPLY_OVERLAYS_SCRIPT" --apply --target dashboard\n', script)

    def test_dashboard_image_script_pins_official_dashboard_reference(self):
        with open(DASHBOARD_SCRIPT_PATH, "r", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("PIONERA_EDC_DASHBOARD_REPO_REF", script)
        self.assertIn("a4cb3e659e1fd3abfa9516a036c261b19432ec13", script)

    def test_sync_dashboard_sources_supports_pinned_reference_without_overwriting_local_changes(self):
        with open(SYNC_DASHBOARD_SCRIPT_PATH, "r", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("--ref|--revision|--commit", script)
        self.assertIn('git -C "$TARGET_DIR" rev-parse --is-inside-work-tree', script)
        self.assertIn("Dashboard sources already at requested ref", script)
        self.assertIn("keeping local changes", script)
        self.assertIn('git -C "$TARGET_DIR" checkout --detach "$SOURCE_REF"', script)
        self.assertIn("Dashboard source tree has local changes", script)
        self.assertIn("Dashboard source target exists but is not a Git working tree", script)
        self.assertIn("Refusing to checkout", script)

    def test_local_edc_service_extensions_register_adapter_kafka_bridge(self):
        if not os.path.isfile(LOCAL_EDC_SERVICE_EXTENSIONS_PATH):
            self.skipTest("local EDC connector source checkout is not materialized")

        with open(LOCAL_EDC_SERVICE_EXTENSIONS_PATH, "r", encoding="utf-8") as handle:
            entries = [line.strip() for line in handle.readlines() if line.strip()]

        self.assertIn("com.pionera.assetfilter.infer.InferenceExtension", entries)
        self.assertIn("com.pionera.assetfilter.proxy.CustomProxyDataPlaneExtension", entries)

    def test_dashboard_asset_service_overlay_exposes_rdf_validation_api(self):
        with open(EDC_DASHBOARD_ASSET_SERVICE_OVERLAY_PATH, "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn("testRdfAsset(", content)
        self.assertIn("/validation/rdf_asset", content)
        self.assertIn("DashboardStateService", content)

    def _create_fake_source_tree(self, root_dir):
        _touch(os.path.join(root_dir, "settings.gradle.kts"), contents="rootProject.name = \"connector\"\n")
        _touch(os.path.join(root_dir, "gradle", "libs.versions.toml"), contents="[versions]\n")
        _touch(os.path.join(root_dir, "gradlew"), contents="#!/usr/bin/env bash\n", executable=True)
        _touch(os.path.join(root_dir, "gradle", "wrapper", "gradle-wrapper.jar"), contents="jar")
        _touch(
            os.path.join(
                root_dir,
                "final-connector",
                "build.gradle.kts",
            ),
            contents="plugins {}\n",
        )
        _touch(
            os.path.join(
                root_dir,
                "final-connector",
                "src",
                "main",
                "java",
                "Example.java",
            ),
            contents="class Example {}\n",
        )
        _touch(
            os.path.join(
                root_dir,
                "final-connector",
                "build",
                "libs",
                "connector.jar",
            ),
            contents="fake-jar",
        )

    def test_build_image_reuses_existing_connector_jar_when_inputs_are_older(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_fake_source_tree(tmpdir)
            jar_path = os.path.join(
                tmpdir,
                "final-connector",
                "build",
                "libs",
                "connector.jar",
            )
            now = time.time()
            os.utime(jar_path, (now, now))

            completed = subprocess.run(
                [
                    "bash",
                    SCRIPT_PATH,
                    "--source-dir",
                    tmpdir,
                    "--skip-minikube-load",
                ],
                text=True,
                capture_output=True,
                cwd=PROJECT_ROOT,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Reusing existing connector jar", completed.stdout)
        self.assertNotIn("GradleWrapperMain", completed.stdout)

    def test_build_image_rebuilds_connector_jar_when_runtime_inputs_changed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_fake_source_tree(tmpdir)
            runtime_build_file = os.path.join(
                tmpdir,
                "final-connector",
                "build.gradle.kts",
            )
            jar_path = os.path.join(
                tmpdir,
                "final-connector",
                "build",
                "libs",
                "connector.jar",
            )
            base_time = time.time()
            os.utime(jar_path, (base_time, base_time))
            os.utime(runtime_build_file, (base_time + 10, base_time + 10))

            completed = subprocess.run(
                [
                    "bash",
                    SCRIPT_PATH,
                    "--source-dir",
                    tmpdir,
                    "--skip-minikube-load",
                ],
                text=True,
                capture_output=True,
                cwd=PROJECT_ROOT,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Connector jar is outdated and will be rebuilt", completed.stdout)
        self.assertIn("source changed: final-connector/build.gradle.kts", completed.stdout)
        self.assertIn("GradleWrapperMain", completed.stdout)

    def test_build_image_uses_bounded_gradle_retry_defaults_for_rebuilds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_fake_source_tree(tmpdir)
            runtime_build_file = os.path.join(
                tmpdir,
                "final-connector",
                "build.gradle.kts",
            )
            jar_path = os.path.join(
                tmpdir,
                "final-connector",
                "build",
                "libs",
                "connector.jar",
            )
            base_time = time.time()
            os.utime(jar_path, (base_time, base_time))
            os.utime(runtime_build_file, (base_time + 10, base_time + 10))
            env = os.environ.copy()
            env.update(
                {
                    "PIONERA_EDC_GRADLE_RETRIES": "3",
                    "PIONERA_EDC_GRADLE_MAX_WORKERS": "1",
                    "PIONERA_EDC_GRADLE_JVMARGS": "-Xmx768m -XX:MaxMetaspaceSize=384m -Dfile.encoding=UTF-8",
                }
            )

            completed = subprocess.run(
                [
                    "bash",
                    SCRIPT_PATH,
                    "--source-dir",
                    tmpdir,
                    "--skip-minikube-load",
                ],
                text=True,
                capture_output=True,
                cwd=PROJECT_ROOT,
                env=env,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Gradle retries:    3", completed.stdout)
        self.assertIn("Gradle max workers: 1", completed.stdout)
        self.assertIn("Gradle JVM args:   -Xmx768m -XX:MaxMetaspaceSize=384m -Dfile.encoding=UTF-8", completed.stdout)
        self.assertIn("--max-workers=1", completed.stdout)
        self.assertIn("-Dorg.gradle.workers.max=1", completed.stdout)
        self.assertIn("-Dorg.gradle.jvmargs=-Xmx768m\\ -XX:MaxMetaspaceSize=384m\\ -Dfile.encoding=UTF-8", completed.stdout)

    def test_build_image_dry_run_allows_missing_connector_jar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_fake_source_tree(tmpdir)
            jar_path = os.path.join(
                tmpdir,
                "final-connector",
                "build",
                "libs",
                "connector.jar",
            )
            os.remove(jar_path)

            completed = subprocess.run(
                [
                    "bash",
                    SCRIPT_PATH,
                    "--source-dir",
                    tmpdir,
                    "--skip-minikube-load",
                ],
                text=True,
                capture_output=True,
                cwd=PROJECT_ROOT,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Dry run: connector jar would be created", completed.stdout)
        self.assertIn("docker build", completed.stdout)

    def test_build_image_refuses_custom_source_sync_when_source_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_source = os.path.join(tmpdir, "missing-connector")

            completed = subprocess.run(
                [
                    "bash",
                    SCRIPT_PATH,
                    "--source-dir",
                    missing_source,
                    "--skip-minikube-load",
                ],
                text=True,
                capture_output=True,
                cwd=PROJECT_ROOT,
                check=False,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Refusing to synchronize into a custom source directory", completed.stderr)
        self.assertNotIn("sync_sources.sh", completed.stdout + completed.stderr)
        self.assertNotIn("git clone", completed.stdout + completed.stderr)

    def test_build_image_refreshes_minikube_image_before_loading_stable_tag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_fake_source_tree(tmpdir)

            completed = subprocess.run(
                [
                    "bash",
                    SCRIPT_PATH,
                    "--source-dir",
                    tmpdir,
                ],
                text=True,
                capture_output=True,
                cwd=PROJECT_ROOT,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "minikube -p \"minikube\" ssh \"docker image rm -f 'validation-environment/edc-connector:local' >/dev/null 2>&1 || true\"",
            completed.stdout,
        )
        self.assertIn(
            "minikube -p \"minikube\" image load \"validation-environment/edc-connector:local\"",
            completed.stdout,
        )

    def test_build_image_imports_local_image_into_k3s_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_fake_source_tree(tmpdir)

            completed = subprocess.run(
                [
                    "bash",
                    SCRIPT_PATH,
                    "--source-dir",
                    tmpdir,
                    "--cluster-runtime",
                    "k3s",
                ],
                text=True,
                capture_output=True,
                cwd=PROJECT_ROOT,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Cluster runtime:   k3s", completed.stdout)
        self.assertIn("docker save \"validation-environment/edc-connector:local\"", completed.stdout)
        self.assertIn("sudo k3s ctr -n k8s.io images import", completed.stdout)
        self.assertNotIn("minikube -p \"minikube\" image load", completed.stdout)


if __name__ == "__main__":
    unittest.main()
