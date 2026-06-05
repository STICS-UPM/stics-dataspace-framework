import unittest

from deployers.shared.lib import image_runtime


class ImageRuntimeTests(unittest.TestCase):
    def test_image_ref_from_values_uses_repository_and_tag(self):
        self.assertEqual(
            image_runtime.image_ref_from_values(
                {
                    "image": {
                        "repository": "example/component",
                        "tag": "local",
                    }
                }
            ),
            "example/component:local",
        )

    def test_image_ref_from_values_returns_none_when_incomplete(self):
        self.assertIsNone(image_runtime.image_ref_from_values({"image": {"repository": "example/component"}}))
        self.assertIsNone(image_runtime.image_ref_from_values({"image": {"tag": "local"}}))

    def test_nested_image_ref_from_values_reads_component_specific_image(self):
        self.assertEqual(
            image_runtime.nested_image_ref_from_values(
                {
                    "mappingEditor": {
                        "image": {
                            "repository": "mapping-editor",
                            "tag": "local",
                        }
                    }
                },
                "mappingEditor",
            ),
            "mapping-editor:local",
        )

    def test_local_image_detection_is_case_insensitive_and_trimmed(self):
        self.assertTrue(image_runtime.is_local_image_ref("  ontology-hub:LOCAL "))
        self.assertFalse(image_runtime.is_local_image_ref("ontology-hub:latest"))
        self.assertFalse(image_runtime.is_local_image_ref(""))

    def test_dedupe_image_refs_keeps_original_order(self):
        self.assertEqual(
            image_runtime.dedupe_image_refs(["a:local", " ", "b:local", "a:local", None]),
            ["a:local", "b:local"],
        )

    def test_k3s_cri_image_ref_alias_matches_container_runtime_normalization(self):
        self.assertEqual(
            image_runtime.k3s_cri_image_ref_alias("ontology-hub:local"),
            "docker.io/library/ontology-hub:local",
        )
        self.assertEqual(
            image_runtime.k3s_cri_image_ref_alias("eclipse-edc/data-dashboard:local"),
            "docker.io/eclipse-edc/data-dashboard:local",
        )
        self.assertEqual(
            image_runtime.k3s_cri_image_ref_alias("registry.example.org/ns/image:tag"),
            "registry.example.org/ns/image:tag",
        )

    def test_k3s_image_save_refs_includes_cri_alias_when_needed(self):
        self.assertEqual(
            image_runtime.k3s_image_save_refs("ontology-hub:local"),
            ["ontology-hub:local", "docker.io/library/ontology-hub:local"],
        )
        self.assertEqual(
            image_runtime.k3s_image_save_refs("registry.example.org/ns/image:tag"),
            ["registry.example.org/ns/image:tag"],
        )

    def test_rendered_local_image_refs_filters_kubernetes_jsonpath_output(self):
        self.assertEqual(
            image_runtime.rendered_local_image_refs(
                " 'ontology-hub:local' \n"
                "ghcr.io/example/component:1.0.0\n"
                '"mapping-editor:local"\n'
                "ontology-hub:local\n"
            ),
            ["ontology-hub:local", "mapping-editor:local"],
        )

    def test_docker_build_command_preserves_existing_order(self):
        self.assertEqual(
            image_runtime.docker_build_command(
                "docker",
                "ontology-hub:local",
                dockerfile="Dockerfile",
                build_args={
                    "REPO_URL": "https://example.test/repo.git",
                    "BRANCH_NAME": "dev",
                    "EMPTY": "",
                },
            ),
            "docker build -t ontology-hub:local "
            "--build-arg REPO_URL=https://example.test/repo.git "
            "--build-arg BRANCH_NAME=dev -f Dockerfile .",
        )

    def test_docker_build_command_quotes_shell_sensitive_values(self):
        self.assertEqual(
            image_runtime.docker_build_command(
                "/opt/Docker Desktop/docker",
                "local/image:tag",
                dockerfile="/tmp/source Dockerfile",
                context="/tmp/build context",
            ),
            "'/opt/Docker Desktop/docker' build -t local/image:tag "
            "-f '/tmp/source Dockerfile' '/tmp/build context'",
        )


if __name__ == "__main__":
    unittest.main()
