from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_SECRET_NAME = "pionera-internal-ingress-tls"
DEFAULT_TRUSTSTORE_SECRET_NAME = "common-tls-cacerts"
DEFAULT_TRUSTSTORE_PASSWORD = "dataspaceunit"


def _as_bool(value, *, default=False):
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def vm_ingress_tls_enabled(config, topology):
    normalized_topology = str(topology or "").strip().lower().replace("_", "-")
    if normalized_topology not in {"vm-single", "vm-distributed"}:
        return False
    for key in (
        "VM_INGRESS_TLS_ENABLED",
        "VM_PUBLIC_INGRESS_TLS_ENABLED",
        f"{normalized_topology.upper().replace('-', '_')}_INGRESS_TLS_ENABLED",
    ):
        if key in (config or {}):
            return _as_bool((config or {}).get(key), default=True)
    return True


def _split_csv(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _hostname_from_url(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    return str(parsed.hostname or parsed.netloc or "").strip().lower()


def configured_hostnames(config):
    hosts = set()
    for key in (
        "KEYCLOAK_FRONTEND_URL",
        "KEYCLOAK_PUBLIC_URL",
        "MINIO_API_PUBLIC_URL",
        "MINIO_CONSOLE_PUBLIC_URL",
        "MINIO_PUBLIC_URL",
        "VM_COMMON_PUBLIC_URL",
        "VM_SINGLE_PUBLIC_URL",
        "VM_PROVIDER_PUBLIC_URL",
        "VM_CONSUMER_PUBLIC_URL",
        "VM_PROVIDER_HTTP_URL",
        "VM_CONSUMER_HTTP_URL",
        "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL",
        "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL",
    ):
        hostname = _hostname_from_url((config or {}).get(key))
        if hostname:
            hosts.add(hostname)
    for key in (
        "VM_INGRESS_TLS_HOSTS",
        "VM_PUBLIC_INGRESS_TLS_HOSTS",
        "PUBLIC_HOSTNAME",
        "PUBLIC_HOSTNAME_PROVIDER",
        "PUBLIC_HOSTNAME_CONSUMER",
    ):
        for item in _split_csv((config or {}).get(key)):
            hostname = _hostname_from_url(item) or item.strip().lower()
            if hostname:
                hosts.add(hostname)
    return sorted(hosts)


def ingress_hosts(ingress):
    hosts = []
    for rule in ((ingress.get("spec") or {}).get("rules") or []):
        host = str(rule.get("host") or "").strip().lower()
        if host:
            hosts.append(host)
    return sorted(set(hosts))


def ingress_tls_patch(hosts, secret_name=DEFAULT_SECRET_NAME):
    cleaned_hosts = sorted({str(host or "").strip().lower() for host in hosts if str(host or "").strip()})
    if not cleaned_hosts:
        return {}
    return {"spec": {"tls": [{"hosts": cleaned_hosts, "secretName": secret_name}]}}


def ingress_redirect_annotation_patch():
    return {
        "metadata": {
            "annotations": {
                "nginx.ingress.kubernetes.io/ssl-redirect": "false",
                "nginx.ingress.kubernetes.io/force-ssl-redirect": "false",
            }
        }
    }


def _safe_name(value):
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in str(value or "")).strip("-")


class VMIngressTLSReconciler:
    def __init__(
        self,
        *,
        config,
        topology,
        cluster_runtime,
        run,
        run_silent,
        artifact_dir,
    ):
        self.config = dict(config or {})
        self.topology = str(topology or "").strip().lower().replace("_", "-")
        self.cluster_runtime = dict(cluster_runtime or {})
        self.run = run
        self.run_silent = run_silent
        self.artifact_dir = Path(artifact_dir)

    @property
    def secret_name(self):
        return (
            str(self.config.get("VM_INGRESS_TLS_SECRET_NAME") or "").strip()
            or DEFAULT_SECRET_NAME
        )

    @property
    def truststore_secret_name(self):
        return (
            str(self.config.get("VM_INGRESS_TLS_TRUSTSTORE_SECRET_NAME") or "").strip()
            or str(self.config.get("CONNECTOR_TLS_CACERTS_SECRET_NAME") or "").strip()
            or DEFAULT_TRUSTSTORE_SECRET_NAME
        )

    @property
    def truststore_password(self):
        return (
            str(self.config.get("VM_INGRESS_TLS_TRUSTSTORE_PASSWORD") or "").strip()
            or DEFAULT_TRUSTSTORE_PASSWORD
        )

    @property
    def base_truststore_password(self):
        return (
            str(self.config.get("VM_INGRESS_TLS_BASE_TRUSTSTORE_PASSWORD") or "").strip()
            or "changeit"
        )

    def _kubectl_prefix(self, kubeconfig):
        if kubeconfig:
            return f"kubectl --kubeconfig {shlex.quote(str(kubeconfig))}"
        return "kubectl"

    def _kubeconfigs(self):
        if self.topology == "vm-single":
            kubeconfig = str(
                self.cluster_runtime.get("k3s_kubeconfig")
                or self.cluster_runtime.get("k3s_kubeconfig_common")
                or self.config.get("K3S_KUBECONFIG")
                or os.environ.get("KUBECONFIG")
                or ""
            ).strip()
            return [os.path.abspath(os.path.expanduser(kubeconfig))] if kubeconfig else [""]

        if self.topology != "vm-distributed":
            return []

        kubeconfigs = []
        for key in (
            "k3s_kubeconfig_common",
            "k3s_kubeconfig_provider",
            "k3s_kubeconfig_consumer",
            "k3s_kubeconfig_components",
            "k3s_kubeconfig",
        ):
            value = str(self.cluster_runtime.get(key) or "").strip()
            if value:
                value = os.path.abspath(os.path.expanduser(value))
                if value not in kubeconfigs:
                    kubeconfigs.append(value)
        return kubeconfigs or [""]

    def _load_ingresses(self, kubeconfig):
        output = self.run_silent(f"{self._kubectl_prefix(kubeconfig)} get ingress -A -o json")
        if not output:
            return []
        try:
            return list((json.loads(output).get("items") or []))
        except (TypeError, ValueError):
            print("Warning: VM ingress TLS skipped for one cluster: could not parse ingress list JSON.")
            return []

    def _host_allowed(self, host, configured_hosts):
        cleaned = str(host or "").strip().lower()
        if not cleaned or ".svc" in cleaned or cleaned.endswith(".cluster.local"):
            return False
        if cleaned in configured_hosts:
            return True
        domain_base = str(
            self.config.get("DOMAIN_BASE") or self.config.get("DS_DOMAIN_BASE") or ""
        ).strip().lower()
        return bool(domain_base and cleaned.endswith(f".{domain_base}"))

    def _target_ingresses(self, kubeconfig):
        configured_hosts = set(configured_hostnames(self.config))
        targets = []
        for ingress in self._load_ingresses(kubeconfig):
            metadata = ingress.get("metadata") or {}
            namespace = str(metadata.get("namespace") or "").strip()
            name = str(metadata.get("name") or "").strip()
            hosts = [host for host in ingress_hosts(ingress) if self._host_allowed(host, configured_hosts)]
            if namespace and name and hosts:
                targets.append({"namespace": namespace, "name": name, "hosts": hosts})
        return targets

    def _configured_cert_paths(self):
        cert = str(self.config.get("VM_INGRESS_TLS_CERT_FILE") or "").strip()
        key = str(self.config.get("VM_INGRESS_TLS_KEY_FILE") or "").strip()
        ca = str(self.config.get("VM_INGRESS_TLS_CA_FILE") or "").strip()
        return (
            os.path.abspath(os.path.expanduser(cert)) if cert else "",
            os.path.abspath(os.path.expanduser(key)) if key else "",
            os.path.abspath(os.path.expanduser(ca)) if ca else "",
        )

    def _cert_dir(self):
        dataspace = (
            str(self.config.get("DS_1_NAME") or self.config.get("DATASPACE_NAME") or "").strip()
            or "dataspace"
        )
        path = self.artifact_dir / "ingress-tls" / self.topology / _safe_name(dataspace)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _generate_self_signed_cert(self, hosts):
        cert_dir = self._cert_dir()
        cert = cert_dir / "tls.crt"
        key = cert_dir / "tls.key"
        san = ",".join(f"DNS:{host}" for host in sorted(set(hosts)))
        if cert.exists() and key.exists():
            return str(cert), str(key), str(cert)
        command = [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            str(self.config.get("VM_INGRESS_TLS_CERT_DAYS") or "825"),
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=pionera-internal-ingress/O=Proyecto PIONERA",
            "-addext",
            f"subjectAltName={san}",
        ]
        proc = subprocess.run(command, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"could not generate VM ingress TLS certificate: {detail}")
        try:
            os.chmod(key, 0o600)
        except OSError:
            pass
        return str(cert), str(key), str(cert)

    def _ensure_cert_material(self, hosts):
        cert, key, ca = self._configured_cert_paths()
        if cert and key:
            return cert, key, ca or cert
        if not _as_bool(self.config.get("VM_INGRESS_TLS_AUTO_GENERATE_DEV_CERT"), default=True):
            raise RuntimeError(
                "VM ingress TLS is enabled but VM_INGRESS_TLS_CERT_FILE and "
                "VM_INGRESS_TLS_KEY_FILE are not configured."
            )
        return self._generate_self_signed_cert(hosts)

    def _secret_manifest(self, namespace, cert_file, key_file):
        cert_b64 = base64.b64encode(Path(cert_file).read_bytes()).decode("ascii")
        key_b64 = base64.b64encode(Path(key_file).read_bytes()).decode("ascii")
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": self.secret_name, "namespace": namespace},
            "type": "kubernetes.io/tls",
            "data": {"tls.crt": cert_b64, "tls.key": key_b64},
        }

    def _generic_secret_manifest(self, namespace, name, data):
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": name, "namespace": namespace},
            "type": "Opaque",
            "data": {
                key: base64.b64encode(value).decode("ascii")
                for key, value in data.items()
            },
        }

    def _apply_manifest(self, kubeconfig, manifest):
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                temp_path = handle.name
                json.dump(manifest, handle)
            return self.run(f"{self._kubectl_prefix(kubeconfig)} apply -f {shlex.quote(temp_path)}", check=False)
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _ensure_tls_secret(self, kubeconfig, namespace, cert_file, key_file):
        return self._apply_manifest(kubeconfig, self._secret_manifest(namespace, cert_file, key_file))

    def _truststore_path(self, ca_file):
        truststore = self._cert_dir() / "cacerts.jks"
        alias = str(self.config.get("VM_INGRESS_TLS_TRUSTSTORE_ALIAS") or "pionera-internal-ingress").strip()
        try:
            truststore.unlink()
        except FileNotFoundError:
            pass

        base_truststore = self._base_truststore_path()
        if base_truststore:
            shutil.copyfile(base_truststore, truststore)
            if self.base_truststore_password != self.truststore_password:
                proc = subprocess.run(
                    [
                        "keytool",
                        "-storepasswd",
                        "-new",
                        self.truststore_password,
                        "-keystore",
                        str(truststore),
                        "-storepass",
                        self.base_truststore_password,
                    ],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    detail = (proc.stderr or proc.stdout or "").strip()
                    raise RuntimeError(f"could not rekey connector TLS truststore: {detail}")

        proc = subprocess.run(
            [
                "keytool",
                "-importcert",
                "-noprompt",
                "-alias",
                alias,
                "-file",
                ca_file,
                "-keystore",
                str(truststore),
                "-storepass",
                self.truststore_password,
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"could not build connector TLS truststore: {detail}")
        return truststore

    def _base_truststore_path(self):
        configured = str(self.config.get("VM_INGRESS_TLS_BASE_TRUSTSTORE_FILE") or "").strip()
        candidates = []
        if configured:
            candidates.append(os.path.abspath(os.path.expanduser(configured)))
        java_home = str(os.environ.get("JAVA_HOME") or "").strip()
        if java_home:
            candidates.append(os.path.join(java_home, "lib", "security", "cacerts"))
        candidates.extend(
            [
                "/etc/ssl/certs/java/cacerts",
                "/usr/lib/jvm/default-java/lib/security/cacerts",
            ]
        )
        candidates.extend(str(path) for path in Path("/usr/lib/jvm").glob("*/lib/security/cacerts"))
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        return ""

    def _ensure_truststore_secret(self, kubeconfig, namespace, ca_file):
        if not ca_file or not _as_bool(self.config.get("VM_INGRESS_TLS_TRUSTSTORE_ENABLED"), default=True):
            return None
        truststore = self._truststore_path(ca_file)
        return self._apply_manifest(
            kubeconfig,
            self._generic_secret_manifest(
                namespace,
                self.truststore_secret_name,
                {"cacerts.jks": truststore.read_bytes()},
            ),
        )

    def _patch_ingress(self, kubeconfig, namespace, name, hosts):
        prefix = self._kubectl_prefix(kubeconfig)
        tls_patch = json.dumps(ingress_tls_patch(hosts, self.secret_name), separators=(",", ":"))
        redirect_patch = json.dumps(ingress_redirect_annotation_patch(), separators=(",", ":"))
        ingress_ref = f"ingress/{shlex.quote(name)}"
        namespace_arg = shlex.quote(namespace)
        self.run(
            f"{prefix} -n {namespace_arg} patch {ingress_ref} --type merge -p {shlex.quote(tls_patch)}",
            check=False,
        )
        if _as_bool(self.config.get("VM_INGRESS_TLS_DISABLE_SSL_REDIRECT"), default=True):
            self.run(
                f"{prefix} -n {namespace_arg} patch {ingress_ref} --type merge -p {shlex.quote(redirect_patch)}",
                check=False,
            )

    def reconcile(self):
        if not vm_ingress_tls_enabled(self.config, self.topology):
            return {"status": "skipped", "reason": "disabled"}

        clusters = []
        all_hosts = set()
        for kubeconfig in self._kubeconfigs():
            targets = self._target_ingresses(kubeconfig)
            if not targets:
                continue
            clusters.append({"kubeconfig": kubeconfig, "targets": targets})
            for target in targets:
                all_hosts.update(target["hosts"])

        if not clusters:
            return {"status": "skipped", "reason": "no-public-ingresses"}

        cert_file, key_file, ca_file = self._ensure_cert_material(all_hosts)
        namespaces = set()
        patched = 0
        for cluster in clusters:
            kubeconfig = cluster["kubeconfig"]
            cluster_namespaces = sorted({target["namespace"] for target in cluster["targets"]})
            for namespace in cluster_namespaces:
                namespaces.add(namespace)
                self._ensure_tls_secret(kubeconfig, namespace, cert_file, key_file)
                try:
                    self._ensure_truststore_secret(kubeconfig, namespace, ca_file)
                except RuntimeError as exc:
                    print(f"Warning: connector TLS truststore sync skipped in namespace {namespace}: {exc}")
            for target in cluster["targets"]:
                self._patch_ingress(kubeconfig, target["namespace"], target["name"], target["hosts"])
                patched += 1

        return {
            "status": "synced",
            "topology": self.topology,
            "secret": self.secret_name,
            "truststore_secret": self.truststore_secret_name,
            "hosts": sorted(all_hosts),
            "namespaces": sorted(namespaces),
            "ingresses": patched,
        }
