"""Shared foundation infrastructure helpers reused by multiple adapters."""

import os
import subprocess
import tempfile

from adapters.inesdata.infrastructure import INESDataInfrastructureAdapter
from deployers.shared.lib.topology import (
    LOCAL_TOPOLOGY,
    VM_DISTRIBUTED_TOPOLOGY,
    VM_SINGLE_TOPOLOGY,
    normalize_topology,
)


def _sudo_write_file(path, content):
    """Write content to a root-owned path via sudo cp from a temporary file."""
    tmp_fd, tmp_path = tempfile.mkstemp()
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        proc = subprocess.run(["sudo", "cp", tmp_path, path], capture_output=True, text=True)
        return proc.returncode == 0, proc.stderr.strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


class SharedFoundationInfrastructureAdapter(INESDataInfrastructureAdapter):
    """Neutral facade for shared Level 1-2 foundation logic."""

    def setup_cluster_preflight(self, topology=LOCAL_TOPOLOGY):
        """Prepare and validate the cluster required by VM-based execution."""
        normalized_topology = normalize_topology(topology)
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
            self._ensure_ingress_nginx_forwarded_headers_vm_distributed,
            self._sync_nginx_stream_proxy_vm_distributed,
            self._sync_nginx_http_proxy_vm_distributed,
        ):
            try:
                sync_step(deployer_config)
            except Exception as exc:
                print(f"Warning: vm-distributed routing sync step skipped: {exc}")
        return {"status": "synced"}

    @staticmethod
    def _has_vm_distributed_routing_config(config):
        return bool(str((config or {}).get("VM_COMMON_IP") or "").strip()) and bool(
            str((config or {}).get("DS_DOMAIN_BASE") or "").strip()
        )

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

    def _ensure_ingress_nginx_forwarded_headers_vm_distributed(self, deployer_config):
        """Patch ingress-nginx on connector clusters to honor forwarded HTTPS headers."""
        patch = '{"data":{"use-forwarded-headers":"true","compute-full-forwarded-for":"true"}}'
        kubeconfigs = []
        for key in ("K3S_KUBECONFIG_PROVIDER", "K3S_KUBECONFIG_CONSUMER"):
            kubeconfig = str((deployer_config or {}).get(key) or "").strip()
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
                deployer_config, provider_ip, provider_shorts, ds_name, ds_domain, provider_nodeport
            )
        if consumer_ip and consumer_shorts:
            self._sync_remote_nginx_vm_distributed(
                deployer_config, consumer_ip, consumer_shorts, ds_name, ds_domain, consumer_nodeport
            )

    def _sync_remote_nginx_vm_distributed(self, deployer_config, remote_ip, connector_shorts, ds_name, ds_domain, nodeport):
        """Write connector proxy blocks on a remote VM when SSH is configured."""
        ssh_target = self._vm_distributed_ssh_target(deployer_config, remote_ip)
        if not ssh_target:
            print(f"Remote NGINX sync skipped for {remote_ip}: VM_SSH_USER is not configured.")
            return

        blocks = []
        for short in connector_shorts:
            hostname = f"conn-{short}-{ds_name}.{ds_domain}"
            blocks.append(
                "server {\n"
                "    listen 80;\n"
                f"    server_name {hostname};\n"
                "    client_max_body_size 0;\n"
                "    location / {\n"
                f"        proxy_pass http://{remote_ip}:{nodeport};\n"
                "        proxy_set_header Host $host;\n"
                "        proxy_set_header X-Real-IP $remote_addr;\n"
                "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                "        proxy_set_header X-Forwarded-Proto $scheme;\n"
                "        proxy_http_version 1.1;\n"
                "    }\n"
                "}\n"
            )
        if not blocks:
            return

        remote_conf = f"/etc/nginx/sites-enabled/pionera-vm-distributed-{ds_name}.conf"
        content = "# Generated by Validation-Environment for vm-distributed connector routing\n" + "\n".join(blocks)
        try:
            write_proc = subprocess.run(
                ["ssh", ssh_target, f"sudo tee {remote_conf} >/dev/null"],
                input=content,
                capture_output=True,
                text=True,
            )
            if write_proc.returncode != 0:
                print(f"Warning: remote NGINX write failed on {remote_ip}: {write_proc.stderr.strip()}")
                return
            reload_proc = subprocess.run(["ssh", ssh_target, "sudo nginx -s reload"], capture_output=True, text=True)
            if reload_proc.returncode == 0:
                print(f"Remote NGINX routing updated on {remote_ip}: {remote_conf}")
            else:
                print(f"Warning: remote NGINX reload failed on {remote_ip}: {reload_proc.stderr.strip()}")
        except Exception as exc:
            print(f"Warning: remote NGINX sync skipped on {remote_ip}: {exc}")
