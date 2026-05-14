import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main


class Level6ConsoleLogTests(unittest.TestCase):
    def test_capture_tees_python_and_subprocess_output_to_experiment_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict("os.environ", {"PIONERA_LEVEL6_CONSOLE_LOG": "1"}):
                with main._Level6ConsoleCapture(tmpdir, mirror_output=False):
                    print("framework level 6 line")
                    subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            "import sys; print('subprocess stdout line'); print('subprocess stderr line', file=sys.stderr)",
                        ],
                        check=True,
                    )

            content = (Path(tmpdir) / main.LEVEL6_CONSOLE_LOG_FILENAME).read_text(encoding="utf-8")

        self.assertIn("framework level 6 line", content)
        self.assertIn("subprocess stdout line", content)
        self.assertIn("subprocess stderr line", content)

    def test_capture_uses_pseudo_terminal_when_original_stdout_is_tty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            previous_force_color = os.environ.get("FORCE_COLOR")
            with mock.patch.dict("os.environ", {"PIONERA_LEVEL6_CONSOLE_LOG": "1"}, clear=False), mock.patch(
                "main.os.isatty",
                return_value=True,
            ):
                with main._Level6ConsoleCapture(tmpdir, mirror_output=False):
                    subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            "import os; print(f'child stdout is tty={os.isatty(1)}')",
                        ],
                        check=True,
                    )

            content = (Path(tmpdir) / main.LEVEL6_CONSOLE_LOG_FILENAME).read_text(encoding="utf-8")

        self.assertIn("child stdout is tty=True", content)
        self.assertEqual(os.environ.get("FORCE_COLOR"), previous_force_color)


if __name__ == "__main__":
    unittest.main()
