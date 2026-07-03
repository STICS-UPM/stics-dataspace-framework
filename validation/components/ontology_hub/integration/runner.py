import json
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from urllib import error, parse, request

from validation.components.ontology_hub.runtime_config import resolve_ontology_hub_runtime

COMPONENT_KEY = "ontology-hub"
API_SEARCH_PATH = "/dataset/api/v2/term/search"
SPARQL_PATH = "/dataset/sparql"
PATTERNS_PATH = "/dataset/patterns"
HOME_PATH = "/dataset"
API_DOCS_PATH = "/dataset/api"

API_CASE_METADATA: Dict[str, Dict[str, str]] = {
    "PT5-OH-08": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "mapped",
        "automation_mode": "api",
        "execution_mode": "api",
        "coverage_status": "automated",
    },
    "PT5-OH-09": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "mapped",
        "automation_mode": "composite_ui_api",
        "execution_mode": "composite_ui_api",
        "coverage_status": "automated",
    },
    "PT5-OH-13": {
        "case_group": "pt5",
        "validation_type": "interoperability",
        "dataspace_dimension": "interoperability",
        "mapping_status": "mapped",
        "automation_mode": "api",
        "execution_mode": "api",
        "coverage_status": "automated",
    },
    "PT5-OH-14": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "services",
        "mapping_status": "mapped",
        "automation_mode": "composite_ui_api",
        "execution_mode": "composite_ui_api",
        "coverage_status": "automated",
    },
    "PT5-OH-15": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "integration",
        "mapping_status": "mapped",
        "automation_mode": "composite_ui_api",
        "execution_mode": "composite_ui_api",
        "coverage_status": "automated",
    },
}


def _component_dir(experiment_dir: str | None) -> str | None:
    if not experiment_dir:
        return None
    path = os.path.join(experiment_dir, "components", COMPONENT_KEY)
    os.makedirs(path, exist_ok=True)
    return path


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _http_get(url: str, timeout: int = 20) -> Tuple[int, str, str]:
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.getcode(), response.headers.get("Content-Type", ""), body
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, exc.headers.get("Content-Type", ""), body


def _http_get_until_stable(
    url: str,
    *,
    attempts: int = 8,
    delay_seconds: float = 5.0,
    transient_statuses: Sequence[int] = (502, 503, 504),
) -> Tuple[int, str, str, List[Dict[str, Any]]]:
    history: List[Dict[str, Any]] = []
    last_status = 0
    last_content_type = ""
    last_body = ""

    for attempt in range(1, max(1, attempts) + 1):
        try:
            last_status, last_content_type, last_body = _http_get(url)
            history.append(
                {
                    "attempt": attempt,
                    "http_status": last_status,
                    "content_type": last_content_type,
                }
            )
        except error.URLError as exc:
            last_status = 0
            last_content_type = ""
            last_body = str(exc)
            history.append(
                {
                    "attempt": attempt,
                    "http_status": 0,
                    "error": str(exc),
                }
            )

        if last_status not in transient_statuses:
            break
        if attempt < attempts:
            time.sleep(delay_seconds)

    return last_status, last_content_type, last_body, history


def _parse_curl_with_markers(stdout: str) -> Tuple[int, str, str]:
    status_match = re.search(r"\n__PIONERA_HTTP_STATUS__:(\d{3})\s*", stdout)
    content_type_match = re.search(r"\n__PIONERA_CONTENT_TYPE__:(.*?)\s*$", stdout, flags=re.DOTALL)
    body_end = status_match.start() if status_match else len(stdout)
    body = stdout[:body_end]
    status = int(status_match.group(1)) if status_match else 0
    content_type = content_type_match.group(1).strip() if content_type_match else ""
    return status, content_type, body


def _kubectl_exec_http_get(
    *,
    namespace: str,
    deployment_name: str,
    url: str,
    timeout: int = 20,
) -> Tuple[int, str, str, Dict[str, Any]]:
    target = f"deployment/{deployment_name}"
    command = [
        "kubectl",
        "exec",
        "-n",
        namespace,
        target,
        "--",
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--max-time",
        str(timeout),
        "--write-out",
        "\n__PIONERA_HTTP_STATUS__:%{http_code}\n__PIONERA_CONTENT_TYPE__:%{content_type}\n",
        url,
    ]
    diagnostic: Dict[str, Any] = {
        "executed": False,
        "namespace": namespace,
        "target": target,
        "url": url,
    }
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
    except FileNotFoundError as exc:
        diagnostic["error"] = f"kubectl not found: {exc}"
        return 0, "", diagnostic["error"], diagnostic
    except subprocess.TimeoutExpired as exc:
        diagnostic["error"] = f"kubectl exec timed out after {exc.timeout}s"
        return 0, "", diagnostic["error"], diagnostic

    diagnostic["executed"] = True
    diagnostic["returncode"] = completed.returncode
    if completed.stderr:
        diagnostic["stderr"] = completed.stderr.strip()

    http_status, content_type, body = _parse_curl_with_markers(completed.stdout or "")
    if completed.returncode != 0 and not body:
        body = (completed.stderr or "").strip()
    if completed.returncode != 0:
        diagnostic["error"] = (completed.stderr or completed.stdout or "").strip()
    return http_status, content_type, body, diagnostic


def _kubectl_exec_shell(
    *,
    namespace: str,
    deployment_name: str,
    script: str,
    timeout: int = 180,
) -> Dict[str, Any]:
    target = f"deployment/{deployment_name}"
    command = [
        "kubectl",
        "exec",
        "-n",
        namespace,
        target,
        "--",
        "sh",
        "-lc",
        script,
    ]
    diagnostic: Dict[str, Any] = {
        "executed": False,
        "namespace": namespace,
        "target": target,
    }
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        diagnostic["error"] = f"kubectl not found: {exc}"
        return diagnostic
    except subprocess.TimeoutExpired as exc:
        diagnostic["error"] = f"kubectl exec timed out after {exc.timeout}s"
        return diagnostic

    diagnostic.update(
        {
            "executed": True,
            "returncode": completed.returncode,
            "stdout_excerpt": (completed.stdout or "")[-3000:],
            "stderr_excerpt": (completed.stderr or "")[-3000:],
        }
    )
    if completed.returncode != 0:
        diagnostic["error"] = (completed.stderr or completed.stdout or "").strip()
    return diagnostic


def _kubectl_http_get_until_stable(
    *,
    namespace: str,
    deployment_name: str,
    url: str,
    attempts: int = 8,
    delay_seconds: float = 5.0,
    transient_statuses: Sequence[int] = (0, 502, 503, 504),
) -> Tuple[int, str, str, List[Dict[str, Any]], bool]:
    history: List[Dict[str, Any]] = []
    last_status = 0
    last_content_type = ""
    last_body = ""
    ever_executed = False

    for attempt in range(1, max(1, attempts) + 1):
        last_status, last_content_type, last_body, diagnostic = _kubectl_exec_http_get(
            namespace=namespace,
            deployment_name=deployment_name,
            url=url,
        )
        ever_executed = ever_executed or bool(diagnostic.get("executed"))
        history.append(
            {
                "attempt": attempt,
                "http_status": last_status,
                "content_type": last_content_type,
                **diagnostic,
            }
        )

        if not diagnostic.get("executed"):
            break
        if last_status not in transient_statuses:
            break
        if attempt < attempts:
            time.sleep(delay_seconds)

    return last_status, last_content_type, last_body, history, ever_executed


