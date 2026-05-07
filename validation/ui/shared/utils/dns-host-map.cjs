"use strict";

const dns = require("node:dns");
const net = require("node:net");

function parseHostMap(rawValue) {
  return String(rawValue || "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean)
    .reduce((mapping, entry) => {
      const separatorIndex = entry.indexOf("=");
      if (separatorIndex <= 0) {
        return mapping;
      }

      const hostname = entry.slice(0, separatorIndex).trim().replace(/\.$/, "").toLowerCase();
      const address = entry.slice(separatorIndex + 1).trim();
      if (hostname && net.isIP(address)) {
        mapping[hostname] = address;
      }
      return mapping;
    }, {});
}

function normalizeHostname(hostname) {
  return String(hostname || "").replace(/\.$/, "").toLowerCase();
}

function familyFor(address, requestedFamily) {
  if (requestedFamily === 4 || requestedFamily === 6) {
    return requestedFamily;
  }
  return net.isIP(address) === 6 ? 6 : 4;
}

const hostMap = parseHostMap(process.env.PLAYWRIGHT_DNS_HOST_MAP);

if (Object.keys(hostMap).length > 0) {
  const originalLookup = dns.lookup.bind(dns);
  const originalPromisesLookup = dns.promises.lookup.bind(dns.promises);

  dns.lookup = function lookupWithPlaywrightHostMap(hostname, options, callback) {
    const callbackFn = typeof options === "function" ? options : callback;
    const lookupOptions = typeof options === "function" || options === undefined ? {} : options;
    const mappedAddress = hostMap[normalizeHostname(hostname)];

    if (!mappedAddress || typeof callbackFn !== "function") {
      return originalLookup(hostname, options, callback);
    }

    const requestedFamily = typeof lookupOptions === "number" ? lookupOptions : lookupOptions.family;
    const family = familyFor(mappedAddress, requestedFamily);

    process.nextTick(() => {
      if (typeof lookupOptions === "object" && lookupOptions.all) {
        callbackFn(null, [{ address: mappedAddress, family }]);
      } else {
        callbackFn(null, mappedAddress, family);
      }
    });
    return undefined;
  };

  dns.promises.lookup = async function lookupWithPlaywrightHostMapPromise(hostname, options = {}) {
    const mappedAddress = hostMap[normalizeHostname(hostname)];
    if (!mappedAddress) {
      return originalPromisesLookup(hostname, options);
    }

    const requestedFamily = typeof options === "number" ? options : options.family;
    const family = familyFor(mappedAddress, requestedFamily);
    if (typeof options === "object" && options.all) {
      return [{ address: mappedAddress, family }];
    }
    return { address: mappedAddress, family };
  };
}
