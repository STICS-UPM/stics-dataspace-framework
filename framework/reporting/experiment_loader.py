import json
import os

from ..experiment_storage import ExperimentStorage


class ExperimentLoader:
    """Load persisted experiment artifacts."""

    ARTIFACTS = (
        "metadata.json",
        "raw_requests.jsonl",
        "newman_results.json",
        "negotiation_metrics.json",
        "aggregated_metrics.json",
        "test_results.json",
        "summary.json",
        "kafka_metrics.json",
        "ui_validation_summary.json",
    )

    @staticmethod
    def experiment_dir(experiment_id):
        if os.path.isdir(experiment_id):
            return experiment_id
        return os.path.join(ExperimentStorage.experiments_base_dir(), experiment_id)

    @classmethod
    def load(cls, experiment_id):
        experiment_dir = cls.experiment_dir(experiment_id)
        data = {"experiment_dir": experiment_dir}
        for artifact in cls.ARTIFACTS:
            path = os.path.join(experiment_dir, artifact)
            if artifact.endswith(".jsonl"):
                items = []
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                items.append(json.loads(line))
                data[artifact] = items
            else:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        data[artifact] = json.load(f)
                else:
                    data[artifact] = None
        return data
