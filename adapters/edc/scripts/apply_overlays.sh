#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OVERLAY_DIR="$ADAPTER_DIR/overlays"
CONNECTOR_SRC="$ADAPTER_DIR/sources/connector"
DASHBOARD_SRC="$ADAPTER_DIR/sources/dashboard"
DASHBOARD_APP="$DASHBOARD_SRC/DataDashboard"

APPLY=0
TARGET="all"

OVERLAY_MARKER="validation-environment-edc-rdf-overlay"

usage() {
  cat <<'EOF'
Usage: apply_overlays.sh [--apply] [--target connector|dashboard|all]

Copy versioned overlays from adapters/edc/overlays onto synced upstream sources.

Options:
  --apply              Execute overlay application. Default is dry-run.
  --target <name>      Apply connector, dashboard, or all overlays (default: all).
  -h, --help           Show this help message.
EOF
}

run_cmd() {
  local cmd="$1"
  echo "+ $cmd"
  if [[ "$APPLY" -eq 1 ]]; then
    bash -lc "$cmd"
  fi
}

append_unique_lines() {
  local target_file="$1"
  local snippet_file="$2"
  local marker="$3"
  local comment_prefix="${4:-#}"

  if [[ ! -f "$snippet_file" ]]; then
    echo "Snippet not found: $snippet_file" >&2
    return 1
  fi

  if [[ -f "$target_file" ]] && grep -qF "$marker" "$target_file"; then
    echo "Patch already present in $(basename "$target_file")"
    return 0
  fi

  if [[ "$APPLY" -eq 1 ]]; then
    printf '\n%s %s\n' "$comment_prefix" "$marker" >> "$target_file"
    cat "$snippet_file" >> "$target_file"
  else
    echo "Would append $(basename "$snippet_file") to $(basename "$target_file")"
  fi
}

merge_libs_versions_snippet() {
  local target_file="$1"
  local snippet_file="$2"
  local marker="$3"

  if [[ ! -f "$target_file" || ! -f "$snippet_file" ]]; then
    echo "Missing libs.versions.toml or snippet" >&2
    return 1
  fi

  if grep -qF "$marker" "$target_file"; then
    echo "Patch already present in $(basename "$target_file")"
    return 0
  fi

  if [[ "$APPLY" -eq 1 ]]; then
    python3 - "$target_file" "$snippet_file" "$marker" <<'PY'
import pathlib
import sys

target_path = pathlib.Path(sys.argv[1])
snippet_path = pathlib.Path(sys.argv[2])
marker = sys.argv[3]
content = target_path.read_text(encoding="utf-8")
if marker in content:
    sys.exit(0)
snippet = snippet_path.read_text(encoding="utf-8").strip().splitlines()
version_lines = []
library_lines = []
for line in snippet:
    stripped = line.strip()
    if not stripped:
        continue
    if stripped.startswith("postgres = \""):
        version_lines.append(stripped)
    else:
        library_lines.append(stripped)
lines = content.splitlines()
out = []
inserted_marker = False
for idx, line in enumerate(lines):
    out.append(line)
    if not version_lines:
        continue
    if line.strip() == "[versions]" and idx + 1 < len(lines):
        # insert version keys before next section header
        j = idx + 1
        existing = set()
        while j < len(lines) and not lines[j].strip().startswith("["):
            key = lines[j].split("=", 1)[0].strip()
            if key:
                existing.add(key)
            j += 1
        additions = [entry for entry in version_lines if entry.split("=", 1)[0].strip() not in existing]
        if additions:
            out.extend(additions)
            inserted_marker = True
if library_lines:
    rebuilt = []
    added_libraries = False
    for line in out:
        if line.strip() == "[plugins]" and not added_libraries:
            rebuilt.append(f"# {marker}")
            rebuilt.extend(library_lines)
            added_libraries = True
        rebuilt.append(line)
    out = rebuilt
elif inserted_marker:
    out.append(f"# {marker}")
target_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY
  else
    echo "Would merge $(basename "$snippet_file") into $(basename "$target_file")"
  fi
}

