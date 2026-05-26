const capabilityCache = new Map();

function cachedRuntimeCapability(runtime, key) {
  const capabilities = runtime.capabilities || {};
  if (!Object.prototype.hasOwnProperty.call(capabilities, key)) {
    return null;
  }

  if (capabilities[key]) {
    return {
      available: true,
      source: "runtime",
    };
  }

  return {
    available: false,
    source: "runtime",
    reason:
      (runtime.capabilityReasons || {})[key] ||
      `Capability '${key}' is not available in the current environment.`,
  };
}

function normalizeText(value) {
  return String(value || "").trim();
}

function lowerBody(body) {
  return normalizeText(body).toLowerCase();
}

function buildCacheKey(prefix, runtime, extra = "") {
  return `${prefix}:${runtime.baseUrl}:${extra}`;
}

async function readJson(response) {
  const body = await response.text();
  try {
    return {
      body,
      payload: JSON.parse(body),
    };
  } catch (error) {
    return {
      body,
      payload: null,
    };
  }
}

function apiFailureReason(response, body, fallback) {
  const snippet = normalizeText(body).slice(0, 240);
  return snippet
    ? `${fallback} HTTP ${response.status()}: ${snippet}`
    : `${fallback} HTTP ${response.status()}`;
}

function buildTermSearchQueries(runtime) {
  const candidates = [
    runtime.expectedSearchTerm,
    runtime.expectedVocabularyPrefix,
    runtime.listingSearchTerm,
    runtime.expectedPrimaryTag,
    "a",
    "e",
    "i",
    "o",
    "r",
    "s",
  ];
  return Array.from(new Set(candidates.map(normalizeText).filter(Boolean)));
}

function firstNonEmpty(values) {
  for (const value of values) {
    if (Array.isArray(value)) {
      const nested = firstNonEmpty(value);
      if (nested) {
        return nested;
      }
      continue;
    }
    if (value && typeof value === "object") {
      const nested = firstNonEmpty(Object.values(value));
      if (nested) {
        return nested;
      }
      continue;
    }
    const normalized = normalizeText(value);
    if (normalized) {
      return normalized;
    }
  }
  return "";
}

function termLabelFromResult(result) {
  const explicitLabel = firstNonEmpty([result.label, result.prefLabel, result.name]);
  if (explicitLabel) {
    return explicitLabel;
  }

  const prefixedName = firstNonEmpty([result.prefixedName]);
  if (prefixedName.includes(":")) {
    return prefixedName.split(":").pop();
  }

  const uri = firstNonEmpty([result.uri]);
  if (!uri) {
    return "";
  }

  const hashParts = uri.split("#");
  if (hashParts.length > 1) {
    return hashParts.pop();
  }
  const pathParts = uri.split("/");
  return pathParts[pathParts.length - 1] || uri;
}

function vocabularyPrefixFromResult(result, fallback = "") {
  return normalizeText(
    firstNonEmpty([
      result["vocabulary.prefix"],
      result.vocabularyPrefix,
      result.vocabulary?.prefix,
      result.vocabulary,
      fallback,
    ]),
  );
}

function resourceTagsFromResult(result, fallback = "") {
  const tags = firstNonEmpty([
    result.tags,
    result["vocabulary.tags"],
    result.vocabulary?.tags,
    fallback,
  ]);
  return normalizeText(tags);
}

async function probeVocabularyResourceApi(request, runtime, options = {}) {
  const cacheKey = buildCacheKey(
    "publicVocabularyResourceApi",
    runtime,
    runtime.expectedVocabularyPrefix,
  );
  if (!options.refresh && capabilityCache.has(cacheKey)) {
    return capabilityCache.get(cacheKey);
  }

  const targetPrefix = normalizeText(runtime.expectedVocabularyPrefix);
  const resourceTypes = ["class", "property", "datatype"];
  let result = {
    available: false,
    reason: `The public vocabulary resource API did not return resources for '${targetPrefix}'.`,
  };

  for (const resourceType of resourceTypes) {
    const url =
      `${runtime.baseUrl}/dataset/api/v2/vocabulary/${encodeURIComponent(targetPrefix)}` +
      `/resources/type/${encodeURIComponent(resourceType)}`;
    const response = await request.get(url);
    const { body, payload } = await readJson(response);

    if (response.status() !== 200 || !Array.isArray(payload)) {
      result = {
        available: false,
        reason: apiFailureReason(
          response,
          body,
          `The public '${resourceType}' resource API for '${targetPrefix}' is not available.`,
        ),
      };
      continue;
    }

    const selected =
      payload.find(
        (item) =>
          vocabularyPrefixFromResult(item).toLowerCase() === targetPrefix.toLowerCase(),
      ) || payload[0];

    if (!selected) {
      continue;
    }

    result = {
      available: true,
      source: "resource-api",
      resourceType,
      label: termLabelFromResult(selected) || targetPrefix,
      prefix: vocabularyPrefixFromResult(selected, targetPrefix),
      primaryTag: resourceTagsFromResult(selected, runtime.expectedPrimaryTag),
      prefixedName: normalizeText(firstNonEmpty([selected.prefixedName])),
      uri: normalizeText(firstNonEmpty([selected.uri])),
    };
    break;
  }

  capabilityCache.set(cacheKey, result);
  return result;
}

