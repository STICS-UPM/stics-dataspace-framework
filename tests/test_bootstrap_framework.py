import os
import platform
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class BootstrapFrameworkTests(unittest.TestCase):
    def _prepare_workspace(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        root = tmpdir.name

        os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
        shutil.copy2(
            os.path.join(PROJECT_ROOT, "scripts", "bootstrap_framework.sh"),
            os.path.join(root, "scripts", "bootstrap_framework.sh"),
        )

        with open(os.path.join(root, "requirements.txt"), "w", encoding="utf-8") as handle:
            handle.write("")
        os.makedirs(os.path.join(root, "validation", "ui"), exist_ok=True)

        for deployer, marker in (
            ("infrastructure", "KC_URL=http://keycloak.local\n"),
            ("inesdata", "DS_1_NAME=demo\n"),
            ("edc", "EDC_DASHBOARD_ENABLED=true\n"),
        ):
            deployer_dir = os.path.join(root, "deployers", deployer)
            os.makedirs(deployer_dir, exist_ok=True)
            with open(os.path.join(deployer_dir, "deployer.config.example"), "w", encoding="utf-8") as handle:
                handle.write(marker)

        fake_bin = os.path.join(root, "fake-bin")
        os.makedirs(fake_bin, exist_ok=True)
        fake_python = os.path.join(fake_bin, "python3")
        with open(fake_python, "w", encoding="utf-8") as handle:
            handle.write(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
                      venv_dir="${3:?}"
                      mkdir -p "$venv_dir/bin"
                      cat > "$venv_dir/bin/python" <<'PY'
                    #!/usr/bin/env bash
                    exit 0
                    PY
                      chmod +x "$venv_dir/bin/python"
                    fi
                    exit 0
                    """
                )
            )
        os.chmod(fake_python, os.stat(fake_python).st_mode | stat.S_IXUSR)

        node_path = os.path.join(fake_bin, "node")
        with open(node_path, "w", encoding="utf-8") as handle:
            handle.write(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    if [[ "${1:-}" == "--version" ]]; then
                      printf 'v20.0.0\\n'
                    fi
                    exit 0
                    """
                )
            )
        os.chmod(node_path, os.stat(node_path).st_mode | stat.S_IXUSR)

        for command_name in ("npm", "npx"):
            command_path = os.path.join(fake_bin, command_name)
            with open(command_path, "w", encoding="utf-8") as handle:
                if command_name == "npx":
                    handle.write(
                        textwrap.dedent(
                            """\
                            #!/usr/bin/env bash
                            set -euo pipefail
                            if [[ -n "${BOOTSTRAP_NPX_LOG:-}" ]]; then
                              printf '%s\n' "$*" >> "$BOOTSTRAP_NPX_LOG"
                            fi
                            exit 0
                            """
                        )
                    )
                else:
                    handle.write("#!/usr/bin/env bash\nexit 0\n")
            os.chmod(command_path, os.stat(command_path).st_mode | stat.S_IXUSR)

        java_path = os.path.join(fake_bin, "java")
        with open(java_path, "w", encoding="utf-8") as handle:
            handle.write(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    printf 'openjdk version "17.0.10" 2024-01-16\\n' >&2
                    exit 0
                    """
                )
            )
        os.chmod(java_path, os.stat(java_path).st_mode | stat.S_IXUSR)
        return root, fake_bin

    def test_bootstrap_fails_fast_with_vm_ubuntu_hint_when_npm_is_missing(self):
        root, fake_bin = self._prepare_workspace()
        with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as handle:
            handle.write('{"private": true}\n')
        for command_name in ("npm", "npx", "node"):
            os.remove(os.path.join(fake_bin, command_name))
        for command_name in ("bash", "cat", "chmod", "dirname", "mkdir", "uname"):
            os.symlink(shutil.which(command_name), os.path.join(fake_bin, command_name))
        node_path = os.path.join(fake_bin, "node")
        with open(node_path, "w", encoding="utf-8") as handle:
            handle.write(
                textwrap.dedent(
                    """\
                    #!/bin/bash
                    set -euo pipefail
                    if [[ "${1:-}" == "--version" ]]; then
                      printf 'v20.0.0\\n'
                      exit 0
                    fi
                    exit 0
                    """
                )
            )
        os.chmod(node_path, os.stat(node_path).st_mode | stat.S_IXUSR)
        env = dict(os.environ)
        env["PATH"] = fake_bin

        result = subprocess.run(
            [
                "/bin/bash",
                os.path.join(root, "scripts", "bootstrap_framework.sh"),
                "--skip-ui-node",
                "--skip-playwright",
                "--without-system-deps",
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("npm is required for Newman/Playwright validation", result.stderr)
        self.assertIn("sudo apt-get update && sudo apt-get install -y nodejs npm", result.stderr)
        self.assertNotIn("Installing Python requirements", result.stdout)

    def test_bootstrap_installs_missing_node_tooling_on_linux_when_system_deps_are_enabled(self):
        root, fake_bin = self._prepare_workspace()
        with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as handle:
            handle.write('{"private": true}\n')
        for command_name in ("npm", "npx", "node"):
            os.remove(os.path.join(fake_bin, command_name))
        for command_name in ("bash", "cat", "chmod", "dirname", "mkdir", "uname"):
            os.symlink(shutil.which(command_name), os.path.join(fake_bin, command_name))
        install_log = os.path.join(root, "apt.log")
        sudo_path = os.path.join(fake_bin, "sudo")
        with open(sudo_path, "w", encoding="utf-8") as handle:
            handle.write(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    "$@"
                    """
                )
            )
        os.chmod(sudo_path, os.stat(sudo_path).st_mode | stat.S_IXUSR)
        apt_get_path = os.path.join(fake_bin, "apt-get")
        with open(apt_get_path, "w", encoding="utf-8") as handle:
            handle.write(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    printf '%s\n' "$*" >> "${BOOTSTRAP_APT_LOG:?}"
                    if [[ "${1:-}" == "install" ]]; then
                      fake_bin="${BOOTSTRAP_FAKE_BIN:?}"
                      printf '%s\n' '#!/usr/bin/env bash' 'if [[ "${1:-}" == "--version" ]]; then printf "v20.0.0\\n"; fi' 'exit 0' > "$fake_bin/node"
                      printf '%s\n' '#!/usr/bin/env bash' 'exit 0' > "$fake_bin/npm"
                      printf '%s\n' '#!/usr/bin/env bash' 'exit 0' > "$fake_bin/npx"
                      chmod +x "$fake_bin/node" "$fake_bin/npm" "$fake_bin/npx"
                    fi
                    exit 0
                    """
                )
            )
        os.chmod(apt_get_path, os.stat(apt_get_path).st_mode | stat.S_IXUSR)
        env = dict(os.environ)
        env["PATH"] = fake_bin
        env["BOOTSTRAP_APT_LOG"] = install_log
        env["BOOTSTRAP_FAKE_BIN"] = fake_bin

        result = subprocess.run(
            [
                "/bin/bash",
                os.path.join(root, "scripts", "bootstrap_framework.sh"),
                "--skip-ui-node",
                "--skip-playwright",
                "--skip-deployer-config",
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Node.js/npm tooling is missing or too old", result.stdout)
        with open(install_log, encoding="utf-8") as handle:
            apt_commands = handle.read()
        self.assertIn("update", apt_commands)
        self.assertIn("install -y nodejs npm", apt_commands)

    def test_bootstrap_fails_fast_with_vm_ubuntu_hint_when_java_is_missing_without_system_deps(self):
        root, fake_bin = self._prepare_workspace()
        with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as handle:
            handle.write('{"private": true}\n')
        os.remove(os.path.join(fake_bin, "java"))
        for command_name in ("bash", "cat", "chmod", "dirname", "mkdir", "uname"):
            target = shutil.which(command_name)
            if target and not os.path.exists(os.path.join(fake_bin, command_name)):
                os.symlink(target, os.path.join(fake_bin, command_name))
        env = dict(os.environ)
        env["PATH"] = fake_bin

        result = subprocess.run(
            [
                "bash",
                os.path.join(root, "scripts", "bootstrap_framework.sh"),
                "--skip-root-node",
                "--skip-ui-node",
                "--skip-playwright",
                "--without-system-deps",
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Java 17+ is required for local connector image builds", result.stderr)
        self.assertIn("sudo apt-get update && sudo apt-get install -y openjdk-17-jdk", result.stderr)
        self.assertNotIn("Installing Python requirements", result.stdout)

    def test_bootstrap_installs_missing_java_tooling_on_linux_when_system_deps_are_enabled(self):
        root, fake_bin = self._prepare_workspace()
        with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as handle:
            handle.write('{"private": true}\n')
        os.remove(os.path.join(fake_bin, "java"))
        for command_name in ("bash", "cat", "chmod", "cp", "dirname", "mkdir", "uname"):
            target = shutil.which(command_name)
            if target and not os.path.exists(os.path.join(fake_bin, command_name)):
                os.symlink(target, os.path.join(fake_bin, command_name))
        install_log = os.path.join(root, "apt.log")
        sudo_path = os.path.join(fake_bin, "sudo")
        with open(sudo_path, "w", encoding="utf-8") as handle:
            handle.write(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    "$@"
                    """
                )
            )
        os.chmod(sudo_path, os.stat(sudo_path).st_mode | stat.S_IXUSR)
        apt_get_path = os.path.join(fake_bin, "apt-get")
        with open(apt_get_path, "w", encoding="utf-8") as handle:
            handle.write(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    printf '%s\n' "$*" >> "${BOOTSTRAP_APT_LOG:?}"
                    if [[ "${1:-}" == "install" && "$*" == *"openjdk-17-jdk"* ]]; then
                      fake_bin="${BOOTSTRAP_FAKE_BIN:?}"
                      printf '%s\n' '#!/usr/bin/env bash' "printf 'openjdk version \"17.0.10\" 2024-01-16\\n' >&2" 'exit 0' > "$fake_bin/java"
                      chmod +x "$fake_bin/java"
                    fi
                    exit 0
                    """
                )
            )
        os.chmod(apt_get_path, os.stat(apt_get_path).st_mode | stat.S_IXUSR)
        env = dict(os.environ)
        env["PATH"] = fake_bin
        env["BOOTSTRAP_APT_LOG"] = install_log
        env["BOOTSTRAP_FAKE_BIN"] = fake_bin

        result = subprocess.run(
            [
                "/bin/bash",
                os.path.join(root, "scripts", "bootstrap_framework.sh"),
                "--skip-root-node",
                "--skip-ui-node",
                "--skip-playwright",
                "--skip-deployer-config",
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Java 17+ tooling is missing or too old", result.stdout)
        with open(install_log, encoding="utf-8") as handle:
            apt_commands = handle.read()
        self.assertIn("update", apt_commands)
        self.assertIn("install -y openjdk-17-jdk", apt_commands)

    def test_bootstrap_initializes_deployer_configs(self):
        root, fake_bin = self._prepare_workspace()
        env = dict(os.environ)
        env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

        result = subprocess.run(
            [
                "bash",
                os.path.join(root, "scripts", "bootstrap_framework.sh"),
                "--skip-root-node",
                "--skip-ui-node",
                "--skip-playwright",
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(os.path.isfile(os.path.join(root, "deployers", "infrastructure", "deployer.config")))
        self.assertTrue(os.path.isfile(os.path.join(root, "deployers", "inesdata", "deployer.config")))
        self.assertTrue(os.path.isfile(os.path.join(root, "deployers", "edc", "deployer.config")))

        with open(os.path.join(root, "deployers", "infrastructure", "deployer.config"), encoding="utf-8") as handle:
            self.assertIn("KC_URL=http://keycloak.local", handle.read())
        with open(os.path.join(root, "deployers", "inesdata", "deployer.config"), encoding="utf-8") as handle:
            self.assertIn("DS_1_NAME=demo", handle.read())
        with open(os.path.join(root, "deployers", "edc", "deployer.config"), encoding="utf-8") as handle:
            self.assertIn("EDC_DASHBOARD_ENABLED=true", handle.read())

    def test_bootstrap_skip_deployer_config_leaves_configs_absent(self):
        root, fake_bin = self._prepare_workspace()
        env = dict(os.environ)
        env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

        result = subprocess.run(
            [
                "bash",
                os.path.join(root, "scripts", "bootstrap_framework.sh"),
                "--skip-root-node",
                "--skip-ui-node",
                "--skip-playwright",
                "--skip-deployer-config",
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(os.path.exists(os.path.join(root, "deployers", "infrastructure", "deployer.config")))
        self.assertFalse(os.path.exists(os.path.join(root, "deployers", "inesdata", "deployer.config")))
        self.assertFalse(os.path.exists(os.path.join(root, "deployers", "edc", "deployer.config")))

    def test_bootstrap_installs_playwright_system_deps_by_default_on_linux(self):
        root, fake_bin = self._prepare_workspace()
        npx_log = os.path.join(root, "npx.log")
        env = dict(os.environ)
        env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
        env["BOOTSTRAP_NPX_LOG"] = npx_log

        result = subprocess.run(
            [
                "bash",
                os.path.join(root, "scripts", "bootstrap_framework.sh"),
                "--skip-root-node",
                "--skip-ui-node",
                "--skip-deployer-config",
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        with open(npx_log, encoding="utf-8") as handle:
            npx_commands = handle.read()

        expected = (
            "playwright install --with-deps"
            if platform.system() == "Linux"
            else "playwright install"
        )
        self.assertIn(expected, npx_commands)

    def test_bootstrap_can_skip_playwright_system_deps(self):
        root, fake_bin = self._prepare_workspace()
        npx_log = os.path.join(root, "npx.log")
        env = dict(os.environ)
        env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
        env["BOOTSTRAP_NPX_LOG"] = npx_log

        result = subprocess.run(
            [
                "bash",
                os.path.join(root, "scripts", "bootstrap_framework.sh"),
                "--skip-root-node",
                "--skip-ui-node",
                "--skip-deployer-config",
                "--without-system-deps",
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        with open(npx_log, encoding="utf-8") as handle:
            npx_commands = handle.read()
        self.assertIn("playwright install", npx_commands)
        self.assertNotIn("--with-deps", npx_commands)


if __name__ == "__main__":
    unittest.main()
