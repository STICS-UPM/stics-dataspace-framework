#!/usr/bin/env python3
"""Reference Python client for the STICS connector Management API.

Covers everything needed to automate publication from an external system:

  * authentication against Keycloak (password grant, automatic token refresh)
  * assets: HttpData, AmazonS3 (direct) and file upload to the STICS Store (InesDataStore)
  * policies and contract definitions
  * verification in the federated catalogue
  * consumer side: catalogue request, contract negotiation, transfer (PULL / PUSH), download

Requires only ``requests``  (pip install requests).

Quick start::

    from stics_connector_client import Connector

    c = Connector("https://stics.bavenir.eu/management", "user-connector-stics", "<password>")
    c.create_http_asset("my-asset", "https://example.org/data.json",
                        name="My asset", description="Demo", keywords=["demo"])
    c.create_allow_all_policy("my-policy", exists_ok=True)
    c.create_contract_definition("my-cd", "my-policy", "my-policy", asset_ids=["my-asset"])

Run this file directly for a small end-to-end demo (see ``main``).
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Union

import requests

EDC_NS = "https://w3id.org/edc/v0.0.1/ns/"
JSONLD_CONTEXT = {
    "@vocab": EDC_NS,
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
}
SIMPLE_CONTEXT = {"@vocab": EDC_NS}
ODRL_CONTEXT = {"@vocab": EDC_NS, "odrl": "http://www.w3.org/ns/odrl/2/"}

UPLOAD_CHUNK_SIZE = 50 * 1024 * 1024  # same chunk size as the connector interface
DSP = "dataspace-protocol-http"


class ConnectorError(Exception):
    """Raised when the connector (or Keycloak) answers with an error status."""

    def __init__(self, status: int, body: Any, method: str = "", url: str = ""):
        self.status, self.body, self.method, self.url = status, body, method, url
        super().__init__(f"{method} {url} -> HTTP {status}: {body}")

    @property
    def messages(self) -> List[str]:
        """Validation messages returned by the connector, if any."""
        if isinstance(self.body, list):
            return [str(m.get("message", m)) for m in self.body if isinstance(m, dict)]
        return [str(self.body)]


class Connector:
    """Client for ONE connector. Create one instance per connector you talk to."""

    def __init__(
        self,
        management_url: str,
        username: str,
        password: str,
        *,
        keycloak_url: str = "https://auth.dev.linkeddata.es",
        realm: str = "stics",
        client_id: str = "dataspace-users",
        verify_tls: Union[bool, str] = True,
        timeout: int = 60,
    ):
        """
        :param management_url: e.g. ``https://stics.bavenir.eu/management`` (no trailing slash)
        :param verify_tls: True, False, or the path of a CA bundle. The Keycloak certificate is
                           issued by an internal CA, so pass the CA bundle or ``False`` if needed.
        """
        self.management_url = management_url.rstrip("/")
        self.base_url = self.management_url[: -len("/management")]
        self._token_url = f"{keycloak_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"
        self._client_id, self._username, self._password = client_id, username, password
        self.verify, self.timeout = verify_tls, timeout
        self._http = requests.Session()
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._expires_at = 0.0

    # ------------------------------------------------------------------ authentication
    def _token_request(self, data: Dict[str, str]) -> Dict[str, Any]:
        r = self._http.post(self._token_url, data=data, verify=self.verify, timeout=self.timeout)
        if r.status_code != 200:
            raise ConnectorError(r.status_code, r.text, "POST", self._token_url)
        return r.json()

    def token(self) -> str:
        """Return a valid access token (tokens last 5 minutes; refreshed automatically)."""
        if self._access_token and time.time() < self._expires_at - 30:
            return self._access_token
        payload = None
        if self._refresh_token:
            try:
                payload = self._token_request({"grant_type": "refresh_token", "client_id": self._client_id,
                                               "refresh_token": self._refresh_token})
            except ConnectorError:
                payload = None
        if payload is None:
            payload = self._token_request({"grant_type": "password", "client_id": self._client_id,
                                           "username": self._username, "password": self._password})
        self._access_token = payload["access_token"]
        self._refresh_token = payload.get("refresh_token")
        self._expires_at = time.time() + int(payload.get("expires_in", 300))
        return self._access_token

    # ------------------------------------------------------------------ low level
    def _call(self, method: str, path: str, *, json_body: Any = None, expected: Iterable[int] = (200, 204),
              ok_statuses: Iterable[int] = (), **kwargs) -> Any:
        url = path if path.startswith("http") else f"{self.management_url}{path}"
        for attempt in (1, 2):
            headers = dict(kwargs.pop("headers", {}) or {})
            headers["Authorization"] = f"Bearer {self.token()}"
            r = self._http.request(method, url, json=json_body, headers=headers, verify=self.verify,
                                   timeout=self.timeout, **kwargs)
            if r.status_code == 401 and attempt == 1:  # token may have just expired: force a refresh
                self._expires_at = 0
                kwargs["headers"] = {k: v for k, v in headers.items() if k != "Authorization"}
                continue
            break
        if r.status_code in tuple(expected) or r.status_code in tuple(ok_statuses):
            if not r.content:
                return None
            try:
                return r.json()
            except ValueError:
                return r.text
        try:
            body = r.json()
        except ValueError:
            body = r.text
        raise ConnectorError(r.status_code, body, method, url)

    @staticmethod
    def _query(offset: int = 0, limit: int = 50, filters: Optional[List[dict]] = None,
               sort_field: Optional[str] = None, sort_order: str = "ASC") -> dict:
        q: Dict[str, Any] = {"@context": SIMPLE_CONTEXT, "offset": offset, "limit": limit,
                             "filterExpression": filters or []}
        if sort_field:
            q.update({"sortField": sort_field, "sortOrder": sort_order})
        return q

    @staticmethod
    def criterion(left: str, operator: str, right: Any) -> dict:
        """Build a filter / selector criterion. ``left`` may be a short property name (``id``, ``name``,
        ``assetType``...); use a full IRI for DCAT / DCTERMS properties, e.g.
        ``http://www.w3.org/ns/dcat#keyword``.

        Verified operators: ``=`` (ids and plain properties), ``in`` (list of asset ids), ``contains`` and
        ``like`` (list-valued properties such as keywords; ``like`` takes ``%value%``).
        """
        if "://" not in left:  # short name -> connector namespace; use a full IRI for DCAT / DCTERMS properties
            left = EDC_NS + left
        return {"@type": "CriterionDto", "operandLeft": left, "operator": operator, "operandRight": right}

    def _paged(self, path: str, filters: Optional[List[dict]] = None, page_size: int = 50) -> Iterator[dict]:
        offset = 0
        while True:
            page = self._call("POST", path, json_body=self._query(offset, page_size, filters)) or []
            yield from page
            if len(page) < page_size:
                return
            offset += page_size

    # ------------------------------------------------------------------ assets
    @staticmethod
    def asset_payload(asset_id: str, data_address: dict, *, name: str, description: str, keywords: List[str],
                      short_description: Optional[str] = None, version: str = "1.0.0",
                      content_type: str = "application/json", asset_type: str = "dataset",
                      extra_properties: Optional[dict] = None) -> dict:
        """Asset body. The connector REQUIRES: ``name``, ``version``, ``assetType``, ``shortDescription``,
        ``dcterms:description`` and ``dcat:keyword`` (HTTP 400 otherwise). ``contenttype`` is optional."""
        props = {
            "name": name, "version": version, "contenttype": content_type, "assetType": asset_type,
            "shortDescription": short_description or description[:200],
            "dcterms:description": description, "dcat:keyword": list(keywords),
        }
        props.update(extra_properties or {})
        return {"@context": JSONLD_CONTEXT, "@id": asset_id, "@type": "Asset", "properties": props,
                "dataAddress": data_address}

    def create_asset(self, payload: dict, *, exists_ok: bool = False) -> Optional[dict]:
        return self._call("POST", "/v3/assets", json_body=payload, ok_statuses=(409,) if exists_ok else ())

    def create_http_asset(self, asset_id: str, base_url: str, *, name: str, description: str, keywords: List[str],
                          method: Optional[str] = None, proxy_path: bool = True, proxy_query_params: bool = False,
                          proxy_body: bool = False, data_content_type: Optional[str] = None,
                          headers: Optional[Dict[str, str]] = None, exists_ok: bool = False, **meta) -> Optional[dict]:
        """Asset whose data is served by an HTTP(S) endpoint (``HttpData``)."""
        da: Dict[str, Any] = {"type": "HttpData", "name": asset_id, "baseUrl": base_url,
                              "proxyPath": str(proxy_path).lower()}
        if method:
            da["method"] = method
        if proxy_query_params:
            da["proxyQueryParams"] = "true"
        if proxy_body:
            da["proxyBody"] = "true"
        if data_content_type:
            da["contentType"] = data_content_type
        for k, v in (headers or {}).items():
            da[f"header:{k}"] = v
        return self.create_asset(self.asset_payload(asset_id, da, name=name, description=description,
                                                    keywords=keywords, **meta), exists_ok=exists_ok)

    def create_s3_asset(self, asset_id: str, bucket: str, key: str, *, access_key_id: str, secret_access_key: str,
                        endpoint_override: str = "https://minio.dev.linkeddata.es", region: str = "eu-central-1",
                        name: str, description: str, keywords: List[str], exists_ok: bool = False,
                        **meta) -> Optional[dict]:
        """Asset pointing at an object that already exists in S3 (``AmazonS3``).

        The connector validator requires all five S3 fields. NOTE: the keys are stored in clear in the
        asset's data address. Prefer :meth:`upload_file_asset` unless the file must stay where it is.
        """
        da = {"type": "AmazonS3", "region": region, "bucketName": bucket, "keyName": key,
              "accessKeyId": access_key_id, "secretAccessKey": secret_access_key,
              "endpointOverride": endpoint_override}
        return self.create_asset(self.asset_payload(asset_id, da, name=name, description=description,
                                                    keywords=keywords, **meta), exists_ok=exists_ok)

    def upload_file_asset(self, asset_id: str, file_path: Union[str, Path], *, name: str, description: str,
                          keywords: List[str], folder: Optional[str] = None, content_type: Optional[str] = None,
                          chunk_size: int = UPLOAD_CHUNK_SIZE, **meta) -> dict:
        """Upload a local file to the connector's own store ("STICS Store") and create the asset.

        Same two-step flow as the connector interface: ``upload-chunk`` (once per chunk) followed by
        ``finalize-upload``. The resulting asset is an ``AmazonS3`` asset without credentials.

        Connector rules: every chunk except the last must be >= 50 MiB, chunks must be sent in order,
        and the file name becomes the S3 key (same name = overwritten). Deleting the asset later does NOT
        delete the stored file.
        """
        if chunk_size < UPLOAD_CHUNK_SIZE:
            raise ValueError("chunk_size must be >= 50 MiB (the connector rejects smaller non-final chunks)")
        path = Path(file_path)
        file_name = path.name
        ctype = content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        da: Dict[str, Any] = {"type": "InesDataStore"}
        if folder:
            da["folder"] = folder
        payload = self.asset_payload(asset_id, da, name=name, description=description, keywords=keywords,
                                     content_type=ctype, **meta)
        body = json.dumps(payload)
        size = path.stat().st_size
        total = max(1, -(-size // chunk_size))
        with path.open("rb") as fh:
            for index in range(total):
                chunk = fh.read(chunk_size)
                self._call(
                    "POST", "/s3assets/upload-chunk",
                    headers={"Content-Disposition": f'attachment; filename="{file_name}"',
                             "Chunk-Index": str(index), "Total-Chunks": str(total)},
                    files={"json": (None, body, "application/json"), "file": (file_name, chunk, ctype)},
                )
        return self._call("POST", "/s3assets/finalize-upload",
                          files={"fileName": (None, file_name), "json": (None, body, "application/json")})

    def get_asset(self, asset_id: str) -> dict:
        return self._call("GET", f"/v3/assets/{asset_id}")

    def list_assets(self, filters: Optional[List[dict]] = None) -> List[dict]:
        return list(self._paged("/v3/assets/request", filters))

    def count_assets(self) -> int:
        return int(self._call("POST", "/pagination/count?type=asset", json_body=self._query()))

    def update_asset(self, payload: dict) -> None:
        """Replace an asset (PUT). Send the complete asset body, same shape as on creation."""
        self._call("PUT", "/v3/assets", json_body=payload)

    def delete_asset(self, asset_id: str, *, missing_ok: bool = True) -> None:
        """Delete an asset. HTTP 409 means it is referenced by a contract agreement (EDC keeps it)."""
        self._call("DELETE", f"/v3/assets/{asset_id}", ok_statuses=(404,) if missing_ok else ())

    # ------------------------------------------------------------------ policies
    def create_policy(self, policy_id: str, *, permissions: Optional[list] = None,
                      prohibitions: Optional[list] = None, obligations: Optional[list] = None,
                      exists_ok: bool = False) -> Optional[dict]:
        body = {"@context": ODRL_CONTEXT, "@id": policy_id,
                "policy": {"@context": "http://www.w3.org/ns/odrl.jsonld", "@type": "Set",
                           "permission": permissions or [], "prohibition": prohibitions or [],
                           "obligation": obligations or []}}
        return self._call("POST", "/v3/policydefinitions", json_body=body, ok_statuses=(409,) if exists_ok else ())

    def create_allow_all_policy(self, policy_id: str, *, exists_ok: bool = False) -> Optional[dict]:
        """Empty ODRL Set: no constraints, everybody may negotiate."""
        return self.create_policy(policy_id, exists_ok=exists_ok)

    def create_always_true_policy(self, policy_id: str, *, exists_ok: bool = False) -> Optional[dict]:
        """Permission ``use`` guarded by the ``ALWAYS_TRUE`` constraint.

        WARNING (verified): usable as a contract definition's *access* policy, but NOT as its *contract*
        policy: consumers' negotiations are TERMINATED. Use :meth:`create_allow_all_policy` for that.
        """
        perm = [{"action": "USE", "constraint": {"leftOperand": "ALWAYS_TRUE", "operator": "eq", "rightOperand": "true"}}]
        return self.create_policy(policy_id, permissions=perm, exists_ok=exists_ok)

    def get_policy(self, policy_id: str) -> dict:
        return self._call("GET", f"/v3/policydefinitions/{policy_id}")

    def list_policies(self) -> List[dict]:
        return list(self._paged("/v3/policydefinitions/request"))

    def delete_policy(self, policy_id: str, *, missing_ok: bool = True) -> None:
        """HTTP 409 means a contract definition or agreement still references the policy."""
        self._call("DELETE", f"/v3/policydefinitions/{policy_id}", ok_statuses=(404,) if missing_ok else ())

    # ------------------------------------------------------------------ contract definitions
    def create_contract_definition(self, cd_id: str, access_policy_id: str, contract_policy_id: str, *,
                                   asset_ids: Optional[List[str]] = None, criteria: Optional[List[dict]] = None,
                                   exists_ok: bool = False) -> Optional[dict]:
        """Expose assets in the catalogue. Pass ``asset_ids`` or free-form ``criteria`` (see :meth:`criterion`).
        Selecting by keyword works with ``=`` or ``contains`` (not ``in``).

        * ``access_policy_id``   - who may SEE the offer in the catalogue
        * ``contract_policy_id`` - the terms the consumer must accept in the negotiation
        """
        selector: List[dict] = list(criteria or [])
        if asset_ids:
            if len(asset_ids) == 1:
                selector.append(self.criterion("id", "=", asset_ids[0]))
            else:
                selector.append(self.criterion("id", "in", list(asset_ids)))
        if not selector:
            raise ValueError("give asset_ids or criteria; an empty selector would expose every asset")
        body = {"@context": SIMPLE_CONTEXT, "@id": cd_id, "accessPolicyId": access_policy_id,
                "contractPolicyId": contract_policy_id, "assetsSelector": selector}
        return self._call("POST", "/v3/contractdefinitions", json_body=body, ok_statuses=(409,) if exists_ok else ())

    def get_contract_definition(self, cd_id: str) -> dict:
        return self._call("GET", f"/v3/contractdefinitions/{cd_id}")

    def list_contract_definitions(self) -> List[dict]:
        return list(self._paged("/v3/contractdefinitions/request"))

    def delete_contract_definition(self, cd_id: str, *, missing_ok: bool = True) -> None:
        self._call("DELETE", f"/v3/contractdefinitions/{cd_id}", ok_statuses=(404,) if missing_ok else ())

    # ------------------------------------------------------------------ catalogue
    @staticmethod
    def _datasets(catalog: dict) -> List[dict]:
        ds = catalog.get("dcat:dataset") or catalog.get("http://www.w3.org/ns/dcat#dataset") or []
        return ds if isinstance(ds, list) else [ds]

    def federated_catalog(self) -> List[dict]:
        """What the connector interface shows in its Catalog page: catalogues of all known participants.

        The federated catalogue is a cache refreshed about every 60 seconds.
        """
        return self._call("POST", "/federatedcatalog/request", json_body=self._query(0, 200)) or []

    def find_in_federated_catalog(self, asset_id: str) -> Optional[dict]:
        for cat in self.federated_catalog():
            for ds in self._datasets(cat):
                if ds.get("@id") == asset_id:
                    return {"participantId": cat.get("https://w3id.org/dspace/v0.8/participantId"), "dataset": ds}
        return None

    def wait_until_in_federated_catalog(self, asset_id: str, timeout: int = 150, poll: int = 10) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            hit = self.find_in_federated_catalog(asset_id)
            if hit:
                return hit
            time.sleep(poll)
        raise TimeoutError(f"{asset_id} did not appear in the federated catalogue within {timeout}s")

    def request_catalog(self, counter_party_dsp: str, counter_party_id: Optional[str] = None,
                        filters: Optional[List[dict]] = None) -> dict:
        """Consumer side: ask another connector's DSP endpoint for its catalogue (DCAT)."""
        body: Dict[str, Any] = {"@context": SIMPLE_CONTEXT, "@type": "CatalogRequest",
                                "counterPartyAddress": counter_party_dsp, "protocol": DSP,
                                "querySpec": {"offset": 0, "limit": 200, "filterExpression": filters or []}}
        if counter_party_id:
            body["counterPartyId"] = counter_party_id
        return self._call("POST", "/v3/catalog/request", json_body=body)

    def find_offer(self, catalog: dict, asset_id: str) -> str:
        """Return the contract offer id of ``asset_id`` in a catalogue returned by :meth:`request_catalog`."""
        for ds in self._datasets(catalog):
            if ds.get("@id") == asset_id:
                offer = ds.get("odrl:hasPolicy") or ds.get("hasPolicy")
                offer = offer[0] if isinstance(offer, list) else offer
                return offer["@id"]
        raise LookupError(f"asset {asset_id} is not in the catalogue (is there a contract definition for it?)")

    # ------------------------------------------------------------------ negotiation & transfer (consumer)
    def negotiate(self, counter_party_dsp: str, provider_id: str, asset_id: str, offer_id: str) -> str:
        body = {"@context": SIMPLE_CONTEXT, "@type": "ContractRequest", "counterPartyAddress": counter_party_dsp,
                "protocol": DSP,
                "policy": {"@context": "http://www.w3.org/ns/odrl.jsonld", "@id": offer_id, "@type": "Offer",
                           "assigner": provider_id, "target": asset_id}}
        return self._call("POST", "/v3/contractnegotiations", json_body=body)["@id"]

    def wait_for_agreement(self, negotiation_id: str, timeout: int = 120, poll: float = 2) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            n = self._call("GET", f"/v3/contractnegotiations/{negotiation_id}")
            if n["state"] == "FINALIZED":
                return n["contractAgreementId"]
            if n["state"] in ("TERMINATED", "TERMINATING"):
                raise RuntimeError(f"negotiation terminated: {n}")
            time.sleep(poll)
        raise TimeoutError("negotiation did not finalize in time")

    def start_transfer(self, counter_party_dsp: str, provider_id: str, agreement_id: str, *,
                       transfer_type: str = "HttpData-PULL", push_destination_url: Optional[str] = None) -> str:
        body: Dict[str, Any] = {"@context": SIMPLE_CONTEXT, "@type": "TransferRequestDto", "connectorId": provider_id,
                                "counterPartyAddress": counter_party_dsp, "contractId": agreement_id,
                                "protocol": DSP, "transferType": transfer_type}
        if transfer_type == "HttpData-PUSH":
            body["dataDestination"] = {"type": "HttpData", "baseUrl": push_destination_url}
        return self._call("POST", "/v3/transferprocesses", json_body=body)["@id"]

    def wait_for_transfer(self, transfer_id: str, until=("STARTED", "COMPLETED"), timeout: int = 120,
                          poll: float = 2) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            t = self._call("GET", f"/v3/transferprocesses/{transfer_id}")
            if t["state"] in until:
                return t["state"]
            if t["state"] == "TERMINATED":
                raise RuntimeError(f"transfer terminated: {t.get('errorDetail')}")
            time.sleep(poll)
        raise TimeoutError("transfer did not reach the expected state in time")

    def get_edr(self, transfer_id: str) -> dict:
        """Endpoint Data Reference of a PULL transfer: ``endpoint`` + ``authorization`` token."""
        return self._call("GET", f"/v3/edrs/{transfer_id}/dataaddress")

    def download(self, edr: dict, **kwargs) -> requests.Response:
        """Fetch the data through the provider's data plane using the EDR."""
        r = self._http.get(edr["endpoint"], headers={"Authorization": edr["authorization"]},
                           verify=self.verify, timeout=self.timeout, **kwargs)
        r.raise_for_status()
        return r

    def pull_asset(self, provider_dsp: str, provider_id: str, asset_id: str) -> requests.Response:
        """Whole consumer flow in one call: catalogue -> negotiation -> PULL transfer -> download."""
        offer = self.find_offer(self.request_catalog(provider_dsp, provider_id), asset_id)
        agreement = self.wait_for_agreement(self.negotiate(provider_dsp, provider_id, asset_id, offer))
        transfer = self.start_transfer(provider_dsp, provider_id, agreement)
        self.wait_for_transfer(transfer)
        return self.download(self.get_edr(transfer))

    # ------------------------------------------------------------------ misc
    def health(self) -> dict:
        r = self._http.get(f"{self.base_url}/api/check/health", verify=self.verify, timeout=self.timeout)
        return {"http": r.status_code, **(r.json() if r.content else {})}


