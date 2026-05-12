import json
import os
import re
import shlex
import subprocess
import time
from html import unescape
from urllib.parse import quote, unquote

import requests

from adapters.inesdata.config import InesdataConfig


def _kubectl_env():
    env = os.environ.copy()
    if not env.get("KUBECONFIG"):
        k3s_default = "/etc/rancher/k3s/k3s.yaml"
        if os.path.exists(k3s_default):
            env["KUBECONFIG"] = k3s_default
    return env


def _run(cmd, check=False):
    print(f"\nExecuting: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, text=True, env=_kubectl_env())
    except Exception as exc:
        print(f"Execution error: {exc}")
        return None

    if result.returncode != 0:
        if check:
            print(f"Command failed with exit code {result.returncode}")
        return None
    return result


def _run_capture(cmd):
    print(f"\nExecuting: {cmd}")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            text=True,
            capture_output=True,
            env=_kubectl_env(),
        )
    except Exception as exc:
        print(f"Execution error: {exc}")
        return None

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        print(stdout)
    if result.returncode != 0:
        if stderr:
            print(stderr)
        print(f"Command failed with exit code {result.returncode}")
        return None
    return stdout


def _ontology_hub_release_name(runtime=None):
    dataspace = str((runtime or {}).get("dataspace") or "").strip()
    if not dataspace:
        dataspace = InesdataConfig.dataspace_name()
    return f"{dataspace}-ontology-hub"


def _ontology_hub_components_namespace(runtime=None):
    namespace = str((runtime or {}).get("componentsNamespace") or "").strip()
    if namespace:
        return namespace
    namespace = str(os.environ.get("ONTOLOGY_HUB_COMPONENTS_NAMESPACE") or "").strip()
    if namespace:
        return namespace
    return "components"


def ontology_hub_functional_reset_mode():
    mode = (
        os.environ.get("ONTOLOGY_HUB_FUNCTIONAL_RESET_MODE")
        or os.environ.get("ONTOLOGY_HUB_APP_FLOWS_RESET_MODE")
        or "soft"
    ).strip().lower()
    if mode not in {"soft", "hard", "off"}:
        return "soft"
    return mode


def reset_ontology_hub_for_functional(runtime=None):
    """Recreate the runtime used by the Ontology Hub functional suite on the current namespace."""
    namespace = _ontology_hub_components_namespace(runtime)
    release_name = _ontology_hub_release_name(runtime)
    namespace_q = shlex.quote(namespace)

    deployments = [
        ("mongodb", f"{release_name}-mongodb", 300),
        ("elasticsearch", f"{release_name}-elasticsearch", 300),
        ("application", release_name, 1800),
    ]

    print("\nResetting Ontology Hub runtime before Ontology Hub Functional...\n")
    for label, deployment_name, timeout_seconds in deployments:
        deployment_q = shlex.quote(deployment_name)
        if _run(
            f"kubectl rollout restart deployment/{deployment_q} -n {namespace_q}",
            check=False,
        ) is None:
            print(f"Could not restart Ontology Hub {label} deployment: {deployment_name}")
            return False

        if _run(
            f"kubectl rollout status deployment/{deployment_q} -n {namespace_q} --timeout={timeout_seconds}s",
            check=False,
        ) is None:
            print(f"Ontology Hub {label} did not become ready in time: {deployment_name}")
            return False

    return True


def _extract_csrf_token(html):
    patterns = [
        r'name=["\']_csrf["\'][^>]*value=["\']([^"\']+)["\']',
        r'value=["\']([^"\']+)["\'][^>]*name=["\']_csrf["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html or "", flags=re.IGNORECASE)
        if match:
            return unescape(match.group(1)).strip()
    return ""


def _strip_html(value):
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(text).split())


def _extract_list_items_by_class(html, class_name):
    pattern = rf'<li[^>]*class=["\'][^"\']*\b{re.escape(class_name)}\b[^"\']*["\'][^>]*>(.*?)</li>'
    return re.findall(pattern, html or "", flags=re.IGNORECASE | re.DOTALL)


