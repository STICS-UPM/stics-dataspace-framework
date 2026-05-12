from .metrics.graphs import MetricsGraphGenerator


class GraphBuilder:
    """Compatibility wrapper over the experiment graph generator."""

    def __init__(self, storage=None, graph_generator=None):
        self.storage = storage
        self.graph_generator = graph_generator or MetricsGraphGenerator()

    @staticmethod
    def _load_plot_backend():
        return MetricsGraphGenerator._load_plot_backend()

    @staticmethod
    def _load_pandas():
        return MetricsGraphGenerator._load_pandas()

    def build(self, experiment_dir):
        self.graph_generator._load_plot_backend = self._load_plot_backend
        self.graph_generator._load_pandas = self._load_pandas
        return self.graph_generator.generate(experiment_dir)

    def describe(self) -> str:
        return "GraphBuilder generates experiment graphs from stored artifacts."
