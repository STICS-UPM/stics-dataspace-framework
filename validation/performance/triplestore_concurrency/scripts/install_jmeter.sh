#!/usr/bin/env bash
# Downloads the pinned Apache JMeter release into ../.tools and verifies its SHA-512.
set -euo pipefail

JMETER_VERSION="${JMETER_VERSION:-5.6.3}"
JMETER_SHA512="5978a1a35edb5a7d428e270564ff49d2b1b257a65e17a759d259a9283fc17093e522fe46f474a043864aea6910683486340706d745fcdf3db1505fd71e689083"

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_DIR="${BENCH_DIR}/.tools"
TARGET="${TOOLS_DIR}/apache-jmeter-${JMETER_VERSION}"

if [[ -x "${TARGET}/bin/jmeter" ]]; then
  echo "${TARGET}/bin/jmeter"
  exit 0
fi

mkdir -p "${TOOLS_DIR}"
TGZ="${TOOLS_DIR}/apache-jmeter-${JMETER_VERSION}.tgz"
# CDN first (fast, current releases only), Apache archive as fallback; the hash pins the content.
for url in "https://dlcdn.apache.org/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz" \
           "https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz"; do
  curl -fsSL --connect-timeout 15 -o "${TGZ}" "${url}" && break
done
echo "${JMETER_SHA512}  ${TGZ}" | sha512sum -c - >&2
tar -xzf "${TGZ}" -C "${TOOLS_DIR}"
rm -f "${TGZ}"
echo "${TARGET}/bin/jmeter"
