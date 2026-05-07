import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from adapters.inesdata.infrastructure import INESDataInfrastructureAdapter


class HostsManagementTests(unittest.TestCase):
    def test_manage_hosts_entries_updates_all_wsl_hosts_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_hosts = os.path.join(tmpdir, "windows-hosts")
            linux_hosts = os.path.join(tmpdir, "linux-hosts")

            for path in (windows_hosts, linux_hosts):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("127.0.0.1 localhost\n")

            infrastructure = INESDataInfrastructureAdapter(
                run=lambda *_args, **_kwargs: None,
                run_silent=lambda *_args, **_kwargs: None,
                auto_mode_getter=lambda: True,
            )
            infrastructure.is_wsl = lambda: True
            infrastructure.get_hosts_paths = lambda: [windows_hosts, linux_hosts]

            infrastructure.manage_hosts_entries([
                "127.0.0.1 backend-demo.dev.ds.dataspaceunit.upm",
            ], auto_confirm=True)

            for path in (windows_hosts, linux_hosts):
                with open(path, "r", encoding="utf-8") as handle:
                    content = handle.read()
                self.assertIn("127.0.0.1 backend-demo.dev.ds.dataspaceunit.upm", content)

    def test_manage_hosts_entries_accepts_tab_separated_hosts_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hosts_path = os.path.join(tmpdir, "hosts")
            desired_entry = "127.0.0.1 backend-demo.dev.ds.dataspaceunit.upm"

            with open(hosts_path, "w", encoding="utf-8") as handle:
                handle.write("127.0.0.1\tbackend-demo.dev.ds.dataspaceunit.upm\n")

            infrastructure = INESDataInfrastructureAdapter(
                run=lambda *_args, **_kwargs: None,
                run_silent=lambda *_args, **_kwargs: None,
                auto_mode_getter=lambda: True,
            )
            infrastructure.get_hosts_paths = lambda: [hosts_path]

            infrastructure.manage_hosts_entries([desired_entry], auto_confirm=True)

            with open(hosts_path, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()

            self.assertEqual(lines, ["127.0.0.1\tbackend-demo.dev.ds.dataspaceunit.upm"])


if __name__ == "__main__":
    unittest.main()