def _lov_config_sync_script() -> str:
    return r'''
sync_lov_config() {
  config_file="/app/scripts/lov.config"
  [ -f "${config_file}" ] || return 0
  update_lov_key() {
    key="$1"
    value="$2"
    [ -n "${value}" ] || return 0
    tmp_file="$(mktemp)"
    awk -v key="${key}" -v value="${value}" '
      BEGIN { prefix = key "="; seen = 0 }
      index($0, prefix) == 1 { print prefix value; seen = 1; next }
      { print }
      END { if (!seen) print prefix value }
    ' "${config_file}" > "${tmp_file}" && mv "${tmp_file}" "${config_file}"
  }
  update_lov_key "ELASTICSEARCH_HOST" "${ELASTIC_SEARCH_HOST:-elasticsearch}"
  update_lov_key "ELASTICSEARCH_CLUSTER" "${ELASTIC_SEARCH_HOST:-elasticsearch}"
  update_lov_key "ELASTIC_SEARCH_HOST" "${ELASTIC_SEARCH_HOST:-elasticsearch}"
  update_lov_key "ELASTIC_SEARCH_USER" "${ELASTIC_SEARCH_USER:-elastic}"
  update_lov_key "ELASTIC_SEARCH_PASSWORD" "${ELASTIC_SEARCH_PASSWORD:-}"
  update_lov_key "ES_USERNAME" "${ELASTIC_SEARCH_USER:-elastic}"
  update_lov_key "ES_PASSWORD" "${ELASTIC_SEARCH_PASSWORD:-}"
}
sync_lov_config
'''


def _lov_legacy_mapping_compat_script() -> str:
    return r'''
ensure_legacy_lov_mapping_paths() {
  actual_mappings=""
  for candidate in /app/app/elastic/mappings /app/elastic/mappings; do
    if [ -d "${candidate}" ]; then
      actual_mappings="${candidate}"
      break
    fi
  done
  [ -n "${actual_mappings}" ] || return 0
  legacy_elastic_dir="/Users/alexel200/Downloads/Pionera/Ontology-Hub/app/elastic"
  mkdir -p "${legacy_elastic_dir}"
  ln -sfn "${actual_mappings}" "${legacy_elastic_dir}/mappings"
}
ensure_legacy_lov_mapping_paths
'''


def _lov_vocabulary_mapping_compat_script() -> str:
    return r'''
ensure_lov_vocabulary_mapping_compat() {
  es_host="${ELASTIC_SEARCH_HOST:-elasticsearch}"
  es_url="http://${es_host}:9200/lov_vocabulary/_mapping"
  mapping_file="$(mktemp)"
  response_file="$(mktemp)"

  curl_es() {
    if [ -n "${ELASTIC_SEARCH_PASSWORD:-}" ]; then
      curl --silent --show-error --max-time 20 --user "${ELASTIC_SEARCH_USER:-elastic}:${ELASTIC_SEARCH_PASSWORD}" "$@"
    else
      curl --silent --show-error --max-time 20 "$@"
    fi
  }

  status="$(curl_es --output "${mapping_file}" --write-out "%{http_code}" "${es_url}" || true)"
  case "${status}" in
    200) ;;
    404)
      echo "Ontology Hub Elasticsearch mapping compatibility: lov_vocabulary is absent; the app will create it from official mappings."
      return 0
      ;;
    *)
      echo "Ontology Hub Elasticsearch mapping compatibility failed while reading lov_vocabulary mapping: HTTP ${status}" >&2
      cat "${mapping_file}" >&2
      return 31
      ;;
  esac

  compat_payload="$(node -e 'const fs=require("fs"); const payload=JSON.parse(fs.readFileSync(process.argv[1],"utf8")); const index=payload.lov_vocabulary || Object.values(payload)[0] || {}; const props=((index.mappings||{}).properties)||{}; const update={properties:{}}; for (const name of ["tags","langs"]) { const field=props[name]||{}; if (!field.type) { update.properties[name]={type:"keyword"}; } else if (field.type==="text" && field.fielddata!==true) { update.properties[name]={type:"text",fielddata:true,fields:field.fields||{keyword:{type:"keyword",ignore_above:256}}}; } } const names=Object.keys(update.properties); if (names.length===0) { process.exit(2); } process.stdout.write(JSON.stringify(update));' "${mapping_file}" || true)"
  if [ -z "${compat_payload}" ]; then
    echo "Ontology Hub Elasticsearch mapping compatibility: lov_vocabulary tags/langs are compatible."
    return 0
  fi

  curl_es \
    --fail \
    --request PUT \
    --header "Content-Type: application/json" \
    --data "${compat_payload}" \
    "${es_url}" >"${response_file}"
  cat "${response_file}"
  echo "Ontology Hub Elasticsearch mapping compatibility: enabled fielddata for legacy lov_vocabulary text facets."
}
ensure_lov_vocabulary_mapping_compat
'''


