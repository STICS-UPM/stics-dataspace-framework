#!/usr/bin/env python3
"""Clean accumulated test-junk offers from the vm-distributed connectors.

The federated catalog grows with every Level 6 / UI run (qa-ui-*, contract-ui-*,
asset-e2e-*, kafka-edc-asset-*, old contract-pt5-mh-*). The federated catalog
cache is capped (~100 datasets), so once enough junk accumulates the fresh
model / e2e / kafka assets fall outside the cap and discovery/negotiation fail.

This removes junk CONTRACT DEFINITIONS (which is what makes an asset appear as a
dataset/offer in the catalog) and, with --assets, the junk assets+policies too.
It PRESERVES the seeded AI Model Hub assets (company-flares-*, model-flares-*,
company-mobility-*, dataset-flares-*) and their policies/contracts.
Use --split-use-case-models after the split Step 10 flow to remove stale
mirrored use-case model assets from the participant that should not own them.

Usage:
  python3 scripts/clean_connector_catalog.py            # dry-run (shows targets)
  python3 scripts/clean_connector_catalog.py --apply    # delete contract defs
  python3 scripts/clean_connector_catalog.py --apply --assets   # also assets+policies
  python3 scripts/clean_connector_catalog.py --apply --assets --vocabularies
  python3 scripts/clean_connector_catalog.py --apply --assets --split-use-case-models
  python3 scripts/clean_connector_catalog.py --apply --agreements --assets --split-use-case-models
  python3 scripts/clean_connector_catalog.py --connectors conn-org2-pionera

Review the dry-run output before using --apply. Deletions are irreversible and
hit the shared dataspace connectors.
"""
import argparse
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://org1.pionera.oeg.fi.upm.es/auth/realms/pionera/protocol/openid-connect/token"
CRED_DIR = "deployers/inesdata/deployments/DEV/vm-distributed/pionera/connectors"
HOSTS = {
    "conn-org2-pionera": "org2.pionera.oeg.fi.upm.es",
    "conn-org3-pionera": "org3.pionera.oeg.fi.upm.es",
}
CONNECTOR_TAGS = {
    "conn-org2-pionera": "city",
    "conn-org3-pionera": "company",
}
JUNK_PREFIXES = (
    "qa-ui-", "asset-e2e-", "kafka-edc-asset-", "test-", "asset-crud-", "todos-",
    "e2e-", "contract-e2e-", "policy-e2e-", "contract-crud-", "policy-crud-",
    "contract-ui-", "policy-ui-", "contract-pt5-mh-", "policy-pt5-mh-",
    "pt5-mh-", "asset-ui-", "policy-test-", "contract-test",
    "a52-amh-", "a52-model-exec-",
)
# Legacy broad seed offers expose every historical machineLearning asset. The
# current Step 10 creates narrow contract-seed-<asset-id> offers instead.
JUNK_EXACT = {
    "contract-seed-city", "contract-seed-company",
    "policy-seed-city", "policy-seed-company",
}
# Preserve the seeded model/dataset assets AND their narrow offers (so MH-LING's
# dataset-flares-subtask2 stays discoverable). Only JUNK_EXACT broad offers go.
KEEP_PREFIXES = (
    "company-flares", "model-flares", "company-mobility", "dataset-flares",
    "contract-seed-", "policy-seed-", "contractdef-flares", "policy-flares",
)
KEEP_VOCABULARY_IDS = {"JS_DAIMO_Model", "JS_DAIMO_Dataset"}
JUNK_VOCABULARY_IDS = {"JS_Pionera_Daimo"}
JUNK_VOCABULARY_PREFIXES = ("qa-ui-", "qa-ui-amh-daimo-vocabulary-")
EDC_CTX = {"@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"}}
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def is_junk(identifier: str) -> bool:
    identifier = str(identifier or "")
    # Broad wildcard seed offers are removed by exact id even though their prefix
    # (contract-seed-/policy-seed-) is otherwise preserved.
    if identifier in JUNK_EXACT:
        return True
    if any(identifier.startswith(k) for k in KEEP_PREFIXES):
        return False
    return any(identifier.startswith(j) for j in JUNK_PREFIXES)


def use_case_model_owner_tag(slug: str) -> str:
    slug = str(slug or "")
    if (
        slug.startswith("flares-dccuchile-albert-")
        or slug.startswith("flares-dccuchile-distilbert-")
        or slug
        in {
            "mobility-lightgbm-actual-travel-time",
            "mobility-randomforest-actual-travel-time",
        }
    ):
        return "city"
    if (
        slug.startswith("flares-dccuchile-bert-base-")
        or slug
        in {
            "mobility-catboost-actual-travel-time",
            "mobility-lightgbm-delay",
            "mobility-randomforest-delay",
            "mobility-catboost-delay",
            "mobility-lightgbm-previous-delay",
            "mobility-randomforest-previous-delay",
            "mobility-catboost-previous-delay",
        }
    ):
        return "company"
    return "both"


