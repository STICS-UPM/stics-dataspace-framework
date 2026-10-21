#!/usr/bin/env python3
"""Generates 07_stics_connector_toolbox.json + 00_environment_toolbox.json.

Run:  python3 build_toolbox_collection.py
The environment written here carries placeholders for the passwords. Fill the five
pw_<connector> values (credentials.json -> connector_user.passwd) before using it.
"""
import json
import uuid
from pathlib import Path

HERE = Path(__file__).parent

# --------------------------------------------------------------------------- helpers
V = "https://w3id.org/edc/v0.0.1/ns/"
CTX = {"@vocab": V}
CTX_DCAT = {"@vocab": V, "dcterms": "http://purl.org/dc/terms/", "dcat": "http://www.w3.org/ns/dcat#",
            "vcard": "http://www.w3.org/2006/vcard/ns#", "citser": "https://stics.linkeddata.es/def/citser#"}


def j(o):
    return json.dumps(o, indent=2, ensure_ascii=False)


def test_event(lines):
    return [{"listen": "test", "script": {"type": "text/javascript", "exec": lines}}]


def req(name, method, url, body=None, auth=None, tests=None, desc="", raw_body=False, extra_headers=None):
    headers = []
    if body is not None:
        headers.append({"key": "Content-Type", "value": "application/json"})
    if auth:
        headers.append({"key": "Authorization", "value": "Bearer {{%s_jwt}}" % auth})
    for k, v in (extra_headers or {}).items():
        headers.append({"key": k, "value": v})
    r = {"method": method, "header": headers, "url": url}
    if desc:
        r["description"] = desc
    if body is not None:
        r["body"] = {"mode": "raw", "raw": body if raw_body else j(body)}
    item = {"name": name, "request": r}
    if tests:
        item["event"] = test_event(tests)
    return item


def folder(name, items, desc=""):
    f = {"name": name, "item": items}
    if desc:
        f["description"] = desc
    return f


def status_test(codes, label=None):
    return ["pm.test('%s', () => pm.expect(%s).to.include(pm.response.code));" % (label or "status is one of %s" % codes, json.dumps(codes))]


QS = lambda **kw: dict({"@context": CTX, "offset": 0, "limit": 50, "filterExpression": []}, **kw)

# --------------------------------------------------------------------------- collection-level scripts
PRE = r"""
// Resolves provider/consumer names -> URLs and keeps fresh Keycloak tokens (auto-login).
const REG = {
  'contest-stics':     {mgmt: 'https://con-test.stics.linkeddata.es/management',       dsp: 'https://con-test.stics.linkeddata.es/protocol',       user: 'user-contest-stics'},
  'conlab-stics':      {mgmt: 'https://con-lab.stics.linkeddata.es/management',        dsp: 'https://con-lab.stics.linkeddata.es/protocol',        user: 'user-conlab-stics'},
  'connector-stics':   {mgmt: 'https://stics.bavenir.eu/management',                   dsp: 'https://stics.bavenir.eu/protocol',                   user: 'user-connector-stics'},
  'connector-bavenir': {mgmt: 'https://connector-bavenir.stics.bavenir.eu/management', dsp: 'https://connector-bavenir.stics.bavenir.eu/protocol', user: 'user-connector-bavenir'},
  'contest-bavenir':   {mgmt: 'https://con-test.stics.bavenir.eu/management',          dsp: 'https://con-test.stics.bavenir.eu/protocol',          user: 'user-contest-bavenir'}
};
const env = pm.environment;
function resolveRole(role) {
  const name = env.get(role);
  const c = REG[name];
  if (!c) { console.warn('Unknown ' + role + ' = "' + name + '". Use one of: ' + Object.keys(REG).join(', ')); return null; }
  env.set(role + 'Mgmt', c.mgmt);
  env.set(role + 'Dsp', c.dsp);
  env.set(role + 'Base', c.mgmt.replace(/\/management$/, ''));
  env.set(role + 'ParticipantId', name);
  env.set(role + '_user', c.user);
  env.set(role + '_password', env.get('pw_' + name) || '');
  return {name: name, c: c};
}
function jwtExp(t) {
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).exp; } catch (e) { return 0; }
}
function ensureToken(role) {
  const info = resolveRole(role);
  if (!info) return;
  const jwt = env.get(role + '_jwt');
  if (jwt && env.get(role + '_jwt_for') === info.name && jwtExp(jwt) - 30 > Date.now() / 1000) return;
  const pw = env.get('pw_' + info.name);
  if (!pw || String(pw).startsWith('<')) { console.warn('Set the environment variable pw_' + info.name + ' (password of ' + info.c.user + ')'); return; }
  pm.sendRequest({
    url: env.get('keycloakUrl') + '/realms/' + env.get('dataspace') + '/protocol/openid-connect/token',
    method: 'POST',
    header: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: {mode: 'urlencoded', urlencoded: [
      {key: 'grant_type', value: 'password'}, {key: 'client_id', value: env.get('keycloakClientId')},
      {key: 'username', value: info.c.user}, {key: 'password', value: pw}]}
  }, function (err, res) {
    if (err || res.code !== 200) { console.warn('Token request failed for ' + info.name + ': ' + (err || res.text())); return; }
    env.set(role + '_jwt', res.json().access_token);
    env.set(role + '_jwt_for', info.name);
  });
}
ensureToken('provider');
ensureToken('consumer');
""".strip().splitlines()

