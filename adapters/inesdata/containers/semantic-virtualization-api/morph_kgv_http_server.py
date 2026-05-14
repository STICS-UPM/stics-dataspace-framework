from __future__ import annotations

import json
import os
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlparse

from morph_kgc import VIRTStore
from rdflib import Graph


DEFAULT_QUERY = "SELECT * WHERE { ?s ?p ?o . } LIMIT 1"
DEFAULT_CONFIG = "/opt/morph-kgv/examples/csv/config.ini"

_GRAPH: Graph | None = None
_CONFIG_DIR: Path | None = None


@contextmanager
def _pushd(path: Path) -> Iterator[None]:
    current = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(current)


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _load_graph() -> Graph:
    global _CONFIG_DIR, _GRAPH

    if _GRAPH is not None:
        return _GRAPH

    config_path = Path(os.environ.get("MORPH_KGV_CONFIG", DEFAULT_CONFIG)).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Morph-KGV config file not found: {config_path}")

    _CONFIG_DIR = config_path.parent
    with _pushd(_CONFIG_DIR):
        store = VIRTStore(config_path.name)
        _GRAPH = Graph(store)
    return _GRAPH


def _run_sparql_query(query: str) -> tuple[bytes, str]:
    graph = _load_graph()
    with _pushd(_CONFIG_DIR or Path.cwd()):
        result = graph.query(query)
    serialized = result.serialize(format="json")
    if isinstance(serialized, str):
        serialized = serialized.encode("utf-8")
    return serialized, "application/sparql-results+json; charset=utf-8"


class MorphKGVRequestHandler(BaseHTTPRequestHandler):
    server_version = "PIONERA-MorphKGV/1.0"

    def log_message(self, _format: str, *_args) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        query = (params.get("query") or [""])[0].strip()

        if parsed.path == "/openapi.json":
            self._send(
                200,
                _json_bytes(
                    {
                        "openapi": "3.0.0",
                        "info": {
                            "title": "PIONERA Morph-KGV Semantic Virtualization API",
                            "version": "1.0.0",
                        },
                        "paths": {
                            "/": {
                                "get": {
                                    "summary": "Health and SPARQL query endpoint",
                                }
                            },
                            "/openapi.json": {
                                "get": {
                                    "summary": "Machine-readable API capabilities",
                                }
                            },
                        },
                    }
                ),
            )
            return

        if not query:
            self._send(
                200,
                _json_bytes(
                    {
                        "service": "semantic-virtualization",
                        "engine": "morph-kgv",
                        "status": "ok",
                        "query_parameter": "query",
                        "default_query": DEFAULT_QUERY,
                    }
                ),
            )
            return

        try:
            body, content_type = _run_sparql_query(query)
        except Exception as exc:
            self._send(
                400,
                _json_bytes(
                    {
                        "status": "error",
                        "engine": "morph-kgv",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                ),
            )
            return

        self._send(200, body, content_type)


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), MorphKGVRequestHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
