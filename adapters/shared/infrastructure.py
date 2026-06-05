"""Shared foundation infrastructure helpers reused by multiple adapters."""

import json
import os
import shlex
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

from adapters.inesdata.infrastructure import INESDataInfrastructureAdapter
from deployers.shared.lib.components import (
    configured_component_host,
    configured_component_public_path,
    configured_optional_components,
    resolve_component_release_name,
)
from deployers.shared.lib.topology import (
    LOCAL_TOPOLOGY,
    VM_DISTRIBUTED_TOPOLOGY,
    VM_SINGLE_TOPOLOGY,
    normalize_topology,
)
from deployers.shared.lib.vm_distributed_public_access import resolve_vm_distributed_public_urls


def _sudo_write_file(path, content, allow_interactive=False):
    """Write content to a root-owned path via sudo cp from a temporary file."""
    tmp_fd, tmp_path = tempfile.mkstemp()
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        proc = subprocess.run(["sudo", "-n", "cp", tmp_path, path], capture_output=True, text=True)
        if proc.returncode == 0:
            return True, ""
        error = proc.stderr.strip()
        if allow_interactive and sys.stdin.isatty():
            print(f"sudo password may be required to update {path}.")
            interactive_proc = subprocess.run(["sudo", "cp", tmp_path, path])
            if interactive_proc.returncode == 0:
                return True, ""
            return False, f"interactive sudo cp exited with {interactive_proc.returncode}: {error}"
        return False, error
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _reload_nginx(allow_interactive=False):
    """Reload local NGINX, allowing an interactive sudo password prompt when appropriate."""
    reload_proc = subprocess.run(["sudo", "-n", "nginx", "-s", "reload"], capture_output=True, text=True)
    if reload_proc.returncode == 0:
        return True, ""

    error = (reload_proc.stderr or reload_proc.stdout or "").strip()
    if allow_interactive and sys.stdin.isatty():
        print("sudo password may be required to reload NGINX.")
        interactive_proc = subprocess.run(["sudo", "nginx", "-s", "reload"])
        if interactive_proc.returncode == 0:
            return True, ""
        return False, f"interactive nginx reload exited with {interactive_proc.returncode}: {error}"

    return False, error