COLLECTION_TEST = [
    "pm.test('response time under 20 s', () => pm.expect(pm.response.responseTime).to.be.below(20000));",
]

# --------------------------------------------------------------------------- 00 Ecosystem / infra
infra = folder("00 · Ecosystem & infra checks", [
    req("Keycloak · OIDC discovery (realm stics)", "GET", "{{keycloakUrl}}/realms/{{dataspace}}/.well-known/openid-configuration",
        tests=status_test([200]) + ["pm.test('issuer is the stics realm', () => pm.expect(pm.response.json().issuer).to.include('/realms/stics'));"]),
    req("Keycloak · JWKS (needed by every connector at boot)", "GET", "{{keycloakUrl}}/realms/{{dataspace}}/protocol/openid-connect/certs",
        tests=status_test([200]) + ["pm.test('has signing keys', () => pm.expect(pm.response.json().keys.length).to.be.above(0));"]),
    req("Vault · seal status (sealed=true takes every connector down)", "GET", "{{vaultUrl}}/v1/sys/seal-status",
        tests=status_test([200]) + ["pm.test('Vault is UNSEALED', () => pm.expect(pm.response.json().sealed).to.eql(false));"]),
    req("MinIO · liveness (S3 for connector storage)", "GET", "{{minioUrl}}/minio/health/live",
        tests=status_test([200]), desc="Can be slow (several seconds) from outside the UPM network."),
    req("Ontology Hub · catalogue page", "GET", "{{ontologyHubUrl}}/dataset", tests=status_test([200, 302])),
    req("Helio adapter · CitSer knowledge graph (Turtle)", "GET", "{{helioDataUrl}}",
        tests=status_test([200]) + ["pm.test('body is Turtle with citser prefix', () => pm.expect(pm.response.text()).to.include('citser:'));"],
        desc="Helio replies Content-Type text/html but the body is Turtle."),
    req("Helio adapter · GUI", "GET", "{{helioGuiUrl}}", tests=status_test([200])),
], "Checks the shared services the connectors depend on. Run these first when something fails.")

# --------------------------------------------------------------------------- 01 Health
def health_items(role):
    out = []
    for ep in ("health", "liveness", "readiness", "startup"):
        t = status_test([200]) + [
            "const d = pm.response.json();",
            "pm.test('system healthy', () => pm.expect(d.isSystemHealthy).to.eql(true));",
            "(d.componentResults||[]).filter(c=>!c.isHealthy).forEach(c => console.warn('UNHEALTHY:', c.component, JSON.stringify(c.failure)));",
        ]
        out.append(req("%s · /api/check/%s" % (role.capitalize(), ep), "GET", "{{%sBase}}/api/check/%s" % (role, ep), tests=t))
    out.append(req("%s · connector-interface (UI) is served" % role.capitalize(), "GET", "{{%sBase}}/connector-interface/" % role,
                   tests=status_test([200])))
    out.append(req("%s · DSP endpoint answers (no auth → 4xx, not 5xx)" % role.capitalize(), "GET", "{{%sDsp}}/catalog/request" % role,
                   tests=["pm.test('protocol endpoint is up (not 5xx)', () => pm.expect(pm.response.code).to.be.below(500));"]))
    return out

health = folder("01 · Health (provider & consumer)", health_items("provider") + health_items("consumer"),
                "Public health probes. A 503 with 'Vault is sealed' means Vault must be unsealed.")

# --------------------------------------------------------------------------- 02 Auth
auth = folder("02 · Auth (optional — the collection logs in automatically)", [
    req("Login · provider", "POST", "{{keycloakUrl}}/realms/{{dataspace}}/protocol/openid-connect/token", body=None,
        tests=["pm.test('token obtained', () => { const j = pm.response.json(); pm.expect(j.access_token).to.be.a('string'); pm.environment.set('provider_jwt', j.access_token); pm.environment.set('provider_jwt_for', pm.environment.get('provider')); });"]),
    req("Login · consumer", "POST", "{{keycloakUrl}}/realms/{{dataspace}}/protocol/openid-connect/token", body=None,
        tests=["pm.test('token obtained', () => { const j = pm.response.json(); pm.expect(j.access_token).to.be.a('string'); pm.environment.set('consumer_jwt', j.access_token); pm.environment.set('consumer_jwt_for', pm.environment.get('consumer')); });"]),
], "The collection pre-request script already fetches and refreshes both tokens. These two requests force a manual login (form body set below).")
# urlencoded bodies for the two manual logins
for it, who in zip(auth["item"], ("provider", "consumer")):
    it["request"]["header"] = [{"key": "Content-Type", "value": "application/x-www-form-urlencoded"}]
    it["request"]["body"] = {"mode": "urlencoded", "urlencoded": [
        {"key": "grant_type", "value": "password"}, {"key": "client_id", "value": "{{keycloakClientId}}"},
        {"key": "username", "value": "{{%s_user}}" % who}, {"key": "password", "value": "{{%s_password}}" % who}]}