insert_dependencies_snippet() {
  local target_file="$1"
  local snippet_file="$2"
  local marker="$3"

  if [[ ! -f "$target_file" ]]; then
    echo "Target file not found: $target_file" >&2
    return 1
  fi

  if grep -qF "$marker" "$target_file"; then
    echo "Patch already present in $(basename "$target_file")"
    return 0
  fi

  if [[ "$APPLY" -eq 1 ]]; then
    python3 - "$target_file" "$snippet_file" "$marker" <<'PY'
import pathlib
import sys

target_path = pathlib.Path(sys.argv[1])
snippet_path = pathlib.Path(sys.argv[2])
marker = sys.argv[3]
content = target_path.read_text(encoding="utf-8")
if marker in content:
    sys.exit(0)
snippet = snippet_path.read_text(encoding="utf-8")
lines = content.splitlines(keepends=True)
out = []
inserted = False
depth = 0
for line in lines:
    out.append(line)
    if not inserted and line.strip().startswith("dependencies"):
        depth = line.count("{") - line.count("}")
        continue
    if not inserted and depth > 0:
        depth += line.count("{") - line.count("}")
        if depth == 0:
            out.insert(len(out) - 1, f"// {marker}\n")
            out.insert(len(out) - 1, snippet if snippet.endswith("\n") else snippet + "\n")
            inserted = True
if not inserted:
    raise SystemExit(f"Could not locate dependencies block in {target_path}")
target_path.write_text("".join(out), encoding="utf-8")
PY
  else
    echo "Would insert $(basename "$snippet_file") into dependencies block of $(basename "$target_file")"
  fi
}

apply_connector_overlay() {
  local extensions_src="$OVERLAY_DIR/connector/extensions"
  local extensions_dst="$CONNECTOR_SRC/extensions"

  if [[ ! -d "$CONNECTOR_SRC" ]]; then
    echo "Connector source not found: $CONNECTOR_SRC" >&2
    return 1
  fi

  run_cmd "mkdir -p \"$extensions_dst\""
  run_cmd "rsync -a --delete \"$extensions_src/\" \"$extensions_dst/\""

  append_unique_lines \
    "$CONNECTOR_SRC/settings.gradle.kts" \
    "$OVERLAY_DIR/connector/patches/settings.gradle.snippet" \
    "$OVERLAY_MARKER" \
    "//"

  merge_libs_versions_snippet \
    "$CONNECTOR_SRC/gradle/libs.versions.toml" \
    "$OVERLAY_DIR/connector/patches/libs.versions.toml.snippet" \
    "$OVERLAY_MARKER"

  insert_dependencies_snippet \
    "$CONNECTOR_SRC/final-connector/build.gradle.kts" \
    "$OVERLAY_DIR/connector/patches/final-connector-dependencies.snippet" \
    "$OVERLAY_MARKER"
}

apply_dashboard_overlay() {
  local dashboard_overlay="$OVERLAY_DIR/dashboard"

  if [[ ! -d "$dashboard_overlay" ]]; then
    echo "Dashboard overlay directory not found: $dashboard_overlay" >&2
    return 1
  fi

  if [[ ! -d "$DASHBOARD_APP" ]]; then
    echo "Dashboard app not found: $DASHBOARD_APP" >&2
    return 1
  fi

  run_cmd "rsync -a \"$dashboard_overlay/\" \"$DASHBOARD_APP/\""
  patch_dashboard_app_config_menu "$DASHBOARD_APP/public/config/app-config.json"
  patch_dashboard_app_config_runtime "$DASHBOARD_APP/public/config/app-config.json"
  patch_dashboard_app_routes "$DASHBOARD_APP/src/app/app.routes.ts"
}

patch_dashboard_app_routes() {
  local routes_file="$1"
  local ontologies_route_marker="validation-environment-edc-ontologies-route"
  local observer_route_marker="validation-environment-edc-model-observer-route"

  if [[ ! -f "$routes_file" ]]; then
    echo "Dashboard routes file not found: $routes_file" >&2
    return 1
  fi

  if [[ "$APPLY" -eq 1 ]]; then
    python3 - "$routes_file" "$ontologies_route_marker" "$observer_route_marker" <<'PY'
import pathlib
import sys

routes_path = pathlib.Path(sys.argv[1])
ontologies_marker = sys.argv[2]
observer_marker = sys.argv[3]
content = routes_path.read_text(encoding="utf-8")

if observer_marker not in content and "path: 'ai-model-observer'" not in content:
    observer_block = """  {
    path: 'ai-model-observer',
    loadComponent: () => import('./features/model-observer/model-observer.component').then(m => m.ModelObserverComponent),
  },
  // validation-environment-edc-model-observer-route
"""
    observer_anchor = "  {\n    path: 'assets',"
    if observer_anchor not in content:
        print("Could not find assets route anchor in app.routes.ts", file=sys.stderr)
        sys.exit(1)
    content = content.replace(observer_anchor, observer_block + observer_anchor, 1)

if ontologies_marker not in content and "path: 'ontologies'" not in content:
    ontologies_block = """  {
    path: 'ontologies',
    loadComponent: () =>
      import('./features/ontologies/ontology-viewer/ontology-viewer.component').then(m => m.OntologyViewerComponent),
  },
  // validation-environment-edc-ontologies-route
"""

    ontologies_anchor = "  {\n    path: 'transfer-history',"
    if ontologies_anchor not in content:
        print("Could not find transfer-history route anchor in app.routes.ts", file=sys.stderr)
        sys.exit(1)
    content = content.replace(ontologies_anchor, ontologies_block + ontologies_anchor, 1)

routes_path.write_text(content, encoding="utf-8")
PY
  else
    echo "Would insert validation routes into $(basename "$routes_file")"
  fi
}

