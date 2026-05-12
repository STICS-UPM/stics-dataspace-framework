#!/usr/bin/env python3
"""
Local deployment entrypoint for Validation-Environment.

This script keeps the historical INESData workflow intact and adds a parallel
path that deploys services using local images built from:
adapters/inesdata/sources
"""

import argparse
import glob
import os
import shlex
import socket
import subprocess
import sys
import time
import requests

from runtime_dependencies import ensure_runtime_dependencies


ensure_runtime_dependencies(
    requirements_path=os.path.join(os.path.dirname(__file__), "requirements.txt"),
    module_names=("yaml", "requests", "tabulate", "ruamel.yaml"),
    label="local INESData entrypoint",
)

from adapters.inesdata import InesdataAdapter


def _is_retryable_command(cmd: str) -> bool:
    if "local_build_load_deploy.sh" in cmd or "build_images.sh" in cmd:
        return False
    if "docker image inspect" in cmd:
        return False
    markers = ("docker", "minikube", "kubectl", "helm")
    return any(marker in cmd for marker in markers)


def run(cmd, capture=False, silent=False, check=True, cwd=None):
    """Execute shell command with simple retry logic for infra commands."""
    attempts = 3 if _is_retryable_command(cmd) else 1
    delay_seconds = 4
    is_portforward_pkill = (
        cmd.strip().startswith("pkill -f 'kubectl port-forward")
        or cmd.strip().startswith('pkill -f "kubectl port-forward')
    )

    for attempt in range(1, attempts + 1):
        if not silent:
            if attempts > 1:
                print(f"\nExecuting (attempt {attempt}/{attempts}): {cmd}")
            else:
                print(f"\nExecuting: {cmd}")

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                text=True,
                capture_output=capture,
                cwd=cwd,
            )
        except Exception as exc:
            if attempt == attempts:
                print(f"Execution error: {exc}")
                return None
            print(f"Transient execution error: {exc}. Retrying in {delay_seconds}s...")
            time.sleep(delay_seconds)
            continue

        if result.returncode == 0:
            if capture:
                return result.stdout.strip()
            return result

        # pkill may return 1 (no process) or be terminated with SIGTERM (-15)
        # when matching short-lived/killed shells. Treat these outcomes as benign.
        if is_portforward_pkill and result.returncode in (1, -15):
            if capture:
                return result.stdout.strip() if result.stdout else ""
            return result

        stderr_text = result.stderr.strip() if result.stderr else ""
        stdout_text = result.stdout.strip() if result.stdout else ""
        combined = f"{stdout_text}\n{stderr_text}".strip()

        if attempt < attempts:
            if not silent and combined:
                print(combined)
            print(f"Command failed with exit code {result.returncode}. Retrying in {delay_seconds}s...")
            time.sleep(delay_seconds)
            continue

        if check:
            print(f"Command failed with exit code {result.returncode}")
            if combined:
                print(combined)
        return None

    return None


def run_silent(cmd, cwd=None):
    return run(cmd, capture=True, silent=True, check=False, cwd=cwd)


def project_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def local_script_path() -> str:
    return os.path.join(project_dir(), "adapters", "inesdata", "scripts", "local_build_load_deploy.sh")


def build_script_path() -> str:
    return os.path.join(project_dir(), "adapters", "inesdata", "scripts", "build_images.sh")


def seed_assets_script_path() -> str:
    return os.path.join(project_dir(), "scripts", "seed_ml_assets_for_connectors.sh")


def fast_step1_script_path() -> str:
    return os.path.join(project_dir(), "adapters", "inesdata", "scripts", "fast_step1_images.sh")


def _component_image_repositories(args):
    base = f"{args.local_registry_host}/{args.local_namespace}"
    return [
        f"{base}/inesdata-connector",
        f"{base}/inesdata-connector-interface",
        f"{base}/inesdata-registration-service",
        f"{base}/inesdata-public-portal-backend",
        f"{base}/inesdata-public-portal-frontend",
    ]


def _filter_component_images(image_rows, repositories):
    selected = set()
    for row in image_rows:
        image_ref = row.strip().split()[0] if row.strip() else ""
        if not image_ref:
            continue
        if any(image_ref.startswith(f"{repo}:") for repo in repositories):
            selected.add(image_ref)
    return sorted(selected)