# --------------------------------------------------------------------------- 03 Assets
asset_http = {"@context": CTX_DCAT, "@id": "{{assetId}}", "@type": "Asset",
              "properties": {"name": "Toolbox HttpData asset", "version": "1.0.0", "contenttype": "application/json", "assetType": "dataset",
                             "shortDescription": "Asset created from the STICS Postman toolbox",
                             "dcterms:description": "Asset created from the STICS Postman toolbox",
                             "dcat:keyword": ["toolbox", "test"]},
              "dataAddress": {"type": "HttpData", "name": "{{assetId}}", "baseUrl": "{{httpBaseUrl}}", "proxyPath": "true"}}

asset_s3 = {"@context": CTX_DCAT, "@id": "{{assetId}}-s3", "@type": "Asset",
            "properties": {"name": "Toolbox S3 asset", "version": "1.0.0", "contenttype": "{{s3ContentType}}", "assetType": "dataset",
                           "shortDescription": "S3-backed asset created from the Postman toolbox",
                           "dcat:keyword": ["toolbox", "s3"]},
            "dataAddress": {"type": "AmazonS3", "region": "{{s3Region}}", "bucketName": "{{s3Bucket}}", "keyName": "{{s3Key}}",
                            "accessKeyId": "{{s3AccessKey}}", "secretAccessKey": "{{s3SecretKey}}", "endpointOverride": "{{s3Endpoint}}"}}

asset_dcat = {"@context": CTX_DCAT, "@id": "{{assetId}}-dcat", "@type": "Asset",
              "properties": {"name": "Toolbox DCAT-enriched asset", "version": "1.0.0", "contenttype": "text/turtle", "assetType": "dataset",
                             "shortDescription": "Asset with enriched DCAT + citser metadata",
                             "dcterms:title": "CitSer Synthetic Knowledge Graph",
                             "dcterms:description": "Synthetic citizen-services knowledge graph served by the Helio adapter.",
                             "dcterms:publisher": "https://stics.linkeddata.es/org/upm-oeg",
                             "dcterms:license": "https://creativecommons.org/licenses/by/4.0/",
                             "dcterms:issued": "2026-07-03",
                             "dcat:keyword": ["citser", "knowledge-graph", "synthetic"],
                             "dcat:landingPage": "https://github.com/STICS-UPM/citser_synthetic_dataset",
                             "dcat:contactPoint": {"@type": "vcard:Organization", "vcard:fn": "STICS — UPM OEG", "vcard:hasEmail": "mailto:stics-oeg@upm.es"},
                             "dcat:distribution": {"@type": "dcat:Distribution", "dcat:accessURL": "{{helioDataUrl}}", "dcat:mediaType": "text/turtle"},
                             "citser:vocabulary": "https://stics.linkeddata.es/def/citser#",
                             "citser:isSynthetic": True},
              "dataAddress": {"type": "HttpData", "name": "{{assetId}}-dcat", "baseUrl": "{{helioDataUrl}}", "method": "GET", "contentType": "text/turtle"}}

s3_tests = [
    "if (!pm.environment.get('s3AccessKey')) {",
    "  pm.test('no s3 keys set -> validator rejects (400, accessKeyId required)', () => { pm.expect(pm.response.code).to.eql(400); pm.expect(pm.response.text()).to.include('accessKeyId'); });",
    "} else {",
    "  pm.test('S3 asset accepted (200 / 409)', () => pm.expect([200, 409]).to.include(pm.response.code));",
    "}",
]
asset_update = json.loads(json.dumps(asset_http))
asset_update["properties"]["shortDescription"] = "UPDATED from Postman at {{$isoTimestamp}}"

ids_log = ["const a = pm.response.json(); const arr = Array.isArray(a) ? a : [a];",
           "console.log('assets (' + arr.length + '):', arr.map(x => x['@id']).join(', '));"]