patch_dashboard_app_config_runtime() {
  local app_config_file="$1"
  local inesdata_ontology_url="http://ontology-hub-demo.dev.ds.dataspaceunit.upm"

  if [[ ! -f "$app_config_file" ]]; then
    return 1
  fi

  if [[ "$APPLY" -eq 1 ]]; then
    python3 - "$app_config_file" "$inesdata_ontology_url" <<'PY'
import json
import pathlib
import sys

app_config_path = pathlib.Path(sys.argv[1])
default_ontology_url = sys.argv[2]
config = json.loads(app_config_path.read_text(encoding="utf-8"))
runtime = config.setdefault("runtime", {})
runtime.setdefault("ontologyUrl", "/edc-dashboard-api/components/ontology-hub")
runtime.setdefault("ontologyPublicUrl", default_ontology_url)
runtime.setdefault("ontologyAdminUser", "")
runtime.setdefault("ontologyAdminPassword", "")
runtime.setdefault("modelObserverUrl", "")
runtime.setdefault("transferProcessBasePath", "transferprocesses")
app_config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY
  else
    echo "Would set runtime.ontology* defaults in $(basename "$app_config_file")"
  fi
}

patch_dashboard_app_config_menu() {
  local app_config_file="$1"
  local ontologies_menu_item_file="$OVERLAY_DIR/dashboard/patches/ontologies-menu-item.json"
  local observer_menu_item_file="$OVERLAY_DIR/dashboard/patches/model-observer-menu-item.json"

  if [[ ! -f "$app_config_file" || ! -f "$ontologies_menu_item_file" || ! -f "$observer_menu_item_file" ]]; then
    echo "Dashboard app-config or validation menu patch not found" >&2
    return 1
  fi

  if [[ "$APPLY" -eq 1 ]]; then
    python3 - "$app_config_file" "$ontologies_menu_item_file" "$observer_menu_item_file" <<'PY'
import json
import pathlib
import sys

app_config_path = pathlib.Path(sys.argv[1])
ontologies_menu_item_path = pathlib.Path(sys.argv[2])
observer_menu_item_path = pathlib.Path(sys.argv[3])
config = json.loads(app_config_path.read_text(encoding="utf-8"))
menu_items = config.setdefault("menuItems", [])

def insert_if_missing(router_path, item_path, anchor_router_path):
    if any(item.get("routerPath") == router_path for item in menu_items):
        return
    new_item = json.loads(item_path.read_text(encoding="utf-8"))
    insert_at = len(menu_items)
    for idx, item in enumerate(menu_items):
        if item.get("routerPath") == anchor_router_path:
            insert_at = idx + 1
            break
    menu_items.insert(insert_at, new_item)

insert_if_missing("ai-model-observer", observer_menu_item_path, "model-benchmarking")
insert_if_missing("ontologies", ontologies_menu_item_path, "contract-definitions")
app_config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY
  else
    echo "Would insert validation menu items into $(basename "$app_config_file")"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --target)
      TARGET="${2:-all}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$TARGET" in
  connector)
    apply_connector_overlay
    ;;
  dashboard)
    apply_dashboard_overlay
    ;;
  all)
    apply_connector_overlay
    apply_dashboard_overlay
    ;;
  *)
    echo "Unsupported target: $TARGET" >&2
    exit 1
    ;;
esac

echo "Overlay application complete (target=$TARGET, apply=$APPLY)"
