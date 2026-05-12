from .reporting.report_generator import ExperimentReportGenerator


class ExperimentSummaryBuilder:
    """Compatibility wrapper over the experiment report generator."""

    def __init__(self, storage=None, report_generator=None):
        self.storage = storage
        self.report_generator = report_generator or ExperimentReportGenerator(storage=storage)

    def build_summary(self, experiment_dir, adapter=None, iterations=1, kafka_enabled=False, timestamp=None):
        return self.report_generator.build_summary(
            experiment_dir,
            adapter=adapter,
            iterations=iterations,
            kafka_enabled=kafka_enabled,
            timestamp=timestamp,
        )

    @staticmethod
    def build_markdown(summary):
        return ExperimentReportGenerator.build_markdown(summary)

    def describe(self) -> str:
        return "ExperimentSummaryBuilder creates JSON and Markdown experiment summaries."
