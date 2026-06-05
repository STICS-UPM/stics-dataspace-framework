import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import inesdata_local_deploy


class InesdataLocalDeploySeedTests(unittest.TestCase):
    def test_seed_model_server_base_prefers_connector_url(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = inesdata_local_deploy._seed_model_server_base_url(
                {
                    "TOPOLOGY": "vm-distributed",
                    "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL": "http://org1.example.test/model-server/",
                    "COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test",
                }
            )

        self.assertEqual(result, "http://org1.example.test/model-server")

    def test_seed_model_server_base_infers_vm_distributed_http_public_url(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = inesdata_local_deploy._seed_model_server_base_url(
                {
                    "TOPOLOGY": "vm-distributed",
                    "VM_COMMON_PUBLIC_URL": "https://org1.example.test",
                    "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH": "/model-server",
                }
            )

        self.assertEqual(result, "http://org1.example.test/model-server")

    def test_seed_model_server_mode_passes_real_modes_to_seed_script(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                inesdata_local_deploy._seed_model_server_mode(
                    {"AI_MODEL_HUB_MODEL_SERVER_MODE": "combined-real"}
                ),
                "combined",
            )
            self.assertEqual(
                inesdata_local_deploy._seed_model_server_mode(
                    {"AI_MODEL_HUB_MODEL_SERVER_MODE": "external"}
                ),
                "use-cases",
            )


if __name__ == "__main__":
    unittest.main()