def cleanup_step_1_images(args):
    repositories = _component_image_repositories(args)

    docker_rows = (
        run("docker images --format '{{.Repository}}:{{.Tag}}'", capture=True, check=False, silent=True)
        or ""
    ).splitlines()
    docker_images = _filter_component_images(docker_rows, repositories)

    minikube_rows = (
        run(
            f"minikube -p {shlex.quote(args.minikube_profile)} image ls",
            capture=True,
            check=False,
            silent=True,
        )
        or ""
    ).splitlines()
    minikube_images = _filter_component_images(minikube_rows, repositories)

    if not docker_images and not minikube_images:
        print("No previous Step 1 local images found for INESData components")
        return

    if docker_images:
        print(f"Removing Docker images ({len(docker_images)})")
        failed = []
        for image_ref in docker_images:
            if run(f"docker rmi -f {shlex.quote(image_ref)}", check=False, silent=True) is None:
                failed.append(image_ref)
        if failed:
            print(f"Warning: failed to remove {len(failed)} Docker images")

    if minikube_images:
        print(f"Removing Minikube cached images ({len(minikube_images)})")
        failed = []
        for image_ref in minikube_images:
            if run(
                f"minikube -p {shlex.quote(args.minikube_profile)} image rm {shlex.quote(image_ref)}",
                check=False,
                silent=True,
            ) is None:
                failed.append(image_ref)
        if failed:
            print(f"Warning: failed to remove {len(failed)} Minikube cached images")


def resolve_platform_dir(platform_dir: str) -> str:
    candidate = platform_dir if os.path.isabs(platform_dir) else os.path.join(project_dir(), platform_dir)

    has_required_chart_dirs = (
        os.path.isdir(os.path.join(candidate, "dataspace"))
        and os.path.isdir(os.path.join(candidate, "connector"))
    )
    if has_required_chart_dirs:
        return candidate

    # Backward-compatible default: if inesdata-testing has no charts, use inesdata-deployment.
    default_testing = os.path.join(project_dir(), "inesdata-testing")
    default_deployment = os.path.join(project_dir(), "inesdata-deployment")
    requested_default_testing = os.path.normpath(candidate) == os.path.normpath(default_testing)
    deployment_has_charts = (
        os.path.isdir(os.path.join(default_deployment, "dataspace"))
        and os.path.isdir(os.path.join(default_deployment, "connector"))
    )

    if requested_default_testing and deployment_has_charts:
        print(f"Auto-resolved platform charts directory: {default_deployment}")
        return default_deployment

    return candidate


def manifests_dir() -> str:
    return os.environ.get("MANIFESTS_DIR", "/tmp/inesdata-manifests")


def resolve_manifest_path(manifest_path: str) -> str:
    if manifest_path:
        candidate = manifest_path if os.path.isabs(manifest_path) else os.path.join(project_dir(), manifest_path)
        if os.path.isfile(candidate):
            return candidate
        raise RuntimeError(f"Manifest file not found: {candidate}")

    preferred = os.path.join(manifests_dir(), "images-fast-step1.tsv")
    if os.path.isfile(preferred):
        return preferred

    candidates = sorted(glob.glob(os.path.join(manifests_dir(), "images-*.tsv")), reverse=True)
    if not candidates:
        raise RuntimeError(
            "No image manifest was found. Run the image build step first or provide --manifest"
        )

    return candidates[0]


def _manifest_components(manifest_path: str):
    components = set()
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            for idx, raw_line in enumerate(handle):
                line = raw_line.strip()
                if not line:
                    continue
                if idx == 0 and line.startswith("component\t"):
                    continue
                component = line.split("\t", 1)[0].strip()
                if component:
                    components.add(component)
    except OSError:
        return set()
    return components


def _required_components_for_deploy_target(deploy_target: str):
    if deploy_target == "dataspace":
        return {"registration-service", "public-portal-backend", "public-portal-frontend"}
    if deploy_target == "connectors":
        return {"connector", "connector-interface"}
    return {
        "connector",
        "connector-interface",
        "registration-service",
        "public-portal-backend",
        "public-portal-frontend",
    }


def _expected_step1_components(args):
    if args.step1_components:
        return {item.strip() for item in args.step1_components.split(",") if item.strip()}

    if args.step1_mode == "initial":
        return {
            "connector",
            "connector-interface",
            "registration-service",
            "public-portal-backend",
            "public-portal-frontend",
        }

    return set()