def _validation_fixture_seed_script(runtime: Dict[str, Any]) -> str:
    payload = {
        "prefix": runtime.get("expectedVocabularyPrefix") or "saref4grid",
        "title": runtime.get("expectedVocabularyTitle") or runtime.get("creationTitle") or "SAREF4GRID",
        "description": runtime.get("creationDescription")
        or "Vocabulary created by the PT5 Ontology Hub validation fixture.",
        "tag": runtime.get("expectedPrimaryTag") or runtime.get("creationTag") or "Services",
        "secondaryTag": runtime.get("expectedSecondaryTag") or "Environment",
        "resourceUri": runtime.get("expectedSparqlResourceUri")
        or runtime.get("creationUri")
        or "https://saref.etsi.org/saref4grid/v2.1.1/",
        "namespace": runtime.get("creationNamespace") or "https://saref.etsi.org/saref4grid/",
        "classUri": runtime.get("expectedClassUri") or "",
        "classLabel": runtime.get("expectedLabel") or runtime.get("expectedSearchTerm") or "Person",
        "searchTerm": runtime.get("expectedSearchTerm") or "Person",
        "language": runtime.get("creationPrimaryLanguage") or "en",
    }
    payload_json = json.dumps(payload, indent=2, ensure_ascii=False)
    return (
        "\ncat > /tmp/pionera-ontology-hub-validation-fixture.json <<'PIONERA_OH_FIXTURE_JSON'\n"
        + payload_json
        + "\nPIONERA_OH_FIXTURE_JSON\n"
        + r'''
if ! command -v node >/dev/null 2>&1; then
  echo "Missing node runtime; cannot seed Ontology Hub validation fixture"
  exit 23
fi
seed_output="$(mktemp)"
node <<'PIONERA_OH_FIXTURE_NODE' >"${seed_output}" 2>&1
const fs = require("fs");
const path = require("path");
const mongoose = require("mongoose");

const fixture = JSON.parse(fs.readFileSync("/tmp/pionera-ontology-hub-validation-fixture.json", "utf8"));

function text(value, fallback) {
  const normalized = String(value || "").trim();
  return normalized || fallback;
}

function trailingSlash(value, fallback) {
  const normalized = text(value, fallback);
  return /[/#]$/.test(normalized) ? normalized : `${normalized}/`;
}

function localName(value, fallback) {
  const normalized = text(value, fallback);
  const pieces = normalized.split(/[#/]/).filter(Boolean);
  return pieces.length ? pieces[pieces.length - 1] : fallback;
}

function turtleLiteral(value) {
  return String(value || "")
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\r?\n/g, "\\n");
}

async function main() {
  const prefix = text(fixture.prefix, "saref4grid");
  const resourceUri = text(fixture.resourceUri, "https://saref.etsi.org/saref4grid/v2.1.1/");
  const namespace = trailingSlash(fixture.namespace, "https://saref.etsi.org/saref4grid/");
  const classLabel = text(fixture.classLabel, text(fixture.searchTerm, "Person"));
  const classUri = text(fixture.classUri, `${namespace}${localName(classLabel, "Person")}`);
  const title = text(fixture.title, prefix);
  const description = text(fixture.description, "Vocabulary created by the PT5 Ontology Hub validation fixture.");
  const primaryTag = text(fixture.tag, "Services");
  const secondaryTag = text(fixture.secondaryTag, "");
  const lang = text(fixture.language, "en").toLowerCase();
  const issuedAt = new Date();
  const issuedStr = issuedAt.toISOString().slice(0, 10);
  const versionName = `v${issuedStr}`;

  await mongoose.connect(process.env.MONGO_URL || process.env.MONGODB_URI || "mongodb://mongodb:27017/lov", {
    serverSelectionTimeoutMS: 10000,
  });
  const vocabularySchema = new mongoose.Schema({}, { strict: false, collection: "vocabularies" });
  const Vocabulary = mongoose.models.PioneraValidationFixtureVocabulary
    || mongoose.model("PioneraValidationFixtureVocabulary", vocabularySchema);

  let vocab = await Vocabulary.findOne({ prefix });
  let created = false;
  if (!vocab) {
    vocab = new Vocabulary({
      _id: new mongoose.Types.ObjectId(),
      uri: resourceUri,
      nsp: namespace,
      prefix,
      titles: [{ value: title, lang }],
      descriptions: [{ value: description, lang }],
      tags: [primaryTag].concat(secondaryTag ? [secondaryTag] : []),
      license: ["https://creativecommons.org/licenses/by/4.0/"],
      issuedAt,
      createdInLOVAt: issuedAt,
      lastModifiedInLOVAt: issuedAt,
      lastDeref: issuedAt,
      homepage: resourceUri,
      isDefinedBy: resourceUri,
      creatorIds: [],
      contributorIds: [],
      publisherIds: [],
      repositoryUri: "",
      reviews: [],
      versions: [],
      datasets: [],
      nbIncomingLinks: 0,
      incomRelMetadata: [],
      incomRelSpecializes: [],
      incomRelGeneralizes: [],
      incomRelExtends: [],
      incomRelEquivalent: [],
      incomRelDisjunc: [],
      incomRelImports: [],
      pt5ValidationFixture: true,
    });
    created = true;
  }

  const versionData = {
    name: versionName,
    issued: issuedAt,
    isReviewed: true,
    classNumber: "1",
    propertyNumber: "0",
    instanceNumber: "0",
    datatypeNumber: "0",
    languageIds: [],
    relMetadata: [],
    relDisjunc: [],
    relEquivalent: [],
    relExtends: [],
    relGeneralizes: [],
    relImports: [],
    relSpecializes: [],
  };
  const currentTags = Array.isArray(vocab.tags) ? vocab.tags.map(String) : [];
  if (!currentTags.includes(primaryTag)) {
    vocab.tags = currentTags.concat(primaryTag);
  }
  if (secondaryTag && !vocab.tags.map(String).includes(secondaryTag)) {
    vocab.tags = vocab.tags.concat(secondaryTag);
  }
  if (!Array.isArray(vocab.titles) || vocab.titles.length === 0) {
    vocab.titles = [{ value: title, lang }];
  }
  if (!Array.isArray(vocab.descriptions) || vocab.descriptions.length === 0) {
    vocab.descriptions = [{ value: description, lang }];
  }
  vocab.uri = text(vocab.uri, resourceUri);
  vocab.nsp = text(vocab.nsp, namespace);
  vocab.isDefinedBy = text(vocab.isDefinedBy, resourceUri);
  vocab.homepage = text(vocab.homepage, resourceUri);
  vocab.lastModifiedInLOVAt = issuedAt;
  vocab.pt5ValidationFixture = vocab.pt5ValidationFixture === true || created;
  if (!Array.isArray(vocab.versions)) {
    vocab.versions = [];
  }
  const hasVersion = vocab.versions.some((version) => String(version && version.name) === versionName);
  if (!hasVersion) {
    vocab.versions.push(versionData);
  }
  await vocab.save();

  const vocabId = String(vocab._id);
  const versionDir = path.join("/app/versions", vocabId);
  fs.mkdirSync(versionDir, { recursive: true });
  const seedFile = path.join(versionDir, `${vocabId}_${issuedStr}.n3`);
  const ontologyBody = [
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
    "@prefix dcterms: <http://purl.org/dc/terms/> .",
    "",
    `<${resourceUri}> a owl:Ontology ;`,
    `  rdfs:label "${turtleLiteral(title)}"@${lang} ;`,
    `  dcterms:title "${turtleLiteral(title)}"@${lang} ;`,
    `  dcterms:description "${turtleLiteral(description)}"@${lang} .`,
    "",
    `<${classUri}> a owl:Class ;`,
    `  rdfs:label "${turtleLiteral(classLabel)}"@${lang} ;`,
    `  rdfs:comment "Class used by the PT5 Ontology Hub validation fixture."@${lang} ;`,
    `  rdfs:isDefinedBy <${resourceUri}> .`,
    "",
  ].join("\n");
  fs.writeFileSync(seedFile, ontologyBody, "utf8");
  fs.chmodSync(seedFile, 0o644);
  console.log(JSON.stringify({
    fixture: "ontology-hub-pt5-validation",
    prefix,
    resourceUri,
    classUri,
    vocabularyId: vocabId,
    created,
    versionName,
    seedFile,
  }));
  await mongoose.disconnect();
}

main().catch(async (error) => {
  console.error(error && error.stack ? error.stack : error);
  try { await mongoose.disconnect(); } catch (_) {}
  process.exit(24);
});
PIONERA_OH_FIXTURE_NODE
seed_rc=$?
cat "${seed_output}"
if [ "${seed_rc}" -ne 0 ]; then
  exit "${seed_rc}"
fi
'''
    )