assets = folder("03 · Assets (provider)", [
    req("Create HttpData asset", "POST", "{{providerMgmt}}/v3/assets", asset_http, "provider", status_test([200, 409]),
        "Points at {{httpBaseUrl}}. 409 = already exists (re-run)."),
    req("Create AmazonS3 asset (direct, needs keys)", "POST", "{{providerMgmt}}/v3/assets", asset_s3, "provider", s3_tests,
        "The connector validator requires region, bucketName, accessKeyId, secretAccessKey and endpointOverride for AmazonS3. "
        "The keys are STORED in the asset's dataAddress. Fill s3* variables first."),
    req("Create DCAT-enriched asset (citser metadata)", "POST", "{{providerMgmt}}/v3/assets", asset_dcat, "provider", status_test([200, 409]),
        "Enriched DCAT + nested objects + custom citser: terms. See the catalogue request in folder 06 to check they survive."),
    req("List assets", "POST", "{{providerMgmt}}/v3/assets/request", QS(), "provider",
        status_test([200]) + ids_log),
    req("Count assets", "POST", "{{providerMgmt}}/pagination/count?type=asset", QS(), "provider",
        status_test([200]) + ["console.log('asset count:', pm.response.text());"],
        "Endpoint used by the connector-interface UI."),
    req("Get asset by id", "GET", "{{providerMgmt}}/v3/assets/{{assetId}}", None, "provider",
        status_test([200]) + ["pm.test('id matches', () => pm.expect(pm.response.json()['@id']).to.eql(pm.environment.get('assetId')));"]),
    req("Update asset (PUT)", "PUT", "{{providerMgmt}}/v3/assets", asset_update, "provider", status_test([200, 204])),
], "Assets exposed by the provider connector. Deletes are in folder 99 so a full Runner pass keeps what it creates.")

# --------------------------------------------------------------------------- 04 Policies
pol_allow = {"@context": {"@vocab": V, "odrl": "http://www.w3.org/ns/odrl/2/"}, "@id": "{{policyId}}",
             "policy": {"@context": "http://www.w3.org/ns/odrl.jsonld", "@type": "Set", "permission": [], "prohibition": [], "obligation": []}}
pol_true = {"@context": {"@vocab": V, "odrl": "http://www.w3.org/ns/odrl/2/"}, "@id": "{{policyId}}-always-true",
            "policy": {"@context": "http://www.w3.org/ns/odrl.jsonld", "@type": "Set",
                       "permission": [{"action": "USE", "constraint": {"leftOperand": "ALWAYS_TRUE", "operator": "eq", "rightOperand": "true"}}],
                       "prohibition": [], "obligation": []}}
policies = folder("04 · Policies (provider)", [
    req("Create policy · allow-all (empty ODRL Set)", "POST", "{{providerMgmt}}/v3/policydefinitions", pol_allow, "provider", status_test([200, 409])),
    req("Create policy · always-true (ALWAYS_TRUE constraint)", "POST", "{{providerMgmt}}/v3/policydefinitions", pol_true, "provider", status_test([200, 409])),
    req("List policies", "POST", "{{providerMgmt}}/v3/policydefinitions/request", QS(), "provider",
        status_test([200]) + ["console.log('policies:', pm.response.json().map(x => x['@id']).join(', '));"]),
    req("Get policy", "GET", "{{providerMgmt}}/v3/policydefinitions/{{policyId}}", None, "provider", status_test([200])),
])

# --------------------------------------------------------------------------- 05 Contract definitions
cd_body = {"@context": CTX, "@id": "{{cdId}}", "accessPolicyId": "{{policyId}}", "contractPolicyId": "{{policyId}}",
           "assetsSelector": [{"@type": "CriterionDto", "operandLeft": V + "id", "operator": "=", "operandRight": "{{assetId}}"}]}
cds = folder("05 · Contract definitions (provider)", [
    req("Create contract definition (asset ← policy)", "POST", "{{providerMgmt}}/v3/contractdefinitions", cd_body, "provider", status_test([200, 409]),
        "Exposes {{assetId}} in the catalogue under {{policyId}}. Nothing is visible to consumers until this exists."),
    req("Create contract definition for the DCAT-enriched asset", "POST", "{{providerMgmt}}/v3/contractdefinitions",
        {"@context": CTX, "@id": "{{cdId}}-dcat", "accessPolicyId": "{{policyId}}", "contractPolicyId": "{{policyId}}",
         "assetsSelector": [{"@type": "CriterionDto", "operandLeft": V + "id", "operator": "=", "operandRight": "{{assetId}}-dcat"}]},
        "provider", status_test([200, 409]), "Needed so the DCAT-enriched asset appears in the catalogue (folder 06)."),
    req("List contract definitions", "POST", "{{providerMgmt}}/v3/contractdefinitions/request", QS(), "provider",
        status_test([200]) + ["console.log('contract definitions:', pm.response.json().map(x => x['@id']).join(', '));"]),
    req("Get contract definition", "GET", "{{providerMgmt}}/v3/contractdefinitions/{{cdId}}", None, "provider", status_test([200])),
])

# --------------------------------------------------------------------------- 06 Catalogue (consumer)
cat_body = {"@context": CTX, "@type": "CatalogRequest", "counterPartyAddress": "{{providerDsp}}", "counterPartyId": "{{providerParticipantId}}",
            "protocol": "dataspace-protocol-http", "querySpec": {"offset": 0, "limit": 200, "filterExpression": []}}
