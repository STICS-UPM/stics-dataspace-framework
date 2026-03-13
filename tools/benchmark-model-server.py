#!/usr/bin/env python3
import json
import math
import os
import re
from errno import EADDRINUSE
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Tuple


TEXT_SCHEMA_ID = "text-v1"
TABULAR_SCHEMA_ID = "tabular-v1"


POSITIVE_WORDS = {
    "good",
    "great",
    "excellent",
    "amazing",
    "love",
    "awesome",
    "happy",
    "fast",
    "best",
    "nice",
    "clean",
    "helpful",
}

NEGATIVE_WORDS = {
    "bad",
    "terrible",
    "awful",
    "hate",
    "slow",
    "worst",
    "broken",
    "sad",
    "poor",
    "buggy",
    "dirty",
    "rude",
}

LINEAR_WEIGHTS = {
    "excellent": 1.2,
    "great": 1.0,
    "fast": 0.8,
    "helpful": 0.7,
    "clean": 0.6,
    "good": 0.5,
    "bad": -0.7,
    "slow": -0.9,
    "rude": -1.1,
    "broken": -1.0,
    "terrible": -1.4,
}


BAYES_LOG_PROBS = {
    "pos": {
        "excellent": -0.30,
        "great": -0.45,
        "good": -0.60,
        "amazing": -0.40,
        "fast": -0.75,
        "helpful": -0.70,
        "clean": -0.80,
    },
    "neg": {
        "bad": -0.45,
        "slow": -0.60,
        "broken": -0.50,
        "rude": -0.70,
        "terrible": -0.35,
        "awful": -0.40,
        "poor": -0.55,
    },
}


