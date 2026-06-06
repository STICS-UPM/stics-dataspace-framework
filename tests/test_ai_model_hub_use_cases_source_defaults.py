import os
import unittest
from unittest import mock

from adapters.shared.components import SharedComponentsAdapter
from deployers.shared.lib import ai_model_hub_model_server as model_server


class AIModelHubUseCasesSourceDefaultsTests(unittest.TestCase):
    def test_blank_model_server_mode_uses_controlled_mock_server(self):
        self.assertEqual(model_server.model_server_mode({})[0], "mock")
        self.assertEqual(model_server.source_repository({}), "")

    def test_explicit_real_source_is_prepared_under_sources_directory(self):
        adapter = SharedComponentsAdapter.__new__(SharedComponentsAdapter)
        source_dir = os.path.join(
            adapter._project_root_dir(),
            "adapters",
            "inesdata",
            "sources",
            "AIModelHub-Use-Cases",
        )
        clone_calls = []

        def fake_run(args, check):
            clone_calls.append((tuple(args), check))
            return None

        with (
            mock.patch("adapters.shared.components.os.path.isdir", return_value=False),
            mock.patch("adapters.shared.components.os.makedirs"),
            mock.patch("adapters.shared.components.subprocess.run", side_effect=fake_run),
        ):
            resolved = adapter._ai_model_hub_model_server_source_dir(
                {"AI_MODEL_HUB_MODEL_SERVER_MODE": "combined"}
            )

        self.assertEqual(resolved, source_dir)
        self.assertEqual(
            clone_calls,
            [
                (
                    (
                        "git",
                        "clone",
                        model_server.DEFAULT_USE_CASES_SOURCE_REPOSITORY,
                        source_dir,
                    ),
                    True,
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