async function probeVocabularyAutocomplete(request, runtime, options = {}) {
  const cached = cachedRuntimeCapability(runtime, "publicVocabularyAutocomplete");
  if (cached) {
    return cached;
  }

  const cacheKey = buildCacheKey("publicVocabularyAutocomplete", runtime, runtime.listingSearchTerm);
  if (!options.refresh && capabilityCache.has(cacheKey)) {
    return capabilityCache.get(cacheKey);
  }

  const query = normalizeText(
    runtime.listingSearchTerm || runtime.expectedVocabularyPrefix || runtime.expectedSearchTerm,
  );
  const url =
    `${runtime.baseUrl}/dataset/api/v2/vocabulary/autocomplete?q=` + encodeURIComponent(query);
  const response = await request.get(url);
  const { body, payload } = await readJson(response);

  let result;
  if (response.status() !== 200 || !payload) {
    result = {
      available: false,
      reason: apiFailureReason(
        response,
        body,
        "The public vocabulary autocomplete is not available.",
      ),
    };
  } else if (payload.error) {
    result = {
      available: false,
      reason: normalizeText(
        `${payload.error}${payload.details ? `: ${payload.details}` : ""}`,
      ),
    };
  } else {
    const results = Array.isArray(payload.results) ? payload.results : [];
    const selected =
      results.find(
        (item) =>
          normalizeText(item.prefix || item.label).toLowerCase() ===
          normalizeText(runtime.expectedVocabularyPrefix).toLowerCase(),
      ) || results[0];

    if (!selected) {
      result = {
        available: false,
        reason: `The public vocabulary autocomplete did not return results for '${query}'.`,
      };
    } else {
      result = {
        available: true,
        query,
        prefix: normalizeText(selected.prefix || selected.label || runtime.expectedVocabularyPrefix),
        title: normalizeText(
          selected.title ||
            selected["http://purl.org/dc/terms/title@en"] ||
            runtime.expectedVocabularyTitle,
        ),
      };
    }
  }

  capabilityCache.set(cacheKey, result);
  return result;
}

async function probeTermSearchApi(request, runtime, options = {}) {
  const cached = cachedRuntimeCapability(runtime, "publicTermSearchApi");
  if (cached) {
    return cached;
  }

  const cacheKey = buildCacheKey("publicTermSearchApi", runtime);
  if (!options.refresh && capabilityCache.has(cacheKey)) {
    return capabilityCache.get(cacheKey);
  }

  const retryDeadline = options.refresh ? Date.now() + 60000 : Date.now();
  let lastResult;
  do {
    lastResult = await _probeTermSearchApiOnce(request, runtime);
    if (lastResult.available) {
      break;
    }
    if (Date.now() < retryDeadline) {
      await new Promise((resolve) => setTimeout(resolve, 5000));
    }
  } while (Date.now() < retryDeadline);

  capabilityCache.set(cacheKey, lastResult);
  return lastResult;
}

