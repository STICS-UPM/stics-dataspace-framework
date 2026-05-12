import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from adapters.inesdata.config import INESDataConfigAdapter, InesdataConfig
from adapters.inesdata.connectors import INESDataConnectorsAdapter


class DataspaceMetadataConfig(InesdataConfig):
    @classmethod
    def script_dir(cls):
        return cls._script_dir


class InesdataConnectorDataspaceMetadataTests(unittest.TestCase):
    def _make_adapter(self, tmpdir):
        DataspaceMetadataConfig._script_dir = tmpdir
        return INESDataConnectorsAdapter(
            run=lambda *_args, **_kwargs: object(),
            run_silent=lambda *_args, **_kwargs: "",
            auto_mode_getter=lambda: False,
            infrastructure_adapter=object(),
            config_adapter=INESDataConfigAdapter(DataspaceMetadataConfig),
            config_cls=DataspaceMetadataConfig,
        )

    def test_load_dataspace_connectors_exposes_connector_role_and_namespace_plan_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)
            with open(
                os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("DS_DOMAIN_BASE=dev.ds.dataspaceunit.upm\n")
            with open(
                os.path.join(tmpdir, "deployers", "inesdata", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    "DS_1_NAME=pilot\n"
                    "DS_1_NAMESPACE=pilot\n"
                    "DS_1_CONNECTORS=citycouncil,company\n"
                    "NAMESPACE_PROFILE=role-aligned\n"
                )

            adapter = self._make_adapter(tmpdir)
            dataspaces = adapter.load_dataspace_connectors()

        self.assertEqual(len(dataspaces), 1)
        dataspace = dataspaces[0]
        self.assertEqual(dataspace["namespace_profile"], "role-aligned")
        self.assertEqual(dataspace["namespace_roles"]["registration_service_namespace"], "pilot-core")
        self.assertEqual(dataspace["namespace_roles"]["provider_namespace"], "pilot")
        self.assertEqual(dataspace["namespace_roles"]["consumer_namespace"], "pilot")
        self.assertEqual(dataspace["planned_namespace_roles"]["provider_namespace"], "pilot-provider")
        self.assertEqual(dataspace["planned_namespace_roles"]["consumer_namespace"], "pilot-consumer")
        self.assertEqual(
            dataspace["connector_roles"],
            {
                "provider": "conn-citycouncil-pilot",
                "consumer": "conn-company-pilot",
                "additional": [],
            },
        )
        self.assertEqual(
            dataspace["connector_details"],
            [
                {
                    "name": "conn-citycouncil-pilot",
                    "role": "provider",
                    "runtime_namespace": "pilot",
                    "active_namespace": "pilot",
                    "planned_namespace": "pilot-provider",
                    "registration_service_namespace": "pilot-core",
                    "planned_registration_service_namespace": "pilot-core",
                },
                {
                    "name": "conn-company-pilot",
                    "role": "consumer",
                    "runtime_namespace": "pilot",
                    "active_namespace": "pilot",
                    "planned_namespace": "pilot-consumer",
                    "registration_service_namespace": "pilot-core",
                    "planned_registration_service_namespace": "pilot-core",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