def main() -> int:
    """Small demo: publish an HTTP asset, make it visible, check the catalogue, clean up."""
    url = os.environ.get("CONNECTOR_URL", "https://con-lab.stics.linkeddata.es/management")
    user, password = os.environ["CONNECTOR_USER"], os.environ["CONNECTOR_PASSWORD"]
    verify = os.environ.get("CA_BUNDLE") or (os.environ.get("VERIFY_TLS", "true").lower() != "false")
    c = Connector(url, user, password, verify_tls=verify)

    print("health:", c.health().get("isSystemHealthy"))
    c.create_http_asset("demo-api-asset", "https://jsonplaceholder.typicode.com/todos/1",
                        name="Demo API asset", description="Created by stics_connector_client.py",
                        keywords=["demo", "api"], exists_ok=True)
    c.create_allow_all_policy("demo-api-policy", exists_ok=True)
    c.create_contract_definition("demo-api-cd", "demo-api-policy", "demo-api-policy",
                                 asset_ids=["demo-api-asset"], exists_ok=True)
    print("published; waiting for the federated catalogue (up to ~2.5 min)...")
    print("visible in catalogue:", c.wait_until_in_federated_catalog("demo-api-asset")["participantId"])

    if os.environ.get("KEEP") != "1":
        c.delete_contract_definition("demo-api-cd")
        c.delete_policy("demo-api-policy")
        c.delete_asset("demo-api-asset")
        print("cleaned up")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConnectorError as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
