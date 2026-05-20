import json
import unittest
from pathlib import Path


POSTMAN_DIR = Path("validation/core/collections/postman")


def load_json(name):
    with (POSTMAN_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def environment_values(environment):
    return {entry["key"]: entry.get("value", "") for entry in environment.get("values", [])}


class PostmanCollectionsTest(unittest.TestCase):
    def test_importable_environments_use_current_namespaces_without_demo_labels(self):
        inesdata = load_json("00_environment.json")
        edc = load_json("00_environment_edc.json")

        serialized = json.dumps([inesdata, edc], ensure_ascii=False).lower()
        self.assertNotIn("demo", serialized)

        inesdata_values = environment_values(inesdata)
        self.assertEqual(inesdata["name"], "00 Environment - INESData PIONERA")
        self.assertEqual(inesdata_values["dataspace"], "pionera")
        self.assertEqual(inesdata_values["registrationNamespace"], "core-control")
        self.assertEqual(inesdata_values["providerNamespace"], "provider")
        self.assertEqual(inesdata_values["consumerNamespace"], "consumer")

        edc_values = environment_values(edc)
        self.assertEqual(edc["name"], "00 Environment - EDC PIONERA")
        self.assertEqual(edc_values["dataspace"], "pionera-edc")
        self.assertEqual(edc_values["registrationNamespace"], "edc-control")
        self.assertEqual(edc_values["providerNamespace"], "edc-provider")
        self.assertEqual(edc_values["consumerNamespace"], "edc-consumer")

    def test_importable_environments_keep_protocol_addresses_runtime_parameterized(self):
        for name in ("00_environment.json", "00_environment_edc.json"):
            values = environment_values(load_json(name))
            self.assertEqual(values["protocolPort"], "19194")
            self.assertEqual(values["protocolPath"], "/protocol")
            self.assertEqual(values["protocolAddressMode"], "public")
            self.assertEqual(values["providerProtocolAddress"], "")
            self.assertEqual(values["consumerProtocolAddress"], "")
            self.assertEqual(values["providerProtocolAddressOverride"], "")
            self.assertEqual(values["consumerProtocolAddressOverride"], "")

    def test_e2e_compact_collection_derives_public_protocol_addresses_by_default(self):
        collection = load_json("03_e2e_compact.json")
        prerequest_scripts = [
            "\n".join(event["script"]["exec"])
            for event in collection.get("event", [])
            if event.get("listen") == "prerequest"
        ]
        script = "\n".join(prerequest_scripts)

        self.assertIn("function publicProtocolAddress(connectorKey)", script)
        self.assertIn("${connector}.${domain}", script)
        self.assertIn('envValue("protocolAddressMode") || "public"', script)
        self.assertIn("function internalProtocolAddress(connectorKey, namespaceKey)", script)
        self.assertIn("${connector}.${namespace}.svc.cluster.local", script)
        self.assertIn("providerProtocolAddressOverride", script)
        self.assertIn("consumerProtocolAddressOverride", script)
        self.assertIn(
            'setResolvedProtocolAddress("providerProtocolAddress", "provider", "providerNamespace", "providerProtocolAddressOverride")',
            script,
        )
        self.assertIn(
            'setResolvedProtocolAddress("consumerProtocolAddress", "consumer", "consumerNamespace", "consumerProtocolAddressOverride")',
            script,
        )


if __name__ == "__main__":
    unittest.main()
