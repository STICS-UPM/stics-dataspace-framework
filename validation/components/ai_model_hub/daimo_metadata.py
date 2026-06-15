"""DAIMO metadata helpers aligned with the AIModelHub seeding scripts."""

from __future__ import annotations

import json
from typing import Any


MODEL_VOCABULARY_ID = "JS_DAIMO_Model"
DATASET_VOCABULARY_ID = "JS_DAIMO_Dataset"
PIONERA_DAIMO_NAMESPACE = "https://w3id.org/pionera/daimo#"

_MODEL_SUBTASKS = {
    "text-classification",
    "token-classification",
    "question-answering",
    "text-generation",
    "summarization",
    "translation",
    "image-classification",
    "object-detection",
    "image-segmentation",
    "tabular-classification",
    "tabular-regression",
    "time-series-forecasting",
    "speech-recognition",
    "text-to-image",
    "embedding",
    "reranking",
    "other",
}


def normalize_task_type(value: str | None = None) -> str:
    normalized = (value or "").lower()
    if "regression" in normalized:
        return "regression"
    if "generation" in normalized:
        return "generation"
    if "ranking" in normalized:
        return "ranking"
    if "retrieval" in normalized:
        return "retrieval"
    if "forecast" in normalized:
        return "forecasting"
    if "segmentation" in normalized:
        return "segmentation"
    if "detection" in normalized:
        return "detection"
    if "embedding" in normalized:
        return "embedding"
    if "anomaly" in normalized:
        return "anomaly_detection"
    return "classification"


def normalize_task_category(value: str | None = None) -> str:
    normalized = (value or "").lower()
    if "image" in normalized or "vision" in normalized:
        return "Computer vision"
    if "tabular" in normalized or "regression" in normalized:
        return "Tabular"
    if "time" in normalized or "forecast" in normalized:
        return "Time series"
    if "audio" in normalized or "speech" in normalized:
        return "Audio"
    if "multimodal" in normalized:
        return "Multimodal"
    if "event" in normalized:
        return "Predictive event"
    return "Natural Language Processing"


def normalize_model_subtask(value: str | None = None) -> str:
    normalized = (value or "").lower()
    if normalized in _MODEL_SUBTASKS:
        return normalized
    if "token" in normalized or "span" in normalized or "5w1h" in normalized:
        return "token-classification"
    if "regression" in normalized:
        return "tabular-regression"
    if "forecast" in normalized:
        return "time-series-forecasting"
    if "embedding" in normalized:
        return "embedding"
    if "ranking" in normalized or "rerank" in normalized:
        return "reranking"
    return "text-classification"


def _normalize_input_type(value: Any) -> str:
    normalized = str(value or "string").lower()
    if normalized in {"string", "integer", "number", "boolean", "array", "object"}:
        return normalized
    return "string"


def _input_definition(input_features: list[dict[str, Any]] | None = None, input_schema: Any | None = None) -> dict[str, Any]:
    fields = []
    for field in input_features or []:
        if not isinstance(field, dict) or field.get("name") is None:
            continue
        normalized = {
            "name": str(field["name"]),
            "type": _normalize_input_type(field.get("type")),
        }
        if field.get("description") is not None:
            normalized["description"] = str(field["description"])
        if field.get("nullable") is not None:
            normalized["nullable"] = bool(field["nullable"])
        fields.append(normalized)

    definition: dict[str, Any] = {}
    if fields:
        definition["fields"] = fields
    if input_schema is not None:
        definition["jsonSchema"] = json.dumps(input_schema, ensure_ascii=False)
    return definition


def model_asset_data(
    *,
    task: str | None = None,
    task_type: str | None = None,
    task_category: str | None = None,
    subtask: str | None = None,
    subtask_description: str | None = None,
    modality: list[str] | None = None,
    endpoint_behavior: str = "prediction",
    request_shape: str = "single",
    description: str | None = None,
    library_name: str = "Custom",
    language: list[str] | None = None,
    license_name: str = "apache-2.0",
    input_features: list[dict[str, Any]] | None = None,
    input_schema: Any | None = None,
    input_example: Any | None = None,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    seed = task or task_type or subtask
    return {
        MODEL_VOCABULARY_ID: {
            "daimo:modality": modality or ["text"],
            "daimo:taskType": task_type or normalize_task_type(seed),
            "daimo:taskCategory": task_category or normalize_task_category(seed),
            "daimo:subtask": normalize_model_subtask(subtask or task),
            "daimo:subtaskDescription": subtask_description or subtask or task or "AI Model Hub validation model",
            "daimo:endpointBehavior": endpoint_behavior,
            "daimo:requestShape": request_shape,
            "dct:description": description or "AI Model Hub model endpoint exposed as HttpData.",
            "daimo:libraryName": library_name,
            "dct:language": language or ["Spanish"],
            "dct:license": license_name,
            "daimo:inputSchema": _input_definition(input_features, input_schema),
            "daimo:inputExample": json.dumps(input_example or {}, ensure_ascii=False),
            "daimo:metrics": metrics or ["Accuracy", "Precision", "Recall", "F1"],
        }
    }


def dataset_asset_data(
    *,
    task: str | None = None,
    task_type: str | None = None,
    task_category: str | None = None,
    subtask: str | None = None,
    subtask_description: str | None = None,
    modality: list[str] | None = None,
    input_columns: list[str],
    label: str,
    label_type: str = "categorical",
    language: list[str] | None = None,
    license_name: str = "apache-2.0",
    data_format: str = "json",
    keywords: list[str] | None = None,
    dataset_version: str = "1.0.0",
    dataset_role: str = "test",
    protocol: str = "holdout-test-set",
) -> dict[str, Any]:
    seed = task or task_type or subtask
    return {
        DATASET_VOCABULARY_ID: {
            "daimo:modality": modality or ["text"],
            "daimo:taskType": task_type or normalize_task_type(seed),
            "daimo:taskCategory": task_category or normalize_task_category(seed),
            "daimo:subtask": normalize_model_subtask(subtask or task),
            "daimo:subtaskDescription": subtask_description or subtask or task or "AI Model Hub benchmark dataset",
            "daimo:input": input_columns,
            "daimo:label": label,
            "daimo:labelType": label_type,
            "dct:language": language or ["Spanish"],
            "dct:license": license_name,
            "dct:format": data_format,
            "dcat:keyword": keywords or ["benchmark", "validation"],
            "daimo:datasetVersion": dataset_version,
            "daimo:datasetRole": dataset_role,
            "daimo:protocol": protocol,
        }
    }
