import os
import tempfile
import unittest
from unittest import mock

from deployers.infrastructure.lib.contracts import DeploymentContext, ValidationProfile
from validation.ui import ui_runner


class UiRunnerInteractionMarkersTests(unittest.TestCase):
    def _context(self):
        return DeploymentContext(
            deployer="inesdata",
            topology="local",
            environment="DEV",
            dataspace_name="demo",
            ds_domain_base="dev.ds.dataspaceunit.upm",
            connectors=["conn-citycouncil-demo", "conn-company-demo"],
            config={"KC_URL": "http://keycloak.dev.ed.dataspaceunit.upm"},
        )

    def _profile(self):
        return ValidationProfile(
            adapter="inesdata",
            playwright_enabled=True,
            playwright_config="validation/ui/playwright.config.ts",
        )

    def test_playwright_validation_enables_interaction_markers_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=self._context(),
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKERS"], "1")
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS"], "150")

    def test_playwright_validation_respects_explicit_marker_override(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            os.environ,
            {"PLAYWRIGHT_INTERACTION_MARKERS": "0"},
        ), mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=self._context(),
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKERS"], "0")


if __name__ == "__main__":
    unittest.main()