cat_filtered = json.loads(json.dumps(cat_body))
cat_filtered["querySpec"]["filterExpression"] = [{"operandLeft": V + "id", "operator": "=", "operandRight": "{{assetId}}"}]

offer_test = [
    "const cat = pm.response.json();",
    "let ds = cat['dcat:dataset'] || cat['http://www.w3.org/ns/dcat#dataset'] || [];",
    "ds = Array.isArray(ds) ? ds : [ds];",
    "const aid = pm.environment.get('assetId');",
    "const d = ds.find(x => x['@id'] === aid);",
    "pm.test('asset ' + aid + ' is in the provider catalogue', () => pm.expect(d, 'not found - create asset+policy+contract definition first').to.be.an('object'));",
    "if (d) { let o = d['odrl:hasPolicy'] || d['hasPolicy']; if (Array.isArray(o)) { console.log('offers for this asset:', o.length, '- using the first'); o = o[0]; }",
    "  const pol = Object.assign({}, o, {'odrl:assigner': {'@id': pm.environment.get('providerParticipantId')}, 'odrl:target': {'@id': aid}});",
    "  pm.environment.set('offerId', o['@id']); pm.environment.set('offerJson', JSON.stringify(pol)); console.log('offerId =', o['@id']); }",
]

catalog = folder("06 · Catalogue (consumer asks the provider via DSP)", [
    req("Fetch full provider catalogue", "POST", "{{consumerMgmt}}/v3/catalog/request", cat_body, "consumer",
        status_test([200]) + [
            "const cat = pm.response.json(); let ds = cat['dcat:dataset'] || []; ds = Array.isArray(ds) ? ds : [ds];",
            "pm.test('catalogue has participantId of the provider', () => pm.expect(JSON.stringify(cat)).to.include(pm.environment.get('providerParticipantId')));",
            "console.log('datasets (' + ds.length + '):', ds.map(x => x['@id']).join(', '));"]),
    req("Find my asset & capture offerId", "POST", "{{consumerMgmt}}/v3/catalog/request", cat_body, "consumer", offer_test,
        "Stores the complete contract offer in {{offerJson}} (and its id in {{offerId}}) for the negotiation."),
    req("Catalogue filtered by asset id", "POST", "{{consumerMgmt}}/v3/catalog/request", cat_filtered, "consumer",
        status_test([200]) + ["console.log(JSON.stringify(pm.response.json()['dcat:dataset'], null, 2));"]),
    req("Show DCAT metadata of my asset (enriched fields)", "POST", "{{consumerMgmt}}/v3/catalog/request", cat_body, "consumer",
        ["const cat = pm.response.json(); let ds = cat['dcat:dataset'] || []; ds = Array.isArray(ds) ? ds : [ds];",
         "const d = ds.find(x => x['@id'] === pm.environment.get('assetId') + '-dcat');",
         "pm.test('enriched asset visible (create it in folder 03 first)', () => pm.expect(d).to.be.an('object'));",
         "if (d) { console.log(JSON.stringify(d, null, 2)); pm.test('nested dcat:distribution survives', () => pm.expect(d['dcat:distribution']).to.be.an('object')); }"]),
    req("Federated catalogue count (as the UI does)", "POST", "{{consumerMgmt}}/pagination/count?type=federatedCatalog", QS(), "consumer",
        status_test([200]) + ["console.log('federated catalogue entries:', pm.response.text());"]),
], "The consumer asks the provider's DSP endpoint for its catalogue (DCAT).")

# --------------------------------------------------------------------------- 07 Negotiation
neg_body = {"@context": {"@vocab": V, "edc": V, "odrl": "http://www.w3.org/ns/odrl/2/"}, "@type": "ContractRequest",
            "counterPartyAddress": "{{providerDsp}}", "protocol": "dataspace-protocol-http", "policy": "__OFFER_JSON__"}