def _extract_delete_targets_from_search(html, query_patterns):
    prefixes = set()
    for raw_prefix in re.findall(
        r'href=["\']/dataset/vocabs/([^"\'/?#]+)["\']',
        html or "",
        flags=re.IGNORECASE,
    ):
        prefix = unquote(raw_prefix).strip()
        if not prefix:
            continue
        if any(pattern.search(prefix) for pattern in query_patterns):
            prefixes.add(prefix)
    return prefixes


def ontology_hub_response_looks_broken(response):
    if response is None:
        return True

    if getattr(response, "status_code", 0) >= 500:
        return True

    body = (getattr(response, "text", "") or "").lower()
    markers = (
        "500 - oops! something went wrong - 500",
        "cannot read properties of null",
        "typeerror:",
        "edition.jade:",
        "/app/app/views/edition.jade",
    )
    return any(marker in body for marker in markers)


def _ontology_hub_session_login(runtime, timeout=20, quiet=False):
    base_url = (runtime.get("baseUrl") or "").rstrip("/")
    if not base_url:
        if not quiet:
            print("Ontology Hub cleanup failed: base URL is empty.")
        return None

    session = requests.Session()
    try:
        login_response = session.get(f"{base_url}/edition/login", timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        if not quiet:
            print(f"Ontology Hub cleanup failed while loading login page: {exc}")
        return None

    if login_response.status_code >= 400:
        if not quiet:
            print(f"Ontology Hub cleanup failed: login page returned {login_response.status_code}")
        return None

    csrf_token = _extract_csrf_token(login_response.text)
    if not csrf_token:
        if not quiet:
            print("Ontology Hub cleanup failed: could not extract CSRF token from login page.")
        return None

    payload = {
        "_csrf": csrf_token,
        "email": runtime.get("adminEmail", ""),
        "password": runtime.get("adminPassword", ""),
    }
    try:
        session.post(
            f"{base_url}/edition/session",
            data=payload,
            timeout=timeout,
            allow_redirects=True,
        )
        edition_response = session.get(f"{base_url}/edition", timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        if not quiet:
            print(f"Ontology Hub cleanup failed during login: {exc}")
        return None

    if edition_response.status_code >= 400 or "/edition/login" in edition_response.url:
        if not quiet:
            print("Ontology Hub cleanup failed: admin login was not accepted.")
        return None
    if ontology_hub_response_looks_broken(edition_response):
        if not quiet:
            print("Ontology Hub cleanup failed: authenticated /edition page is broken.")
        return None

    return session


def _ontology_hub_soft_cleanup_users(session, runtime, timeout=20):
    base_url = (runtime.get("baseUrl") or "").rstrip("/")
    target_emails = {"testing@myemail.com"}
    try:
        response = session.get(f"{base_url}/edition/users", timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        print(f"Ontology Hub soft cleanup failed while listing users: {exc}")
        return None

    if response.status_code >= 400:
        print(f"Ontology Hub soft cleanup failed: /edition/users returned {response.status_code}")
        return None
    if ontology_hub_response_looks_broken(response):
        print("Ontology Hub soft cleanup failed: /edition/users rendered a broken server page.")
        return None

    csrf_token = _extract_csrf_token(response.text)
    rows = _extract_list_items_by_class(response.text, "SearchBoxperson")
    deleted = []
    for row in rows:
        email_match = re.search(r'href=["\']mailto:([^"\']+)["\']', row, flags=re.IGNORECASE)
        action_match = re.search(r'action=["\'](/edition/users/[^"\']+)["\']', row, flags=re.IGNORECASE)
        email = unescape(email_match.group(1)).strip() if email_match else ""
        if email not in target_emails or not action_match or not csrf_token:
            continue
        try:
            session.post(
                f"{base_url}{action_match.group(1)}",
                data={"_csrf": csrf_token, "_method": "DELETE"},
                timeout=timeout,
                allow_redirects=True,
            )
            deleted.append(email)
        except requests.RequestException as exc:
            print(f"Ontology Hub soft cleanup warning: could not delete user {email}: {exc}")
    return deleted


def _ontology_hub_mongo_cleanup_test_identities(runtime):
    """Remove only the deterministic functional-suite test identities from MongoDB."""
    namespace = _ontology_hub_components_namespace(runtime)
    release_name = _ontology_hub_release_name(runtime)
    deployment_ref = f"deployment/{release_name}-mongodb"
    script = r'''
db = db.getSiblingDB("lov");
const emailRegex = /^testing(?:[-+][^@]+)?@myemail\.com$/i;
const userDocs = db.users.find({ email: emailRegex }).toArray();
const agentIds = userDocs.map((user) => user.agent).filter(Boolean);
db.agents.find({
  $or: [
    { name: /^Testing User/i },
    { prefUri: /testingUser/i }
  ]
}).toArray().forEach((agent) => agentIds.push(agent._id));
const userDelete = db.users.deleteMany({
  $or: [
    { email: emailRegex },
    { agent: { $in: agentIds } }
  ]
});
const agentDelete = db.agents.deleteMany({
  $or: [
    { _id: { $in: agentIds } },
    { name: /^Testing User/i },
    { prefUri: /testingUser/i }
  ]
});
print(JSON.stringify({ users: userDelete.deletedCount, agents: agentDelete.deletedCount }));
'''
    output = _run_capture(
        "kubectl exec "
        f"-n {shlex.quote(namespace)} "
        f"{shlex.quote(deployment_ref)} "
        f"-- mongosh --quiet --eval {shlex.quote(script)}"
    )
    if output is None:
        return None

    match = re.search(r"\{[^{}]*\"users\"[^{}]*\"agents\"[^{}]*\}", output)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _ontology_hub_soft_cleanup_tags(session, runtime, timeout=20):
    base_url = (runtime.get("baseUrl") or "").rstrip("/")
    tag_patterns = [
        re.compile(r"^MiTag-[A-Za-z0-9_-]+$"),
        re.compile(r"^MiTagPrueba-[A-Za-z0-9_-]+$"),
    ]
    try:
        response = session.get(f"{base_url}/edition/tags", timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        print(f"Ontology Hub soft cleanup failed while listing tags: {exc}")
        return None

    if response.status_code >= 400:
        print(f"Ontology Hub soft cleanup failed: /edition/tags returned {response.status_code}")
        return None
    if ontology_hub_response_looks_broken(response):
        print("Ontology Hub soft cleanup failed: /edition/tags rendered a broken server page.")
        return None

    csrf_token = _extract_csrf_token(response.text)
    rows = _extract_list_items_by_class(response.text, "SearchBoxtag")
    deleted = []
    for row in rows:
        label_match = re.search(
            r'<div[^>]*class=["\']label["\'][^>]*>(.*?)</div>',
            row,
            flags=re.IGNORECASE | re.DOTALL,
        )
        action_match = re.search(r'action=["\'](/edition/tags/[^"\']+)["\']', row, flags=re.IGNORECASE)
        label = _strip_html(label_match.group(1)) if label_match else ""
        if not label or not any(pattern.match(label) for pattern in tag_patterns) or not action_match or not csrf_token:
            continue
        try:
            session.post(
                f"{base_url}{action_match.group(1)}",
                data={"_csrf": csrf_token, "_method": "DELETE"},
                timeout=timeout,
                allow_redirects=True,
            )
            deleted.append(label)
        except requests.RequestException as exc:
            print(f"Ontology Hub soft cleanup warning: could not delete tag {label}: {exc}")
    return deleted


def _ontology_hub_soft_cleanup_agents(session, runtime, timeout=20):
    base_url = (runtime.get("baseUrl") or "").rstrip("/")
    target_names = ["Testing User Admin", "Testing User"]
    deleted = []
    for agent_name in target_names:
        try:
            response = session.get(
                f"{base_url}/dataset/agents/{quote(agent_name, safe='')}",
                timeout=timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            print(f"Ontology Hub soft cleanup warning: could not open agent {agent_name}: {exc}")
            continue

        if response.status_code >= 400:
            continue

        action_match = re.search(
            r'<form[^>]*action=["\'](/edition/agents/[^"\']+)["\'][^>]*id=["\']formDelete["\']',
            response.text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not action_match:
            action_match = re.search(
                r'<form[^>]*id=["\']formDelete["\'][^>]*action=["\'](/edition/agents/[^"\']+)["\']',
                response.text,
                flags=re.IGNORECASE | re.DOTALL,
            )
        csrf_token = _extract_csrf_token(response.text)
        if not action_match or not csrf_token:
            continue
        try:
            session.post(
                f"{base_url}{action_match.group(1)}",
                data={"_csrf": csrf_token, "_method": "DELETE"},
                timeout=timeout,
                allow_redirects=True,
            )
            deleted.append(agent_name)
        except requests.RequestException as exc:
            print(f"Ontology Hub soft cleanup warning: could not delete agent {agent_name}: {exc}")
    return deleted


def _ontology_hub_soft_cleanup_vocabularies(session, runtime, timeout=20):
    base_url = (runtime.get("baseUrl") or "").rstrip("/")
    query_patterns = [
        re.compile(r"^saref4grid$", re.IGNORECASE),
        re.compile(r"^ontology-development-repository-example$", re.IGNORECASE),
        re.compile(r"^s4grid-fw-[a-z0-9-]+$", re.IGNORECASE),
        re.compile(r"^oh-0[34]-", re.IGNORECASE),
    ]
    queries = [
        "saref4grid",
        "s4grid",
        "Ontology-Development-Repository-Example",
        "ontology-development-repository-example",
    ]
    prefixes = {"saref4grid", "ontology-development-repository-example"}
    for query in queries:
        try:
            response = session.get(
                f"{base_url}/dataset/vocabs",
                params={"q": query},
                timeout=timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            print(f"Ontology Hub soft cleanup warning: could not search vocabularies with query '{query}': {exc}")
            continue
        if response.status_code >= 400:
            continue
        prefixes.update(_extract_delete_targets_from_search(response.text, query_patterns))

    deleted = []
    for prefix in sorted(prefixes):
        try:
            response = session.get(
                f"{base_url}/dataset/vocabs/{quote(prefix, safe='')}",
                timeout=timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            print(f"Ontology Hub soft cleanup warning: could not open vocabulary {prefix}: {exc}")
            continue
        if response.status_code >= 400:
            continue
        action_match = re.search(
            r'<form[^>]*action=["\'](/edition/vocabs/[^"\']+)["\'][^>]*id=["\']formDelete["\']',
            response.text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not action_match:
            action_match = re.search(
                r'<form[^>]*id=["\']formDelete["\'][^>]*action=["\'](/edition/vocabs/[^"\']+)["\']',
                response.text,
                flags=re.IGNORECASE | re.DOTALL,
            )
        csrf_token = _extract_csrf_token(response.text)
        if not action_match or not csrf_token:
            continue
        try:
            session.post(
                f"{base_url}{action_match.group(1)}",
                data={"_csrf": csrf_token, "_method": "DELETE"},
                timeout=timeout,
                allow_redirects=True,
            )
            deleted.append(prefix)
        except requests.RequestException as exc:
            print(f"Ontology Hub soft cleanup warning: could not delete vocabulary {prefix}: {exc}")
    return deleted


def soft_cleanup_ontology_hub_for_functional(runtime):
    """Delete Ontology Hub functional-suite leftovers without restarting pods."""
    session = _ontology_hub_session_login(runtime)
    if session is None:
        return False

    print("\nCleaning Ontology Hub Functional leftovers without restarting pods...\n")
    db_cleanup = _ontology_hub_mongo_cleanup_test_identities(runtime)
    users = _ontology_hub_soft_cleanup_users(session, runtime)
    agents = _ontology_hub_soft_cleanup_agents(session, runtime)
    vocabularies = _ontology_hub_soft_cleanup_vocabularies(session, runtime)
    tags = _ontology_hub_soft_cleanup_tags(session, runtime)

    failed_sections = []
    if users is None:
        failed_sections.append("users")
    if agents is None:
        failed_sections.append("agents")
    if vocabularies is None:
        failed_sections.append("vocabularies")
    if tags is None:
        failed_sections.append("tags")

    if failed_sections:
        print("Ontology Hub soft cleanup failed in: " + ", ".join(failed_sections))
        return False

    print(
        "Ontology Hub soft cleanup summary: "
        f"db_users={(db_cleanup or {}).get('users', 'n/a')}, "
        f"db_agents={(db_cleanup or {}).get('agents', 'n/a')}, "
        f"users={len(users)}, agents={len(agents)}, vocabularies={len(vocabularies)}, tags={len(tags)}"
    )
    return True


def wait_for_ontology_hub_preflight(runtime, timeout_seconds=180, stable_successes_required=2):
    """Wait until public and authenticated areas answer consistently after a runtime reset."""
    normalized_runtime = dict(runtime or {})
    normalized_base_url = str(normalized_runtime.get("baseUrl") or "").strip().rstrip("/")
    if not normalized_base_url:
        print("Ontology Hub preflight skipped: base URL is empty.")
        return False

    targets = [
        ("home", normalized_base_url),
        ("dataset", f"{normalized_base_url}/dataset"),
        ("edition", f"{normalized_base_url}/edition"),
    ]
    deadline = time.time() + timeout_seconds
    last_statuses = {}
    stable_successes = 0

    print("\nWaiting for Ontology Hub HTTP preflight...\n")
    while time.time() < deadline:
        all_ready = True
        for label, url in targets:
            try:
                response = requests.get(url, timeout=10, allow_redirects=True)
                last_statuses[label] = str(response.status_code)
                if ontology_hub_response_looks_broken(response):
                    all_ready = False
            except requests.RequestException as exc:
                last_statuses[label] = str(exc)
                all_ready = False

        session = None
        if all_ready:
            session = _ontology_hub_session_login(
                normalized_runtime,
                timeout=10,
                quiet=True,
            )
            if session is not None:
                last_statuses["edition-auth"] = "ok"
                stable_successes += 1
                if stable_successes >= max(int(stable_successes_required or 0), 1):
                    print(
                        "Ontology Hub preflight ready: "
                        + ", ".join(f"{label}={status}" for label, status in last_statuses.items())
                    )
                    close = getattr(session, "close", None)
                    if callable(close):
                        close()
                    return True
            else:
                last_statuses["edition-auth"] = "login-unavailable"
                all_ready = False
        if session is not None:
            close = getattr(session, "close", None)
            if callable(close):
                close()

        if not all_ready:
            stable_successes = 0

        time.sleep(5)

    print(
        "Ontology Hub preflight failed: "
        + ", ".join(f"{label}={status}" for label, status in last_statuses.items())
    )
    return False


def prepare_ontology_hub_for_functional(runtime):
    mode = ontology_hub_functional_reset_mode()
    preflight_timeout = int(runtime.get("preflightTimeout") or 180)

    if mode == "off":
        print("\nOntology Hub Functional cleanup skipped (ONTOLOGY_HUB_FUNCTIONAL_RESET_MODE=off).\n")
        return wait_for_ontology_hub_preflight(runtime, timeout_seconds=min(preflight_timeout, 60))

    if mode == "hard":
        if not reset_ontology_hub_for_functional(runtime):
            return False
        return wait_for_ontology_hub_preflight(runtime, timeout_seconds=preflight_timeout)

    if not soft_cleanup_ontology_hub_for_functional(runtime):
        print("\nOntology Hub soft cleanup failed. Falling back to hard reset...\n")
        if not reset_ontology_hub_for_functional(runtime):
            return False
        return wait_for_ontology_hub_preflight(runtime, timeout_seconds=preflight_timeout)

    if wait_for_ontology_hub_preflight(runtime, timeout_seconds=min(preflight_timeout, 60)):
        return True

    print("\nOntology Hub soft cleanup left the app unhealthy. Falling back to hard reset...\n")
    if not reset_ontology_hub_for_functional(runtime):
        return False
    return wait_for_ontology_hub_preflight(runtime, timeout_seconds=preflight_timeout)


_prepare_ontology_hub_for_functional = prepare_ontology_hub_for_functional
