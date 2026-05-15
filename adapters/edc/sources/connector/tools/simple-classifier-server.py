#!/usr/bin/env python3
import json
import os
from errno import EADDRINUSE
from http.server import BaseHTTPRequestHandler, HTTPServer


POSITIVE_WORDS = {
    "good", "great", "excellent", "amazing", "love", "awesome", "happy", "fast", "best", "nice"
}
NEGATIVE_WORDS = {
    "bad", "terrible", "awful", "hate", "slow", "worst", "broken", "sad", "poor", "buggy"
}


def classify_text(text: str) -> dict:
    tokens = [token.strip(".,!?;:()[]{}\"'").lower() for token in text.split()]
    positive = sum(1 for token in tokens if token in POSITIVE_WORDS)
    negative = sum(1 for token in tokens if token in NEGATIVE_WORDS)

    if positive > negative:
        return {"label": "POSITIVE", "score": round(positive / max(1, positive + negative), 3)}
    if negative > positive:
        return {"label": "NEGATIVE", "score": round(negative / max(1, positive + negative), 3)}
    return {"label": "NEUTRAL", "score": 0.5}


class Handler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
            return
        self._set_headers(404)
        self.wfile.write(json.dumps({"error": "not_found"}).encode("utf-8"))

    def do_POST(self):
        if self.path != "/infer":
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "not_found"}).encode("utf-8"))
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._set_headers(400)
            self.wfile.write(json.dumps({"error": "invalid_json"}).encode("utf-8"))
            return

        raw_input = payload.get("inputs", "")
        if isinstance(raw_input, list):
            text = " ".join(str(item) for item in raw_input)
        else:
            text = str(raw_input)

        result = classify_text(text)
        response = {
            "model": "simple-text-classifier-v1",
            "task": "text-classification",
            "input": payload,
            "result": result
        }
        self._set_headers(200)
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    port = int(os.getenv("PORT", "9100"))
    tries = int(os.getenv("PORT_TRIES", "20"))

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
    print(f"Simple classifier server running on http://localhost:{actual_port}")
    print("Inference endpoint: POST /infer")
    server.serve_forever()