neg_poll = [
    "const j = pm.response.json(); const st = j.state; console.log('negotiation state:', st);",
    "if (!st) { pm.test('negotiation exists (run Start negotiation first)', () => { throw new Error(pm.response.text().substring(0, 300)); }); }",
    "else if (st === 'FINALIZED') { pm.environment.set('agreementId', j.contractAgreementId); pm.environment.unset('negRetries');",
    "  pm.test('negotiation FINALIZED with agreement', () => pm.expect(j.contractAgreementId).to.be.a('string')); }",
    "else if (st === 'TERMINATED' || st === 'TERMINATING') { pm.test('negotiation not terminated', () => { throw new Error(JSON.stringify(j)); }); }",
    "else { const n = parseInt(pm.environment.get('negRetries') || '0', 10) + 1; pm.environment.set('negRetries', n);",
    "  if (n <= 30) { setTimeout(() => {}, 2000); postman.setNextRequest(pm.info.requestName); }",
    "  else { pm.test('negotiation finalized in time', () => { throw new Error('timeout after 30 polls'); }); } }",
]
term_body = lambda idv: {"@context": CTX, "@id": idv, "reason": "terminated from Postman toolbox"}
negotiation = folder("07 · Contract negotiation (consumer)", [
    req("Start negotiation (sends the complete offer)", "POST", "{{consumerMgmt}}/v3/contractnegotiations", j(neg_body).replace('"__OFFER_JSON__"', "{{offerJson}}"), "consumer",
        ["const j = pm.response.json(); pm.test('negotiation started', () => pm.expect(j['@id']).to.be.a('string'));",
         "pm.environment.set('negotiationId', j['@id']); pm.environment.set('negRetries', '0');"],
        "Run 'Find my asset & capture offerId' (folder 06) first: it stores the COMPLETE offer in {{offerJson}}. "
        "Sending only the offer id makes the negotiation TERMINATE for any policy that has rules.", raw_body=True),
    req("Poll negotiation state (re-send until FINALIZED)", "GET", "{{consumerMgmt}}/v3/contractnegotiations/{{negotiationId}}", None, "consumer", neg_poll,
        "In the Collection Runner this request loops itself (max 30 polls). Manually: re-send until state = FINALIZED."),
    req("Get contract agreement", "GET", "{{consumerMgmt}}/v3/contractagreements/{{agreementId}}", None, "consumer",
        status_test([200]) + ["pm.test('agreement targets my asset', () => pm.expect(pm.response.json().assetId).to.eql(pm.environment.get('assetId')));"]),
    req("List negotiations (consumer view)", "POST", "{{consumerMgmt}}/v3/contractnegotiations/request", QS(), "consumer",
        status_test([200]) + ["console.log(pm.response.json().map(n => n['@id'] + ' ' + n.state).join('\\n'));"]),
    req("List agreements (consumer view)", "POST", "{{consumerMgmt}}/v3/contractagreements/request", QS(), "consumer",
        status_test([200]) + ["console.log('agreements:', pm.response.json().length);"]),
    req("Terminate negotiation", "POST", "{{consumerMgmt}}/v3/contractnegotiations/{{negotiationId}}/terminate", term_body("{{negotiationId}}"), "consumer",
        status_test([200, 204, 409, 500]), "Meant for a negotiation that is not yet finalized; on a FINALIZED one EDC answers with an error (409/500)."),
])

# --------------------------------------------------------------------------- 08 Transfer
pull_body = {"@context": CTX, "@type": "TransferRequestDto", "connectorId": "{{providerParticipantId}}", "counterPartyAddress": "{{providerDsp}}",
             "contractId": "{{agreementId}}", "protocol": "dataspace-protocol-http", "transferType": "HttpData-PULL"}
push_body = {"@context": CTX, "@type": "TransferRequestDto", "connectorId": "{{providerParticipantId}}", "counterPartyAddress": "{{providerDsp}}",
             "contractId": "{{agreementId}}", "protocol": "dataspace-protocol-http", "transferType": "HttpData-PUSH",
             "dataDestination": {"type": "HttpData", "baseUrl": "{{pushSinkUrl}}"}}