VARIANTS = {
    "text-keyword-v1": {"task": "text-classification", "schema": TEXT_SCHEMA_ID, "default_port": 9201},
    "text-bayes-v1": {"task": "text-classification", "schema": TEXT_SCHEMA_ID, "default_port": 9202},
    "text-linear-v1": {"task": "text-classification", "schema": TEXT_SCHEMA_ID, "default_port": 9203},
    "tabular-linear-v1": {"task": "tabular-regression", "schema": TABULAR_SCHEMA_ID, "default_port": 9301},
    "tabular-tree-v1": {"task": "tabular-regression", "schema": TABULAR_SCHEMA_ID, "default_port": 9302},
}


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def normalize_text_input(payload: Dict[str, Any]) -> str:
    if "text" in payload:
        return str(payload["text"])
    if "inputs" in payload:
        raw = payload["inputs"]
        if isinstance(raw, list):
            return " ".join(str(item) for item in raw)
        return str(raw)
    return ""


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[a-zA-Z0-9']+", text)]


def predict_text_keyword(text: str) -> Tuple[str, float, Dict[str, Any]]:
    tokens = tokenize(text)
    pos = sum(1 for token in tokens if token in POSITIVE_WORDS)
    neg = sum(1 for token in tokens if token in NEGATIVE_WORDS)
    raw = (pos - neg) / max(1, len(tokens))
    score = round(sigmoid(raw * 4.0), 4)

    if score >= 0.56:
        label = "POSITIVE"
    elif score <= 0.44:
        label = "NEGATIVE"
    else:
        label = "NEUTRAL"

    details = {"positive_hits": pos, "negative_hits": neg, "token_count": len(tokens)}
    return label, score, details


def predict_text_bayes(text: str) -> Tuple[str, float, Dict[str, Any]]:
    tokens = tokenize(text)
    log_pos = math.log(0.5)
    log_neg = math.log(0.5)

    for token in tokens:
        log_pos += BAYES_LOG_PROBS["pos"].get(token, -1.6)
        log_neg += BAYES_LOG_PROBS["neg"].get(token, -1.6)

    score = round(1.0 / (1.0 + math.exp(log_neg - log_pos)), 4)
    if score >= 0.58:
        label = "POSITIVE"
    elif score <= 0.42:
        label = "NEGATIVE"
    else:
        label = "NEUTRAL"

    details = {
        "log_pos": round(log_pos, 4),
        "log_neg": round(log_neg, 4),
        "token_count": len(tokens),
    }
    return label, score, details


def predict_text_linear(text: str) -> Tuple[str, float, Dict[str, Any]]:
    tokens = tokenize(text)
    weighted_sum = -0.05
    matched = 0
    for token in tokens:
        if token in LINEAR_WEIGHTS:
            weighted_sum += LINEAR_WEIGHTS[token]
            matched += 1

    score = round(sigmoid(weighted_sum), 4)
    if score >= 0.57:
        label = "POSITIVE"
    elif score <= 0.43:
        label = "NEGATIVE"
    else:
        label = "NEUTRAL"

    details = {
        "weighted_sum": round(weighted_sum, 4),
        "matched_tokens": matched,
        "token_count": len(tokens),
    }
    return label, score, details


def normalize_tabular_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    if "features" in payload and isinstance(payload["features"], dict):
        source = payload["features"]
    else:
        source = payload

    return {
        "age": source.get("age"),
        "income": source.get("income"),
        "tenure_months": source.get("tenure_months"),
    }


def read_tabular_features(payload: Dict[str, Any]) -> Tuple[int, float, int]:
    values = normalize_tabular_input(payload)
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise ValueError(f"Missing required tabular fields: {', '.join(missing)}")

    try:
        age = int(values["age"])
        income = float(values["income"])
        tenure = int(values["tenure_months"])
    except (TypeError, ValueError) as error:
        raise ValueError("Tabular fields age, income, tenure_months must be numeric.") from error

    return age, income, tenure


def predict_tabular_linear(age: int, income: float, tenure: int) -> Tuple[float, Dict[str, Any]]:
    prediction = 5000 + (income * 0.12) + (tenure * 85) - (age * 18)
    confidence = 0.79
    return round(prediction, 2), {"confidence": confidence, "formula": "5000 + income*0.12 + tenure*85 - age*18"}


def predict_tabular_tree(age: int, income: float, tenure: int) -> Tuple[float, Dict[str, Any]]:
    base = 6200.0

    if income > 90000:
        base += 4200
    elif income > 60000:
        base += 2600
    else:
        base += 1200

    if tenure > 30:
        base += 1600
    elif tenure < 6:
        base -= 700

    if age < 28:
        base += 500
    elif age > 58:
        base -= 350

    confidence = 0.74
    return round(base, 2), {"confidence": confidence, "tree_version": "v1"}


def predict(variant: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    config = VARIANTS[variant]

    if config["schema"] == TEXT_SCHEMA_ID:
        text = normalize_text_input(payload)
        if not text.strip():
            raise ValueError("Text models require 'text' (or 'inputs') in payload.")

        if variant == "text-keyword-v1":
            label, score, details = predict_text_keyword(text)
        elif variant == "text-bayes-v1":
            label, score, details = predict_text_bayes(text)
        else:
            label, score, details = predict_text_linear(text)

        return {
            "model": variant,
            "task": config["task"],
            "prediction": label,
            "result": {"label": label, "score": score, "details": details},
            "input": payload,
            "meta": {"schema": config["schema"], "version": "1.0.0"},
        }

    age, income, tenure = read_tabular_features(payload)
    if variant == "tabular-linear-v1":
        value, details = predict_tabular_linear(age, income, tenure)
    else:
        value, details = predict_tabular_tree(age, income, tenure)

    return {
        "model": variant,
        "task": config["task"],
        "prediction": value,
        "result": {"value": value, "unit": "score", "details": details},
        "input": payload,
        "meta": {"schema": config["schema"], "version": "1.0.0"},
    }


MODEL_VARIANT = os.getenv("MODEL_VARIANT", "text-keyword-v1").strip()
if MODEL_VARIANT not in VARIANTS:
    raise ValueError(
        f"Unsupported MODEL_VARIANT '{MODEL_VARIANT}'. Allowed: {', '.join(sorted(VARIANTS.keys()))}"
    )


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_GET(self) -> None:
        if self.path == "/health":
            config = VARIANTS[MODEL_VARIANT]
            self._json(
                200,
                {
                    "status": "ok",
                    "model": MODEL_VARIANT,
                    "task": config["task"],
                    "schema": config["schema"],
                },
            )
            return

        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/infer":
            self._json(404, {"error": "not_found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""

        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid_json"})
            return

        if not isinstance(payload, dict):
            self._json(400, {"error": "payload_must_be_object"})
            return

        try:
            response = predict(MODEL_VARIANT, payload)
        except ValueError as error:
            self._json(400, {"error": str(error)})
            return
        except Exception as error:  # pragma: no cover
            self._json(500, {"error": f"inference_error: {error}"})
            return

        self._json(200, response)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


if __name__ == "__main__":
    default_port = VARIANTS[MODEL_VARIANT]["default_port"]
    start_port = int(os.getenv("PORT", str(default_port)))
    tries = int(os.getenv("PORT_TRIES", "20"))

    server = None
    last_error = None
    for candidate in range(start_port, start_port + tries):
        try:
            server = HTTPServer(("0.0.0.0", candidate), Handler)
            break
        except OSError as error:
            if error.errno == EADDRINUSE:
                last_error = error
                continue
            raise

    if server is None:
        raise OSError(
            f"Could not bind any port in range {start_port}-{start_port + tries - 1}"
        ) from last_error

    actual_port = server.server_address[1]
    config = VARIANTS[MODEL_VARIANT]

    print(f"Benchmark model server running on http://localhost:{actual_port}")
    print(f"Variant: {MODEL_VARIANT}")
    print(f"Task: {config['task']}")
    print(f"Schema group: {config['schema']}")
    print("Endpoints: GET /health, POST /infer")
    server.serve_forever()