class SharedFoundationInfrastructureAdapter(INESDataInfrastructureAdapter):
    """Neutral facade for shared Level 1-2 foundation logic."""

    def setup_cluster_preflight(self, topology=LOCAL_TOPOLOGY):
        """Prepare and validate the cluster required by VM-based execution."""
        normalized_topology = normalize_topology(topology)
        try:
            self.config_adapter.topology = normalized_topology
        except Exception:
            pass
        if normalized_topology == LOCAL_TOPOLOGY:
            return self.setup_cluster()
        if normalized_topology not in {VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}:
            raise RuntimeError(
                f"Level 1 preflight is not implemented for topology '{normalized_topology}' yet."
            )

        cluster_runtime = self._cluster_runtime_config()
        cluster_type = cluster_runtime.get("cluster_type", "minikube")
        if normalized_topology == VM_SINGLE_TOPOLOGY:
            print(
                "Topology 'vm-single' uses a Kubernetes cluster managed on the VM.\n"
                f"Level 1 will prepare the managed {cluster_type} cluster to keep runs reproducible."
            )
            self.setup_cluster()
            print("Managed vm-single cluster recreated. Running cluster preflight checks.")
        else:
            print(
                "Topology 'vm-distributed' uses an existing Kubernetes cluster/context.\n"
                "Level 1 will run read-only preflight checks against the configured common kubeconfig."
            )

        checks = []

        def run_check(
            command,
            label,
            *,
            require_output=False,
            failure_message=None,
            validator=None,
            detail_override=None,
        ):
            result = self.run(command, capture=True, check=False)
            detail = str(result or "").strip()
            ok = result is not None and (not require_output or bool(detail))
            if ok and callable(validator):
                ok = bool(validator(detail))
            checks.append(
                {
                    "label": label,
                    "command": command,
                    "status": "passed" if ok else "failed",
                    "detail": detail_override if detail_override is not None else detail,
                }
            )
            if not ok:
                self._fail(failure_message or f"Level 1 vm-single preflight failed during {label}")
            return detail

        print("Checking kubectl...")
        run_check("which kubectl", "kubectl binary", require_output=True, failure_message="kubectl is not installed")
        run_check(
            "kubectl version --client=true",
            "kubectl client version",
            require_output=True,
            failure_message="kubectl client is not available",
        )

        print("\nChecking Helm...")
        run_check("which helm", "helm binary", require_output=True, failure_message="Helm is not installed")
        run_check(
            "helm version --short",
            "helm version",
            require_output=True,
            failure_message="Helm is not available",
        )

        print("\nChecking cluster access...")
        current_context = run_check(
            "kubectl config current-context",
            "kubectl current context",
            require_output=True,
            failure_message="kubectl has no active context configured",
        )
        run_check(
            "kubectl cluster-info",
            "cluster info",
            require_output=True,
            failure_message="kubectl cannot reach the target cluster",
        )
        run_check(
            "kubectl get nodes --no-headers",
            "cluster nodes",
            require_output=True,
            failure_message="the target cluster returned no schedulable nodes",
        )

        print("\nChecking ingress and storage primitives...")
        run_check(
            "kubectl get ingressclass -o name",
            "ingress classes",
            require_output=True,
            failure_message="no IngressClass is available in the target cluster",
        )
        run_check(
            "kubectl get storageclass -o name",
            "storage classes",
            require_output=True,
            failure_message="no StorageClass is available in the target cluster",
        )

        print("\nChecking namespace permissions...")
        run_check(
            "kubectl auth can-i create namespace",
            "create namespace permission",
            require_output=True,
            failure_message="the active kubectl identity cannot create namespaces",
            validator=lambda detail: detail.strip().lower() in {"yes", "true"},
            detail_override="yes",
        )

        self.complete_level(1)
        return {
            "status": "ready",
            "mode": "managed-recreate" if normalized_topology == VM_SINGLE_TOPOLOGY else "preflight-only",
            "topology": normalized_topology,
            "cluster_runtime": cluster_type,
            "current_context": current_context,
            "cluster_creation": "recreated" if normalized_topology == VM_SINGLE_TOPOLOGY else "external",
            "checks": checks,
        }

    def deploy_infrastructure_for_topology(self, topology=LOCAL_TOPOLOGY):
        """Run Level 2 foundation deployment using the safest topology-aware path."""
        normalized_topology = normalize_topology(topology)
        if hasattr(self.config_adapter, "topology"):
            self.config_adapter.topology = normalized_topology
        if normalized_topology == LOCAL_TOPOLOGY:
            return self.deploy_infrastructure()
        if normalized_topology not in {VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}:
            raise RuntimeError(
                f"Level 2 deploy_infrastructure_for_topology() is not implemented for topology "
                f"'{normalized_topology}' yet."
            )

        result = self._deploy_infrastructure_runtime(
            skip_hosts=True,
            host_sync_message=(
                f"Skipping client-side hosts synchronization for topology '{normalized_topology}'. "
                "Use the dedicated hosts command if you need local name resolution."
            ),
        )
        if normalized_topology == VM_DISTRIBUTED_TOPOLOGY:
            self.sync_vm_distributed_routing()
        elif normalized_topology == VM_SINGLE_TOPOLOGY:
            self.sync_vm_distributed_public_access(topology=normalized_topology)
        return result

    def sync_vm_distributed_routing(self):
        """Refresh vm-distributed NGINX routing artifacts when configuration is available."""
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception as exc:
            print(f"Warning: vm-distributed routing sync skipped: could not load configuration: {exc}")
            return {"status": "skipped", "reason": "missing-config"}

        if not self._has_vm_distributed_routing_config(deployer_config):
            print("vm-distributed routing sync skipped: VM_COMMON_IP and DS_DOMAIN_BASE are required.")
            return {"status": "skipped", "reason": "incomplete-config"}

        for sync_step in (
            self._sync_common_service_external_ips_vm_distributed,
            self._ensure_ingress_nginx_forwarded_headers_vm_distributed,
            self._sync_nginx_stream_proxy_vm_distributed,
            self._sync_nginx_http_proxy_vm_distributed,
        ):
            try:
                sync_step(deployer_config)
            except Exception as exc:
                print(f"Warning: vm-distributed routing sync step skipped: {exc}")
        return {"status": "synced"}

    def sync_vm_distributed_public_access(self, topology=VM_DISTRIBUTED_TOPOLOGY):
        """Reconcile the public entrypoints expected by VM-based topologies."""
        normalized_topology = normalize_topology(topology)
        if hasattr(self.config_adapter, "topology"):
            self.config_adapter.topology = normalized_topology
        if normalized_topology == VM_SINGLE_TOPOLOGY:
            return self._sync_vm_single_public_access()
        if normalized_topology != VM_DISTRIBUTED_TOPOLOGY:
            raise RuntimeError(
                "public access reconciliation is only supported for topologies "
                f"'{VM_SINGLE_TOPOLOGY}' and '{VM_DISTRIBUTED_TOPOLOGY}'"
            )

        cluster_runtime = self._cluster_runtime_config()
        ingress_service_type = str(cluster_runtime.get("k3s_ingress_service_type") or "").strip()
        if str(cluster_runtime.get("cluster_type") or "").strip().lower() == "k3s" and ingress_service_type:
            self._patch_k3s_ingress_nginx_service(ingress_service_type)

        routing = self.sync_vm_distributed_routing()
        common_paths = self._sync_vm_distributed_common_public_path_ingresses()
        component_paths = self._sync_vm_distributed_component_public_path_ingresses()
        status = "synced"
        if any(
            isinstance(item, dict) and item.get("status") == "failed"
            for item in (common_paths, component_paths)
        ):
            status = "failed"
        return {
            "status": status,
            "topology": normalized_topology,
            "ingress_service_type": ingress_service_type,
            "routing": routing,
            "common_public_paths": common_paths,
            "component_public_paths": component_paths,
        }

    def _sync_vm_single_public_access(self):
        """Reconcile the vm-single public entrypoint on the VM-local NGINX bridge."""
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception as exc:
            print(f"Warning: vm-single public access sync skipped: could not load configuration: {exc}")
            return {"status": "skipped", "topology": VM_SINGLE_TOPOLOGY, "reason": "missing-config"}

        cluster_runtime = self._cluster_runtime_config()
        ingress_service_type = str(cluster_runtime.get("k3s_ingress_service_type") or "").strip()
        if str(cluster_runtime.get("cluster_type") or "").strip().lower() == "k3s" and ingress_service_type:
            self._patch_k3s_ingress_nginx_service(ingress_service_type)

        common_paths = self._sync_vm_distributed_common_public_path_ingresses()
        nginx_http = self._sync_nginx_http_proxy_vm_single(deployer_config)
        status = "synced"
        if any(
            isinstance(item, dict) and item.get("status") == "failed"
            for item in (common_paths, nginx_http)
        ):
            status = "failed"
        elif any(
            isinstance(item, dict) and item.get("status") == "skipped"
            for item in (common_paths, nginx_http)
        ):
            status = "partial"
        return {
            "status": status,
            "topology": VM_SINGLE_TOPOLOGY,
            "ingress_service_type": ingress_service_type,
            "common_public_paths": common_paths,
            "nginx_http": nginx_http,
        }

    def _vm_single_public_http_url(self, deployer_config):
        values = {**dict(deployer_config or {}), "TOPOLOGY": VM_SINGLE_TOPOLOGY}
        resolved = resolve_vm_distributed_public_urls(values)
        return str(
            values.get("VM_SINGLE_PUBLIC_URL")
            or values.get("VM_SINGLE_HTTP_URL")
            or resolved.get("VM_SINGLE_PUBLIC_URL")
            or resolved.get("VM_COMMON_PUBLIC_URL")
            or ""
        ).strip()

    def _vm_single_ingress_http_nodeport(self, deployer_config):
        configured = self._vm_distributed_config_value(
            deployer_config,
            "VM_SINGLE_INGRESS_HTTP_NODEPORT",
            "K3S_INGRESS_HTTP_NODEPORT",
        )
        if configured:
            return configured

        command = ["kubectl"]
        kubeconfig = str((deployer_config or {}).get("K3S_KUBECONFIG") or os.environ.get("KUBECONFIG") or "").strip()
        if kubeconfig:
            command.extend(["--kubeconfig", os.path.expanduser(kubeconfig)])
        command.extend(["get", "svc", "ingress-nginx-controller", "-n", "ingress-nginx", "-o", "json"])

        proc = subprocess.run(command, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"could not discover ingress-nginx HTTP NodePort: {detail}")

        try:
            service = json.loads(proc.stdout or "{}")
        except ValueError as exc:
            raise RuntimeError(f"could not parse ingress-nginx service JSON: {exc}") from exc

        for port in (service.get("spec") or {}).get("ports") or []:
            name = str(port.get("name") or "").strip().lower()
            number = str(port.get("port") or "").strip()
            nodeport = str(port.get("nodePort") or "").strip()
            if nodeport and (name == "http" or number == "80"):
                return nodeport

        raise RuntimeError("ingress-nginx-controller service does not expose an HTTP NodePort")

    def _sync_nginx_http_proxy_vm_single(self, deployer_config):
        """Write the VM-local HTTP bridge for the single public domain used by vm-single."""
        conf_dir = "/etc/nginx/sites-enabled"
        if not os.path.isdir(conf_dir):
            print(f"vm-single local NGINX HTTP sync skipped: {conf_dir} is not available.")
            return {"status": "skipped", "reason": "nginx-sites-enabled-unavailable"}

        public_url = self._vm_single_public_http_url(deployer_config)
        parsed = urlparse(public_url if "://" in public_url else f"//{public_url}")
        public_host = str(parsed.hostname or "").strip()
        if not public_host:
            print("vm-single local NGINX HTTP sync skipped: VM_SINGLE_HTTP_URL or VM_SINGLE_PUBLIC_URL is required.")
            return {"status": "skipped", "reason": "missing-public-host"}

        try:
            nodeport = self._vm_single_ingress_http_nodeport(deployer_config)
        except Exception as exc:
            print(f"Warning: vm-single local NGINX HTTP sync skipped: {exc}")
            return {"status": "failed", "reason": "ingress-nodeport-discovery-failed", "error": str(exc)}

        conf_path = os.path.join(conf_dir, "00-validation-environment-vm-single-public.conf")
        content = (
            "# Generated by Validation-Environment for vm-single public access\n"
            "# This VM-local bridge sends the public domain to the Kubernetes ingress controller.\n"
            "server {\n"
            "    listen 80;\n"
            f"    server_name {public_host};\n"
            "    client_max_body_size 0;\n\n"
            "    location / {\n"
            f"        proxy_pass http://127.0.0.1:{nodeport};\n"
            "        proxy_http_version 1.1;\n"
            "        proxy_set_header Host $host;\n"
            "        proxy_set_header X-Real-IP $remote_addr;\n"
            "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
            "        proxy_set_header X-Forwarded-Host $host;\n"
            "        proxy_set_header X-Forwarded-Port $server_port;\n"
            "        proxy_set_header X-Forwarded-Proto https;\n"
            "        proxy_set_header Upgrade $http_upgrade;\n"
            '        proxy_set_header Connection "upgrade";\n'
            "        proxy_buffering off;\n"
            "        proxy_request_buffering off;\n"
            "    }\n"
            "}\n"
        )
        ok, error = _sudo_write_file(conf_path, content, allow_interactive=True)
        if not ok:
            print(f"Warning: could not write {conf_path}: {error}")
            return {
                "status": "failed",
                "reason": "nginx-write-failed",
                "path": conf_path,
                "error": error,
            }

        reload_ok, reload_error = _reload_nginx(allow_interactive=True)
        if reload_ok:
            print(f"NGINX vm-single HTTP routing updated: {conf_path}")
            return {
                "status": "synced",
                "path": conf_path,
                "host": public_host,
                "target": f"127.0.0.1:{nodeport}",
            }

        print(f"Warning: NGINX reload failed after vm-single HTTP sync: {reload_error}")
        return {
            "status": "failed",
            "reason": "nginx-reload-failed",
            "path": conf_path,
            "host": public_host,
            "target": f"127.0.0.1:{nodeport}",
            "error": reload_error,
        }

    def _vm_distributed_component_public_path_ingresses(self, config):
        deployer_config = dict(config or {})
        namespace = str(
            deployer_config.get("COMPONENTS_NAMESPACE")
            or getattr(self.config, "COMPONENTS_NAMESPACE", "")
            or "components"
        ).strip() or "components"
        dataspace_name = self._vm_distributed_dataspace_name(deployer_config)
        components = configured_optional_components(deployer_config)
        ingresses = []

        for component in components:
            ingresses.append(
                self._vm_distributed_component_public_path_ingress(
                    component,
                    deployer_config,
                    namespace=namespace,
                    dataspace_name=dataspace_name,
                )
            )

        if (
            "semantic-virtualization" in components
            and self._parse_config_bool(
                deployer_config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED")
                if deployer_config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED") is not None
                else deployer_config.get("MAPPING_EDITOR_ENABLED"),
                default=False,
            )
        ):
            ingresses.append(
                self._vm_distributed_component_public_path_ingress(
                    "semantic-virtualization-editor",
                    deployer_config,
                    namespace=namespace,
                    dataspace_name=dataspace_name,
                )
            )

        return [item for item in ingresses if item]

    def _vm_distributed_component_public_path_ingress(
        self,
        component,
        deployer_config,
        *,
        namespace,
        dataspace_name,
    ):
        host = configured_component_host(
            component,
            deployer_config,
            dataspace_name=dataspace_name,
        )
        public_path = configured_component_public_path(component, deployer_config)
        if not host or not public_path:
            return None

        release_component = "semantic-virtualization" if component == "semantic-virtualization-editor" else component
        release_name = resolve_component_release_name(release_component, dataspace_name=dataspace_name)
        service_name = f"{release_name}-editor" if component == "semantic-virtualization-editor" else release_name
        service_port = {
            "ontology-hub": 3333,
            "ai-model-hub": 8080,
            "semantic-virtualization": 8000,
            "semantic-virtualization-editor": 8501,
        }.get(component)
        if not service_port:
            return None

        env_key = str(component or "").strip().upper().replace("-", "_")
        rewrite_enabled = self._parse_config_bool(
            deployer_config.get(f"{env_key}_PUBLIC_PATH_REWRITE")
            if deployer_config.get(f"{env_key}_PUBLIC_PATH_REWRITE") is not None
            else deployer_config.get("COMPONENTS_PUBLIC_PATH_REWRITE"),
            default=True,
        )
        annotations = {}
        path = public_path
        path_type = "Prefix"
        if rewrite_enabled:
            annotations = {
                "nginx.ingress.kubernetes.io/use-regex": "true",
                "nginx.ingress.kubernetes.io/rewrite-target": "/$2",
            }
            path = f"{public_path}(/|$)(.*)"
            path_type = "ImplementationSpecific"

        metadata = {
            "name": self._k8s_name_with_suffix(service_name, "public-path"),
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "validation-environment",
                "app.kubernetes.io/part-of": "vm-distributed",
                "app.kubernetes.io/component": component,
            },
        }
        if annotations:
            metadata["annotations"] = annotations

        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": metadata,
            "spec": {
                "ingressClassName": "nginx",
                "rules": [
                    {
                        "host": host,
                        "http": {
                            "paths": [
                                {
                                    "path": path,
                                    "pathType": path_type,
                                    "backend": {
                                        "service": {
                                            "name": service_name,
                                            "port": {"number": service_port},
                                        }
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
        }

    def _sync_vm_distributed_component_public_path_ingresses(self):
        if not self._is_vm_distributed_topology():
            return {"status": "skipped", "reason": "not-vm-distributed"}
        config = self.config_adapter.load_deployer_config()
        owner = str(
            config.get("VM_DISTRIBUTED_COMPONENT_PUBLIC_PATH_INGRESS_OWNER")
            or config.get("COMPONENTS_PUBLIC_PATH_INGRESS_OWNER")
            or "level5"
        ).strip().lower()
        if owner not in {"infrastructure", "foundation", "level3"}:
            return {"status": "skipped", "reason": "component-ingresses-owned-by-level5"}

        ingresses = self._vm_distributed_component_public_path_ingresses(config)
        if not ingresses:
            return {"status": "skipped", "reason": "no-component-public-paths"}

        existing_routes = self._existing_ingress_route_keys()
        missing = [
            item
            for item in ingresses
            if self._ingress_route_key(item) not in existing_routes
        ]
        if not missing:
            return {
                "status": "unchanged",
                "routes": [self._public_path_route_summary(item) for item in ingresses],
                "skipped_existing": [self._public_path_route_summary(item) for item in ingresses],
            }

        manifest = {
            "apiVersion": "v1",
            "kind": "List",
            "items": missing,
        }
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                temp_path = handle.name
                json.dump(manifest, handle)
            if self.run(f"kubectl apply -f {temp_path!r}", check=False) is None:
                return {
                    "status": "failed",
                    "reason": "kubectl-apply-failed",
                    "routes": [self._public_path_route_summary(item) for item in missing],
                }
            routes = ", ".join(
                f"{item['spec']['rules'][0]['host']}{item['spec']['rules'][0]['http']['paths'][0]['path']}"
                for item in missing
            )
            print(f"vm-distributed component public path ingresses synchronized: {routes}")
            return {
                "status": "synced",
                "routes": [self._public_path_route_summary(item) for item in missing],
                "skipped_existing": [
                    self._public_path_route_summary(item)
                    for item in ingresses
                    if item not in missing
                ],
            }
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _existing_ingress_route_keys(self):
        raw = self.run_silent("kubectl get ingress -A -o json") or ""
        if not raw:
            return set()
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return set()
        route_keys = set()
        for item in payload.get("items") or []:
            for rule in ((item.get("spec") or {}).get("rules") or []):
                host = str(rule.get("host") or "").strip()
                paths = (((rule.get("http") or {}).get("paths")) or [])
                for path in paths:
                    route_path = str(path.get("path") or "").strip()
                    if host and route_path:
                        route_keys.add((host, route_path))
        return route_keys

    @staticmethod
    def _ingress_route_key(item):
        rule = item["spec"]["rules"][0]
        return (
            str(rule.get("host") or "").strip(),
            str(rule["http"]["paths"][0].get("path") or "").strip(),
        )

    @staticmethod
    def _public_path_route_summary(item):
        rule = item["spec"]["rules"][0]
        path = rule["http"]["paths"][0]
        return {
            "name": item["metadata"]["name"],
            "namespace": item["metadata"]["namespace"],
            "host": rule["host"],
            "path": path["path"],
            "service": path["backend"]["service"]["name"],
            "port": path["backend"]["service"]["port"]["number"],
        }

    @staticmethod
    def _k8s_name_with_suffix(name, suffix):
        base = str(name or "").strip().strip("-")
        resolved_suffix = str(suffix or "").strip().strip("-")
        if not resolved_suffix:
            return base[:63].strip("-")
        max_base_length = 63 - len(resolved_suffix) - 1
        return f"{base[:max_base_length].strip('-')}-{resolved_suffix}".strip("-")

    @staticmethod
    def _parse_config_bool(value, default=False):
        if value is None:
            return bool(default)
        normalized = str(value).strip().lower()
        if not normalized:
            return bool(default)
        return normalized in {"1", "true", "yes", "y", "on", "s", "si", "sí"}

    @staticmethod
    def _has_vm_distributed_routing_config(config):
        return bool(str((config or {}).get("VM_COMMON_IP") or "").strip()) and bool(
            str((config or {}).get("DS_DOMAIN_BASE") or "").strip()
        )

    def _sync_common_service_external_ips_vm_distributed(self, deployer_config):
        """Expose common services on the common VM IP for connector clusters."""
        common_ip = str((deployer_config or {}).get("VM_COMMON_IP") or "").strip()
        if not common_ip:
            return

        common_namespace = str(
            (deployer_config or {}).get("NS_COMMON")
            or (deployer_config or {}).get("COMMON_SERVICES_NAMESPACE")
            or getattr(self.config, "NS_COMMON", "common-srvs")
        ).strip() or "common-srvs"

        for service in ("common-srvs-postgresql", "common-srvs-vault"):
            proc = subprocess.run(
                [
                    "kubectl",
                    "patch",
                    "svc",
                    service,
                    "-n",
                    common_namespace,
                    "--type",
                    "merge",
                    "-p",
                    json.dumps({"spec": {"externalIPs": [common_ip]}}),
                ],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip()
                print(f"Warning: could not expose {service} through {common_ip}: {detail}")
        print(f"vm-distributed common service externalIPs synchronized: {common_ip}")

    def _vm_distributed_dataspace_name(self, deployer_config):
        for getter_name in ("primary_dataspace_name", "dataspace_name"):
            getter = getattr(self.config_adapter, getter_name, None)
            if callable(getter):
                try:
                    value = getter()
                except Exception:
                    value = None
                if value:
                    return str(value).strip()
        return (
            str((deployer_config or {}).get("DS_1_NAME") or getattr(self.config, "DS_NAME", "") or "pionera").strip()
            or "pionera"
        )

    @staticmethod
    def _split_config_list(value):
        return [item.strip() for item in str(value or "").split(",") if item.strip()]

    @staticmethod
    def _vm_distributed_ssh_target(config, host):
        host = str(host or "").strip()
        if not host:
            return ""
        user = str((config or {}).get("VM_SSH_USER") or "").strip()
        if not user:
            return ""
        return f"{user}@{host}"

    @staticmethod
    def _vm_distributed_config_value(config, *keys, default=""):
        for key in keys:
            value = str((config or {}).get(key) or "").strip()
            if value:
                return value
        return default

    @staticmethod
    def _vm_distributed_remote_ssh_command(config, role, fallback_host, remote_command, *, force_tty=False):
        role_key = str(role or "").strip().upper()
        host = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
            config,
            f"VM_{role_key}_SSH_HOST",
            default=str(fallback_host or "").strip(),
        )
        user = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
            config,
            f"VM_{role_key}_SSH_USER",
            "VM_SSH_USER",
        )
        if not host or not user:
            return []

        timeout = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
            config,
            "SSH_CONNECT_TIMEOUT_SECONDS",
            default="5",
        )
        known_hosts_strategy = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
            config,
            "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY",
            default="accept-new",
        )
        port = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
            config,
            f"VM_{role_key}_SSH_PORT",
            default="22",
        )
        identity_file = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
            config,
            f"VM_{role_key}_SSH_IDENTITY_FILE",
            "VM_DISTRIBUTED_SSH_IDENTITY_FILE",
            "SSH_IDENTITY_FILE",
        )

        command = [
            "ssh",
            "-o",
            f"ConnectTimeout={timeout}",
            "-o",
            f"StrictHostKeyChecking={known_hosts_strategy}",
            "-p",
            port or "22",
        ]
        if force_tty:
            command.insert(1, "-tt")
        if identity_file:
            command.extend(["-i", os.path.expanduser(identity_file)])

        access_mode = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
            config,
            f"VM_{role_key}_SSH_ACCESS_MODE",
            "SSH_ACCESS_MODE",
        ).lower().replace("_", "-")
        bastion_host = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
            config,
            f"VM_{role_key}_SSH_BASTION_HOST",
            "SSH_BASTION_HOST",
        )
        if access_mode == "bastion" or (not access_mode and bastion_host):
            bastion_user = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
                config,
                f"VM_{role_key}_SSH_BASTION_USER",
                "SSH_BASTION_USER",
            )
            bastion_port = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
                config,
                f"VM_{role_key}_SSH_BASTION_PORT",
                "SSH_BASTION_PORT",
                default="2222",
            )
            bastion_identity_file = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
                config,
                f"VM_{role_key}_SSH_BASTION_IDENTITY_FILE",
                "SSH_BASTION_IDENTITY_FILE",
            )
            if bastion_host and bastion_user:
                bastion_target = f"{bastion_user}@{bastion_host}"
                if bastion_port:
                    bastion_target = f"{bastion_target}:{bastion_port}"
                if bastion_identity_file:
                    command.extend(["-i", os.path.expanduser(bastion_identity_file)])
                command.extend(["-J", bastion_target])

        command.append(f"{user}@{host}")
        if remote_command:
            command.append(remote_command)
        return command

    @staticmethod
    def _vm_distributed_remote_nginx_interactive_mode(config):
        value = SharedFoundationInfrastructureAdapter._vm_distributed_config_value(
            config,
            "VM_DISTRIBUTED_REMOTE_NGINX_INTERACTIVE",
            default="never",
        )
        normalized = str(value or "").strip().lower()
        if normalized in {"auto", "fallback", "if-needed", "if_needed", "prompt-if-needed", "prompt_if_needed"}:
            return "auto"
        if normalized in {"1", "true", "yes", "y", "on", "always", "interactive"}:
            return "always"
        return "never"

    @staticmethod
    def _remote_sudo_needs_interactive(stderr):
        message = str(stderr or "").strip().lower()
        return any(
            token in message
            for token in (
                "a terminal is required",
                "password is required",
                "no tty",
                "a password is required",
            )
        )

    @staticmethod
    def _remote_nginx_temp_path(role, ds_name):
        safe = "".join(
            char if char.isalnum() or char in {"-", "_"} else "-"
            for char in f"{role or 'role'}-{ds_name or 'dataspace'}"
        ).strip("-")
        return f"/tmp/pionera-vm-distributed-{safe or 'routing'}.conf"

    def _ensure_ingress_nginx_forwarded_headers_vm_distributed(self, deployer_config):
        """Patch ingress-nginx on connector clusters to honor forwarded HTTPS headers."""
        patch = '{"data":{"use-forwarded-headers":"true","compute-full-forwarded-for":"true"}}'
        kubeconfigs = []
        for key in ("K3S_KUBECONFIG_PROVIDER", "K3S_KUBECONFIG_CONSUMER"):
            raw_kubeconfig = str((deployer_config or {}).get(key) or "").strip()
            kubeconfig = os.path.abspath(os.path.expanduser(raw_kubeconfig)) if raw_kubeconfig else ""
            if kubeconfig and kubeconfig not in kubeconfigs:
                kubeconfigs.append(kubeconfig)

        for kubeconfig in kubeconfigs:
            try:
                proc = subprocess.run(
                    [
                        "kubectl",
                        "--kubeconfig",
                        kubeconfig,
                        "patch",
                        "configmap",
                        "ingress-nginx-controller",
                        "-n",
                        "ingress-nginx",
                        "--type=merge",
                        "-p",
                        patch,
                    ],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode == 0:
                    print(f"ingress-nginx forwarded headers enabled for kubeconfig: {kubeconfig}")
                else:
                    print(f"Warning: ingress-nginx forwarded header patch failed: {proc.stderr.strip()}")
            except Exception as exc:
                print(f"Warning: ingress-nginx forwarded header patch skipped: {exc}")

    def _sync_nginx_stream_proxy_vm_distributed(self, deployer_config):
        """Expose common-service ClusterIPs through local NGINX stream routing."""
        stream_conf = "/etc/nginx/pionera-stream.conf"
        stream_dir = os.path.dirname(stream_conf)
        if not os.path.isdir(stream_dir):
            print(f"vm-distributed local NGINX stream sync skipped: {stream_dir} is not available.")
            return

        common_namespace = str(
            (deployer_config or {}).get("NS_COMMON") or getattr(self.config, "NS_COMMON", "common-srvs")
        ).strip() or "common-srvs"

        def cluster_ip(namespace, service):
            try:
                value = subprocess.check_output(
                    [
                        "kubectl",
                        "get",
                        "svc",
                        service,
                        "-n",
                        namespace,
                        "-o",
                        "jsonpath={.spec.clusterIP}",
                    ],
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
                return value if value and value != "None" else ""
            except Exception:
                return ""

        entries = []
        for listen_port, namespace, service, service_port in (
            ("5432", common_namespace, "common-srvs-postgresql", "5432"),
            ("8200", common_namespace, "common-srvs-vault", "8200"),
            ("8080", common_namespace, "common-srvs-keycloak", "80"),
        ):
            ip = cluster_ip(namespace, service)
            if not ip:
                continue
            entries.append(
                "    server {\n"
                f"        listen {listen_port};\n"
                f"        proxy_pass {ip}:{service_port};\n"
                "        proxy_timeout 600s;\n"
                "        proxy_connect_timeout 10s;\n"
                "    }"
            )

        if not entries:
            print("Warning: common service ClusterIPs could not be resolved; skipping NGINX stream sync.")
            return

        content = "stream {\n" + "\n".join(entries) + "\n}\n"
        ok, error = _sudo_write_file(stream_conf, content)
        if not ok:
            print(f"Warning: could not write {stream_conf}: {error}")
            return
        reload_proc = subprocess.run(["sudo", "nginx", "-s", "reload"], capture_output=True, text=True)
        if reload_proc.returncode == 0:
            print(f"NGINX stream routing updated: {stream_conf}")
        else:
            print(f"Warning: NGINX reload failed after stream sync: {reload_proc.stderr.strip()}")

    def _sync_nginx_http_proxy_vm_distributed(self, deployer_config):
        """Write vm-distributed HTTP routing for dataspace and connector hostnames."""
        common_ip = str((deployer_config or {}).get("VM_COMMON_IP") or "").strip()
        provider_ip = str((deployer_config or {}).get("VM_PROVIDER_IP") or "").strip()
        consumer_ip = str((deployer_config or {}).get("VM_CONSUMER_IP") or "").strip()
        ds_domain = str((deployer_config or {}).get("DS_DOMAIN_BASE") or "").strip()
        nodeport = str((deployer_config or {}).get("K3S_INGRESS_HTTP_NODEPORT") or "31667").strip()
        provider_http_port = str((deployer_config or {}).get("VM_PROVIDER_INGRESS_HTTP_PORT") or nodeport).strip()
        consumer_http_port = str((deployer_config or {}).get("VM_CONSUMER_INGRESS_HTTP_PORT") or nodeport).strip()
        provider_nodeport = str((deployer_config or {}).get("VM_PROVIDER_INGRESS_NODEPORT") or nodeport).strip()
        consumer_nodeport = str((deployer_config or {}).get("VM_CONSUMER_INGRESS_NODEPORT") or nodeport).strip()
        ds_name = self._vm_distributed_dataspace_name(deployer_config)

        provider_shorts = self._split_config_list((deployer_config or {}).get("VM_PROVIDER_CONNECTORS"))
        consumer_shorts = self._split_config_list((deployer_config or {}).get("VM_CONSUMER_CONNECTORS"))
        if not (provider_shorts or consumer_shorts):
            locations = str((deployer_config or {}).get("DS_1_CONNECTOR_NAMESPACES") or "")
            for item in self._split_config_list(locations):
                if ":" not in item:
                    continue
                short, role = [part.strip() for part in item.split(":", 1)]
                if role.lower() == "provider":
                    provider_shorts.append(short)
                elif role.lower() == "consumer":
                    consumer_shorts.append(short)

        def server_block(server_name, proxy_target):
            return (
                "server {\n"
                "    listen 80;\n"
                f"    server_name {server_name};\n"
                "    client_max_body_size 0;\n"
                "    location / {\n"
                f"        proxy_pass http://{proxy_target};\n"
                "        proxy_set_header Host $host;\n"
                "        proxy_set_header X-Real-IP $remote_addr;\n"
                "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                "        proxy_set_header X-Forwarded-Proto $scheme;\n"
                "        proxy_http_version 1.1;\n"
                "        proxy_set_header Upgrade $http_upgrade;\n"
                '        proxy_set_header Connection "upgrade";\n'
                "    }\n"
                "}\n"
            )

        blocks = [
            server_block(f"registration-service-{ds_name}.{ds_domain}", f"{common_ip}:{nodeport}"),
            server_block(f"*.{ds_domain}", f"{common_ip}:{nodeport}"),
        ]
        for short in provider_shorts:
            target_host = provider_ip or common_ip
            blocks.append(server_block(f"conn-{short}-{ds_name}.{ds_domain}", f"{target_host}:{provider_http_port}"))
        for short in consumer_shorts:
            target_host = consumer_ip or common_ip
            blocks.append(server_block(f"conn-{short}-{ds_name}.{ds_domain}", f"{target_host}:{consumer_http_port}"))

        conf_path = f"/etc/nginx/sites-enabled/pionera-vm-distributed-{ds_name}.conf"
        conf_dir = os.path.dirname(conf_path)
        if not os.path.isdir(conf_dir):
            print(f"vm-distributed local NGINX HTTP sync skipped: {conf_dir} is not available.")
            return

        content = "# Generated by Validation-Environment for vm-distributed routing\n" + "\n".join(blocks)
        ok, error = _sudo_write_file(conf_path, content)
        if not ok:
            print(f"Warning: could not write {conf_path}: {error}")
            return

        reload_proc = subprocess.run(["sudo", "nginx", "-s", "reload"], capture_output=True, text=True)
        if reload_proc.returncode == 0:
            print(f"NGINX vm-distributed HTTP routing updated: {conf_path}")
        else:
            print(f"Warning: NGINX reload failed after HTTP sync: {reload_proc.stderr.strip()}")

        if provider_ip and provider_shorts:
            self._sync_remote_nginx_vm_distributed(
                deployer_config, "provider", provider_ip, provider_shorts, ds_name, ds_domain, provider_nodeport
            )
        if consumer_ip and consumer_shorts:
            self._sync_remote_nginx_vm_distributed(
                deployer_config, "consumer", consumer_ip, consumer_shorts, ds_name, ds_domain, consumer_nodeport
            )

    def _sync_remote_nginx_vm_distributed(
        self, deployer_config, role, remote_ip, connector_shorts, ds_name, ds_domain, nodeport
    ):
        """Write connector proxy blocks on a remote VM when SSH is configured."""
        remote_conf = f"/etc/nginx/sites-enabled/pionera-vm-distributed-{ds_name}.conf"
        remote_conf_dir = os.path.dirname(remote_conf)
        ssh_write_command = self._vm_distributed_remote_ssh_command(
            deployer_config,
            role,
            remote_ip,
            f"sudo mkdir -p {shlex.quote(remote_conf_dir)} && sudo tee {shlex.quote(remote_conf)} >/dev/null",
        )
        ssh_reload_command = self._vm_distributed_remote_ssh_command(
            deployer_config,
            role,
            remote_ip,
            "sudo nginx -s reload",
        )
        if not ssh_write_command or not ssh_reload_command:
            print(
                f"Remote NGINX sync skipped for {role} ({remote_ip}): "
                f"VM_{str(role or '').upper()}_SSH_HOST and VM_SSH_USER are required."
            )
            return

        server_names = []
        public_hostname = self._vm_distributed_role_public_hostname(deployer_config, role)
        if public_hostname:
            server_names.append(public_hostname)
        for short in connector_shorts:
            hostname = f"conn-{short}-{ds_name}.{ds_domain}"
            if hostname not in server_names:
                server_names.append(hostname)
        server_name_line = " ".join(server_names) if server_names else "_"

        if not server_names:
            return
        blocks = [
            "server {\n"
            "    listen 80;\n"
            f"    server_name {server_name_line};\n"
            "    client_max_body_size 0;\n"
            "    location / {\n"
            f"        proxy_pass http://127.0.0.1:{nodeport};\n"
            "        proxy_set_header Host $host;\n"
            "        proxy_set_header X-Real-IP $remote_addr;\n"
            "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
            "        proxy_set_header X-Forwarded-Proto $scheme;\n"
            "        proxy_http_version 1.1;\n"
            "    }\n"
            "}\n"
        ]

        content = "# Generated by Validation-Environment for vm-distributed connector routing\n" + "\n".join(blocks)
        interactive_mode = self._vm_distributed_remote_nginx_interactive_mode(deployer_config)
        try:
            write_proc = subprocess.run(
                ssh_write_command,
                input=content,
                capture_output=True,
                text=True,
            )
            if write_proc.returncode != 0:
                if (
                    interactive_mode in {"auto", "always"}
                    and self._remote_sudo_needs_interactive(write_proc.stderr)
                ):
                    remote_temp = self._remote_nginx_temp_path(role, ds_name)
                    temp_write_command = self._vm_distributed_remote_ssh_command(
                        deployer_config,
                        role,
                        remote_ip,
                        f"cat > {shlex.quote(remote_temp)}",
                    )
                    install_command = self._vm_distributed_remote_ssh_command(
                        deployer_config,
                        role,
                        remote_ip,
                        (
                            f"sudo mkdir -p {shlex.quote(remote_conf_dir)} && "
                            f"sudo install -m 0644 {shlex.quote(remote_temp)} "
                            f"{shlex.quote(remote_conf)} && rm -f {shlex.quote(remote_temp)}"
                        ),
                        force_tty=True,
                    )
                    if not temp_write_command or not install_command:
                        print(
                            f"Warning: remote NGINX write failed on {role} ({remote_ip}): "
                            f"{write_proc.stderr.strip()}"
                        )
                        return
                    print(
                        f"Remote NGINX write on {role} ({remote_ip}) needs sudo password; "
                        "retrying with an interactive prompt."
                    )
                    temp_proc = subprocess.run(
                        temp_write_command,
                        input=content,
                        capture_output=True,
                        text=True,
                    )
                    if temp_proc.returncode != 0:
                        print(
                            f"Warning: remote NGINX temporary write failed on {role} ({remote_ip}): "
                            f"{temp_proc.stderr.strip()}"
                        )
                        return
                    install_proc = subprocess.run(install_command)
                    if install_proc.returncode != 0:
                        print(f"Warning: remote NGINX interactive write failed on {role} ({remote_ip})")
                        return
                else:
                    print(
                        f"Warning: remote NGINX write failed on {role} ({remote_ip}): "
                        f"{write_proc.stderr.strip()}"
                    )
                    return
            reload_proc = subprocess.run(ssh_reload_command, capture_output=True, text=True)
            if reload_proc.returncode == 0:
                print(f"Remote NGINX routing updated on {role} ({remote_ip}): {remote_conf}")
            elif (
                interactive_mode in {"auto", "always"}
                and self._remote_sudo_needs_interactive(reload_proc.stderr)
            ):
                interactive_reload_command = self._vm_distributed_remote_ssh_command(
                    deployer_config,
                    role,
                    remote_ip,
                    "sudo nginx -s reload",
                    force_tty=True,
                )
                print(
                    f"Remote NGINX reload on {role} ({remote_ip}) needs sudo password; "
                    "retrying with an interactive prompt."
                )
                interactive_reload_proc = subprocess.run(interactive_reload_command)
                if interactive_reload_proc.returncode == 0:
                    print(f"Remote NGINX routing updated on {role} ({remote_ip}): {remote_conf}")
                else:
                    print(f"Warning: remote NGINX interactive reload failed on {role} ({remote_ip})")
            else:
                print(f"Warning: remote NGINX reload failed on {role} ({remote_ip}): {reload_proc.stderr.strip()}")
        except Exception as exc:
            print(f"Warning: remote NGINX sync skipped on {role} ({remote_ip}): {exc}")

    @staticmethod
    def _vm_distributed_role_public_hostname(deployer_config, role):
        normalized_role = str(role or "").strip().upper()
        if normalized_role not in {"PROVIDER", "CONSUMER"}:
            return ""
        for key in (
            f"PUBLIC_HOSTNAME_{normalized_role}",
            f"VM_{normalized_role}_PUBLIC_URL",
            f"VM_{normalized_role}_HTTP_URL",
        ):
            raw_value = str((deployer_config or {}).get(key) or "").strip()
            if not raw_value:
                continue
            parsed = urlparse(raw_value if "://" in raw_value else f"//{raw_value}")
            hostname = str(parsed.hostname or "").strip()
            if hostname:
                return hostname
        return ""