def _validation_fixture_search_index_script() -> str:
    return r'''
if ! command -v node >/dev/null 2>&1; then
  echo "Missing node runtime; cannot build Ontology Hub Elasticsearch validation document"
  exit 23
fi
node <<'PIONERA_OH_ES_FIXTURE_NODE'
const fs = require("fs");
const fixture = JSON.parse(fs.readFileSync("/tmp/pionera-ontology-hub-validation-fixture.json", "utf8"));

function text(value, fallback) {
  const normalized = String(value || "").trim();
  return normalized || fallback;
}

function trailingSlash(value, fallback) {
  const normalized = text(value, fallback);
  return /[/#]$/.test(normalized) ? normalized : `${normalized}/`;
}

function localName(value, fallback) {
  const normalized = text(value, fallback);
  const pieces = normalized.split(/[#/]/).filter(Boolean);
  return pieces.length ? pieces[pieces.length - 1] : fallback;
}

const prefix = text(fixture.prefix, "saref4grid");
const resourceUri = text(fixture.resourceUri, "https://saref.etsi.org/saref4grid/v2.1.1/");
const namespace = trailingSlash(fixture.namespace, "https://saref.etsi.org/saref4grid/");
const label = text(fixture.classLabel, text(fixture.searchTerm, "Person"));
const classUri = text(fixture.classUri, `${namespace}${localName(label, "Person")}`);
const primaryTag = text(fixture.tag, "Services");
const secondaryTag = text(fixture.secondaryTag, "");
const tags = [primaryTag].concat(secondaryTag ? [secondaryTag] : []);
const docId = `${prefix}-${localName(classUri, label)}`.replace(/[^A-Za-z0-9_.-]/g, "_");
const document = {
  uri: classUri,
  type: "class",
  prefixedName: `${prefix}:${localName(classUri, label)}`,
  localName: localName(classUri, label),
  label,
  comment: "Class used by the PT5 Ontology Hub validation fixture.",
  vocabulary: {
    uri: resourceUri,
    prefix,
    titles: [{ value: text(fixture.title, prefix), lang: text(fixture.language, "en") }],
    tags,
  },
  tags,
  metrics: {
    occurrencesInVocabularies: 0,
    occurrencesInDatasets: 0,
    reusedByVocabularies: 0,
    reusedByDatasets: 0,
  },
};
fs.writeFileSync("/tmp/pionera-ontology-hub-es-doc-id", docId, "utf8");
fs.writeFileSync("/tmp/pionera-ontology-hub-es-doc.json", JSON.stringify(document), "utf8");
PIONERA_OH_ES_FIXTURE_NODE
es_seed_rc=$?
if [ "${es_seed_rc}" -ne 0 ]; then
  exit "${es_seed_rc}"
fi

curl_es() {
  if [ -n "${ELASTIC_SEARCH_PASSWORD:-}" ]; then
    curl --silent --show-error --max-time 20 --user "${ELASTIC_SEARCH_USER:-elastic}:${ELASTIC_SEARCH_PASSWORD}" "$@"
  else
    curl --silent --show-error --max-time 20 "$@"
  fi
}

es_host="${ELASTIC_SEARCH_HOST:-elasticsearch}"
es_index_url="http://${es_host}:9200/lov_class"
if ! curl_es --head "${es_index_url}" >/dev/null 2>&1; then
  curl_es \
    --request PUT \
    --header "Content-Type: application/json" \
    --data '{"mappings":{"properties":{"localName":{"type":"text","fields":{"ngram":{"type":"text"}}},"prefixedName":{"type":"text"},"tags":{"type":"keyword"},"uri":{"type":"keyword"},"type":{"type":"keyword"},"label":{"type":"text"},"comment":{"type":"text"},"vocabulary":{"properties":{"prefix":{"type":"text","fields":{"keyword":{"type":"keyword"}}},"uri":{"type":"keyword"},"tags":{"type":"keyword"}}},"metrics":{"properties":{"occurrencesInDatasets":{"type":"double"},"reusedByDatasets":{"type":"double"},"occurrencesInVocabularies":{"type":"double"},"reusedByVocabularies":{"type":"double"}}}}}}' \
    "${es_index_url}" >/tmp/pionera-ontology-hub-es-create-index.json
fi
es_doc_id="$(cat /tmp/pionera-ontology-hub-es-doc-id)"
curl_es \
  --request PUT \
  --header "Content-Type: application/json" \
  --data-binary "@/tmp/pionera-ontology-hub-es-doc.json" \
  "${es_index_url}/_doc/${es_doc_id}?refresh=true" >/tmp/pionera-ontology-hub-es-index.json
cat /tmp/pionera-ontology-hub-es-index.json
'''


def _prepare_sparql_store(runtime: Dict[str, Any]) -> Dict[str, Any]:
    script = (
        r'''
set -u
export PATH="/opt/java/openjdk/bin:/opt/java/openjdk/jre/bin:${PATH}"
'''
        + _lov_config_sync_script()
        + _lov_legacy_mapping_compat_script()
        + _lov_vocabulary_mapping_compat_script()
        + _validation_fixture_seed_script(runtime)
        + r'''
if [ -x /app/setup/lovInitialization.sh ]; then
  init_output="$(mktemp)"
  bash /app/setup/lovInitialization.sh >"${init_output}" 2>&1
  init_rc=$?
  cat "${init_output}"
  if grep -Eiq "status:[[:space:]]*401|security_exception|authentication|unauthorized" "${init_output}"; then
    if [ -s /app/public/lov.nq ]; then
      echo "Ontology Hub legacy LOV Elasticsearch indexer was rejected by authentication; continuing because /app/public/lov.nq is available for SPARQL preparation."
    else
      echo "Ontology Hub SPARQL preparation failed: Elasticsearch rejected the LOV indexer authentication and /app/public/lov.nq was not generated." >&2
      exit 31
    fi
  fi
  if [ "${init_rc}" -ne 0 ]; then
    if grep -Fq "Index 'lov' does not exist" "${init_output}"; then
      echo "Ontology Hub legacy index-lov did not find index 'lov'; continuing with framework-managed ES fixture index."
    elif grep -Eiq "status:[[:space:]]*401|security_exception|authentication|unauthorized" "${init_output}" && [ -s /app/public/lov.nq ]; then
      echo "Ontology Hub legacy index-lov authentication failure is non-blocking for SPARQL because /app/public/lov.nq exists."
    else
      exit "${init_rc}"
    fi
  fi
fi
'''
        + _validation_fixture_search_index_script()
        + r'''
if [ ! -s /app/public/lov.nq ]; then
  echo "Missing /app/public/lov.nq; cannot prepare SPARQL store"
  exit 21
fi
pkill -f "[f]useki-server" || true
sleep 1
rm -f /app/jena/tdb_lov_db/*
FORCE_RELOAD=true bash /app/setup/jena.sh
'''
    )
    return _kubectl_exec_shell(
        namespace=runtime["componentsNamespace"],
        deployment_name=runtime["releaseName"],
        script=script,
        timeout=240,
    )


def _prepare_validation_fixture(runtime: Dict[str, Any]) -> Dict[str, Any]:
    script = (
        r'''
set -u
export PATH="/opt/java/openjdk/bin:/opt/java/openjdk/jre/bin:${PATH}"
'''
        + _lov_config_sync_script()
        + _lov_legacy_mapping_compat_script()
        + _validation_fixture_seed_script(runtime)
        + r'''
if [ ! -x /app/setup/lovInitialization.sh ]; then
  echo "Missing executable /app/setup/lovInitialization.sh; cannot prepare validation fixture"
  exit 22
fi
init_output="$(mktemp)"
bash /app/setup/lovInitialization.sh >"${init_output}" 2>&1
init_rc=$?
cat "${init_output}"
if grep -Eiq "status:[[:space:]]*401|security_exception|authentication|unauthorized" "${init_output}"; then
  if [ -s /app/public/lov.nq ]; then
    echo "Ontology Hub legacy LOV Elasticsearch indexer was rejected by authentication; continuing because /app/public/lov.nq is available for validation."
  else
    echo "Ontology Hub fixture preparation failed: Elasticsearch rejected the LOV indexer authentication and /app/public/lov.nq was not generated." >&2
    exit 31
  fi
fi
if [ "${init_rc}" -ne 0 ]; then
  if grep -Fq "Index 'lov' does not exist" "${init_output}"; then
    echo "Ontology Hub legacy index-lov did not find index 'lov'; continuing with framework-managed ES fixture index."
  elif grep -Eiq "status:[[:space:]]*401|security_exception|authentication|unauthorized" "${init_output}" && [ -s /app/public/lov.nq ]; then
    echo "Ontology Hub legacy index-lov authentication failure is non-blocking for validation because /app/public/lov.nq exists."
  else
    exit "${init_rc}"
  fi
fi
'''
        + _validation_fixture_search_index_script()
        + r'''
if [ ! -s /app/public/lov.nq ]; then
  echo "Missing /app/public/lov.nq after LOV initialization"
  exit 21
fi
pkill -f "[f]useki-server" || true
sleep 1
rm -f /app/jena/tdb_lov_db/*
FORCE_RELOAD=true bash /app/setup/jena.sh
'''
    )
    return _kubectl_exec_shell(
        namespace=runtime["componentsNamespace"],
        deployment_name=runtime["releaseName"],
        script=script,
        timeout=300,
    )