def _validate_step1_manifest(args, manifest_path: str):
    components = _manifest_components(manifest_path)
    if not components:
        raise RuntimeError(
            "Step 3 produced an empty manifest. "
            "Re-run Step 3 and verify component source directories under adapters/inesdata/sources"
        )

    expected = _expected_step1_components(args)
    if expected and not expected.issubset(components):
        missing = sorted(expected - components)
        raise RuntimeError(
            "Step 3 manifest is incomplete. Missing components: "
            f"{', '.join(missing)}. Manifest: {manifest_path}"
        )


def _candidate_manifests(preselected: str = ""):
    candidates = []

    def add_candidate(path: str):
        if not path:
            return
        if not os.path.isfile(path):
            return
        if path in candidates:
            return
        candidates.append(path)

    add_candidate(preselected)

    preferred = os.path.join(manifests_dir(), "images-fast-step1.tsv")
    add_candidate(preferred)

    for path in sorted(glob.glob(os.path.join(manifests_dir(), "images-*.tsv")), reverse=True):
        add_candidate(path)

    return candidates


def ensure_prerequisites():
    if run("which docker", capture=True, check=False, silent=True) is None:
        raise RuntimeError("Docker is not installed or not found in PATH")

    if run("which minikube", capture=True, check=False, silent=True) is None:
        raise RuntimeError("Minikube is not installed or not found in PATH")

    if run("which helm", capture=True, check=False, silent=True) is None:
        raise RuntimeError("Helm is not installed or not found in PATH")

    if run("docker info", capture=True, check=False, silent=True) is None:
        raise RuntimeError("Docker daemon is not reachable. Start Docker and retry")


def print_manual_actions():
    print("\n" + "=" * 60)
    print("MANUAL ACTION REQUIRED BEFORE STEP 3 (DATASPACE)")
    print("=" * 60)
    print("1) Open another terminal and run:")
    print("   minikube tunnel")
    print("\n2) Open another terminal and run:")
    print(
        "   cd /home/edmundo/Validation-Environment && "
        "kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8080:80"
    )
    print("\nKeep both commands running during dataspace and connectors deployment.")
    print("=" * 60)


