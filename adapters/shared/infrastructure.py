"""Shared foundation infrastructure helpers reused by multiple adapters."""

from adapters.inesdata.infrastructure import INESDataInfrastructureAdapter
from deployers.shared.lib.topology import LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY, normalize_topology


class SharedFoundationInfrastructureAdapter(INESDataInfrastructureAdapter):
    """Neutral facade for shared Level 1-2 foundation logic."""

    def setup_cluster_preflight(self, topology=LOCAL_TOPOLOGY):
        """Prepare and validate the cluster required by VM-based execution."""
        normalized_topology = normalize_topology(topology)
        if normalized_topology == LOCAL_TOPOLOGY:
            return self.setup_cluster()
        if normalized_topology != VM_SINGLE_TOPOLOGY:
            raise RuntimeError(
                f"Level 1 preflight is not implemented for topology '{normalized_topology}' yet."
            )

        cluster_runtime = self._cluster_runtime_config()
        cluster_type = cluster_runtime.get("cluster_type", "minikube")
        print(
            "Topology 'vm-single' uses a Kubernetes cluster managed on the VM.\n"
            f"Level 1 will prepare the managed {cluster_type} cluster to keep runs reproducible."
        )
        self.setup_cluster()
        print("Managed vm-single cluster recreated. Running cluster preflight checks.")

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
            "mode": "managed-recreate",
            "topology": normalized_topology,
            "cluster_runtime": cluster_type,
            "current_context": current_context,
            "cluster_creation": "recreated",
            "checks": checks,
        }

    def deploy_infrastructure_for_topology(self, topology=LOCAL_TOPOLOGY):
        """Run Level 2 foundation deployment using the safest topology-aware path."""
        normalized_topology = normalize_topology(topology)
        if normalized_topology == LOCAL_TOPOLOGY:
            return self.deploy_infrastructure()
        if normalized_topology != VM_SINGLE_TOPOLOGY:
            raise RuntimeError(
                f"Level 2 deploy_infrastructure_for_topology() is not implemented for topology "
                f"'{normalized_topology}' yet."
            )

        return self._deploy_infrastructure_runtime(
            skip_hosts=True,
            host_sync_message=(
                "Skipping client-side hosts synchronization for topology 'vm-single'. "
                "Use the dedicated hosts command if you need local name resolution."
            ),
        )