def use_case_model_asset_parts(identifier: str):
    identifier = str(identifier or "")
    for tag in ("city", "company"):
        prefix = f"{tag}-"
        if identifier.startswith(prefix):
            return tag, identifier[len(prefix):]
    return "", ""


def is_wrong_owner_use_case_model(identifier: str, connector: str) -> bool:
    asset_tag, slug = use_case_model_asset_parts(identifier)
    if not asset_tag:
        return False
    owner_tag = use_case_model_owner_tag(slug)
    if owner_tag == "both":
        return False
    connector_tag = CONNECTOR_TAGS.get(connector, "")
    return asset_tag != owner_tag or (connector_tag and asset_tag != connector_tag)


def policy_seed_asset(identifier: str) -> str:
    identifier = str(identifier or "")
    return identifier[len("policy-seed-"):] if identifier.startswith("policy-seed-") else ""


def is_junk_vocabulary(vocabulary: dict) -> bool:
    identifier = str(vocabulary.get("@id") or vocabulary.get("id") or "")
    name = str(vocabulary.get("name") or vocabulary.get("edc:name") or "")
    if identifier in KEEP_VOCABULARY_IDS:
        return False
    if identifier in JUNK_VOCABULARY_IDS:
        return True
    if any(identifier.startswith(prefix) for prefix in JUNK_VOCABULARY_PREFIXES):
        return True
    text = f"{identifier} {name}".lower()
    return any(term in text for term in ("sentiment", "twitter", "ecommerce"))


def token(conn: str) -> str:
    cu = json.load(open(f"{CRED_DIR}/{conn}/credentials.json"))["connector_user"]
    data = urllib.parse.urlencode({
        "grant_type": "password", "client_id": "dataspace-users",
        "username": cu["user"], "password": cu["passwd"],
    }).encode()
    return json.load(urllib.request.urlopen(
        urllib.request.Request(TOKEN_URL, data=data), timeout=20, context=_ctx))["access_token"]


def query(host: str, tok: str, kind: str):
    body = json.dumps({**EDC_CTX, "@type": "QuerySpec", "limit": 10000}).encode()
    req = urllib.request.Request(
        f"https://{host}/management/v3/{kind}/request", data=body,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120, context=_ctx))


