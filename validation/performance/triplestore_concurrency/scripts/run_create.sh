#!/usr/bin/env bash
# S1/S2 runner: executes jmeter/S1_S2_create_assets.jmx for every thread count x repetition
# and stores raw JTL + metadata under experiments/perf_store_concurrency_<timestamp>/.
#
#   BENCH_PASSWORD=... scripts/run_create.sh -e env/stics.properties [-t "1 5 10 25 50"] [-r 5]
#
# threads=1 is S1 (sequential); threads>1 is S2 (parallel). Each run pre-cleans and tears
# down the dataset assets so every repetition starts from the same store state.
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(git -C "${BENCH_DIR}" rev-parse --show-toplevel)"

ENV_FILE=""
THREADS="1 5 10 25 50"
REPS=5
WARMUP=1
SOURCE=sk-catalog
COUNT=100
SEED=20261014
PAUSE=5

usage() {
  sed -n '2,8p' "$0"
  echo "Options: -e env file (required)  -t thread counts  -r repetitions  -w warm-up runs (default 1)"
  echo "         -S dataset source: sk-catalog (default, committed snapshot) | synthetic"
  echo "         -n asset count (default 100)  -s seed, synthetic only (default 20261014)  -p pause between runs in s (default 5)"
  exit 1
}
while getopts "e:t:r:w:S:n:s:p:h" opt; do
  case "${opt}" in
    e) ENV_FILE="${OPTARG}" ;;
    t) THREADS="${OPTARG}" ;;
    r) REPS="${OPTARG}" ;;
    w) WARMUP="${OPTARG}" ;;
    S) SOURCE="${OPTARG}" ;;
    n) COUNT="${OPTARG}" ;;
    s) SEED="${OPTARG}" ;;
    p) PAUSE="${OPTARG}" ;;
    *) usage ;;
  esac
done
[[ -n "${ENV_FILE}" && -f "${ENV_FILE}" ]] || usage
: "${BENCH_PASSWORD:?export BENCH_PASSWORD with the connector user password}"

JMETER="$("${BENCH_DIR}/scripts/install_jmeter.sh")"
DATASET_DIR="$(python3 -I "${BENCH_DIR}/dataset/generate_assets.py" --source "${SOURCE}" --count "${COUNT}" --seed "${SEED}" | head -1)"

OUT_DIR="${REPO_ROOT}/experiments/perf_store_concurrency_$(date +%Y-%m-%d_%H-%M-%S)"
mkdir -p "${OUT_DIR}/jtl" "${OUT_DIR}/logs"
cp "${DATASET_DIR}/manifest.json" "${OUT_DIR}/dataset_manifest.json"

# Translate env file URLs into the host/port/path properties the .jmx expects; the password
# goes into a private properties file instead of the command line.
PROPS="$(mktemp)"
chmod 600 "${PROPS}"
trap 'rm -f "${PROPS}"' EXIT
python3 -I - "${ENV_FILE}" "${DATASET_DIR}" "${COUNT}" > "${PROPS}" <<'PY'
import sys, os
from urllib.parse import urlsplit
env = {}
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
def split(prefix, url):
    u = urlsplit(url)
    port = u.port or (443 if u.scheme == "https" else 80)
    return {f"{prefix}_protocol": u.scheme, f"{prefix}_host": u.hostname, f"{prefix}_port": port}, u.path.rstrip("/")
mgmt, mgmt_path = split("mgmt", env["mgmt_url"])
kc, _ = split("kc", env["kc_url"])
props = {**mgmt, "mgmt_base_path": mgmt_path, **kc,
         "kc_realm": env["kc_realm"], "kc_client_id": env.get("kc_client_id", "dataspace-users"),
         "user": env["user"], "password": os.environ["BENCH_PASSWORD"],
         "dataset_dir": sys.argv[2], "asset_count": sys.argv[3]}
for key, value in props.items():
    print(f"{key}={str(value).replace(chr(92), chr(92) * 2)}")
PY

TARGET_LABEL="$(sed -n 's/^target_label=//p' "${ENV_FILE}")"
python3 -I - "${OUT_DIR}/metadata.json" <<PY
import json, platform, os, subprocess, sys, datetime
def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout.strip() or None
    except OSError:
        return None
manifest = json.load(open("${OUT_DIR}/dataset_manifest.json"))
meta = {
    "experiment_id": os.path.basename("${OUT_DIR}"),
    "timestamp": datetime.datetime.now().isoformat(),
    "measurement_type": "store_concurrency",
    "scenario": "S1_S2_create_assets",
    "target_label": "${TARGET_LABEL:-unknown}",
    "mgmt_url": "$(sed -n 's/^mgmt_url=//p' "${ENV_FILE}")",
    "thread_counts": [int(t) for t in "${THREADS}".split()],
    "repetitions": ${REPS},
    "warmup_runs": ${WARMUP},
    "dataset": {k: manifest[k] for k in ("source", "count", "seed", "snapshot", "id_prefix",
                                         "generator_version", "dataset_sha256") if k in manifest},
    "git_commit": sh("git", "-C", "${REPO_ROOT}", "rev-parse", "HEAD"),
    "git_dirty": bool(sh("git", "-C", "${REPO_ROOT}", "status", "--porcelain", "--", "${BENCH_DIR}")),
    "jmeter": "${JMETER}".split("apache-jmeter-")[-1].split("/")[0],
    "java": (subprocess.run(["java", "-version"], capture_output=True, text=True).stderr.splitlines() or [None])[0],
    "client_host": {"hostname": platform.node(), "os": platform.platform(), "cpus": os.cpu_count(),
                    "mem_total_kb": next((int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith("MemTotal")), None)},
}
json.dump(meta, open(sys.argv[1], "w"), indent=2)
PY

run_jmeter() {  # $1 = run name, $2 = threads
  "${JMETER}" -n -t "${BENCH_DIR}/jmeter/S1_S2_create_assets.jmx" \
    -q "${PROPS}" -Jthreads="$2" -Jrampup=0 \
    -Jjmeter.save.saveservice.output_format=csv \
    -l "${OUT_DIR}/jtl/$1.jtl" -j "${OUT_DIR}/logs/$1.log" > "${OUT_DIR}/logs/$1.console.log"
}

for t in ${THREADS}; do
  scenario=$([[ "${t}" -eq 1 ]] && echo S1 || echo S2)
  for ((w = 1; w <= WARMUP; w++)); do
    echo "[warm-up] ${scenario} threads=${t} (${w}/${WARMUP})"
    run_jmeter "warmup_${scenario}_t${t}_w${w}" "${t}"
    sleep "${PAUSE}"
  done
  for ((r = 1; r <= REPS; r++)); do
    echo "[run] ${scenario} threads=${t} rep=${r}/${REPS}"
    run_jmeter "${scenario}_t${t}_r${r}" "${t}"
    sleep "${PAUSE}"
  done
done

python3 -I "${BENCH_DIR}/analysis/summarize.py" "${OUT_DIR}"
echo "Results: ${OUT_DIR}"