def _is_port_open(host: str, port: int, timeout_seconds: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def verify_manual_actions(timeout_seconds: int = 30) -> bool:
    tunnel_proc = run_silent('pgrep -af "minikube tunnel"')
    if not tunnel_proc:
        print("minikube tunnel process not detected")
        return False

    port_forward_proc = run_silent(
        'pgrep -af "kubectl.*port-forward.*ingress-nginx-controller.*8080:80"'
    )
    if not port_forward_proc:
        print("kubectl port-forward process for ingress-nginx-controller on 8080 not detected")
        return False

    started_at = time.time()
    while time.time() - started_at < timeout_seconds:
        if _is_port_open("127.0.0.1", 8080):
            return True
        time.sleep(1)

    print("Port 8080 is not reachable on localhost")
    return False


def wait_for_manual_confirmation(manual_ready: bool) -> bool:
    if manual_ready:
        print("Manual readiness was provided via flag. Continuing...")
        return True

    if not sys.stdin.isatty():
        print_manual_actions()
        print(
            "\nNon-interactive terminal detected. "
            "Run again with --resume-after-manual --manual-ready once manual actions are active."
        )
        return False

    print_manual_actions()
    input("\nWhen both commands are active, press ENTER to continue...")
    return True


def run_local_image_build(args) -> str:
    if args.skip_build:
        manifest = resolve_manifest_path(args.manifest)
        print(f"Using existing manifest: {manifest}")
        return manifest

    # Fail early with explicit diagnostics if Docker cannot fetch required base images.
    prefetch_base_images()

    script = fast_step1_script_path()
    if not os.path.isfile(script):
        raise RuntimeError(f"Fast Step 1 script not found: {script}")

    manifest_output = args.manifest or os.path.join(manifests_dir(), "images-fast-step1.tsv")
    command_parts = [
        "bash",
        script,
        "--mode",
        args.step1_mode,
        "--namespace",
        args.namespace,
        "--minikube-profile",
        args.minikube_profile,
        "--registry-host",
        args.local_registry_host,
        "--registry-namespace",
        args.local_namespace,
        "--image-tag",
        args.step1_image_tag,
        "--manifest",
        manifest_output,
    ]

    if args.step1_components:
        command_parts.extend(["--components", args.step1_components])

    if args.step1_refresh_runtime:
        command_parts.append("--refresh-runtime")

    if args.step1_skip_minikube_load:
        command_parts.append("--skip-minikube-load")

    if run(" ".join(shlex.quote(part) for part in command_parts), cwd=project_dir()) is None:
        raise RuntimeError("Fast Step 1 build workflow failed")

    manifest = resolve_manifest_path(manifest_output)
    _validate_step1_manifest(args, manifest)
    print(f"Image manifest selected: {manifest}")
    return manifest


def run_local_image_deploy(args, manifest_path: str, deploy_target: str = "all"):
    script = local_script_path()
    if not os.path.isfile(script):
        raise RuntimeError(f"Local deployment script not found: {script}")

    platform_dir = resolve_platform_dir(args.platform_dir)
    if not os.path.isdir(platform_dir):
        raise RuntimeError(
            "Platform directory not found. "
            f"Expected: {platform_dir}. "
            "Use --platform-dir inesdata-deployment or an absolute path"
        )

    if not os.path.isdir(os.path.join(platform_dir, "dataspace")) or not os.path.isdir(
        os.path.join(platform_dir, "connector")
    ):
        raise RuntimeError(
            "Platform directory is missing required Helm chart folders ('dataspace' and 'connector'). "
            f"Provided: {platform_dir}. "
            "Use --platform-dir inesdata-deployment or a path containing both folders"
        )

    command_parts = [
        "bash",
        script,
        "--apply",
        "--platform-dir",
        platform_dir,
        "--namespace",
        args.namespace,
        "--minikube-profile",
        args.minikube_profile,
        "--skip-build",
        "--manifest",
        manifest_path,
        "--deploy-target",
        deploy_target,
    ]

    quoted_command = " ".join(shlex.quote(part) for part in command_parts)
    env_parts = [
        f"LOCAL_REGISTRY_HOST={shlex.quote(args.local_registry_host)}",
        f"LOCAL_NAMESPACE={shlex.quote(args.local_namespace)}",
    ]

    if args.disable_buildkit:
        env_parts.insert(0, "COMPOSE_DOCKER_CLI_BUILD=0")
        env_parts.insert(0, "DOCKER_BUILDKIT=0")

    env_prefix = " ".join(env_parts)

    full_command = f"{env_prefix} {quoted_command}"
    if run(full_command, cwd=project_dir()) is None:
        raise RuntimeError("Local build/load/deploy failed")


def run_validation_pipeline():
    command = f"{shlex.quote(sys.executable)} main.py inesdata validate"
    if run(command, cwd=project_dir()) is None:
        raise RuntimeError("Validation step failed")


def run_seed_assets_pipeline(args):
    script = seed_assets_script_path()
    if not os.path.isfile(script):
        raise RuntimeError(f"Seed assets script not found: {script}")

    command_parts = [
        "bash",
        script,
        "--namespace",
        args.namespace,
        "--count",
        str(args.seed_assets_count),
        "--connectors",
        args.seed_connectors,
        "--credentials-dir",
        args.seed_credentials_dir,
        "--vocabulary-id",
        args.seed_vocabulary_id,
        "--vocabulary-name",
        args.seed_vocabulary_name,
        "--vocabulary-category",
        args.seed_vocabulary_category,
        "--vocabulary-schema",
        args.seed_vocabulary_schema,
    ]

    if args.seed_keycloak_token_url:
        command_parts.extend(["--keycloak-token-url", args.seed_keycloak_token_url])

    command = " ".join(shlex.quote(part) for part in command_parts)
    if run(command, cwd=project_dir()) is None:
        raise RuntimeError("Step 6 assets seeding failed")


def _normalize_http_url(value: str) -> str:
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"http://{value}"


def _ensure_validation_prerequisites(args, adapter):
    deployer_config = adapter.load_deployer_config() or {}
    keycloak_url = _normalize_http_url(
        deployer_config.get("KC_URL") or deployer_config.get("KC_INTERNAL_URL") or ""
    )

    if keycloak_url:
        realm_url = f"{keycloak_url}/realms/{args.namespace}"
        try:
            response = requests.get(realm_url, timeout=8)
            if response.status_code != 200:
                raise RuntimeError(
                    f"Keycloak realm '{args.namespace}' is not ready (HTTP {response.status_code}). "
                    "Run Step 3 (Dataspace deployment) first."
                )
        except requests.RequestException as exc:
            raise RuntimeError(
                "Unable to reach Keycloak for validation precheck. "
                "Ensure tunnel/port-forward are active and run Step 3 first."
            ) from exc

    connectors = adapter.get_cluster_connectors()
    if len(connectors) < 2:
        raise RuntimeError(
            "Validation requires at least 2 running connectors. "
            "Run Step 4 (Connectors deployment) first."
        )


def _ensure_manual_prerequisites_for_recovery(args):
    if verify_manual_actions(timeout_seconds=args.manual_check_timeout):
        return

    if not wait_for_manual_confirmation(args.manual_ready):
        raise RuntimeError(
            "Manual actions were not confirmed. "
            "Start minikube tunnel and ingress port-forward, then press ENTER."
        )

    if not verify_manual_actions(timeout_seconds=args.manual_check_timeout):
        raise RuntimeError(
            "Manual prerequisites are not active. "
            "Ensure minikube tunnel and kubectl port-forward 8080:80 are running."
        )


def _select_manifest_for_deploy(args, manifest_path: str, deploy_target: str) -> str:
    required_components = _required_components_for_deploy_target(deploy_target)

    provided_manifest = ""
    if manifest_path:
        provided_manifest = manifest_path
    elif args.manifest:
        provided_manifest = resolve_manifest_path(args.manifest)

    for candidate in _candidate_manifests(provided_manifest):
        components = _manifest_components(candidate)
        if required_components.issubset(components):
            if provided_manifest and candidate != provided_manifest:
                print(f"Selected compatible manifest instead of incomplete one: {candidate}")
            return candidate

    raise RuntimeError(
        "No compatible image manifest found for deployment target "
        f"'{deploy_target}'. Required components: {', '.join(sorted(required_components))}. "
        "Run Step 3 (Build local images) to regenerate a complete manifest."
    )


def step_1_build(args) -> str:
    print("\n[Step 3/7] Build/rebuild local images from adapters/inesdata/sources")
    return run_local_image_build(args)


def _pull_image_with_retries(image_ref: str, attempts: int = 3, delay_seconds: int = 4) -> bool:
    for attempt in range(1, attempts + 1):
        print(f"Preparing base image ({attempt}/{attempts}): {image_ref}")
        result = subprocess.run(
            f"docker pull {shlex.quote(image_ref)}",
            shell=True,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            return True

        error_text = "\n".join(
            part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part
        )

        if attempt < attempts:
            if error_text:
                print(error_text)
            print(f"Base image pull failed. Retrying in {delay_seconds}s...")
            time.sleep(delay_seconds)
            continue

        if error_text:
            print(error_text)
    return False


def _extract_base_images_from_dockerfile(dockerfile_path: str):
    images = []
    try:
        with open(dockerfile_path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if not line.upper().startswith("FROM "):
                    continue

                tokens = line.split()
                if len(tokens) < 2:
                    continue

                # Supports syntaxes like:
                # FROM image:tag
                # FROM image:tag AS builder
                # FROM --platform=linux/amd64 image:tag AS builder
                image_token = ""
                for token in tokens[1:]:
                    if token.startswith("--"):
                        continue
                    image_token = token
                    break

                if image_token:
                    images.append(image_token)
    except OSError:
        return []

    return images


def _discover_step_1_base_images():
    sources_dir = os.path.join(project_dir(), "adapters", "inesdata", "sources")
    dockerfiles = [
        os.path.join(sources_dir, "inesdata-connector", "docker", "Dockerfile"),
        os.path.join(sources_dir, "inesdata-connector-interface", "docker", "Dockerfile"),
        os.path.join(sources_dir, "inesdata-registration-service", "docker", "Dockerfile"),
        os.path.join(sources_dir, "inesdata-public-portal-backend", "Dockerfile"),
        os.path.join(sources_dir, "inesdata-public-portal-frontend", "docker", "Dockerfile"),
    ]

    discovered = set()
    for dockerfile in dockerfiles:
        for image_ref in _extract_base_images_from_dockerfile(dockerfile):
            discovered.add(image_ref)

    return sorted(discovered)


def prefetch_base_images():
    base_images = _discover_step_1_base_images() or [
        "eclipse-temurin:17-jre-jammy",
        "eclipse-temurin:17-jre-alpine",
        "node:20.11-alpine",
        "node:18.16-alpine",
        "node:18-alpine",
        "nginx:alpine",
    ]

    print("Pre-fetching required base images for Step 1")
    failed_images = []

    for image_ref in base_images:
        already_present = run(
            f"docker image inspect {shlex.quote(image_ref)}",
            capture=True,
            check=False,
            silent=True,
        )
        if already_present is not None:
            continue

        if not _pull_image_with_retries(image_ref):
            failed_images.append(image_ref)

    if failed_images:
        docker_host = os.environ.get("DOCKER_HOST", "")
        context_name = run("docker context show", capture=True, check=False, silent=True) or "unknown"
        raise RuntimeError(
            "Unable to pull required base images for Step 1. "
            f"Failed images: {', '.join(failed_images)}. "
            f"Docker context: {context_name}. "
            f"DOCKER_HOST: {docker_host or '(not set)'}. "
            "Check DNS/proxy connectivity to registry-1.docker.io and retry."
        )


def step_2_common_services(args, adapter):
    print("\n[Step 1/7] Cluster setup and common services")

    if args.skip_level1:
        print("Cluster setup skipped (--skip-level1)")
    else:
        adapter.setup_cluster()

    if args.skip_level2:
        print("Common services deployment skipped (--skip-level2)")
    else:
        adapter.deploy_infrastructure()


def step_2_manual_network_prerequisites(args, prompt_user: bool = True):
    print("\n[Step 2/7] Manual network prerequisites (tunnel + ingress port-forward)")

    if prompt_user:
        if not wait_for_manual_confirmation(args.manual_ready):
            raise RuntimeError(
                "Manual actions not confirmed. Run again after starting tunnel and port-forward."
            )
    elif not args.manual_ready:
        raise RuntimeError(
            "--resume-after-manual requires --manual-ready to confirm tunnel and port-forward"
        )

    if not verify_manual_actions(timeout_seconds=args.manual_check_timeout):
        raise RuntimeError(
            "Manual prerequisites are not active. "
            "Ensure minikube tunnel and kubectl port-forward 8080:80 are running."
        )


def step_3_dataspace(args, adapter_bootstrap, manifest_path: str):
    print("\n[Step 4/7] Dataspace deployment (local images)")

    if not verify_manual_actions(timeout_seconds=args.manual_check_timeout):
        raise RuntimeError(
            "Manual prerequisites are not active. "
            "Ensure minikube tunnel and kubectl port-forward 8080:80 are running."
        )

    selected_manifest = _select_manifest_for_deploy(args, manifest_path, "dataspace")
    print("Applying dataspace bootstrap workflow...")
    adapter_bootstrap.deploy_dataspace()
    print("Applying local dataspace images...")
    run_local_image_deploy(args, selected_manifest, deploy_target="dataspace")
    return selected_manifest


def step_4_connectors(args, adapter_bootstrap, manifest_path: str):
    print("\n[Step 5/7] Connectors deployment (local images)")
    selected_manifest = _select_manifest_for_deploy(args, manifest_path, "connectors")
    print("Applying connectors bootstrap workflow...")
    connectors = adapter_bootstrap.deploy_connectors()
    print("Applying local connector images...")
    run_local_image_deploy(args, selected_manifest, deploy_target="connectors")

    if not adapter_bootstrap.wait_for_all_connectors(connectors):
        raise RuntimeError(
            "Local connector images were applied, but connector health checks failed. "
            "Management/protocol endpoints are not ready."
        )

    return selected_manifest


def step_5_validation(args, adapter, adapter_bootstrap, manifest_path: str):
    if args.skip_validation:
        print("\n[Step 6/7] Validation skipped (--skip-validation)")
        return

    try:
        _ensure_validation_prerequisites(args, adapter)
    except RuntimeError as exc:
        print(f"Validation precheck failed: {exc}")
        print("Running automatic recovery for Step 5 prerequisites...")

        _ensure_manual_prerequisites_for_recovery(args)
        selected_manifest = _select_manifest_for_deploy(args, manifest_path, "all")

        print("Recovery: bootstrap dataspace")
        adapter_bootstrap.deploy_dataspace()
        print("Recovery: apply local dataspace images")
        run_local_image_deploy(args, selected_manifest, deploy_target="dataspace")

        print("Recovery: bootstrap connectors")
        adapter_bootstrap.deploy_connectors()
        print("Recovery: apply local connector images")
        run_local_image_deploy(args, selected_manifest, deploy_target="connectors")

        _ensure_validation_prerequisites(args, adapter)

    print("\n[Step 6/7] Validation tests")
    run_validation_pipeline()


def step_6_seed_assets(args):
    if args.skip_seed_assets:
        print("\n[Step 7/7] Assets seeding skipped (--skip-seed-assets)")
        return

    print("\n[Step 7/7] Initialize connector data (vocabulary + ML assets)")
    run_seed_assets_pipeline(args)


def execute(args):
    ensure_prerequisites()

    adapter = InesdataAdapter(
        run=run,
        run_silent=run_silent,
        auto_mode_getter=lambda: False,
    )
    adapter_bootstrap = InesdataAdapter(
        run=run,
        run_silent=run_silent,
        auto_mode_getter=lambda: True,
    )

    manifest_path = ""

    if args.resume_after_manual:
        step_2_manual_network_prerequisites(args, prompt_user=False)
        manifest_path = step_1_build(args)
    else:
        step_2_common_services(args, adapter)
        step_2_manual_network_prerequisites(args, prompt_user=True)
        manifest_path = step_1_build(args)

    manifest_path = step_3_dataspace(args, adapter_bootstrap, manifest_path)
    manifest_path = step_4_connectors(args, adapter_bootstrap, manifest_path)
    step_5_validation(args, adapter, adapter_bootstrap, manifest_path)
    step_6_seed_assets(args)

    print("\nLocal deployment completed with local images from adapters/inesdata/sources")
    return 0


def show_menu(args):
    """Display a numbered local deployment menu analogous to the historical INESData menu."""
    ensure_prerequisites()

    adapter = InesdataAdapter(
        run=run,
        run_silent=run_silent,
        auto_mode_getter=lambda: False,
    )
    adapter_bootstrap = InesdataAdapter(
        run=run,
        run_silent=run_silent,
        auto_mode_getter=lambda: True,
    )
    manifest_path = ""

    while True:
        print("\n" + "=" * 60)
        print("LOCAL INESDATA DEPLOYMENT")
        print("=" * 60)
        print("\n[Full Deployment]")
        print("0 - Run all steps (1-7) sequentially")
        print("\n[Individual Steps]")
        print("1 - Step 1: Setup cluster + deploy common services")
        print("2 - Step 2: Confirm tunnel + ingress port-forward")
        print("3 - Step 3: Build local images")
        print("4 - Step 4: Deploy dataspace (local images)")
        print("5 - Step 5: Deploy connectors (local images)")
        print("6 - Step 6: Run validation tests")
        print("7 - Step 7: Seed vocabulary + ML assets")
        print("\n[Control]")
        print("Q - Exit")
        print("=" * 60)

        try:
            choice = input("\nSelection: ").strip().upper()
        except EOFError:
            print("\nNo more input. Exiting Local INESData Deployment\n")
            return 0

        if choice == "Q":
            print("\nExiting Local INESData Deployment\n")
            return 0

        if choice == "0":
            return execute(args)

        try:
            if choice == "1":
                step_2_common_services(args, adapter)
            elif choice == "2":
                step_2_manual_network_prerequisites(args, prompt_user=True)
            elif choice == "3":
                manifest_path = step_1_build(args)
            elif choice == "4":
                manifest_path = step_3_dataspace(args, adapter_bootstrap, manifest_path)
            elif choice == "5":
                manifest_path = step_4_connectors(args, adapter_bootstrap, manifest_path)
            elif choice == "6":
                step_5_validation(args, adapter, adapter_bootstrap, manifest_path)
            elif choice == "7":
                step_6_seed_assets(args)
            else:
                print("\nInvalid selection. Please try again.\n")
        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user\n")
        except Exception as exc:
            print(f"\nError during execution: {exc}\n")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Local deploy pipeline for Validation-Environment using local component images"
    )
    parser.add_argument("--namespace", default="demo", help="Kubernetes namespace (default: demo)")
    parser.add_argument(
        "--platform-dir",
        default="inesdata-testing",
        help=(
            "Platform chart directory relative to Validation-Environment "
            "(default: inesdata-testing; auto-fallback to inesdata-deployment if charts are not present)"
        ),
    )
    parser.add_argument(
        "--minikube-profile",
        default="minikube",
        help="Minikube profile name (default: minikube)",
    )
    parser.add_argument(
        "--local-registry-host",
        default="local",
        help="Registry host prefix used for local images (default: local)",
    )
    parser.add_argument(
        "--local-namespace",
        default="inesdata",
        help="Registry namespace used for local images (default: inesdata)",
    )
    parser.add_argument(
        "--step1-mode",
        choices=("initial", "changed"),
        default="initial",
        help="Fast Step 1 mode: initial cleans all INESData images, changed rebuilds only modified components",
    )
    parser.add_argument(
        "--step1-components",
        default="",
        help="Optional comma-separated components for Step 1 override",
    )
    parser.add_argument(
        "--step1-image-tag",
        default="dev",
        help="Stable Step 1 image tag used for all built components (default: dev)",
    )
    parser.add_argument(
        "--step1-refresh-runtime",
        action="store_true",
        help="After Step 1 build/load, restart relevant deployments to reflect changes quickly",
    )
    parser.add_argument(
        "--step1-skip-minikube-load",
        action="store_true",
        help="Step 1 builds local images only and skips loading to minikube cache",
    )
    parser.add_argument("--manifest", default="", help="Optional manifest TSV for prebuilt images")
    parser.add_argument("--skip-build", action="store_true", help="Skip image build and reuse manifest")
    parser.add_argument(
        "--disable-buildkit",
        action="store_true",
        help="Disable Docker BuildKit and use legacy builder compatibility mode",
    )
    parser.add_argument("--skip-level1", action="store_true", help="Skip cluster setup inside Step 2")
    parser.add_argument("--skip-level2", action="store_true", help="Skip common services deployment inside Step 2")
    parser.add_argument("--skip-validation", action="store_true", help="Skip validation phase")
    parser.add_argument("--skip-seed-assets", action="store_true", help="Skip Step 6 ML assets initialization")
    parser.add_argument(
        "--seed-assets-count",
        type=int,
        default=8,
        help="Assets to insert per connector in Step 6 (default: 8)",
    )
    parser.add_argument(
        "--seed-connectors",
        default="conn-citycouncil-demo,conn-company-demo",
        help="Comma-separated connectors to seed in Step 6",
    )
    default_seed_credentials_dir = os.path.join(project_dir(), "inesdata-testing", "deployments", "DEV", "demo")
    if not os.path.isdir(default_seed_credentials_dir):
        default_seed_credentials_dir = os.path.join(project_dir(), "inesdata-deployment", "deployments", "DEV", "demo")
    parser.add_argument(
        "--seed-credentials-dir",
        default=default_seed_credentials_dir,
        help=(
            "Credentials directory for Step 6 (default: inesdata-testing/deployments/DEV/demo; "
            "fallback to inesdata-deployment if missing)"
        ),
    )
    parser.add_argument(
        "--seed-vocabulary-id",
        default="JS_Pionera_Daimo",
        help="Vocabulary ID to register/use in Step 6",
    )
    parser.add_argument(
        "--seed-vocabulary-name",
        default="JS Metadata Daimo",
        help="Vocabulary name for Step 6",
    )
    parser.add_argument(
        "--seed-vocabulary-category",
        default="machineLearning",
        help="Vocabulary category for Step 6",
    )
    parser.add_argument(
        "--seed-vocabulary-schema",
        default=os.path.join(project_dir(), "JS_Metadata_Daimo.schema.json"),
        help="Vocabulary schema file path for Step 6",
    )
    parser.add_argument(
        "--seed-keycloak-token-url",
        default="",
        help="Optional Keycloak token URL override for Step 6",
    )
    parser.add_argument(
        "--manual-check-timeout",
        type=int,
        default=30,
        help="Seconds to wait for localhost:8080 after tunnel/port-forward check (default: 30)",
    )
    parser.add_argument(
        "--manual-ready",
        action="store_true",
        help="Confirm that minikube tunnel and ingress port-forward are already active",
    )
    parser.add_argument(
        "--resume-after-manual",
        action="store_true",
        help="Resume from Step 3 after manual tunnel/port-forward setup",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run full local pipeline directly without interactive numbered menu",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.non_interactive or not sys.stdin.isatty():
            return execute(args)
        return show_menu(args)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    except Exception as exc:
        print(f"\nError: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