def query_vocabulary_endpoint(host: str, tok: str):
    body = json.dumps({**EDC_CTX, "@type": "QuerySpec", "limit": 10000}).encode()
    for base in ("vocabularies", "v3/vocabularies"):
        req = urllib.request.Request(
            f"https://{host}/management/{base}/request", data=body,
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        try:
            return base, json.load(urllib.request.urlopen(req, timeout=120, context=_ctx))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
    return "", []


def delete(host: str, tok: str, kind: str, ident: str) -> str:
    req = urllib.request.Request(
        f"https://{host}/management/v3/{kind}/{urllib.parse.quote(ident, safe='')}",
        headers={"Authorization": f"Bearer {tok}"}, method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=30, context=_ctx)
        return "ok"
    except urllib.error.HTTPError as exc:
        return str(exc.code)
    except Exception as exc:  # noqa: BLE001
        return f"err:{exc}"


def delete_vocabulary(host: str, tok: str, base: str, ident: str) -> str:
    req = urllib.request.Request(
        f"https://{host}/management/{base}/{urllib.parse.quote(ident, safe='')}",
        headers={"Authorization": f"Bearer {tok}"}, method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=30, context=_ctx)
        return "ok"
    except urllib.error.HTTPError as exc:
        return str(exc.code)
    except Exception as exc:  # noqa: BLE001
        return f"err:{exc}"


def cdef_asset(cd: dict) -> str:
    sel = cd.get("assetsSelector") or cd.get("https://w3id.org/edc/v0.0.1/ns/assetsSelector") or []
    if isinstance(sel, dict):
        sel = [sel]
    for crit in sel:
        val = crit.get("operandRight") or crit.get("https://w3id.org/edc/v0.0.1/ns/operandRight")
        if val:
            return str(val)
    return ""


def agreement_asset(agreement: dict) -> str:
    for key in (
        "assetId",
        "https://w3id.org/edc/v0.0.1/ns/assetId",
        "edc:assetId",
    ):
        value = agreement.get(key)
        if value:
            return str(value)
    return ""


def stale_asset(identifier: str, connector: str, split_use_case_models: bool) -> bool:
    if is_junk(identifier):
        return True
    return split_use_case_models and is_wrong_owner_use_case_model(identifier, connector)


def run(conns, apply: bool, assets: bool, vocabularies: bool, split_use_case_models: bool, agreements: bool):
    for conn in conns:
        host = HOSTS[conn]
        tok = token(conn)
        print(f"\n=== {conn} ({host}) {'APPLY' if apply else 'DRY-RUN'} ===")
        if agreements:
            items = query(host, tok, "contractagreements")
            tg = []
            split_tg = []
            for item in items:
                ident = item.get("@id") or item.get("id")
                asset_id = agreement_asset(item)
                if is_junk(asset_id):
                    tg.append(ident)
                elif split_use_case_models and is_wrong_owner_use_case_model(asset_id, conn):
                    tg.append(ident)
                    split_tg.append(ident)
            print(f"contract-agreements: {len(items)} total, {len(tg)} stale")
            if split_use_case_models:
                print(f"  split wrong-owner targets: {len(split_tg)}")
            codes = {}
            for ident in tg:
                res = delete(host, tok, "contractagreements", ident) if apply else "DRY"
                codes[res] = codes.get(res, 0) + 1
            print(f"  result: {codes}")

        cds = query(host, tok, "contractdefinitions")
        targets = []
        split_targets = []
        for cd in cds:
            cid = cd.get("@id") or cd.get("id")
            selected_asset = cdef_asset(cd)
            if is_junk(cid) or is_junk(selected_asset):
                targets.append(cid)
            elif split_use_case_models and is_wrong_owner_use_case_model(selected_asset, conn):
                targets.append(cid)
                split_targets.append(cid)
        print(f"contract-definitions: {len(cds)} total, {len(targets)} junk")
        if split_use_case_models:
            print(f"  split wrong-owner targets: {len(split_targets)}")
        codes = {}
        for cid in targets:
            res = delete(host, tok, "contractdefinitions", cid) if apply else "DRY"
            codes[res] = codes.get(res, 0) + 1
        print(f"  result: {codes}")
        if assets:
            for kind in ("policydefinitions", "assets"):
                items = query(host, tok, kind)
                tg = []
                split_tg = []
                for item in items:
                    ident = item.get("@id") or item.get("id")
                    split_candidate = ident
                    if kind == "policydefinitions":
                        split_candidate = policy_seed_asset(ident)
                    if stale_asset(ident, conn, split_use_case_models):
                        tg.append(ident)
                        if split_use_case_models and is_wrong_owner_use_case_model(ident, conn):
                            split_tg.append(ident)
                    elif split_use_case_models and is_wrong_owner_use_case_model(split_candidate, conn):
                        tg.append(ident)
                        split_tg.append(ident)
                print(f"{kind}: {len(items)} total, {len(tg)} junk")
                if split_use_case_models:
                    print(f"  split wrong-owner targets: {len(split_tg)}")
                codes = {}
                for ident in tg:
                    res = delete(host, tok, kind, ident) if apply else "DRY"
                    codes[res] = codes.get(res, 0) + 1
                print(f"  result: {codes}")
        if vocabularies:
            vocab_base, items = query_vocabulary_endpoint(host, tok)
            tg = [(i.get("@id") or i.get("id")) for i in items if is_junk_vocabulary(i)]
            print(f"vocabularies: {len(items)} total, {len(tg)} junk")
            codes = {}
            for ident in tg:
                res = delete_vocabulary(host, tok, vocab_base, ident) if apply else "DRY"
                codes[res] = codes.get(res, 0) + 1
            print(f"  result: {codes}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry-run)")
    ap.add_argument("--assets", action="store_true", help="also delete junk policies+assets")
    ap.add_argument("--agreements", action="store_true", help="also delete stale contract agreements before deleting assets")
    ap.add_argument("--vocabularies", action="store_true", help="also delete junk DAIMO vocabularies")
    ap.add_argument("--split-use-case-models", action="store_true", help="also delete stale mirrored use-case models not owned by the connector tag")
    ap.add_argument("--connectors", default=",".join(HOSTS), help="comma list")
    args = ap.parse_args()
    run(
        [c.strip() for c in args.connectors.split(",") if c.strip()],
        args.apply,
        args.assets,
        args.vocabularies,
        args.split_use_case_models,
        args.agreements,
    )


if __name__ == "__main__":
    main()