def _collect_strings(value: Any) -> Iterable[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        results: List[str] = []
        for item in value.values():
            results.extend(_collect_strings(item))
        return results
    if isinstance(value, (list, tuple, set)):
        results = []
        for item in value:
            results.extend(_collect_strings(item))
        return results
    return [str(value)]


def _flatten_text(value: Any) -> str:
    return " ".join(_collect_strings(value)).strip()


def _get_result_value(result: Dict[str, Any], key: str) -> Any:
    if key in result:
        return result.get(key)
    current: Any = result
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current.get(part)
    return current


def _find_bucket(aggregations: Dict[str, Any], agg_name: str, bucket_key: str) -> Dict[str, Any] | None:
    buckets = (((aggregations or {}).get(agg_name) or {}).get("buckets")) or []
    for bucket in buckets:
        if str(bucket.get("key")) == str(bucket_key):
            return bucket
    return None


def _result_contains_value(result: Dict[str, Any], key: str, expected_value: str) -> bool:
    flattened = _flatten_text(_get_result_value(result, key)).lower()
    return expected_value.lower() in flattened


def evaluate_term_search_response(
    http_status: int,
    content_type: str,
    body_text: str,
    *,
    expected_query: str,
    expected_vocab: str | None = None,
    expected_tag: str | None = None,
    require_results: bool = True,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "http_status": http_status,
        "content_type": content_type,
        "body_excerpt": body_text[:500],
        "status": "passed",
        "assertions": [],
    }

    if http_status != 200:
        result["status"] = "failed"
        result["assertions"].append(f"Expected HTTP 200, got HTTP {http_status}")
        return result

    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError as exc:
        result["status"] = "failed"
        result["assertions"].append(f"Response is not valid JSON: {exc}")
        return result

    result["json_type"] = type(payload).__name__
    if isinstance(payload, dict):
        embedded_status = payload.get("statusCode")
        if isinstance(embedded_status, int) and embedded_status >= 400:
            result["status"] = "failed"
            result["assertions"].append(
                f"Application payload reports embedded error statusCode={embedded_status}"
            )
        if payload.get("error") or payload.get("msg"):
            result["status"] = "failed"
            result["assertions"].append("Application payload contains error markers")
        result["payload_keys"] = sorted(payload.keys())
        results_payload = payload.get("results")
        total_results = payload.get("total_results")
        filters = payload.get("filters") or {}
        aggregations = payload.get("aggregations") or {}
        result["reported_total_results"] = total_results

        if require_results:
            if not isinstance(results_payload, list) or not results_payload:
                result["status"] = "failed"
                result["assertions"].append("Expected at least one search result, but the payload is empty")
                return result

            if isinstance(total_results, int) and total_results < 1:
                result["status"] = "failed"
                result["assertions"].append("Expected total_results >= 1")

            matched_query = False
            matched_vocab = expected_vocab is None
            matched_tag = expected_tag is None
            for item in results_payload:
                flattened = _flatten_text(item).lower()
                if expected_query.lower() in flattened:
                    matched_query = True
                if expected_vocab and _result_contains_value(item, "vocabulary.prefix", expected_vocab):
                    matched_vocab = True
                if expected_tag and _result_contains_value(item, "tags", expected_tag):
                    matched_tag = True
            if not matched_query:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected at least one result containing the search term '{expected_query}'"
                )
            if not matched_vocab:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected at least one result belonging to vocabulary '{expected_vocab}'"
                )
            if not matched_tag:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected at least one result tagged with '{expected_tag}'"
                )

        if expected_vocab:
            if filters.get("vocab") and filters.get("vocab") != expected_vocab:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected filter vocab='{expected_vocab}', got '{filters.get('vocab')}'"
                )
            if (
                filters.get("vocab") != expected_vocab
                and _find_bucket(aggregations, "vocabs", expected_vocab) is None
            ):
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected the response to expose vocabulary '{expected_vocab}' either in filters or aggregations"
                )

        if expected_tag:
            if filters.get("tag") and filters.get("tag") != expected_tag:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected filter tag='{expected_tag}', got '{filters.get('tag')}'"
                )
            if filters.get("tag") != expected_tag and _find_bucket(aggregations, "tags", expected_tag) is None:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected the response to expose tag '{expected_tag}' either in filters or aggregations"
                )
    else:
        result["payload_size"] = len(payload)

    return result


def evaluate_html_page_response(
    http_status: int,
    content_type: str,
    body_text: str,
    *,
    required_markers: Sequence[str],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "http_status": http_status,
        "content_type": content_type,
        "body_excerpt": body_text[:500],
        "status": "passed",
        "assertions": [],
    }

    if http_status != 200:
        result["status"] = "failed"
        result["assertions"].append(f"Expected HTTP 200, got HTTP {http_status}")
        return result

    normalized_body = body_text.lower()
    normalized_type = (content_type or "").lower()
    if "html" not in normalized_type and "<html" not in normalized_body and "<!doctype html" not in normalized_body:
        result["status"] = "failed"
        result["assertions"].append("Expected an HTML response")

    embedded_error_markers = (
        "500 - oops! something went wrong - 500",
        "cannot read properties of null",
        "typeerror:",
        "edition.jade:",
        "/app/app/views/edition.jade",
    )
    if any(marker in normalized_body for marker in embedded_error_markers):
        result["status"] = "failed"
        result["assertions"].append("HTML response renders an embedded server error page")

    missing_markers = [marker for marker in required_markers if marker.lower() not in normalized_body]
    if missing_markers:
        result["status"] = "failed"
        result["assertions"].append(
            f"Missing expected page markers: {', '.join(missing_markers)}"
        )

    return result


def _build_case_result(
    *,
    test_case_id: str,
    description: str,
    case_type: str,
    metadata: Dict[str, str],
    requests_payload: Dict[str, Any] | List[Dict[str, Any]],
    responses_payload: Dict[str, Any] | List[Dict[str, Any]],
    evaluation: Dict[str, Any],
    expected_result: str,
) -> Dict[str, Any]:
    return {
        "test_case_id": test_case_id,
        "description": description,
        "type": case_type,
        "case_group": metadata["case_group"],
        "validation_type": metadata["validation_type"],
        "dataspace_dimension": metadata["dataspace_dimension"],
        "mapping_status": metadata["mapping_status"],
        "automation_mode": metadata["automation_mode"],
        "execution_mode": metadata["execution_mode"],
        "coverage_status": metadata["coverage_status"],
        "request": requests_payload,
        "response": responses_payload,
        "evaluation": evaluation,
        "expected_result": expected_result,
    }


