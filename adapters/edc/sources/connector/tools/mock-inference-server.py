#!/usr/bin/env python3
import json
import os
from errno import EADDRINUSE
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        try:
            payload = json.loads(body) if body else None
        except json.JSONDecodeError:
            payload = body

        response = {
            "model": "mock-inference-v1",
            "task": "echo",
            "input": payload,
            "result": {"label": "OK", "score": 1.0}
        }
        self._set_headers(200)
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    port = int(os.getenv("PORT", "9000"))
    tries = int(os.getenv("PORT_TRIES", "20"))

    if port == 0:
        server = HTTPServer(("0.0.0.0", 0), Handler)
    else:
        server = None
        last_error = None
        for candidate in range(port, port + tries):
            try:
                server = HTTPServer(("0.0.0.0", candidate), Handler)
                break
            except OSError as err:
                if err.errno == EADDRINUSE:
                    last_error = err
                    continue
                raise

        if server is None:
            raise OSError(
                f"Could not bind any port in range {port}-{port + tries - 1}"
            ) from last_error

    actual_port = server.server_address[1]
    print(f"Mock inference server running on http://localhost:{actual_port}")
    server.serve_forever()