xfer_poll = lambda ok: [
    "const j = pm.response.json(); const st = j.state; console.log('transfer state:', st);",
    "if (!st) { pm.test('transfer exists (run Start transfer first)', () => { throw new Error(pm.response.text().substring(0, 300)); }); }",
    "else if (%s.includes(st)) { pm.test('transfer reached ' + st, () => pm.expect(%s).to.include(st)); pm.environment.unset('xferRetries'); }" % (json.dumps(ok), json.dumps(ok)),
    "else if (st === 'TERMINATED') { pm.test('transfer not terminated', () => { throw new Error(JSON.stringify(j)); }); }",
    "else { const n = parseInt(pm.environment.get('xferRetries') || '0', 10) + 1; pm.environment.set('xferRetries', n);",
    "  if (n <= 40) { setTimeout(() => {}, 2000); postman.setNextRequest(pm.info.requestName); }",
    "  else { pm.test('transfer progressed in time', () => { throw new Error('timeout'); }); } }",
]
transfer = folder("08 · Transfer (consumer)", [
    req("Start transfer · HttpData-PULL", "POST", "{{consumerMgmt}}/v3/transferprocesses", pull_body, "consumer",
        ["const j = pm.response.json(); pm.test('transfer started', () => pm.expect(j['@id']).to.be.a('string'));",
         "pm.environment.set('transferId', j['@id']); pm.environment.set('xferRetries', '0');"],
        "Needs {{agreementId}} from the negotiation."),
    req("Poll transfer state (until STARTED/COMPLETED)", "GET", "{{consumerMgmt}}/v3/transferprocesses/{{transferId}}", None, "consumer", xfer_poll(["STARTED", "COMPLETED"])),
    req("Get EDR (endpoint + access token)", "GET", "{{consumerMgmt}}/v3/edrs/{{transferId}}/dataaddress", None, "consumer",
        ["const j = pm.response.json(); pm.test('EDR has endpoint', () => pm.expect(j.endpoint).to.be.a('string'));",
         "pm.environment.set('edrEndpoint', j.endpoint); pm.environment.set('edrAuthorization', j.authorization);"]),
    req("Pull the data through the provider data plane (EDR)", "GET", "{{edrEndpoint}}", None, None,
        status_test([200]) + ["console.log('PULLED DATA:', pm.response.text().substring(0, 800));"],
        "This is the actual download: provider data plane public API, authorised with the EDR token.",
        extra_headers={"Authorization": "{{edrAuthorization}}"}),
    req("Start transfer · HttpData-PUSH (to pushSinkUrl)", "POST", "{{consumerMgmt}}/v3/transferprocesses", push_body, "consumer",
        ["const j = pm.response.json(); pm.test('push transfer started', () => pm.expect(j['@id']).to.be.a('string'));",
         "pm.environment.set('transferId', j['@id']); pm.environment.set('xferRetries', '0');"],
        "The provider POSTs the data to {{pushSinkUrl}} (default: httpbin.org echo). The in-house sink behind con-lab /push-sink needs a process on stics2lab:9999, which is not always running."),
    req("Poll PUSH transfer (until COMPLETED)", "GET", "{{consumerMgmt}}/v3/transferprocesses/{{transferId}}", None, "consumer", xfer_poll(["COMPLETED"])),
    req("List transfer processes (consumer view)", "POST", "{{consumerMgmt}}/v3/transferprocesses/request", QS(), "consumer",
        status_test([200]) + ["console.log(pm.response.json().map(t => t['@id'] + ' ' + t.state).join('\\n'));"]),
    req("List EDRs", "POST", "{{consumerMgmt}}/v3/edrs/request", QS(), "consumer", status_test([200])),
    req("Terminate transfer", "POST", "{{consumerMgmt}}/v3/transferprocesses/{{transferId}}/terminate", term_body("{{transferId}}"), "consumer",
        status_test([200, 204, 404, 409, 500]), "For a running transfer. Already COMPLETED/TERMINATED ones answer with an error."),
])

# --------------------------------------------------------------------------- 09 Provider view
provider_view = folder("09 · Provider-side view of what consumers did", [
    req("Provider · list negotiations", "POST", "{{providerMgmt}}/v3/contractnegotiations/request", QS(), "provider",
        status_test([200]) + ["console.log(pm.response.json().map(n => n['@id'] + ' ' + n.state + ' ' + (n.counterPartyId||'')).join('\\n'));"]),
    req("Provider · list agreements", "POST", "{{providerMgmt}}/v3/contractagreements/request", QS(), "provider", status_test([200])),
    req("Provider · list transfer processes", "POST", "{{providerMgmt}}/v3/transferprocesses/request", QS(), "provider",
        status_test([200]) + ["console.log(pm.response.json().map(t => t['@id'] + ' ' + t.state).join('\\n'));"]),
])

# --------------------------------------------------------------------------- 10 Security
sec_body = QS()
security = folder("10 · Security sanity checks", [
    req("Management API without token → 401", "POST", "{{providerMgmt}}/v3/assets/request", sec_body, None, status_test([401])),
    req("Management API with garbage token → 401/403", "POST", "{{providerMgmt}}/v3/assets/request", sec_body, None, status_test([401, 403]),
        extra_headers={"Authorization": "Bearer not-a-real-token"}),
    req("Upload API exists (/s3assets/upload-chunk, no token → 401)", "POST", "{{providerMgmt}}/s3assets/upload-chunk", None, None, status_test([401, 403]),
        "The connector-side file upload API used by the connector-interface. 404 would mean the extension is missing."),
    req("Keycloak rejects a wrong password", "POST", "{{keycloakUrl}}/realms/{{dataspace}}/protocol/openid-connect/token", None, None, status_test([401])),
])
sec_login = security["item"][-1]["request"]
sec_login["header"] = [{"key": "Content-Type", "value": "application/x-www-form-urlencoded"}]
sec_login["body"] = {"mode": "urlencoded", "urlencoded": [
    {"key": "grant_type", "value": "password"}, {"key": "client_id", "value": "{{keycloakClientId}}"},
    {"key": "username", "value": "nobody"}, {"key": "password", "value": "wrong"}]}