def _summarize_case_list(executed_cases: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {
        "total": len(executed_cases),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
    }
    for case in executed_cases:
        status = ((case.get("evaluation") or {}).get("status") or "").lower()
        if status in summary:
            summary[status] += 1
    return summary


def _build_api_evidence_index(
    executed_cases: List[Dict[str, Any]],
    report_path: str | None,
    raw_artifact_paths: Dict[str, str],
) -> List[Dict[str, Any]]:
    evidence_index: List[Dict[str, Any]] = []
    if report_path:
        evidence_index.append(
            {
                "scope": "suite",
                "suite": "api",
                "artifact_name": "report_json",
                "path": report_path,
            }
        )

    for case in executed_cases:
        artifact_path = raw_artifact_paths.get(case.get("test_case_id", ""))
        if not artifact_path:
            continue
        evidence_index.append(
            {
                "scope": "case",
                "suite": "api",
                "test_case_id": case.get("test_case_id"),
                "case_group": case.get("case_group"),
                "artifact_name": "raw_response",
                "path": artifact_path,
            }
        )
    return evidence_index


def _run_search_case(
    *,
    base_url: str,
    test_case_id: str,
    description: str,
    query_params: Dict[str, str],
    expected_result: str,
    expected_vocab: str | None = None,
    expected_tag: str | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    request_url = f"{base_url}{API_SEARCH_PATH}?{parse.urlencode(query_params)}"
    http_status, content_type, body_text = _http_get(request_url)
    evaluation = evaluate_term_search_response(
        http_status,
        content_type,
        body_text,
        expected_query=query_params["q"],
        expected_vocab=expected_vocab,
        expected_tag=expected_tag,
    )
    case_result = _build_case_result(
        test_case_id=test_case_id,
        description=description,
        case_type="api",
        metadata=API_CASE_METADATA[test_case_id],
        requests_payload={
            "method": "GET",
            "url": request_url,
            "query": dict(query_params),
        },
        responses_payload={
            "http_status": http_status,
            "content_type": content_type,
        },
        evaluation=evaluation,
        expected_result=expected_result,
    )
    raw_artifact = {
        "url": request_url,
        "http_status": http_status,
        "content_type": content_type,
        "body": body_text,
    }
    return case_result, raw_artifact


def _fixture_recovery_enabled(runtime: Dict[str, Any]) -> bool:
    return bool(runtime.get("prepareValidationFixture", runtime.get("prepareSparqlStore", True)))


def _fixture_retry_attempts(runtime: Dict[str, Any]) -> int:
    try:
        return max(1, int(runtime.get("validationFixtureRetryAttempts", 6)))
    except (TypeError, ValueError):
        return 6


def _fixture_retry_delay_seconds(runtime: Dict[str, Any]) -> float:
    try:
        return max(0.0, float(runtime.get("validationFixtureRetryDelaySeconds", 5)))
    except (TypeError, ValueError):
        return 5.0


def _case_passed(case_result: Dict[str, Any]) -> bool:
    return ((case_result.get("evaluation") or {}).get("status") or "").lower() == "passed"


def _run_search_case_with_fixture_recovery(
    *,
    runtime: Dict[str, Any],
    base_url: str,
    test_case_id: str,
    description: str,
    query_params: Dict[str, str],
    expected_result: str,
    expected_vocab: str | None = None,
    expected_tag: str | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    first_case, first_artifact = _run_search_case(
        base_url=base_url,
        test_case_id=test_case_id,
        description=description,
        query_params=query_params,
        expected_result=expected_result,
        expected_vocab=expected_vocab,
        expected_tag=expected_tag,
    )
    if _case_passed(first_case) or not _fixture_recovery_enabled(runtime):
        return first_case, first_artifact

    preparation = {
        "attempted": True,
        "enabled": True,
        **_prepare_validation_fixture(runtime),
    }
    if preparation.get("error") or preparation.get("returncode") not in (None, 0):
        first_case["fixture_recovery"] = {
            "attempted": True,
            "status": "failed",
        }
        first_artifact["fixture_preparation"] = preparation
        return first_case, first_artifact
    retry_history: List[Dict[str, Any]] = []
    retry_case = first_case
    retry_artifact = first_artifact
    for attempt in range(1, _fixture_retry_attempts(runtime) + 1):
        retry_case, retry_artifact = _run_search_case(
            base_url=base_url,
            test_case_id=test_case_id,
            description=description,
            query_params=query_params,
            expected_result=expected_result,
            expected_vocab=expected_vocab,
            expected_tag=expected_tag,
        )
        retry_history.append(
            {
                "attempt": attempt,
                "http_status": retry_artifact.get("http_status"),
                "content_type": retry_artifact.get("content_type"),
                "status": (retry_case.get("evaluation") or {}).get("status"),
                "assertions": (retry_case.get("evaluation") or {}).get("assertions", []),
            }
        )
        if _case_passed(retry_case):
            break
        if attempt < _fixture_retry_attempts(runtime):
            time.sleep(_fixture_retry_delay_seconds(runtime))
    retry_case["fixture_recovery"] = {
        "attempted": True,
        "status": "passed" if _case_passed(retry_case) else "failed",
    }
    retry_artifact["initial_attempt"] = first_artifact
    retry_artifact["fixture_preparation"] = preparation
    retry_artifact["retry_history"] = retry_history
    return retry_case, retry_artifact


def _run_html_case(
    *,
    base_url: str,
    test_case_id: str,
    description: str,
    path: str,
    required_markers: Sequence[str],
    expected_result: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    request_url = f"{base_url}{path}"
    http_status, content_type, body_text = _http_get(request_url)
    evaluation = evaluate_html_page_response(
        http_status,
        content_type,
        body_text,
        required_markers=required_markers,
    )
    case_result = _build_case_result(
        test_case_id=test_case_id,
        description=description,
        case_type="api",
        metadata=API_CASE_METADATA[test_case_id],
        requests_payload={
            "method": "GET",
            "url": request_url,
        },
        responses_payload={
            "http_status": http_status,
            "content_type": content_type,
        },
        evaluation=evaluation,
        expected_result=expected_result,
    )
    raw_artifact = {
        "url": request_url,
        "http_status": http_status,
        "content_type": content_type,
        "body": body_text,
    }
    return case_result, raw_artifact


def _run_html_case_with_fixture_recovery(
    *,
    runtime: Dict[str, Any],
    base_url: str,
    test_case_id: str,
    description: str,
    path: str,
    required_markers: Sequence[str],
    expected_result: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    first_case, first_artifact = _run_html_case(
        base_url=base_url,
        test_case_id=test_case_id,
        description=description,
        path=path,
        required_markers=required_markers,
        expected_result=expected_result,
    )
    if _case_passed(first_case) or not _fixture_recovery_enabled(runtime):
        return first_case, first_artifact

    preparation = {
        "attempted": True,
        "enabled": True,
        **_prepare_validation_fixture(runtime),
    }
    if preparation.get("error") or preparation.get("returncode") not in (None, 0):
        first_case["fixture_recovery"] = {
            "attempted": True,
            "status": "failed",
        }
        first_artifact["fixture_preparation"] = preparation
        return first_case, first_artifact
    retry_history: List[Dict[str, Any]] = []
    retry_case = first_case
    retry_artifact = first_artifact
    for attempt in range(1, _fixture_retry_attempts(runtime) + 1):
        retry_case, retry_artifact = _run_html_case(
            base_url=base_url,
            test_case_id=test_case_id,
            description=description,
            path=path,
            required_markers=required_markers,
            expected_result=expected_result,
        )
        retry_history.append(
            {
                "attempt": attempt,
                "http_status": retry_artifact.get("http_status"),
                "content_type": retry_artifact.get("content_type"),
                "status": (retry_case.get("evaluation") or {}).get("status"),
                "assertions": (retry_case.get("evaluation") or {}).get("assertions", []),
            }
        )
        if _case_passed(retry_case):
            break
        if attempt < _fixture_retry_attempts(runtime):
            time.sleep(_fixture_retry_delay_seconds(runtime))
    retry_case["fixture_recovery"] = {
        "attempted": True,
        "status": "passed" if _case_passed(retry_case) else "failed",
    }
    retry_artifact["initial_attempt"] = first_artifact
    retry_artifact["fixture_preparation"] = preparation
    retry_artifact["retry_history"] = retry_history
    return retry_case, retry_artifact


def _run_ui_api_access_case(base_url: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ui_url = f"{base_url}{HOME_PATH}"
    api_url = f"{base_url}{API_DOCS_PATH}"
    ui_status, ui_type, ui_body = _http_get(ui_url)
    api_status, api_type, api_body = _http_get(api_url)
    ui_evaluation = evaluate_html_page_response(
        ui_status,
        ui_type,
        ui_body,
        required_markers=["/dataset/api", "/dataset/vocabs"],
    )
    api_evaluation = evaluate_html_page_response(
        api_status,
        api_type,
        api_body,
        required_markers=["/api/v2/term/search", "/dataset/api/v2/agent/list"],
    )
    overall_status = "passed"
    assertions: List[str] = []
    if ui_evaluation["status"] != "passed":
        overall_status = "failed"
        assertions.extend(f"UI: {message}" for message in ui_evaluation["assertions"])
    if api_evaluation["status"] != "passed":
        overall_status = "failed"
        assertions.extend(f"API docs: {message}" for message in api_evaluation["assertions"])

    case_result = _build_case_result(
        test_case_id="PT5-OH-15",
        description="Coordinated access through UI and API",
        case_type="api",
        metadata=API_CASE_METADATA["PT5-OH-15"],
        requests_payload=[
            {"method": "GET", "url": ui_url, "role": "ui"},
            {"method": "GET", "url": api_url, "role": "api_docs"},
        ],
        responses_payload=[
            {"http_status": ui_status, "content_type": ui_type, "role": "ui"},
            {"http_status": api_status, "content_type": api_type, "role": "api_docs"},
        ],
        evaluation={
            "status": overall_status,
            "assertions": assertions,
            "checks": {
                "ui": ui_evaluation,
                "api_docs": api_evaluation,
            },
        },
        expected_result="The main UI and API documentation are published in a coordinated and accessible way.",
    )
    raw_artifact = {
        "ui": {
            "url": ui_url,
            "http_status": ui_status,
            "content_type": ui_type,
            "body": ui_body,
        },
        "api_docs": {
            "url": api_url,
            "http_status": api_status,
            "content_type": api_type,
            "body": api_body,
        },
    }
    return case_result, raw_artifact


def evaluate_sparql_response(
    http_status: int,
    content_type: str,
    body_text: str,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "http_status": http_status,
        "content_type": content_type,
        "body_excerpt": body_text[:500],
        "status": "passed",
        "assertions": [],
    }

    if http_status != 200:
        result["status"] = "failed"
        result["assertions"].append(f"Expected HTTP 200, got HTTP {http_status}")
        return result

    normalized_type = (content_type or "").lower()
    if "xml" in normalized_type or body_text.lstrip().startswith("<?xml"):
        xml_match = re.search(r"<boolean>\s*(true|false)\s*</boolean>", body_text, flags=re.IGNORECASE)
        if not xml_match:
            result["status"] = "failed"
            result["assertions"].append("SPARQL XML response does not contain a <boolean> result")
            return result
        boolean_value = xml_match.group(1).lower() == "true"
        result["boolean"] = boolean_value
        if not boolean_value:
            result["status"] = "failed"
            result["assertions"].append("Expected SPARQL ASK query to return boolean=true")
        return result

    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError as exc:
        result["status"] = "failed"
        result["assertions"].append(f"SPARQL response is not valid JSON: {exc}")
        return result

    result["payload_keys"] = sorted(payload.keys()) if isinstance(payload, dict) else []
    boolean_value = payload.get("boolean") if isinstance(payload, dict) else None
    result["boolean"] = boolean_value
    if boolean_value is not True:
        result["status"] = "failed"
        result["assertions"].append("Expected SPARQL ASK query to return boolean=true")
    return result


def _assertion_summary(evaluation: Dict[str, Any]) -> str:
    assertions = list(evaluation.get("assertions") or [])
    if assertions:
        return "; ".join(str(message) for message in assertions)
    status = evaluation.get("http_status")
    if status:
        return f"HTTP {status}"
    return str(evaluation.get("body_excerpt") or "unknown error")[:240]


def _combine_sparql_evaluations(
    *,
    internal_evaluation: Dict[str, Any],
    public_evaluation: Dict[str, Any],
    internal_executed: bool,
) -> Dict[str, Any]:
    internal_passed = internal_evaluation.get("status") == "passed"
    public_passed = public_evaluation.get("status") == "passed"
    assertions: List[str] = []
    warnings: List[str] = []

    if internal_executed:
        if not internal_passed:
            assertions.append(f"Internal cluster SPARQL check failed: {_assertion_summary(internal_evaluation)}")
    elif not public_passed:
        assertions.append("Internal cluster SPARQL check could not be executed and the public endpoint also failed.")
    else:
        warnings.append("Internal cluster SPARQL check could not be executed; public endpoint evidence was used.")

    if not public_passed:
        message = (
            "Public SPARQL exposure through ingress did not pass. "
            f"Diagnostic: {_assertion_summary(public_evaluation)}"
        )
        if internal_passed:
            warnings.append(message)
        else:
            assertions.append(message)

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "warnings": warnings,
        "internal_cluster_status": internal_evaluation.get("status"),
        "public_ingress_status": public_evaluation.get("status"),
        "checks": {
            "internal_cluster": internal_evaluation,
            "public_ingress": public_evaluation,
        },
    }


def _kubectl_sparql_until_passed(
    *,
    namespace: str,
    deployment_name: str,
    url: str,
    attempts: int,
    delay_seconds: float,
) -> Tuple[int, str, str, List[Dict[str, Any]], bool, Dict[str, Any]]:
    history: List[Dict[str, Any]] = []
    last_status = 0
    last_content_type = ""
    last_body = ""
    last_evaluation: Dict[str, Any] = evaluate_sparql_response(0, "", "")
    ever_executed = False

    for attempt in range(1, max(1, attempts) + 1):
        last_status, last_content_type, last_body, diagnostic = _kubectl_exec_http_get(
            namespace=namespace,
            deployment_name=deployment_name,
            url=url,
        )
        ever_executed = ever_executed or bool(diagnostic.get("executed"))
        last_evaluation = evaluate_sparql_response(last_status, last_content_type, last_body)
        history.append(
            {
                "attempt": attempt,
                "http_status": last_status,
                "content_type": last_content_type,
                "evaluation_status": last_evaluation.get("status"),
                "assertions": last_evaluation.get("assertions", []),
                **diagnostic,
            }
        )
        if last_evaluation.get("status") == "passed":
            break
        if not diagnostic.get("executed"):
            break
        if attempt < attempts:
            time.sleep(delay_seconds)

    last_evaluation["retry_history"] = history
    last_evaluation["executed"] = ever_executed
    return last_status, last_content_type, last_body, history, ever_executed, last_evaluation


def _run_sparql_access_case(base_url: str, runtime: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    expected_resource_uri = runtime["expectedSparqlResourceUri"]
    sparql_query = f"ASK {{ GRAPH ?g {{ <{expected_resource_uri}> ?p ?o }} }}"
    query_string = parse.urlencode({"query": sparql_query})
    public_request_url = f"{base_url}{SPARQL_PATH}?{query_string}"
    internal_request_url = f"{runtime['internalBaseUrl']}{SPARQL_PATH}?{query_string}"
    preparation: Dict[str, Any] = {
        "attempted": False,
        "enabled": bool(runtime.get("prepareSparqlStore", True)),
    }

    internal_status, internal_type, internal_body, internal_retry_history, internal_executed = _kubectl_http_get_until_stable(
        namespace=runtime["componentsNamespace"],
        deployment_name=runtime["releaseName"],
        url=internal_request_url,
    )
    internal_evaluation = evaluate_sparql_response(internal_status, internal_type, internal_body)
    internal_evaluation["retry_history"] = internal_retry_history
    internal_evaluation["executed"] = internal_executed

    if runtime.get("prepareSparqlStore", True) and internal_executed and internal_evaluation.get("status") != "passed":
        preparation = {
            "attempted": True,
            "enabled": True,
            **_prepare_sparql_store(runtime),
        }
        (
            internal_status,
            internal_type,
            internal_body,
            internal_retry_history,
            internal_executed,
            internal_evaluation,
        ) = _kubectl_sparql_until_passed(
            namespace=runtime["componentsNamespace"],
            deployment_name=runtime["releaseName"],
            url=internal_request_url,
            attempts=_fixture_retry_attempts(runtime),
            delay_seconds=_fixture_retry_delay_seconds(runtime),
        )
        internal_evaluation["preparation"] = preparation

    public_status, public_type, public_body, public_retry_history = _http_get_until_stable(public_request_url)
    public_evaluation = evaluate_sparql_response(public_status, public_type, public_body)
    public_evaluation["retry_history"] = public_retry_history

    evaluation = _combine_sparql_evaluations(
        internal_evaluation=internal_evaluation,
        public_evaluation=public_evaluation,
        internal_executed=internal_executed,
    )
    case_result = _build_case_result(
        test_case_id="PT5-OH-13",
        description="Real SPARQL query against the seeded example ontology",
        case_type="api",
        metadata=API_CASE_METADATA["PT5-OH-13"],
        requests_payload=[
            {
                "role": "internal_cluster",
                "method": "GET",
                "url": internal_request_url,
                "query": sparql_query,
                "expected_resource_uri": expected_resource_uri,
                "namespace": runtime["componentsNamespace"],
                "deployment": runtime["releaseName"],
            },
            {
                "role": "public_ingress",
                "method": "GET",
                "url": public_request_url,
                "query": sparql_query,
                "expected_resource_uri": expected_resource_uri,
            },
        ],
        responses_payload=[
            {
                "role": "internal_cluster",
                "http_status": internal_status,
                "content_type": internal_type,
                "executed": internal_executed,
            },
            {
                "role": "public_ingress",
                "http_status": public_status,
                "content_type": public_type,
            },
        ],
        evaluation=evaluation,
        expected_result=(
            "The ASK query against the seeded RDF resource returns true inside the cluster. "
            "Public ingress exposure is recorded as diagnostic evidence."
        ),
    )
    raw_artifact = {
        "query": sparql_query,
        "expected_resource_uri": expected_resource_uri,
        "preparation": preparation,
        "internal_cluster": {
            "url": internal_request_url,
            "namespace": runtime["componentsNamespace"],
            "deployment": runtime["releaseName"],
            "http_status": internal_status,
            "content_type": internal_type,
            "body": internal_body,
            "retry_history": internal_retry_history,
            "executed": internal_executed,
        },
        "public_ingress": {
            "url": public_request_url,
            "http_status": public_status,
            "content_type": public_type,
            "body": public_body,
            "retry_history": public_retry_history,
        },
        "evaluation": evaluation,
    }
    return case_result, raw_artifact


def run_ontology_hub_validation(
    base_url: str,
    experiment_dir: str | None = None,
    case_ids: list[str] | tuple[str, ...] | set[str] | None = None,
) -> Dict[str, Any]:
    runtime = resolve_ontology_hub_runtime(base_url=base_url)
    normalized_base_url = runtime["baseUrl"]
    started_at = datetime.now().isoformat()
    requested_case_ids = {str(case_id or "").strip().upper() for case_id in (case_ids or []) if str(case_id or "").strip()}

    executed_cases: List[Dict[str, Any]] = []
    raw_artifacts: List[Tuple[str, str, Dict[str, Any]]] = []

    def requested(test_case_id: str) -> bool:
        return not requested_case_ids or test_case_id.upper() in requested_case_ids

    if requested("PT5-OH-08"):
        pt5_oh_08, artifact_08 = _run_search_case_with_fixture_recovery(
            runtime=runtime,
            base_url=normalized_base_url,
            test_case_id="PT5-OH-08",
            description="Free-text vocabulary search with indexed real content",
            query_params={
                "q": runtime["expectedSearchTerm"],
                "type": "class",
            },
            expected_result="The search returns at least one indexed example term, with coherent aggregations and content.",
            expected_vocab=runtime["expectedVocabularyPrefix"],
        )
        executed_cases.append(pt5_oh_08)
        raw_artifacts.append(("PT5-OH-08", "pt5-oh-08-response.json", artifact_08))

    if requested("PT5-OH-09"):
        pt5_oh_09, artifact_09 = _run_search_case_with_fixture_recovery(
            runtime=runtime,
            base_url=normalized_base_url,
            test_case_id="PT5-OH-09",
            description="Vocabulary filtering by vocabulary and tag",
            query_params={
                "q": runtime["expectedSearchTerm"],
                "type": "class",
                "vocab": runtime["expectedVocabularyPrefix"],
                "tag": runtime["expectedPrimaryTag"],
            },
            expected_result="The filtered search returns results consistent with the example vocabulary and tag.",
            expected_vocab=runtime["expectedVocabularyPrefix"],
            expected_tag=runtime["expectedPrimaryTag"],
        )
        executed_cases.append(pt5_oh_09)
        raw_artifacts.append(("PT5-OH-09", "pt5-oh-09-response.json", artifact_09))

    if requested("PT5-OH-13"):
        pt5_oh_13, artifact_13 = _run_sparql_access_case(normalized_base_url, runtime)
        executed_cases.append(pt5_oh_13)
        raw_artifacts.append(("PT5-OH-13", "pt5-oh-13-response.json", artifact_13))

    if requested("PT5-OH-14"):
        pt5_oh_14, artifact_14 = _run_html_case_with_fixture_recovery(
            runtime=runtime,
            base_url=normalized_base_url,
            test_case_id="PT5-OH-14",
            description="Pattern service access",
            path=f"{PATTERNS_PATH}?{parse.urlencode({'q': runtime['expectedVocabularyPrefix']})}",
            required_markers=["/dataset/api/v2/patterns", "detectPatterns"],
            expected_result="The pattern service page is published and accessible.",
        )
        executed_cases.append(pt5_oh_14)
        raw_artifacts.append(("PT5-OH-14", "pt5-oh-14-response.json", artifact_14))

    if requested("PT5-OH-15"):
        pt5_oh_15, artifact_15 = _run_ui_api_access_case(normalized_base_url)
        executed_cases.append(pt5_oh_15)
        raw_artifacts.append(("PT5-OH-15", "pt5-oh-15-response.json", artifact_15))

    summary = {
        "total": len(executed_cases),
        "passed": sum(1 for case in executed_cases if case["evaluation"]["status"] == "passed"),
        "failed": sum(1 for case in executed_cases if case["evaluation"]["status"] == "failed"),
        "skipped": 0,
    }
    overall_status = "failed" if summary["failed"] else "passed" if summary["total"] else "skipped"
    pt5_summary = _summarize_case_list(executed_cases)

    component_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "base_url": normalized_base_url,
        "status": overall_status,
        "timestamp": started_at,
        "seed_expectations": {
            "search_term": runtime["expectedSearchTerm"],
            "expected_label": runtime["expectedLabel"],
            "expected_vocabulary": runtime["expectedVocabularyPrefix"],
            "expected_tag": runtime["expectedPrimaryTag"],
        },
        "runtime": runtime,
        "executed_cases": executed_cases,
        "summary": summary,
        "pt5_cases": executed_cases,
        "support_checks": [],
        "pt5_summary": pt5_summary,
        "support_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "evidence_index": [],
    }

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        artifact_paths: Dict[str, str] = {}
        case_artifact_paths: Dict[str, str] = {}
        for test_case_id, file_name, payload in raw_artifacts:
            artifact_path = os.path.join(component_dir, file_name)
            _write_json(artifact_path, payload)
            artifact_paths[file_name] = artifact_path
            case_artifact_paths[test_case_id] = artifact_path
        report_path = os.path.join(component_dir, "ontology_hub_validation.json")
        component_result["evidence_index"] = _build_api_evidence_index(
            executed_cases,
            report_path,
            case_artifact_paths,
        )
        _write_json(report_path, component_result)
        component_result["artifacts"] = {
            "report_json": report_path,
            **artifact_paths,
        }

    return component_result