async function _probeTermSearchApiOnce(request, runtime) {
  let result = {
    available: false,
    reason: "The public term search API did not return reusable results.",
  };

  for (const query of buildTermSearchQueries(runtime)) {
    const url =
      `${runtime.baseUrl}/dataset/api/v2/term/search?q=` +
      encodeURIComponent(query) +
      "&type=class";
    const response = await request.get(url);
    const { body, payload } = await readJson(response);

    if (response.status() !== 200 || !payload) {
      result = {
        available: false,
        reason: apiFailureReason(
          response,
          body,
          "The public term search API is not available.",
        ),
      };
      continue;
    }

    const matches = Array.isArray(payload.results) ? payload.results : [];
    const selected =
      matches.find(
        (item) =>
          vocabularyPrefixFromResult(item).toLowerCase() ===
          normalizeText(runtime.expectedVocabularyPrefix).toLowerCase(),
      ) || matches[0];

    if (!selected) {
      continue;
    }

    result = {
      available: true,
      query,
      label: termLabelFromResult(selected) || query,
      prefix: vocabularyPrefixFromResult(selected, runtime.expectedVocabularyPrefix),
      primaryTag: resourceTagsFromResult(selected, runtime.expectedPrimaryTag),
      prefixedName: normalizeText(firstNonEmpty([selected.prefixedName])),
      uri: normalizeText(firstNonEmpty([selected.uri])),
    };
    break;
  }

  if (!result.available) {
    const resourceApiProbe = await probeVocabularyResourceApi(request, runtime, {});
    if (resourceApiProbe.available) {
      result = {
        ...resourceApiProbe,
        query: resourceApiProbe.label || runtime.expectedVocabularyPrefix,
      };
    }
  }

  return result;
}

async function probeTermsPage(request, runtime) {
  const cached = cachedRuntimeCapability(runtime, "publicTermSearchUi");
  if (cached) {
    return cached;
  }

  const cacheKey = buildCacheKey("publicTermSearchUi", runtime);
  if (capabilityCache.has(cacheKey)) {
    return capabilityCache.get(cacheKey);
  }

  const response = await request.get(`${runtime.baseUrl}/dataset/terms`);
  const body = await response.text();
  const normalized = lowerBody(body);

  let result;
  if (response.status() !== 200) {
    result = {
      available: false,
      reason: `The public terms page returned HTTP ${response.status()}.`,
    };
  } else if (normalized.includes("oops! something went wrong") || normalized.includes("500 -")) {
    result = {
      available: false,
      reason: "The public terms page returns a 500 error in the current environment.",
    };
  } else if (!normalized.includes("searchinput")) {
    result = {
      available: false,
      reason: "The public terms page does not show the expected search box.",
    };
  } else {
    result = {
      available: true,
    };
  }

  capabilityCache.set(cacheKey, result);
  return result;
}

async function probeVocabularyDetail(
  request,
  runtime,
  prefix = runtime.expectedVocabularyPrefix,
  options = {},
) {
  const runtimeKey = prefix === runtime.expectedVocabularyPrefix ? "publicVocabularyDetail" : null;
  const cached = runtimeKey ? cachedRuntimeCapability(runtime, runtimeKey) : null;
  if (cached) {
    return cached;
  }

  const cacheKey = buildCacheKey("publicVocabularyDetail", runtime, prefix);
  if (!options.refresh && capabilityCache.has(cacheKey)) {
    return capabilityCache.get(cacheKey);
  }

  const response = await request.get(`${runtime.baseUrl}/dataset/vocabs/${encodeURIComponent(prefix)}`);
  const body = await response.text();
  const normalized = lowerBody(body);

  let result;
  if (response.status() !== 200) {
    result = {
      available: false,
      prefix,
      reason: `The detail view for '${prefix}' returned HTTP ${response.status()}.`,
      versionHistory: false,
      statistics: false,
    };
  } else if (normalized.includes("oops! something went wrong") || normalized.includes("500 -")) {
    result = {
      available: false,
      prefix,
      reason: `The detail view for '${prefix}' returns a 500 error.`,
      versionHistory: false,
      statistics: false,
    };
  } else {
    const hasMetadata = normalized.includes("metadata");
    const hasVersionHistory =
      normalized.includes("version history") ||
      normalized.includes("vocabulary version history") ||
      normalized.includes("/versions/");
    const hasStatistics =
      normalized.includes("statistics") &&
      normalized.includes("chartelements") &&
      normalized.includes('"label":"classes"') &&
      normalized.includes('"label":"properties"') &&
      normalized.includes('"label":"datatypes"') &&
      normalized.includes('"label":"instances"');

    result = {
      available: hasMetadata,
      prefix,
      reason: hasMetadata
        ? ""
        : `The detail view for '${prefix}' does not show the expected Metadata section.`,
      versionHistory: hasVersionHistory,
      statistics: hasStatistics,
    };
  }

  capabilityCache.set(cacheKey, result);
  return result;
}

module.exports = {
  probeTermSearchApi,
  probeTermsPage,
  probeVocabularyAutocomplete,
  probeVocabularyDetail,
  probeVocabularyResourceApi,
};