# --------------------------------------------------------------------------- 99 Cleanup
cleanup = folder("99 · Cleanup (provider)", [
    req("Delete contract definition", "DELETE", "{{providerMgmt}}/v3/contractdefinitions/{{cdId}}", None, "provider", status_test([200, 204, 404])),
    req("Delete contract definition · DCAT demo", "DELETE", "{{providerMgmt}}/v3/contractdefinitions/{{cdId}}-dcat", None, "provider", status_test([200, 204, 404])),
    req("Delete policy · allow-all", "DELETE", "{{providerMgmt}}/v3/policydefinitions/{{policyId}}", None, "provider", status_test([200, 204, 404, 409])),
    req("Delete policy · always-true", "DELETE", "{{providerMgmt}}/v3/policydefinitions/{{policyId}}-always-true", None, "provider", status_test([200, 204, 404, 409])),
    req("Delete asset · HttpData", "DELETE", "{{providerMgmt}}/v3/assets/{{assetId}}", None, "provider", status_test([200, 204, 404, 409])),
    req("Delete asset · S3", "DELETE", "{{providerMgmt}}/v3/assets/{{assetId}}-s3", None, "provider", status_test([200, 204, 404, 409])),
    req("Delete asset · DCAT demo", "DELETE", "{{providerMgmt}}/v3/assets/{{assetId}}-dcat", None, "provider", status_test([200, 204, 404, 409])),
], "Removes what this collection created. Assets referenced by a contract agreement answer 409 (EDC keeps them).")

DESC = """STICS connector toolbox. One collection to exercise any pair of STICS connectors.

SETUP
1. Import this collection and 00_environment_toolbox.json, select the environment.
2. Fill the five pw_<connector> variables (credentials.json -> connector_user.passwd). Tokens are fetched and refreshed automatically.
3. Set `provider` and `consumer` to any two of: contest-stics, conlab-stics, connector-stics, connector-bavenir, contest-bavenir. All URLs are derived from the names.

END-TO-END ORDER (Collection Runner, run folders in this order)
00 ecosystem -> 01 health -> 03 assets (create HttpData) -> 04 policies (create) -> 05 contract definitions (create) -> 06 catalogue (find my asset) -> 07 negotiation -> 08 transfer (PULL) -> 99 cleanup.

NOTES
- Poll requests loop by themselves in the Runner; sent manually, re-send until the state is final.
- Cleanup cannot delete an asset that already has a contract agreement (409): that is EDC behaviour.
- The AmazonS3 asset stores the keys in the asset data address. Fill s3* variables only if you want to test that.
"""

collection = {
    "info": {"name": "07 · STICS connector toolbox", "_postman_id": str(uuid.uuid4()), "description": DESC,
             "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
    "event": [{"listen": "prerequest", "script": {"type": "text/javascript", "exec": PRE}},
              {"listen": "test", "script": {"type": "text/javascript", "exec": COLLECTION_TEST}}],
    "item": [infra, health, auth, assets, policies, cds, catalog, negotiation, transfer, provider_view, security, cleanup],
}

# --------------------------------------------------------------------------- environment
def ev(k, v, t="text"):
    return {"key": k, "value": v, "type": t, "enabled": True}

values = [
    ev("keycloakUrl", "https://auth.dev.linkeddata.es"), ev("keycloakClientId", "dataspace-users"), ev("dataspace", "stics"),
    ev("vaultUrl", "https://conn-citycouncil-demo.dev.linkeddata.es"), ev("minioUrl", "https://minio.dev.linkeddata.es"),
    ev("ontologyHubUrl", "https://ontology-hub-demo.dev.linkeddata.es"),
    ev("helioDataUrl", "https://helio-adapter.stics.linkeddata.es/api/citser_knowledge_graph/data"),
    ev("helioGuiUrl", "https://gui-helio-adapter.stics.linkeddata.es/"),
    ev("provider", "contest-stics"), ev("consumer", "conlab-stics"),
    ev("assetId", "toolbox-demo-asset"), ev("policyId", "toolbox-demo-policy"), ev("cdId", "toolbox-demo-cd"),
    ev("httpBaseUrl", "https://jsonplaceholder.typicode.com/todos/1"),
    ev("pushSinkUrl", "https://httpbin.org/post"),
    ev("s3Endpoint", "https://minio.dev.linkeddata.es"), ev("s3Region", "eu-central-1"), ev("s3Bucket", "stics-connector-bavenir"),
    ev("s3Key", "example.ttl"), ev("s3ContentType", "text/turtle"), ev("s3AccessKey", "", "secret"), ev("s3SecretKey", "", "secret"),
]
for n in ("contest-stics", "conlab-stics", "connector-stics", "connector-bavenir", "contest-bavenir"):
    values.append(ev("pw_" + n, "<credentials.json: connectors/%s -> connector_user.passwd>" % n, "secret"))
for k in ("provider_jwt", "consumer_jwt", "offerId", "offerJson", "negotiationId", "agreementId", "transferId", "edrEndpoint", "edrAuthorization"):
    values.append(ev(k, "", "secret" if "jwt" in k or "edrAuth" in k else "text"))

environment = {"id": str(uuid.uuid4()), "name": "00 Environment - STICS connector toolbox", "values": values, "_postman_variable_scope": "environment"}

(HERE / "07_stics_connector_toolbox.json").write_text(json.dumps(collection, indent=2, ensure_ascii=False))
(HERE / "00_environment_toolbox.json").write_text(json.dumps(environment, indent=2, ensure_ascii=False))
n = sum(len(f["item"]) for f in collection["item"])
print("collection: %d folders, %d requests" % (len(collection["item"]), n))
