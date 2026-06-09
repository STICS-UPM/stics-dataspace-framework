import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { lastValueFrom } from 'rxjs';
import {
  AiModelBenchmarkModelType,
  AiModelExecutionInputFeature,
  AiModelExecutionItem,
  AiModelMetricDirection,
  AiModelRequestShape,
  ModelExecutionResponsePayload
} from 'src/app/shared/models/ai-model-execution-item';
import {
  BenchmarkDatasetAsset,
  BenchmarkDatasetMapping
} from 'src/app/shared/models/benchmark-dataset-asset';
import { BenchmarkDatasetService } from 'src/app/shared/services/benchmark-dataset.service';
import { ModelExecutionService } from 'src/app/shared/services/model-execution.service';
import { ModelObserverJournalService } from 'src/app/shared/services/model-observer-journal.service';
import { NotificationService } from 'src/app/shared/services/notification.service';

type ModelTask = 'classification' | 'regression' | 'unsupported';
type RankingSortDirection = 'asc' | 'desc';

interface RankingSortState {
  key: string;
  direction: RankingSortDirection;
}

interface BenchmarkAsset {
  id: string;
  name: string;
  task: string;
  subtask: string;
  algorithm: string;
  framework: string;
  source: string;
  provider: string;
  hasAgreement: boolean;
  isLocal: boolean;
  inputFeatures: AiModelExecutionInputFeature[];
  inputColumns: string[];
  inputSchema: any;
  inputExample?: any;
  requestShape: AiModelRequestShape;
  benchmarkModelType: AiModelBenchmarkModelType;
  targetFields: string[];
  predictionFields: string[];
  supportedMetrics: string[];
  metricDirections: Record<string, AiModelMetricDirection>;
}

interface SchemaField {
  name: string;
  type: string;
  required: boolean;
  min?: number;
  max?: number;
  description?: string;
}

interface RankingRow {
  rank: number;
  modelId: string;
  modelName: string;
  metrics: Record<string, number>;
  latency: number;
  successCount: number;
  compositeScore?: number;
  top?: boolean;
  errorMessage?: string;
}

interface RowTestResult {
  modelId: string;
  modelName: string;
  modelType: AiModelBenchmarkModelType;
  status: 'success' | 'partial' | 'error';
  latencyMs: number;
  rowsTested: number;
  successfulRows: number;
  failedRows: number;
  outputPreview: string;
  errorMessage?: string;
}

@Component({
  selector: 'app-ai-model-benchmarking',
  templateUrl: './ai-model-benchmarking.component.html',
  styleUrls: ['./ai-model-benchmarking.component.scss']
})
export class AiModelBenchmarkingComponent implements OnInit {

  // Execution state
  isRunning = false;
  isTestingRows = false;
  statusMessage = 'Select models and configure benchmark settings to begin.';
  rowTestStatusMessage = 'Load a dataset, then test a few rows before running the full benchmark.';
  progress = 0;

  // Model pool
  modelPoolAssets: BenchmarkAsset[] = [];
  filteredModelPoolAssets: BenchmarkAsset[] = [];
  selectedAssetIds: string[] = [];
  isLoadingAssets = false;
  assetsError = '';

  // Search and filters
  searchKeyword = '';
  activeFilter: string = 'all';

  // Task detection
  detectedTask: ModelTask | null = null;
  availableMetrics: string[] = [];
  selectedMetrics: string[] = [];

  // Validation dataset
  validationDatasetFileName = '';
  validationDatasetRows: any[] = [];
  benchmarkDatasetAssets: BenchmarkDatasetAsset[] = [];
  selectedBenchmarkDatasetId = '';
  benchmarkDatasetSearch = '';
  benchmarkInputColumnsText = '';
  benchmarkLabelColumnText = '';
  isLoadingBenchmarkDatasets = false;
  isLoadingSelectedBenchmarkDataset = false;
  benchmarkDatasetError = '';

  // Row test
  rowTestSampleSize = 3;
  rowTestSampleSizes = [1, 3, 5, 10];
  rowTestResults: RowTestResult[] = [];

  // Ranking
  rankingRows: RankingRow[] = [];
  rankingSort: RankingSortState = { key: 'score', direction: 'desc' };
  recommendationMetric = '';
  lastBenchmarkRunId = '';

  // Benchmark tuning
  private readonly benchmarkBatchSize = 300;
  private readonly batchRequestBenchmarkBatchSize = 64;
  private readonly benchmarkRequestTimeoutMs = 10000;
  private readonly batchRequestBenchmarkRequestTimeoutMs = 45000;
  validationDatasetSource: 'manual' | 'dataspace' | null = null;
  private validationDatasetMapping: BenchmarkDatasetMapping | null = null;

  private readonly metricsConfig: Record<ModelTask, string[]> = {
    classification: ['Accuracy', 'Precision', 'Recall', 'F1 Score'],
    regression: ['RMSE', 'MAE', 'MSE', 'R2'],
    unsupported: []
  };
  private readonly lowerIsBetterMetrics = ['RMSE', 'MAE', 'MSE'];

  constructor(
    private readonly benchmarkDatasetService: BenchmarkDatasetService,
    private readonly modelExecutionService: ModelExecutionService,
    private readonly modelObserverJournalService: ModelObserverJournalService,
    private readonly notificationService: NotificationService,
    private readonly router: Router
  ) {}

  ngOnInit(): void {
    this.loadModels();
    this.loadBenchmarkDatasets();
  }

  get selectedCount(): number {
    return this.selectedAssetIds.length;
  }

  get canRunBenchmark(): boolean {
    return this.selectedAssetIds.length >= 2
      && this.selectedMetrics.length > 0
      && this.validationDatasetRows.length > 0
      && !this.isRunning
      && !this.isTestingRows;
  }

  get observerAssetId(): string {
    return this.rankingRows[0]?.modelId || this.selectedAssetIds[0] || '';
  }

  get canTestRows(): boolean {
    return this.selectedAssetIds.length > 0
      && this.selectedMetrics.length > 0
      && this.validationDatasetRows.length > 0
      && !this.isRunning
      && !this.isTestingRows
      && !this.isLoadingSelectedBenchmarkDataset;
  }

  get filteredBenchmarkDatasetAssets(): BenchmarkDatasetAsset[] {
    const keyword = this.benchmarkDatasetSearch.trim().toLowerCase();
    if (!keyword) {
      return this.benchmarkDatasetAssets;
    }

    return this.benchmarkDatasetAssets.filter(asset =>
      asset.name.toLowerCase().includes(keyword)
      || asset.description.toLowerCase().includes(keyword)
      || asset.provider.toLowerCase().includes(keyword)
      || asset.tags.some(tag => tag.toLowerCase().includes(keyword))
      || asset.format.toLowerCase().includes(keyword)
      || asset.contentType.toLowerCase().includes(keyword)
    );
  }

  get selectedBenchmarkDataset(): BenchmarkDatasetAsset | undefined {
    return this.benchmarkDatasetAssets.find(asset => asset.id === this.selectedBenchmarkDatasetId);
  }

  get canLoadSelectedBenchmarkDataset(): boolean {
    return this.selectedAssetIds.length > 0
      && !!this.selectedBenchmarkDataset
      && !this.isRunning
      && !this.isTestingRows
      && !this.isLoadingSelectedBenchmarkDataset;
  }

  // ---------------------------------------------------------------------------
  // Model pool loading
  // ---------------------------------------------------------------------------

  private loadModels(): void {
    this.isLoadingAssets = true;
    this.assetsError = '';

    this.modelExecutionService.getBenchmarkModels().subscribe({
      next: models => {
        this.modelPoolAssets = models.map(m => this.mapToBenchmarkAsset(m));
        this.filteredModelPoolAssets = [...this.modelPoolAssets];
        this.isLoadingAssets = false;
      },
      error: () => {
        this.assetsError = 'Failed to load models from the connector.';
        this.isLoadingAssets = false;
      }
    });
  }

  loadBenchmarkDatasets(): void {
    this.isLoadingBenchmarkDatasets = true;
    this.benchmarkDatasetError = '';

    this.benchmarkDatasetService.getBenchmarkDatasets().subscribe({
      next: datasets => {
        this.benchmarkDatasetAssets = datasets;
        if (this.selectedBenchmarkDatasetId && !datasets.some(dataset => dataset.id === this.selectedBenchmarkDatasetId)) {
          this.selectedBenchmarkDatasetId = '';
          this.benchmarkInputColumnsText = '';
          this.benchmarkLabelColumnText = '';
        } else if (this.selectedBenchmarkDatasetId) {
          this.populateBenchmarkMappingFieldsFromMetadata();
        }
        this.isLoadingBenchmarkDatasets = false;
      },
      error: () => {
        this.benchmarkDatasetError = 'Failed to load benchmark datasets from the connector.';
        this.benchmarkDatasetAssets = [];
        this.selectedBenchmarkDatasetId = '';
        this.isLoadingBenchmarkDatasets = false;
      }
    });
  }

  private mapToBenchmarkAsset(item: AiModelExecutionItem): BenchmarkAsset {
    return {
      id: item.id,
      name: item.name,
      task: item.tasks?.[0] || 'Unknown',
      subtask: item.subtasks?.[0] || '',
      algorithm: item.algorithms?.[0] || '',
      framework: item.frameworks?.[0] || '',
      source: item.source,
      provider: item.provider,
      hasAgreement: item.hasAgreement,
      isLocal: item.isLocal,
      inputFeatures: item.inputFeatures || [],
      inputColumns: item.inputColumns || [],
      inputSchema: item.inputSchema,
      inputExample: item.inputExample,
      requestShape: item.requestShape || 'single',
      benchmarkModelType: item.benchmarkModelType || 'output',
      targetFields: item.targetFields || [],
      predictionFields: item.predictionFields || [],
      supportedMetrics: item.supportedMetrics || [],
      metricDirections: item.metricDirections || {}
    };
  }

  // ---------------------------------------------------------------------------
  // Search & filters
  // ---------------------------------------------------------------------------

  filterModelPool(): void {
    let pool = [...this.modelPoolAssets];

    const anchorModel = this.getSelectionAnchorModel();
    if (anchorModel) {
      pool = pool.filter(model => this.isSchemaCompatible(anchorModel, model));
    }

    if (this.activeFilter !== 'all') {
      pool = pool.filter(model => model.task === this.activeFilter);
    }

    if (this.searchKeyword.trim()) {
      const keyword = this.searchKeyword.trim().toLowerCase();
      pool = pool.filter(m =>
        m.name.toLowerCase().includes(keyword)
        || m.task.toLowerCase().includes(keyword)
        || m.subtask.toLowerCase().includes(keyword)
        || m.algorithm.toLowerCase().includes(keyword)
        || m.framework.toLowerCase().includes(keyword)
      );
    }

    this.filteredModelPoolAssets = this.orderModelPool(pool);
  }

  clearSearch(): void {
    this.searchKeyword = '';
    this.filterModelPool();
  }

  setFilter(filter: string): void {
    this.activeFilter = filter;
    this.filterModelPool();
  }

  getTaskFilters(): string[] {
    return this.uniqueStrings(this.modelPoolAssets.map(model => model.task))
      .filter(task => task.toLowerCase() !== 'unknown')
      .sort((left, right) => left.localeCompare(right));
  }

  // ---------------------------------------------------------------------------
  // Model selection
  // ---------------------------------------------------------------------------

  isAssetSelected(asset: BenchmarkAsset): boolean {
    return this.selectedAssetIds.includes(asset.id);
  }

  canSelectAsset(asset: BenchmarkAsset): boolean {
    if (this.isAssetSelected(asset)) {
      return true;
    }

    return (asset.isLocal || asset.hasAgreement) && this.isCompatibleWithCurrentSelection(asset);
  }

  toggleAssetSelection(asset: BenchmarkAsset): void {
    if (this.isRunning || this.isTestingRows) {
      return;
    }

    if (!asset.isLocal && !asset.hasAgreement) {
      this.notificationService.showWarning('This federated model is visible in the pool, but it needs a finalized agreement before benchmarking.');
      return;
    }

    if (!this.isAssetSelected(asset) && !this.isCompatibleWithCurrentSelection(asset)) {
      const anchorModel = this.getSelectionAnchorModel();
      const anchorName = anchorModel?.name || 'the first selected model';
      this.notificationService.showWarning(`This model is not comparable with ${anchorName}. Select models with the same metadata-defined input schema.`);
      return;
    }

    const index = this.selectedAssetIds.indexOf(asset.id);
    const isFirstSelection = index < 0 && this.selectedAssetIds.length === 0;
    if (index >= 0) {
      this.selectedAssetIds.splice(index, 1);
    } else {
      this.selectedAssetIds.push(asset.id);
      if (isFirstSelection) {
        this.activeFilter = 'all';
        this.searchKeyword = '';
      }
    }
    this.updateTaskAndMetrics();
  }

  private updateTaskAndMetrics(): void {
    const selectedModels = this.modelPoolAssets.filter(m => this.selectedAssetIds.includes(m.id));

    if (selectedModels.length === 0) {
      this.detectedTask = null;
      this.availableMetrics = [];
      this.selectedMetrics = [];
      this.rowTestResults = [];
      this.filterModelPool();
      return;
    }

    this.detectedTask = this.detectModelTask(selectedModels);
    this.availableMetrics = this.getAvailableMetricsForSelection(selectedModels);
    this.selectedMetrics = [...this.availableMetrics];
    this.recommendationMetric = this.getDefaultRecommendationMetric(this.selectedMetrics, this.detectedTask);
    this.resetRankingSort();
    this.rowTestResults = [];

    if (this.validationDatasetRows.length > 0) {
      this.revalidateLoadedValidationDataset(selectedModels);
    }

    this.filterModelPool();
  }

  private inferModelTask(model: BenchmarkAsset): ModelTask {
    const task = `${model.task} ${model.subtask}`.toLowerCase();
    const algorithm = model.algorithm.toLowerCase();

    if (task.includes('regress') || algorithm.includes('regress')) return 'regression';
    if (task.includes('classif') || algorithm.includes('classif')) return 'classification';
    if (task.includes('binary') || task.includes('multiclass') || task.includes('multi-class') || task.includes('multi class')) return 'classification';

    return 'unsupported';
  }

  private detectModelTask(models: BenchmarkAsset[]): ModelTask {
    const tasks = models.map(m => this.inferModelTask(m));
    const uniqueTasks = [...new Set(tasks)];

    return uniqueTasks.length === 1 ? uniqueTasks[0] : 'unsupported';
  }

  private getAvailableMetricsForSelection(models: BenchmarkAsset[]): string[] {
    if (models.length > 0 && models.every(model => this.isMetricBenchmarkModel(model))) {
      return this.getMetadataMetricsForSelection(models);
    }

    const task = this.detectedTask || this.detectModelTask(models);
    return this.metricsConfig[task] || [];
  }

  private getMetadataMetricsForSelection(models: BenchmarkAsset[]): string[] {
    const declaredMetrics = models
      .map(model => this.uniqueStrings(model.supportedMetrics))
      .filter(metrics => metrics.length > 0);
    if (declaredMetrics.length === 0) {
      return [];
    }

    const [firstMetrics, ...remainingMetrics] = declaredMetrics;
    const commonMetrics = firstMetrics.filter(metric =>
      remainingMetrics.every(metrics => metrics.some(candidate => this.normalizeMetricName(candidate) === this.normalizeMetricName(metric)))
    );

    return commonMetrics.length > 0
      ? commonMetrics
      : this.uniqueStrings(declaredMetrics.reduce<string[]>((allMetrics, metrics) => allMetrics.concat(metrics), []));
  }

  private getDefaultRecommendationMetric(metrics: string[], task: ModelTask | null): string {
    const preferencesByTask: Record<ModelTask, string[]> = {
      classification: ['Accuracy', 'F1 Score', 'Precision', 'Recall'],
      regression: ['RMSE', 'MAE', 'MSE', 'R2'],
      unsupported: []
    };
    const preferences = preferencesByTask[task || 'unsupported'];
    return preferences.find(metric => metrics.includes(metric)) || metrics[0] || '';
  }

  // ---------------------------------------------------------------------------
  // Metrics
  // ---------------------------------------------------------------------------

  toggleMetricSelection(metric: string): void {
    if (this.selectedMetrics.includes(metric)) {
      this.selectedMetrics = this.selectedMetrics.filter(m => m !== metric);
    } else {
      this.selectedMetrics = [...this.selectedMetrics, metric];
    }
    if (this.selectedMetrics.length === 0) {
      this.recommendationMetric = '';
    } else if (!this.selectedMetrics.includes(this.recommendationMetric)) {
      this.recommendationMetric = this.getDefaultRecommendationMetric(this.selectedMetrics, this.detectedTask);
    }
    if (this.isMetricSortKey(this.rankingSort.key) && !this.selectedMetrics.includes(this.extractMetricSortName(this.rankingSort.key))) {
      this.resetRankingSort();
      this.applyRankingSort();
    }
  }

  getAssetMeta(asset: BenchmarkAsset): string {
    const parts = [asset.task, asset.subtask, asset.algorithm, asset.provider].filter(Boolean);
    return parts.length > 0 ? parts.join(' · ') : 'HTTP Model';
  }

  getModelPoolSubtitle(): string {
    const anchorModel = this.getSelectionAnchorModel();
    if (!anchorModel) {
      return 'Select 2+ HTTP models with compatible metadata-defined inputs';
    }

    return `Compatible input models for ${anchorModel.name}`;
  }

  getValidationDatasetSubtitle(): string {
    const anchorModel = this.getSelectionAnchorModel();
    if (!anchorModel) {
      return 'Select models, then load an agreed dataspace dataset or upload a benchmark file';
    }

    return `Load one dataset for ${anchorModel.name}, then test sample rows before running the full benchmark.`;
  }

  getLoadedDatasetColumns(): string[] {
    const columns = this.validationDatasetRows.slice(0, 10).reduce<Set<string>>((set, row) => {
      if (row && typeof row === 'object' && !Array.isArray(row)) {
        Object.keys(row).forEach(key => set.add(key));
      }
      return set;
    }, new Set<string>());

    return Array.from(columns);
  }

  getDatasetPreviewRows(): any[] {
    return this.validationDatasetRows.slice(0, 3);
  }

  formatDatasetPreviewValue(value: any): string {
    if (value === undefined || value === null) {
      return '';
    }

    const text = typeof value === 'object' ? JSON.stringify(value) : String(value);
    return text.length <= 80 ? text : `${text.slice(0, 80)}...`;
  }

  getEffectiveRowTestSampleSize(): number {
    const requestedSize = Number(this.rowTestSampleSize);
    const safeSize = Number.isFinite(requestedSize) ? Math.max(1, Math.trunc(requestedSize)) : 3;
    return Math.min(safeSize, Math.max(this.validationDatasetRows.length, 1));
  }

  formatBenchmarkModelType(type: AiModelBenchmarkModelType): string {
    return type === 'metric' ? 'Metric' : 'Output';
  }

  // ---------------------------------------------------------------------------
  // File handling
  // ---------------------------------------------------------------------------

  async handleValidationDatasetSelection(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    if (this.selectedAssetIds.length === 0) {
      this.notificationService.showWarning('Select at least one model before uploading a validation dataset');
      input.value = '';
      return;
    }

    const selectedModels = this.modelPoolAssets.filter(m => this.selectedAssetIds.includes(m.id));
    try {
      const content = await this.readFileAsText(file);
      const parsedRows = this.parseBatchInputFile(file.name, content);
      if (parsedRows.length === 0) {
        throw new Error('The validation dataset contains no rows.');
      }

      const mapping = this.resolveBenchmarkDatasetMapping(null);
      const validationErrors = this.validateValidationDatasetRows(parsedRows, selectedModels, mapping);
      if (validationErrors.length > 0) {
        this.notificationService.showError(`Validation dataset invalid: ${validationErrors[0]}`);
        this.statusMessage = `Validation dataset invalid: ${validationErrors[0]}`;
        input.value = '';
        return;
      }

      this.validationDatasetRows = parsedRows;
      this.validationDatasetFileName = file.name;
      this.validationDatasetSource = 'manual';
      this.validationDatasetMapping = mapping;
      this.rowTestResults = [];
      this.rowTestStatusMessage = `Dataset loaded. Test ${this.getEffectiveRowTestSampleSize()} row(s) before running the full benchmark.`;
      this.statusMessage = `Validation dataset loaded and validated (${parsedRows.length} rows).`;
      this.notificationService.showInfo(`Validation dataset valid (${parsedRows.length} rows)`);
    } catch (error: any) {
      this.validationDatasetRows = [];
      this.validationDatasetFileName = '';
      this.validationDatasetSource = null;
      this.validationDatasetMapping = null;
      this.rowTestResults = [];
      this.notificationService.showError(error?.message || 'Could not load validation dataset');
      this.statusMessage = 'Could not load validation dataset.';
      input.value = '';
    }
  }

  clearBenchmarkDatasetSearch(): void {
    this.benchmarkDatasetSearch = '';
  }

  selectBenchmarkDataset(assetId: string): void {
    this.selectedBenchmarkDatasetId = assetId;
    this.populateBenchmarkMappingFieldsFromMetadata();
  }

  getBenchmarkInputColumnsPlaceholder(): string {
    const mapping = this.getSelectedBenchmarkDatasetMetadataMapping();
    return mapping?.input.length ? mapping.input.join(', ') : 'column_a, column_b';
  }

  getBenchmarkLabelColumnPlaceholder(): string {
    const mapping = this.getSelectedBenchmarkDatasetMetadataMapping();
    return mapping?.label || 'label';
  }

  getBenchmarkDatasetMappingSummary(): string {
    const mapping = this.getSelectedBenchmarkDatasetMetadataMapping();
    if (!mapping || (mapping.input.length === 0 && !mapping.label)) {
      return 'No mapping metadata found.';
    }

    const input = mapping.input.length > 0 ? mapping.input.join(', ') : '-';
    return `Metadata input: ${input} · label: ${mapping.label || '-'}`;
  }

  datasetAssetMeta(asset: BenchmarkDatasetAsset): string {
    const parts = [
      asset.source === 'own' ? 'Local' : 'Federated',
      asset.provider,
      asset.format || asset.contentType || asset.storageType
    ].filter(Boolean);
    return parts.join(' · ');
  }

  private getSelectedBenchmarkDatasetMetadataMapping(): BenchmarkDatasetMapping | null {
    const dataset = this.selectedBenchmarkDataset;
    return dataset ? this.benchmarkDatasetService.extractDatasetMapping(dataset) : null;
  }

  private populateBenchmarkMappingFieldsFromMetadata(): void {
    const mapping = this.getSelectedBenchmarkDatasetMetadataMapping();
    this.benchmarkInputColumnsText = mapping?.input.length ? mapping.input.join(', ') : '';
    this.benchmarkLabelColumnText = mapping?.label || '';
  }

  private resolveBenchmarkDatasetMapping(metadataMapping: BenchmarkDatasetMapping | null): BenchmarkDatasetMapping | null {
    const inputOverride = this.parseBenchmarkInputColumns(this.benchmarkInputColumnsText);
    const labelOverride = this.benchmarkLabelColumnText.trim();
    const input = inputOverride.length > 0 ? inputOverride : (metadataMapping?.input || []);
    const label = labelOverride || metadataMapping?.label || '';

    return input.length > 0 || label ? { input, label } : null;
  }

  private parseBenchmarkInputColumns(value: string): string[] {
    return Array.from(new Set(
      value
        .split(/[,\n;]+/)
        .map(column => column.trim())
        .filter(column => column.length > 0)
    ));
  }

  private getActiveValidationDatasetMapping(): BenchmarkDatasetMapping | null {
    const metadataMapping = this.validationDatasetSource === 'dataspace'
      ? this.getSelectedBenchmarkDatasetMetadataMapping()
      : null;
    return this.resolveBenchmarkDatasetMapping(metadataMapping);
  }

  async loadSelectedBenchmarkDataset(): Promise<void> {
    const dataset = this.selectedBenchmarkDataset;
    if (!dataset) {
      this.notificationService.showWarning('Select a benchmark dataset first');
      return;
    }

    if (this.selectedAssetIds.length === 0) {
      this.notificationService.showWarning('Select at least one model before loading a benchmark dataset');
      return;
    }

    this.isLoadingSelectedBenchmarkDataset = true;
    try {
      const selectedModels = this.modelPoolAssets.filter(model => this.selectedAssetIds.includes(model.id));
      const fileName = this.benchmarkDatasetService.resolveDatasetFileName(dataset);
      this.statusMessage = dataset.isLocal
        ? `Loading dataspace validation dataset "${dataset.name}"...`
        : `Starting transfer for external validation dataset "${dataset.name}"...`;
      const payload = await this.benchmarkDatasetService.loadDatasetPayload(dataset);
      const parsedRows = this.parseBenchmarkDatasetPayload(fileName, payload);
      const mapping = this.resolveBenchmarkDatasetMapping(this.benchmarkDatasetService.extractDatasetMapping(dataset));
      const requiresColumnMapping = selectedModels.some(model => !this.isMetricBenchmarkModel(model));
      if (requiresColumnMapping && (!mapping || mapping.input.length === 0 || !mapping.label)) {
        throw new Error('Benchmark dataset metadata must define daimo:input column names and a daimo:label column.');
      }
      const normalizedRows = this.normalizeBenchmarkDatasetRows(parsedRows);
      if (normalizedRows.length === 0) {
        throw new Error('The benchmark dataset contains no rows.');
      }

      const validationErrors = this.validateValidationDatasetRows(normalizedRows, selectedModels, mapping);
      if (validationErrors.length > 0) {
        throw new Error(`Validation dataset invalid: ${validationErrors[0]}`);
      }

      this.validationDatasetRows = normalizedRows;
      this.validationDatasetFileName = fileName;
      this.validationDatasetSource = 'dataspace';
      this.validationDatasetMapping = mapping;
      this.rowTestResults = [];
      this.rowTestStatusMessage = `Dataset loaded. Test ${this.getEffectiveRowTestSampleSize()} row(s) before running the full benchmark.`;
      this.statusMessage = `Dataspace validation dataset loaded and validated (${normalizedRows.length} rows).`;
      this.notificationService.showInfo(`Benchmark dataset loaded (${normalizedRows.length} rows)`);
    } catch (error: any) {
      this.notificationService.showError(error?.message || 'Could not load benchmark dataset');
      this.statusMessage = 'Could not load benchmark dataset.';
    } finally {
      this.isLoadingSelectedBenchmarkDataset = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Model compatibility
  // ---------------------------------------------------------------------------

  private getSelectionAnchorModel(): BenchmarkAsset | null {
    const anchorId = this.selectedAssetIds[0];
    if (!anchorId) {
      return null;
    }

    return this.modelPoolAssets.find(asset => asset.id === anchorId) || null;
  }

  private isCompatibleWithCurrentSelection(asset: BenchmarkAsset): boolean {
    const anchorModel = this.getSelectionAnchorModel();
    if (!anchorModel || anchorModel.id === asset.id) {
      return true;
    }

    return this.isSchemaCompatible(anchorModel, asset);
  }

  private isSchemaCompatible(referenceModel: BenchmarkAsset, candidateModel: BenchmarkAsset): boolean {
    if (referenceModel.id === candidateModel.id) {
      return true;
    }

    if (referenceModel.requestShape !== candidateModel.requestShape) {
      return false;
    }

    if (referenceModel.benchmarkModelType !== candidateModel.benchmarkModelType) {
      return false;
    }

    const referenceSignature = this.buildInputColumnSignature(referenceModel);
    const candidateSignature = this.buildInputColumnSignature(candidateModel);
    if (!referenceSignature || !candidateSignature) {
      return false;
    }

    return referenceSignature === candidateSignature;
  }

  private orderModelPool(pool: BenchmarkAsset[]): BenchmarkAsset[] {
    const selectedAssetIds = new Set(this.selectedAssetIds);
    return [...pool].sort((left, right) => {
      const leftSelected = selectedAssetIds.has(left.id);
      const rightSelected = selectedAssetIds.has(right.id);
      if (leftSelected !== rightSelected) {
        return leftSelected ? -1 : 1;
      }

      return left.name.localeCompare(right.name);
    });
  }

  private buildInputColumnSignature(model: BenchmarkAsset): string {
    if (model.inputColumns.length > 0) {
      return this.normalizeColumnSignature(model.inputColumns);
    }

    const fields = this.getSchemaFieldsFromModel(model);
    if (fields.length > 0) {
      return this.normalizeColumnSignature(fields.map(field => field.name));
    }

    const example = this.parseObjectLikeValue(model.inputExample);
    if (!example) {
      return '';
    }

    return this.normalizeColumnSignature(Object.keys(example));
  }

  private getPreferredRegressionKeys(model: BenchmarkAsset): string[] {
    return this.uniqueStrings(model.targetFields);
  }

  private getPreferredClassificationKeys(model: BenchmarkAsset): string[] {
    return this.uniqueStrings(model.targetFields);
  }

  private getPreferredPredictionKeys(model: BenchmarkAsset): string[] {
    return this.uniqueStrings([...model.predictionFields, ...model.targetFields]);
  }

  private uniqueStrings(values: string[]): string[] {
    return Array.from(new Set(values.map(value => value.trim()).filter(value => value.length > 0)));
  }

  private normalizeColumnSignature(columns: string[]): string {
    return this.uniqueStrings(columns)
      .map(column => column.toLowerCase())
      .sort()
      .join('|');
  }

  private parseObjectLikeValue(value: unknown): Record<string, any> | null {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return value as Record<string, any>;
    }

    if (typeof value !== 'string' || !value.trim()) {
      return null;
    }

    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }

  // ---------------------------------------------------------------------------
  // Test sample rows
  // ---------------------------------------------------------------------------

  async testSampleRows(): Promise<void> {
    if (!this.canTestRows) {
      this.notificationService.showWarning('Select model(s), load a dataset, and select metric(s) before testing rows');
      return;
    }

    const selectedModels = this.modelPoolAssets.filter(model => this.selectedAssetIds.includes(model.id));
    const activeMapping = this.getActiveValidationDatasetMapping();
    const sampleRows = this.validationDatasetRows.slice(0, this.getEffectiveRowTestSampleSize());
    const validationErrors = this.validateValidationDatasetRows(sampleRows, selectedModels, activeMapping);
    if (validationErrors.length > 0) {
      this.rowTestResults = [];
      this.rowTestStatusMessage = `Sample rows invalid: ${validationErrors[0]}`;
      this.notificationService.showError(`Sample rows invalid: ${validationErrors[0]}`);
      return;
    }

    this.validationDatasetMapping = activeMapping;
    this.isTestingRows = true;
    this.rowTestResults = [];
    this.rowTestStatusMessage = `Testing ${sampleRows.length} row(s) against ${selectedModels.length} model(s)...`;

    try {
      const results: RowTestResult[] = [];
      for (const model of selectedModels) {
        results.push(await this.executeRowTestForModel(model, sampleRows));
      }

      this.rowTestResults = results;
      const successful = results.filter(result => result.status === 'success').length;
      const partial = results.filter(result => result.status === 'partial').length;
      const failed = results.length - successful - partial;
      this.rowTestStatusMessage = `Row test complete. Success: ${successful}, partial: ${partial}, errors: ${failed}.`;
      if (failed > 0 || partial > 0) {
        this.notificationService.showWarning('Row test completed with warnings');
      } else {
        this.notificationService.showInfo('Row test completed successfully');
      }
    } catch (error: any) {
      this.rowTestStatusMessage = `Row test failed: ${error?.message || 'Unknown error'}`;
      this.notificationService.showError('Row test failed');
    } finally {
      this.isTestingRows = false;
    }
  }

  private async executeRowTestForModel(model: BenchmarkAsset, sampleRows: any[]): Promise<RowTestResult> {
    if (this.isMetricBenchmarkModel(model)) {
      return this.executeMetricRowTestForModel(model, sampleRows);
    }

    return this.executeOutputRowTestForModel(model, sampleRows);
  }

  private async executeMetricRowTestForModel(model: BenchmarkAsset, sampleRows: any[]): Promise<RowTestResult> {
    const startedAt = Date.now();
    try {
      const response = await this.executeModel(
        model.id,
        this.buildBenchmarkMetricExecutionPayload(sampleRows),
        this.batchRequestBenchmarkRequestTimeoutMs
      );
      const output = this.extractExecutionOutput(response);
      const metrics = this.extractMetricModelMetrics(output);
      if (Object.keys(metrics).length === 0) {
        throw new Error('Metric model did not return selected benchmark metrics.');
      }

      return {
        modelId: model.id,
        modelName: model.name,
        modelType: model.benchmarkModelType,
        status: 'success',
        latencyMs: Date.now() - startedAt,
        rowsTested: sampleRows.length,
        successfulRows: sampleRows.length,
        failedRows: 0,
        outputPreview: this.buildOutputPreview(metrics)
      };
    } catch (error: any) {
      return {
        modelId: model.id,
        modelName: model.name,
        modelType: model.benchmarkModelType,
        status: 'error',
        latencyMs: Date.now() - startedAt,
        rowsTested: sampleRows.length,
        successfulRows: 0,
        failedRows: sampleRows.length,
        outputPreview: 'Execution failed.',
        errorMessage: error?.message || 'Unknown execution error'
      };
    }
  }

  private async executeOutputRowTestForModel(model: BenchmarkAsset, sampleRows: any[]): Promise<RowTestResult> {
    const startedAt = Date.now();
    if (this.shouldUseBatchBenchmarkExecution(model)) {
      try {
        const response = await this.executeModel(
          model.id,
          this.buildBenchmarkExecutionPayload(model, sampleRows),
          this.getBenchmarkRequestTimeoutMsForModel(model)
        );
        const output = this.extractExecutionOutput(response);
        const outputs = this.expandBatchExecutionOutputs(output, sampleRows.length);
        const successfulRows = outputs.filter(item => item !== undefined && item !== null).length;
        const failedRows = Math.max(sampleRows.length - successfulRows, 0);
        return {
          modelId: model.id,
          modelName: model.name,
          modelType: model.benchmarkModelType,
          status: failedRows === 0 ? 'success' : successfulRows > 0 ? 'partial' : 'error',
          latencyMs: Date.now() - startedAt,
          rowsTested: sampleRows.length,
          successfulRows,
          failedRows,
          outputPreview: this.buildOutputPreview(outputs),
          errorMessage: failedRows > 0 ? 'Batch response did not contain an output for every row.' : undefined
        };
      } catch (error: any) {
        return {
          modelId: model.id,
          modelName: model.name,
          modelType: model.benchmarkModelType,
          status: 'error',
          latencyMs: Date.now() - startedAt,
          rowsTested: sampleRows.length,
          successfulRows: 0,
          failedRows: sampleRows.length,
          outputPreview: 'Execution failed.',
          errorMessage: error?.message || 'Unknown execution error'
        };
      }
    }

    const settledRows = await Promise.all(sampleRows.map(async row => {
      try {
        const response = await this.executeModel(
          model.id,
          this.buildBenchmarkExecutionPayload(model, row),
          this.benchmarkRequestTimeoutMs
        );
        return { success: true, output: this.extractExecutionOutput(response) };
      } catch (error: any) {
        return { success: false, output: null, errorMessage: error?.message || 'Execution failed.' };
      }
    }));

    const outputs = settledRows.filter(row => row.success).map(row => row.output);
    const successfulRows = outputs.length;
    const failedRows = sampleRows.length - successfulRows;
    const firstError = settledRows.find(row => !row.success)?.errorMessage;
    return {
      modelId: model.id,
      modelName: model.name,
      modelType: model.benchmarkModelType,
      status: failedRows === 0 ? 'success' : successfulRows > 0 ? 'partial' : 'error',
      latencyMs: Date.now() - startedAt,
      rowsTested: sampleRows.length,
      successfulRows,
      failedRows,
      outputPreview: this.buildOutputPreview(outputs),
      errorMessage: firstError
    };
  }

  // ---------------------------------------------------------------------------
  // Run Benchmark (Ranking)
  // ---------------------------------------------------------------------------

  async runRanking(): Promise<void> {
    if (!this.canRunBenchmark) {
      this.notificationService.showWarning('Select at least 2 models, 1 metric and a valid validation dataset');
      return;
    }

    this.isRunning = true;
    this.statusMessage = 'Executing benchmark with validation dataset...';
    this.progress = 0;
    this.rankingRows = [];

    const selectedModels = this.modelPoolAssets.filter(m => this.selectedAssetIds.includes(m.id));
    const benchmarkRunId = this.modelObserverJournalService.createId('benchmark');
    const correlationId = this.modelObserverJournalService.createId('corr');
    this.lastBenchmarkRunId = benchmarkRunId;

    try {
      const datasetRows = this.validationDatasetRows;
      const activeMapping = this.getActiveValidationDatasetMapping();
      this.validationDatasetMapping = activeMapping;
      const datasetValidationErrors = this.validateValidationDatasetRows(datasetRows, selectedModels, activeMapping);
      if (datasetValidationErrors.length > 0) {
        throw new Error(`Validation dataset invalid: ${datasetValidationErrors[0]}`);
      }

      this.publishBenchmarkEvent({
        eventType: 'BENCHMARK_STARTED',
        status: 'STARTED',
        correlationId,
        benchmarkRunId,
        taskType: this.detectedTask || this.detectModelTask(selectedModels),
        datasetFingerprint: this.buildDatasetFingerprint(datasetRows),
        datasetRowCount: datasetRows.length,
        selectedMetrics: [...this.selectedMetrics],
        details: {
          selectedModels: selectedModels.map(model => ({
            assetId: model.id,
            modelName: model.name,
            provider: model.provider,
            source: model.source
          }))
        }
      });

      const results: RankingRow[] = [];
      const totalModels = selectedModels.length;

      for (let i = 0; i < selectedModels.length; i++) {
        const model = selectedModels[i];
        this.statusMessage = `Executing ${model.name} (${i + 1}/${totalModels}) with ${datasetRows.length} validation rows...`;

        try {
          const benchmarkResult = await this.executeBenchmarkRowsForModel(model, datasetRows, i, totalModels, benchmarkRunId, correlationId);
          results.push({
            rank: 0, modelId: model.id, modelName: model.name,
            metrics: benchmarkResult.metrics,
            latency: Math.round(benchmarkResult.averageLatency),
            successCount: benchmarkResult.successCount
          });
        } catch (error: any) {
          results.push({
            rank: 0, modelId: model.id, modelName: model.name,
            metrics: {}, latency: 0, successCount: 0,
            errorMessage: error?.message || 'Benchmark execution failed.'
          });
        }
      }

      const successfulResultCount = results.filter(row => this.getMetricValue(row, this.recommendationMetric) !== null).length;
      if (successfulResultCount === 0) {
        throw new Error('All selected models failed during benchmark execution. Review the sample test errors or connector logs.');
      }

      this.rankingRows = this.rankResults(results, datasetRows.length);
      this.progress = 100;
      this.isRunning = false;
      const failedResultCount = results.length - successfulResultCount;
      this.statusMessage = failedResultCount > 0
        ? `Benchmark completed with warnings: ${successfulResultCount}/${results.length} models produced comparable results using ${datasetRows.length} validation rows.`
        : `Benchmark completed successfully using ${datasetRows.length} validation rows!`;
      this.publishBenchmarkEvent({
        eventType: 'BENCHMARK_COMPLETED',
        status: 'COMPLETED',
        correlationId,
        benchmarkRunId,
        taskType: this.detectedTask || this.detectModelTask(selectedModels),
        datasetFingerprint: this.buildDatasetFingerprint(datasetRows),
        datasetRowCount: datasetRows.length,
        selectedMetrics: [...this.selectedMetrics],
        benchmarkSummary: {
          totalModels: this.rankingRows.length,
          topModelId: this.rankingRows[0]?.modelId || null,
          topModelName: this.rankingRows[0]?.modelName || null,
          recommendationMetric: this.recommendationMetric || null
        }
      });
      if (failedResultCount > 0) {
        this.notificationService.showWarning(`Benchmark completed with warnings: ${failedResultCount} model(s) failed to produce comparable results.`);
      } else {
        this.notificationService.showInfo('Benchmark completed');
      }
    } catch (error: any) {
      this.isRunning = false;
      this.statusMessage = 'Benchmark failed: ' + error.message;
      this.publishBenchmarkEvent({
        eventType: 'BENCHMARK_FAILED',
        status: 'FAILED',
        correlationId,
        benchmarkRunId,
        taskType: this.detectedTask || this.detectModelTask(selectedModels),
        datasetFingerprint: this.buildDatasetFingerprint(this.validationDatasetRows),
        datasetRowCount: this.validationDatasetRows.length,
        selectedMetrics: [...this.selectedMetrics],
        details: {
          message: error?.message || 'Unknown error'
        }
      });
      this.notificationService.showError('Benchmark failed');
    }
  }

  openObserverTimeline(): void {
    if (!this.observerAssetId) {
      return;
    }

    this.router.navigate(['/ai-model-observer/timeline', this.observerAssetId]);
  }

  openBenchmarkObserver(): void {
    if (!this.lastBenchmarkRunId) {
      return;
    }

    this.router.navigate(['/ai-model-observer/benchmarks', this.lastBenchmarkRunId]);
  }

  // ---------------------------------------------------------------------------
  // Benchmark execution helpers
  // ---------------------------------------------------------------------------

  private async executeBenchmarkRowsForModel(
    model: BenchmarkAsset,
    datasetRows: any[],
    modelIndex: number,
    totalModels: number,
    benchmarkRunId: string,
    correlationId: string
  ): Promise<{ metrics: Record<string, number>; averageLatency: number; successCount: number }> {
    if (this.isMetricBenchmarkModel(model)) {
      return this.executeMetricBenchmarkModel(model, datasetRows, modelIndex, totalModels, benchmarkRunId, correlationId);
    }

    const modelTask = this.detectModelTask([model]);
    if (modelTask === 'unsupported') {
      throw new Error(`Output-model metrics are only available for classification or regression. Use a metric model for ${model.name}.`);
    }

    const totalRows = datasetRows.length;
    const useBatchExecution = this.shouldUseBatchBenchmarkExecution(model);
    const batchSize = Math.max(1, Math.min(this.getBenchmarkBatchSizeForModel(model), totalRows));
    const totalBatches = Math.ceil(totalRows / batchSize);

    let successCount = 0;
    let totalLatency = 0;
    const predictions: any[] = [];
    let firstErrorMessage = '';

    for (let batchIndex = 0; batchIndex < totalBatches; batchIndex++) {
      const batchStart = batchIndex * batchSize;
      const batchEnd = Math.min(batchStart + batchSize, totalRows);
      const batchRows = datasetRows.slice(batchStart, batchEnd);

      this.statusMessage = `Executing ${model.name} (${modelIndex + 1}/${totalModels}) - batch ${batchIndex + 1}/${totalBatches} rows ${batchStart + 1}-${batchEnd}`;

      const settledBatch = useBatchExecution
        ? await this.executeBenchmarkBatchForModel(model, batchRows, batchStart, benchmarkRunId, correlationId)
        : await Promise.all(
          batchRows.map(async (row, rowOffset) => {
            const startedAt = Date.now();
            try {
              const result = await this.executeModel(model.id, this.buildBenchmarkExecutionPayload(model, row), this.benchmarkRequestTimeoutMs, benchmarkRunId, correlationId, model.name);
              return { rowIndex: batchStart + rowOffset, success: true, output: this.extractExecutionOutput(result), latencyMs: Date.now() - startedAt };
            } catch (error: any) {
              return {
                rowIndex: batchStart + rowOffset,
                success: false,
                output: null as any,
                latencyMs: Date.now() - startedAt,
                errorMessage: error?.message || 'Execution failed.'
              };
            }
          })
        );

      settledBatch.forEach(item => {
        predictions[item.rowIndex] = item.output;
        totalLatency += item.latencyMs;
        if (item.success) {
          successCount += 1;
        } else if (!firstErrorMessage && item.errorMessage) {
          firstErrorMessage = item.errorMessage;
        }
      });

      const baseProgress = modelIndex / totalModels;
      const modelProgress = (batchEnd / totalRows) / totalModels;
      this.progress = Math.round((baseProgress + modelProgress) * 100);
    }

    if (successCount === 0) {
      throw new Error(firstErrorMessage || `All benchmark requests failed for ${model.name}.`);
    }

    const comparablePairCount = modelTask === 'regression'
      ? this.buildRegressionPairs(model, datasetRows, predictions).length
      : this.buildClassificationPairs(model, datasetRows, predictions).length;
    if (comparablePairCount === 0) {
      throw new Error(`No comparable predictions were produced for ${model.name}. Ensure the validation dataset contains the expected target field.`);
    }

    const metrics = this.calculateMetrics(model, datasetRows, predictions, modelTask);

    return {
      metrics,
      averageLatency: totalRows > 0 ? totalLatency / totalRows : 0,
      successCount
    };
  }

  private async executeMetricBenchmarkModel(
    model: BenchmarkAsset,
    datasetRows: any[],
    modelIndex: number,
    totalModels: number,
    benchmarkRunId: string,
    correlationId: string
  ): Promise<{ metrics: Record<string, number>; averageLatency: number; successCount: number }> {
    this.statusMessage = `Executing metric model ${model.name} (${modelIndex + 1}/${totalModels}) with ${datasetRows.length} validation rows`;

    const startedAt = Date.now();
    const result = await this.executeModel(
      model.id,
      this.buildBenchmarkMetricExecutionPayload(datasetRows),
      this.batchRequestBenchmarkRequestTimeoutMs,
      benchmarkRunId,
      correlationId,
      model.name
    );
    const latencyMs = Date.now() - startedAt;
    const metrics = this.extractMetricModelMetrics(this.extractExecutionOutput(result));

    if (Object.keys(metrics).length === 0) {
      throw new Error(`Metric model ${model.name} did not return any selected benchmark metrics.`);
    }

    this.progress = Math.round(((modelIndex + 1) / totalModels) * 100);

    return {
      metrics,
      averageLatency: datasetRows.length > 0 ? latencyMs / datasetRows.length : latencyMs,
      successCount: datasetRows.length
    };
  }

  private async executeBenchmarkBatchForModel(
    model: BenchmarkAsset,
    batchRows: any[],
    batchStart: number,
    benchmarkRunId: string,
    correlationId: string
  ): Promise<Array<{ rowIndex: number; success: boolean; output: any; latencyMs: number; errorMessage?: string }>> {
    const startedAt = Date.now();

    try {
      const result = await this.executeModel(
        model.id,
        this.buildBenchmarkExecutionPayload(model, batchRows),
        this.getBenchmarkRequestTimeoutMsForModel(model),
        benchmarkRunId,
        correlationId,
        model.name
      );
      const output = this.extractExecutionOutput(result);
      const outputs = this.expandBatchExecutionOutputs(output, batchRows.length);
      const elapsed = Date.now() - startedAt;
      const perRowLatency = elapsed / Math.max(batchRows.length, 1);

      return batchRows.map((_, rowOffset) => {
        const rowOutput = outputs[rowOffset];
        const hasOutput = rowOutput !== undefined && rowOutput !== null;
        return {
          rowIndex: batchStart + rowOffset,
          success: hasOutput,
          output: hasOutput ? rowOutput : null,
          latencyMs: perRowLatency,
          errorMessage: hasOutput ? undefined : 'Batch response did not contain an output for this row.'
        };
      });
    } catch (error: any) {
      const elapsed = Date.now() - startedAt;
      const perRowLatency = elapsed / Math.max(batchRows.length, 1);
      const errorMessage = error?.message || 'Batch execution failed.';
      return batchRows.map((_, rowOffset) => ({
        rowIndex: batchStart + rowOffset,
        success: false,
        output: null,
        latencyMs: perRowLatency,
        errorMessage
      }));
    }
  }

  private shouldUseBatchBenchmarkExecution(model: BenchmarkAsset): boolean {
    return model.requestShape === 'batch';
  }

  private isMetricBenchmarkModel(model: BenchmarkAsset): boolean {
    return model.benchmarkModelType === 'metric';
  }

  private getBenchmarkBatchSizeForModel(model: BenchmarkAsset): number {
    return this.shouldUseBatchBenchmarkExecution(model)
      ? this.batchRequestBenchmarkBatchSize
      : this.benchmarkBatchSize;
  }

  private getBenchmarkRequestTimeoutMsForModel(model: BenchmarkAsset): number {
    return this.shouldUseBatchBenchmarkExecution(model)
      ? this.batchRequestBenchmarkRequestTimeoutMs
      : this.benchmarkRequestTimeoutMs;
  }

  private expandBatchExecutionOutputs(output: any, expectedCount: number): any[] {
    if (Array.isArray(output)) {
      return output;
    }

    if (output && typeof output === 'object') {
      for (const key of ['predictions', 'outputs', 'results', 'data', 'items', 'values']) {
        const nested = output[key];
        if (Array.isArray(nested)) {
          return nested;
        }
      }
    }

    return expectedCount === 1 ? [output] : [];
  }

  private normalizeExecutionPayload(model: BenchmarkAsset, input: any): any {
    const executionInput = this.buildExecutionInputForModel(model, input);
    if (model.requestShape === 'batch' && !Array.isArray(executionInput)) {
      return [executionInput];
    }

    return executionInput;
  }

  private buildBenchmarkExecutionPayload(model: BenchmarkAsset, input: any): any {
    const benchmarkInput = Array.isArray(input)
      ? input.map(row => this.buildBenchmarkInputRecord(row))
      : this.buildBenchmarkInputRecord(input);
    return this.normalizeExecutionPayload(model, benchmarkInput);
  }

  private buildBenchmarkMetricExecutionPayload(rows: any[]): any[] {
    return rows;
  }

  private buildBenchmarkInputRecord(row: any, mapping: BenchmarkDatasetMapping | null = this.validationDatasetMapping): any {
    if (!mapping || mapping.input.length === 0) {
      return row;
    }

    return mapping.input.reduce<Record<string, any>>((payload, column) => {
      const value = row?.[column];
      if (value !== undefined) {
        payload[column] = value;
      }
      return payload;
    }, {});
  }

  private buildExecutionInputForModel(model: BenchmarkAsset, input: any): any {
    if (Array.isArray(input)) {
      return input.map(row => this.buildExecutionRecordForModel(model, row));
    }

    return this.buildExecutionRecordForModel(model, input);
  }

  private buildExecutionRecordForModel(model: BenchmarkAsset, row: any): any {
    if (!row || typeof row !== 'object' || Array.isArray(row)) {
      return row;
    }

    const fields = this.getSchemaFieldsFromModel(model);
    if (fields.length === 0) {
      return row;
    }

    return fields.reduce<Record<string, any>>((payload, field) => {
      const value = row[field.name];
      if (value !== undefined && value !== null && value !== '') {
        payload[field.name] = this.normalizeExampleValue(field, value);
      }

      return payload;
    }, {});
  }

  private executeModel(
    assetId: string,
    input: any,
    requestTimeoutMs = 30000,
    benchmarkRunId?: string,
    correlationId?: string,
    modelName?: string
  ): Promise<ModelExecutionResponsePayload> {
    return new Promise((resolve, reject) => {
      let settled = false;

      const subscription = this.modelExecutionService.executeModel({
        assetId,
        payload: input,
        benchmarkRunId,
        correlationId,
        modelName
      }).subscribe({
        next: (response: ModelExecutionResponsePayload) => {
          if (settled) return;
          settled = true;
          clearTimeout(clientTimeout);
          resolve(response);
        },
        error: (error: any) => {
          if (settled) return;
          settled = true;
          clearTimeout(clientTimeout);
          reject(error);
        }
      });

      const clientTimeout = setTimeout(() => {
        if (settled) return;
        settled = true;
        subscription.unsubscribe();
        reject(new Error(`Execution request timeout after ${requestTimeoutMs}ms`));
      }, requestTimeoutMs + 2000);
    });
  }

  private extractExecutionOutput(response: ModelExecutionResponsePayload): any {
    if (!response) return null;
    if (response.statusCode >= 400) {
      throw new Error(`Model execution failed with status ${response.statusCode}`);
    }
    return response.parsedBody ?? response.body;
  }

  private extractMetricModelMetrics(output: any): Record<string, number> {
    const source = this.findMetricOutputSource(output);
    const metrics: Record<string, number> = {};

    this.selectedMetrics.forEach(metric => {
      const value = this.readMetricOutputValue(source, metric);
      if (Number.isFinite(value)) {
        metrics[metric] = value;
      }
    });

    return metrics;
  }

  private findMetricOutputSource(output: any): any {
    if (Array.isArray(output)) {
      return output.length === 1 ? this.findMetricOutputSource(output[0]) : output;
    }

    if (typeof output === 'string') {
      const trimmed = output.trim();
      if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
        try {
          return this.findMetricOutputSource(JSON.parse(trimmed));
        } catch {
          return output;
        }
      }
    }

    if (!output || typeof output !== 'object') {
      return output;
    }

    for (const key of ['metrics', 'scores', 'evaluation', 'benchmark']) {
      const nested = output[key];
      if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
        return nested;
      }
      if (Array.isArray(nested)) {
        return nested;
      }
    }

    for (const key of ['result', 'results', 'data', 'body']) {
      const nested = output[key];
      if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
        return this.findMetricOutputSource(nested);
      }
      if (Array.isArray(nested)) {
        return nested;
      }
    }

    return output;
  }

  private readMetricOutputValue(source: any, metric: string): number {
    if (source === undefined || source === null) {
      return Number.NaN;
    }

    if (Array.isArray(source)) {
      for (const item of source) {
        const value = this.readMetricOutputValue(item, metric);
        if (Number.isFinite(value)) {
          return value;
        }
      }
      return Number.NaN;
    }

    if (typeof source !== 'object') {
      return this.readMetricNumericValue(source);
    }

    const expectedKey = this.normalizeMetricName(metric);
    for (const [key, value] of Object.entries(source)) {
      if (this.normalizeMetricName(key) === expectedKey) {
        return this.readMetricNumericValue(value);
      }
    }

    const sourceMetricName = this.firstDefined(source.metric, source.name, source.key);
    if (sourceMetricName !== undefined && this.normalizeMetricName(String(sourceMetricName)) === expectedKey) {
      return this.readMetricNumericValue(this.firstDefined(source.value, source.score, source.result));
    }

    return Number.NaN;
  }

  private readMetricNumericValue(value: any): number {
    const direct = this.readNumericValue(value);
    if (Number.isFinite(direct)) {
      return direct;
    }

    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return Number.NaN;
    }

    return this.readNumericValue(this.firstDefined(value.value, value.score, value.result));
  }

  private normalizeMetricName(value: string): string {
    const normalized = String(value).toLowerCase().replace(/[^a-z0-9]/g, '');
    return normalized === 'f1score' ? 'f1' : normalized;
  }

  private firstDefined(...values: any[]): any {
    return values.find(value => value !== undefined && value !== null && value !== '');
  }

  private publishBenchmarkEvent(event: {
    eventType: string;
    status: string;
    correlationId: string;
    benchmarkRunId: string;
    taskType?: string;
    datasetFingerprint?: string;
    datasetRowCount?: number;
    selectedMetrics?: string[];
    benchmarkSummary?: Record<string, unknown>;
    details?: Record<string, unknown>;
  }): void {
    void lastValueFrom(this.modelObserverJournalService.publish(event));
  }

  private buildDatasetFingerprint(rows: any[]): string {
    if (!rows || rows.length === 0) {
      return 'rows-0-empty';
    }

    const firstRow = rows[0] || {};
    const keys = Object.keys(firstRow).sort().join('|');
    return `rows-${rows.length}-keys-${keys}`;
  }

  private calculateMetrics(model: BenchmarkAsset, datasetRows: any[], predictions: any[], taskType: ModelTask): Record<string, number> {
    const metrics: Record<string, number> = {};
    if (taskType === 'unsupported') {
      return metrics;
    }

    const regressionPairs = this.buildRegressionPairs(model, datasetRows, predictions);
    const classificationPairs = this.buildClassificationPairs(model, datasetRows, predictions);
    const accuracy = this.computeClassificationAccuracy(classificationPairs);
    const precision = this.computeMacroPrecision(classificationPairs);
    const recall = this.computeMacroRecall(classificationPairs);
    const f1Score = this.computeMacroF1(classificationPairs);
    const mae = this.computeMae(regressionPairs);
    const mse = this.computeMse(regressionPairs);
    const rmse = Math.sqrt(mse);
    const r2 = this.computeR2(regressionPairs);

    this.selectedMetrics.forEach(metric => {
      switch (this.normalizeMetricName(metric)) {
        case 'precision':
          metrics[metric] = precision;
          break;
        case 'recall':
          metrics[metric] = recall;
          break;
        case 'f1':
          metrics[metric] = f1Score;
          break;
        case 'rmse':
          metrics[metric] = rmse;
          break;
        case 'mae':
          metrics[metric] = mae;
          break;
        case 'mse':
          metrics[metric] = mse;
          break;
        case 'r2':
          metrics[metric] = r2;
          break;
        case 'accuracy':
          metrics[metric] = accuracy;
          break;
        default:
          metrics[metric] = Number.NaN;
      }
    });

    return metrics;
  }

  private buildClassificationPairs(
    model: BenchmarkAsset,
    datasetRows: any[],
    predictions: any[]
  ): Array<{ actual: string; predicted: string }> {
    const excludedKeys = new Set(this.getSchemaFieldsFromModel(model).map(field => field.name));
    const pairs: Array<{ actual: string; predicted: string }> = [];

    datasetRows.forEach((row, index) => {
      const actual = this.extractExpectedClassificationValue(model, row, excludedKeys);
      const predicted = this.extractComparableClassificationValue(model, predictions[index]);
      if (!actual || !predicted) {
        return;
      }

      pairs.push({ actual, predicted });
    });

    return pairs;
  }

  private buildRegressionPairs(
    model: BenchmarkAsset,
    datasetRows: any[],
    predictions: any[]
  ): Array<{ actual: number; predicted: number }> {
    const excludedKeys = new Set(this.getSchemaFieldsFromModel(model).map(field => field.name));
    const pairs: Array<{ actual: number; predicted: number }> = [];

    datasetRows.forEach((row, index) => {
      const actual = this.extractExpectedRegressionValue(model, row, excludedKeys);
      const predicted = this.extractComparableRegressionValue(model, predictions[index]);
      if (!Number.isFinite(actual) || !Number.isFinite(predicted)) {
        return;
      }

      pairs.push({ actual, predicted });
    });

    return pairs;
  }

  private extractExpectedClassificationValue(model: BenchmarkAsset, row: any, excludedKeys: Set<string>): string | null {
    const mappedValue = this.extractDatasetExpectedValue(row);
    if (mappedValue !== undefined) {
      return this.normalizeClassificationValue(mappedValue);
    }

    const preferredValue = this.findComparableValue(row, this.getPreferredClassificationKeys(model));
    if (preferredValue !== undefined) {
      return this.normalizeClassificationValue(preferredValue);
    }

    return this.normalizeClassificationValue(this.findComparableValue(row, [
      'label', 'target', 'expected', 'ground_truth', 'groundTruth', 'actual', 'y',
      'prediction', 'category', 'class', 'decision', 'result', 'value'
    ], excludedKeys));
  }

  private extractExpectedRegressionValue(model: BenchmarkAsset, row: any, excludedKeys: Set<string>): number {
    const mappedValue = this.extractDatasetExpectedValue(row);
    if (mappedValue !== undefined) {
      return this.readNumericValue(mappedValue);
    }

    const preferredValue = this.findComparableValue(row, this.getPreferredRegressionKeys(model));
    if (preferredValue !== undefined) {
      return this.readNumericValue(preferredValue);
    }

    return this.readNumericValue(this.findComparableValue(row, [
      'label', 'target', 'expected', 'ground_truth', 'groundTruth', 'actual', 'y', 'value',
      'prediction', 'score', 'result'
    ], excludedKeys));
  }

  private extractDatasetExpectedValue(row: any, mapping: BenchmarkDatasetMapping | null = this.validationDatasetMapping): any {
    if (!mapping || !mapping.label) {
      return undefined;
    }

    return row?.[mapping.label];
  }

  private extractComparableClassificationValue(model: BenchmarkAsset, output: any): string | null {
    if (output === undefined || output === null) {
      return null;
    }

    if (Array.isArray(output)) {
      for (const item of output) {
        const value = this.extractComparableClassificationValue(model, item);
        if (value) {
          return value;
        }
      }
      return null;
    }

    if (typeof output !== 'object') {
      return this.normalizeClassificationValue(output);
    }

    const preferredValue = this.findComparableValue(output, this.getPreferredPredictionKeys(model));
    if (preferredValue !== undefined) {
      return this.normalizeClassificationValue(preferredValue);
    }

    return this.normalizeClassificationValue(this.findComparableValue(output, [
      'prediction', 'label', 'target', 'expected', 'category', 'class', 'decision', 'result', 'value'
    ]));
  }

  private extractComparableRegressionValue(model: BenchmarkAsset, output: any): number {
    if (output === undefined || output === null) {
      return Number.NaN;
    }

    if (Array.isArray(output)) {
      for (const item of output) {
        const value = this.extractComparableRegressionValue(model, item);
        if (Number.isFinite(value)) {
          return value;
        }
      }
      return Number.NaN;
    }

    if (typeof output !== 'object') {
      return this.readNumericValue(output);
    }

    const preferredValue = this.findComparableValue(output, this.getPreferredPredictionKeys(model));
    if (preferredValue !== undefined) {
      return this.readNumericValue(preferredValue);
    }

    return this.readNumericValue(this.findComparableValue(output, [
      'value', 'prediction', 'target', 'expected', 'label', 'score', 'result'
    ]));
  }

  private findComparableValue(record: any, keys: string[], excludedKeys?: Set<string>): any {
    if (!record || typeof record !== 'object' || Array.isArray(record)) {
      return undefined;
    }

    for (const key of keys) {
      if (excludedKeys?.has(key)) {
        continue;
      }

      const value = record[key];
      if (value !== undefined && value !== null && value !== '') {
        return value;
      }
    }

    return undefined;
  }

  private normalizeClassificationValue(value: any): string | null {
    if (value === undefined || value === null || value === '') {
      return null;
    }
    if (typeof value === 'object') {
      return null;
    }

    return String(value).trim().toLowerCase();
  }

  private readNumericValue(value: any): number {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : Number.NaN;
    }

    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : Number.NaN;
  }

  private computeClassificationAccuracy(pairs: Array<{ actual: string; predicted: string }>): number {
    if (pairs.length === 0) {
      return 0;
    }

    const correct = pairs.filter(pair => pair.actual === pair.predicted).length;
    return correct / pairs.length;
  }

  private computeMacroPrecision(pairs: Array<{ actual: string; predicted: string }>): number {
    const labels = this.collectDistinctLabels(pairs);
    if (labels.length === 0) {
      return 0;
    }

    const total = labels.reduce((sum, label) => {
      const tp = pairs.filter(pair => pair.actual === label && pair.predicted === label).length;
      const fp = pairs.filter(pair => pair.actual !== label && pair.predicted === label).length;
      return sum + (tp + fp === 0 ? 0 : tp / (tp + fp));
    }, 0);

    return total / labels.length;
  }

  private computeMacroRecall(pairs: Array<{ actual: string; predicted: string }>): number {
    const labels = this.collectDistinctLabels(pairs);
    if (labels.length === 0) {
      return 0;
    }

    const total = labels.reduce((sum, label) => {
      const tp = pairs.filter(pair => pair.actual === label && pair.predicted === label).length;
      const fn = pairs.filter(pair => pair.actual === label && pair.predicted !== label).length;
      return sum + (tp + fn === 0 ? 0 : tp / (tp + fn));
    }, 0);

    return total / labels.length;
  }

  private computeMacroF1(pairs: Array<{ actual: string; predicted: string }>): number {
    const precision = this.computeMacroPrecision(pairs);
    const recall = this.computeMacroRecall(pairs);
    if ((precision + recall) === 0) {
      return 0;
    }
    return (2 * precision * recall) / (precision + recall);
  }

  private collectDistinctLabels(pairs: Array<{ actual: string; predicted: string }>): string[] {
    const labels = pairs.reduce<string[]>((result, pair) => {
      if (pair.actual) {
        result.push(pair.actual);
      }
      if (pair.predicted) {
        result.push(pair.predicted);
      }
      return result;
    }, []);

    return [...new Set(labels)];
  }

  private computeMae(pairs: Array<{ actual: number; predicted: number }>): number {
    if (pairs.length === 0) {
      return 0;
    }

    const totalError = pairs.reduce((sum, pair) => sum + Math.abs(pair.actual - pair.predicted), 0);
    return totalError / pairs.length;
  }

  private computeMse(pairs: Array<{ actual: number; predicted: number }>): number {
    if (pairs.length === 0) {
      return 0;
    }

    const totalError = pairs.reduce((sum, pair) => {
      const diff = pair.actual - pair.predicted;
      return sum + (diff * diff);
    }, 0);
    return totalError / pairs.length;
  }

  private computeR2(pairs: Array<{ actual: number; predicted: number }>): number {
    if (pairs.length === 0) {
      return 0;
    }

    const meanActual = pairs.reduce((sum, pair) => sum + pair.actual, 0) / pairs.length;
    const ssRes = pairs.reduce((sum, pair) => sum + ((pair.actual - pair.predicted) ** 2), 0);
    const ssTot = pairs.reduce((sum, pair) => sum + ((pair.actual - meanActual) ** 2), 0);
    if (ssTot === 0) {
      return ssRes === 0 ? 1 : 0;
    }
    return 1 - (ssRes / ssTot);
  }

  // ---------------------------------------------------------------------------
  // Ranking
  // ---------------------------------------------------------------------------

  private rankResults(results: RankingRow[], datasetRowCount: number): RankingRow[] {
    const lowerIsBetter = this.isLowerBetterMetric(this.recommendationMetric);
    const validMetricValues = results
      .map(row => this.getMetricValue(row, this.recommendationMetric))
      .filter((value): value is number => value !== null);
    const maxLatency = Math.max(...results.map(r => r.latency), 1);
    const maxMetric = Math.max(...validMetricValues, 1);
    const totalRows = Math.max(datasetRowCount, 1);

    results.forEach(row => {
      const metricValue = this.getMetricValue(row, this.recommendationMetric);
      if (metricValue === null) {
        row.compositeScore = 0;
        return;
      }

      const normalizedLatency = 1 - (row.latency / maxLatency);
      const successRate = Math.max(0, Math.min(1, row.successCount / totalRows));

      const normalizedMetric = lowerIsBetter
        ? 1 - (metricValue / maxMetric)
        : metricValue / maxMetric;

      row.compositeScore = (normalizedMetric * 0.7) + (successRate * 0.2) + (normalizedLatency * 0.1);
    });

    this.resetRankingSort();
    return this.sortRankingRows(results);
  }

  sortRanking(key: string): void {
    if (this.rankingRows.length === 0) {
      return;
    }

    const direction = this.rankingSort.key === key
      ? this.toggleRankingSortDirection(this.rankingSort.direction)
      : this.getDefaultRankingSortDirection(key);

    this.rankingSort = { key, direction };
    this.applyRankingSort();
  }

  isRankingSortActive(key: string): boolean {
    return this.rankingSort.key === key;
  }

  getRankingSortIcon(key: string): string {
    if (!this.isRankingSortActive(key)) {
      return 'unfold_more';
    }
    return this.rankingSort.direction === 'asc' ? 'arrow_upward' : 'arrow_downward';
  }

  getRankingAriaSort(key: string): 'ascending' | 'descending' | 'none' {
    if (!this.isRankingSortActive(key)) {
      return 'none';
    }
    return this.rankingSort.direction === 'asc' ? 'ascending' : 'descending';
  }

  getRankingSortLabel(): string {
    const key = this.rankingSort.key;
    const directionLabel = this.rankingSort.direction === 'asc' ? 'ascending' : 'descending';
    if (this.isMetricSortKey(key)) {
      return `${this.extractMetricSortName(key)} ${directionLabel}`;
    }
    const labels: Record<string, string> = {
      modelName: 'model name',
      success: 'successful rows',
      latency: 'latency',
      score: 'ranking score'
    };
    return `${labels[key] || key} ${directionLabel}`;
  }

  private applyRankingSort(): void {
    this.rankingRows = this.sortRankingRows(this.rankingRows);
  }

  private sortRankingRows(rows: RankingRow[]): RankingRow[] {
    const sorted = [...rows].sort((a, b) => this.compareRankingRows(a, b));
    sorted.forEach((row, index) => {
      row.rank = index + 1;
      row.top = index === 0;
    });
    return sorted;
  }

  private compareRankingRows(a: RankingRow, b: RankingRow): number {
    const key = this.rankingSort.key;
    let comparison = 0;

    if (this.isMetricSortKey(key)) {
      const metric = this.extractMetricSortName(key);
      comparison = this.compareRankingNumbers(this.getMetricValue(a, metric), this.getMetricValue(b, metric), this.rankingSort.direction);
    } else if (key === 'modelName') {
      comparison = this.compareRankingText(a.modelName, b.modelName, this.rankingSort.direction);
    } else if (key === 'success') {
      comparison = this.compareRankingNumbers(a.successCount, b.successCount, this.rankingSort.direction);
    } else if (key === 'latency') {
      comparison = this.compareRankingNumbers(a.latency, b.latency, this.rankingSort.direction);
    } else {
      comparison = this.compareRankingNumbers(a.compositeScore ?? null, b.compositeScore ?? null, this.rankingSort.direction);
    }

    if (comparison !== 0) {
      return comparison;
    }

    if (key !== 'score') {
      const scoreComparison = this.compareRankingNumbers(a.compositeScore ?? null, b.compositeScore ?? null, 'desc');
      if (scoreComparison !== 0) {
        return scoreComparison;
      }
    }

    return this.compareRankingText(a.modelName, b.modelName, 'asc');
  }

  private compareRankingNumbers(a: number | null | undefined, b: number | null | undefined, direction: RankingSortDirection): number {
    const aIsValid = Number.isFinite(a ?? Number.NaN);
    const bIsValid = Number.isFinite(b ?? Number.NaN);
    if (!aIsValid && !bIsValid) {
      return 0;
    }
    if (!aIsValid) {
      return 1;
    }
    if (!bIsValid) {
      return -1;
    }

    return direction === 'asc'
      ? (a as number) - (b as number)
      : (b as number) - (a as number);
  }

  private compareRankingText(a: string, b: string, direction: RankingSortDirection): number {
    const comparison = a.localeCompare(b);
    return direction === 'asc' ? comparison : -comparison;
  }

  private getDefaultRankingSortDirection(key: string): RankingSortDirection {
    if (key === 'modelName' || key === 'latency') {
      return 'asc';
    }
    if (this.isMetricSortKey(key) && this.isLowerBetterMetric(this.extractMetricSortName(key))) {
      return 'asc';
    }
    return 'desc';
  }

  private toggleRankingSortDirection(direction: RankingSortDirection): RankingSortDirection {
    return direction === 'asc' ? 'desc' : 'asc';
  }

  private resetRankingSort(): void {
    this.rankingSort = { key: 'score', direction: 'desc' };
  }

  private isMetricSortKey(key: string): boolean {
    return key.startsWith('metric:');
  }

  private extractMetricSortName(key: string): string {
    return key.replace(/^metric:/, '');
  }

  private isLowerBetterMetric(metric: string): boolean {
    const metricKey = this.normalizeMetricName(metric);
    const selectedModels = this.modelPoolAssets.filter(model => this.selectedAssetIds.includes(model.id));
    const metadataDirection = selectedModels
      .map(model => model.metricDirections[metricKey])
      .find(direction => !!direction);

    if (metadataDirection) {
      return metadataDirection === 'lower';
    }

    return this.lowerIsBetterMetrics.some(fallbackMetric => this.normalizeMetricName(fallbackMetric) === metricKey);
  }

  getTopModel(): RankingRow | null {
    return this.rankingRows.find(row => row.top) || null;
  }

  formatMetricValue(value: number | null | undefined, metric: string): string {
    if (!Number.isFinite(value ?? Number.NaN)) {
      return 'N/A';
    }
    if (['rmse', 'mae', 'mse'].includes(this.normalizeMetricName(metric))) return value.toFixed(4);
    return value.toFixed(3);
  }

  private getMetricValue(row: RankingRow, metric: string): number | null {
    const value = row.metrics[metric];
    return Number.isFinite(value) ? value : null;
  }

  formatLatency(ms: number): string { return `${ms}ms`; }

  getRankingSuccessText(row: RankingRow): string {
    return `${row.successCount}/${this.validationDatasetRows.length || 0}`;
  }

  // ---------------------------------------------------------------------------
  // Download
  // ---------------------------------------------------------------------------

  exportResults(): void {
    if (this.rankingRows.length === 0) return;

    const headers = ['Rank', 'Model Name', 'Model ID'];
    this.selectedMetrics.forEach(m => headers.push(m));
    headers.push('Successful Rows', 'Validation Rows', 'Latency (ms)', 'Composite Score');

    const csvRows: string[] = [headers.join(',')];
    this.rankingRows.forEach(row => {
      const rowData: string[] = [row.rank.toString(), `"${row.modelName}"`, `"${row.modelId}"`];
      this.selectedMetrics.forEach(metric => {
        const value = row.metrics[metric];
        rowData.push(Number.isFinite(value) ? value.toFixed(4) : 'N/A');
      });
      rowData.push(
        row.successCount.toString(),
        this.validationDatasetRows.length.toString(),
        row.latency.toFixed(2),
        (row.compositeScore || 0).toFixed(4)
      );
      csvRows.push(rowData.join(','));
    });

    csvRows.push('', `Generated,${new Date().toISOString()}`, `Task Type,${this.detectedTask || 'Unknown'}`,
      `Dataset,${this.validationDatasetFileName || 'N/A'}`, `Validation Rows,${this.validationDatasetRows.length}`,
      `Models Compared,${this.rankingRows.length}`);

    this.downloadContent(csvRows.join('\n'), `model-benchmark-results-${Date.now()}.csv`, 'text/csv;charset=utf-8;');
  }

  // ---------------------------------------------------------------------------
  // Execution value normalization
  // ---------------------------------------------------------------------------

  private getDefaultValueForSchemaField(field: SchemaField): any {
    if (field.type === 'boolean') return false;
    if (field.type === 'integer') return field.min !== undefined ? Math.trunc(field.min) : 0;
    if (field.type === 'number') return field.min !== undefined ? field.min : 0;
    if (field.type === 'array') return [];
    if (field.type === 'object') return {};
    return '';
  }

  private normalizeExampleValue(field: SchemaField, value: any): any {
    if (field.type === 'integer') {
      const numeric = Number(value);
      return Number.isFinite(numeric) ? Math.trunc(numeric) : this.getDefaultValueForSchemaField(field);
    }

    if (field.type === 'number') {
      const numeric = Number(value);
      return Number.isFinite(numeric) ? numeric : this.getDefaultValueForSchemaField(field);
    }

    if (field.type === 'boolean') {
      if (typeof value === 'boolean') {
        return value;
      }

      return String(value).toLowerCase() === 'true';
    }

    if (field.type === 'array') {
      return Array.isArray(value) ? value : this.getDefaultValueForSchemaField(field);
    }

    if (field.type === 'object') {
      return value && typeof value === 'object' && !Array.isArray(value)
        ? value
        : this.getDefaultValueForSchemaField(field);
    }

    return String(value);
  }

  // ---------------------------------------------------------------------------
  // Schema helpers
  // ---------------------------------------------------------------------------

  private getSchemaFieldsFromModel(model: BenchmarkAsset): SchemaField[] {
    if (model.inputFeatures && model.inputFeatures.length > 0) {
      return model.inputFeatures.map(f => ({
        name: f.name,
        type: this.normalizeFieldType(f.type),
        required: f.required !== false,
        min: f.minValue,
        max: f.maxValue,
        description: f.description
      }));
    }

    const schemaFields = this.buildSchemaFieldsFromInputSchema(model.inputSchema);
    if (schemaFields.length > 0) {
      return schemaFields;
    }

    return this.buildSchemaFieldsFromExample(model.inputExample);
  }

  private buildSchemaFieldsFromInputSchema(schema: any): SchemaField[] {
    const schemaRecord = this.asSchemaRecord(schema);
    if (!schemaRecord) {
      return [];
    }

    const rawFields = Array.isArray(schemaRecord.fields)
      ? schemaRecord.fields
      : Array.isArray(schemaRecord.features)
        ? schemaRecord.features
        : [];
    if (rawFields.length > 0) {
      return rawFields.filter((field: any) => !!field?.name).map((field: any) => ({
        name: String(field.name),
        type: this.normalizeFieldType(field.type),
        required: field.required !== false,
        min: typeof field.min === 'number' ? field.min : undefined,
        max: typeof field.max === 'number' ? field.max : undefined,
        description: field.description ? String(field.description) : undefined
      }));
    }

    const schemaRoot = this.resolveSchemaRootNode(schemaRecord);
    const fields: SchemaField[] = [];
    this.collectSchemaFields(schemaRoot, '', fields);
    return fields;
  }

  private buildSchemaFieldsFromExample(example: any): SchemaField[] {
    const exampleRecord = this.parseObjectLikeValue(example);
    if (!exampleRecord) {
      return [];
    }

    return Object.entries(exampleRecord).map(([name, value]) => ({
      name,
      type: this.inferValueType(value),
      required: true
    }));
  }

  private asSchemaRecord(value: any): Record<string, any> | null {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return value as Record<string, any>;
    }

    return this.parseObjectLikeValue(value);
  }

  private resolveSchemaRootNode(schemaRecord: Record<string, any>): Record<string, any> {
    if (this.isArraySchemaNode(schemaRecord)) {
      const itemSchema = this.asSchemaRecord(schemaRecord.items);
      if (itemSchema) {
        return itemSchema;
      }
    }

    const nestedKeys = ['input', 'payload', 'body', 'requestBody'];
    for (const key of nestedKeys) {
      const nested = this.asSchemaRecord(schemaRecord[key]);
      if (nested && this.isArraySchemaNode(nested)) {
        const itemSchema = this.asSchemaRecord(nested.items);
        if (itemSchema) {
          return itemSchema;
        }
      }
      if (nested?.properties && typeof nested.properties === 'object') {
        return nested;
      }
    }

    return schemaRecord;
  }

  private isArraySchemaNode(schemaNode: Record<string, any>): boolean {
    const typeNode = schemaNode.type;
    if (typeof typeNode === 'string') {
      return typeNode.trim().toLowerCase() === 'array';
    }

    return Array.isArray(typeNode)
      && typeNode.some(item => typeof item === 'string' && item.trim().toLowerCase() === 'array');
  }

  private collectSchemaFields(schemaNode: Record<string, any>, prefix: string, target: SchemaField[]): void {
    const properties = this.asSchemaRecord(schemaNode.properties);
    if (!properties) {
      return;
    }

    const requiredSet = new Set(Array.isArray(schemaNode.required) ? schemaNode.required.map((item: any) => String(item)) : []);

    Object.entries(properties).forEach(([propertyName, propertySchema]) => {
      const fieldSchema = this.asSchemaRecord(propertySchema) || {};
      const path = prefix ? `${prefix}.${propertyName}` : propertyName;
      const fieldType = this.inferSchemaFieldType(fieldSchema);

      if (fieldType === 'object' && fieldSchema.properties) {
        this.collectSchemaFields(fieldSchema, path, target);
        return;
      }

      if (fieldType === 'array') {
        const itemSchema = this.asSchemaRecord(fieldSchema.items);
        if (itemSchema?.properties) {
          this.collectSchemaFields(itemSchema, `${path}[]`, target);
          return;
        }
      }

      target.push({
        name: path,
        type: this.normalizeFieldType(fieldType),
        required: requiredSet.has(propertyName),
        min: typeof fieldSchema.min === 'number' ? fieldSchema.min : typeof fieldSchema.minimum === 'number' ? fieldSchema.minimum : undefined,
        max: typeof fieldSchema.max === 'number' ? fieldSchema.max : typeof fieldSchema.maximum === 'number' ? fieldSchema.maximum : undefined,
        description: fieldSchema.description ? String(fieldSchema.description) : undefined
      });
    });
  }

  private inferSchemaFieldType(schemaNode: Record<string, any>): string {
    const typeNode = schemaNode.type;
    if (typeof typeNode === 'string' && typeNode.trim()) {
      return typeNode.trim().toLowerCase();
    }

    if (Array.isArray(typeNode)) {
      const typeValue = typeNode.find(item => typeof item === 'string' && item.trim() && item !== 'null');
      if (typeof typeValue === 'string') {
        return typeValue.trim().toLowerCase();
      }
    }

    if (schemaNode.properties) {
      return 'object';
    }

    if (schemaNode.items) {
      return 'array';
    }

    return 'string';
  }

  private inferValueType(value: any): string {
    if (Array.isArray(value)) {
      return 'array';
    }

    if (value && typeof value === 'object') {
      return 'object';
    }

    if (typeof value === 'boolean') {
      return 'boolean';
    }

    if (typeof value === 'number') {
      return Number.isInteger(value) ? 'integer' : 'number';
    }

    return 'string';
  }

  private normalizeFieldType(type: any): string {
    const normalized = String(type || 'string').toLowerCase();
    if (['float', 'double', 'number', 'numeric'].includes(normalized)) return 'number';
    if (['int', 'integer', 'long'].includes(normalized)) return 'integer';
    if (['bool', 'boolean'].includes(normalized)) return 'boolean';
    if (['object', 'record'].includes(normalized)) return 'object';
    if (['array', 'list'].includes(normalized)) return 'array';
    return 'string';
  }

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  private validateRecordAgainstSchema(record: any, schemaFields: SchemaField[], context: string): string[] {
    const errors: string[] = [];
    if (!record || typeof record !== 'object' || Array.isArray(record)) {
      return [`${context}: input must be a JSON object.`];
    }
    for (const field of schemaFields) {
      const value = this.readSchemaFieldValue(record, field.name);
      const hasValue = value !== undefined && value !== null && value !== '';
      if (field.required && !hasValue) { errors.push(`${context}: required field "${field.name}" is missing.`); continue; }
      if (!hasValue) continue;
      if (field.type === 'string' && typeof value !== 'string') errors.push(`${context}: field "${field.name}" must be string.`);
      if (field.type === 'boolean' && typeof value !== 'boolean') errors.push(`${context}: field "${field.name}" must be boolean.`);
      if (field.type === 'number') {
        if (typeof value !== 'number' || Number.isNaN(value)) { errors.push(`${context}: field "${field.name}" must be number.`); continue; }
        if (field.min !== undefined && value < field.min) errors.push(`${context}: field "${field.name}" must be >= ${field.min}.`);
        if (field.max !== undefined && value > field.max) errors.push(`${context}: field "${field.name}" must be <= ${field.max}.`);
      }
      if (field.type === 'integer') {
        if (typeof value !== 'number' || !Number.isInteger(value)) { errors.push(`${context}: field "${field.name}" must be integer.`); continue; }
        if (field.min !== undefined && value < field.min) errors.push(`${context}: field "${field.name}" must be >= ${field.min}.`);
        if (field.max !== undefined && value > field.max) errors.push(`${context}: field "${field.name}" must be <= ${field.max}.`);
      }
      if (field.type === 'object' && (typeof value !== 'object' || Array.isArray(value))) errors.push(`${context}: field "${field.name}" must be object.`);
      if (field.type === 'array' && !Array.isArray(value)) errors.push(`${context}: field "${field.name}" must be array.`);
    }
    return errors;
  }

  private readSchemaFieldValue(record: any, fieldName: string): any {
    if (!record || typeof record !== 'object' || Array.isArray(record)) {
      return undefined;
    }

    if (Object.prototype.hasOwnProperty.call(record, fieldName)) {
      return record[fieldName];
    }

    if (!fieldName.includes('.') && !fieldName.includes('[]')) {
      return record[fieldName];
    }

    const path = fieldName.replace(/\[\]/g, '').split('.').filter(Boolean);
    return path.reduce<any>((current, segment) => {
      if (current === undefined || current === null) {
        return undefined;
      }
      return current[segment];
    }, record);
  }

  private validateValidationDatasetRows(
    rows: any[],
    selectedModels: BenchmarkAsset[],
    mapping: BenchmarkDatasetMapping | null = this.validationDatasetMapping
  ): string[] {
    if (!Array.isArray(rows) || rows.length === 0) return ['Validation dataset must contain at least one row.'];
    const errors: string[] = [];
    for (const model of selectedModels) {
      const schemaFields = this.getSchemaFieldsFromModel(model);
      const excludedKeys = new Set(schemaFields.map(field => field.name));
      const modelTask = this.detectModelTask([model]);
      if (!this.isMetricBenchmarkModel(model) && modelTask === 'unsupported') {
        errors.push(`${model.name}: output-model metrics are only available for classification or regression. Use a metric model for this task.`);
        continue;
      }

      rows.forEach((row, index) => {
        if (schemaFields.length > 0) {
          const inputRecord = this.isMetricBenchmarkModel(model) ? row : this.buildBenchmarkInputRecord(row, mapping);
          errors.push(...this.validateRecordAgainstSchema(inputRecord, schemaFields, `${model.name} row #${index + 1}`));
        }

        if (!this.isMetricBenchmarkModel(model) && modelTask === 'regression') {
          const mappedValue = this.extractDatasetExpectedValue(row, mapping);
          const expectedValue = mappedValue !== undefined
            ? this.readNumericValue(mappedValue)
            : this.extractExpectedRegressionValue(model, row, excludedKeys);
          if (!Number.isFinite(expectedValue)) {
            errors.push(`${model.name} row #${index + 1}: validation dataset must include a numeric target/label field for benchmarking.`);
          }
        } else if (!this.isMetricBenchmarkModel(model)) {
          const mappedValue = this.extractDatasetExpectedValue(row, mapping);
          const expectedValue = mappedValue !== undefined
            ? this.normalizeClassificationValue(mappedValue)
            : this.extractExpectedClassificationValue(model, row, excludedKeys);
          if (!expectedValue) {
            errors.push(`${model.name} row #${index + 1}: validation dataset must include a label/target field for benchmarking.`);
          }
        }
      });
    }
    return [...new Set(errors)];
  }

  private revalidateLoadedValidationDataset(selectedModels: BenchmarkAsset[]): void {
    const errors = this.validateValidationDatasetRows(this.validationDatasetRows, selectedModels);
    if (errors.length > 0) {
      const previousFileName = this.validationDatasetFileName;
      this.validationDatasetRows = [];
      this.validationDatasetFileName = '';
      this.validationDatasetSource = null;
      this.validationDatasetMapping = null;
      this.notificationService.showWarning(`Validation dataset (${previousFileName}) discarded — incompatible with current input schema.`);
    }
  }

  // ---------------------------------------------------------------------------
  // Output preview
  // ---------------------------------------------------------------------------

  private buildOutputPreview(output: any): string {
    if (output === undefined || output === null) return 'No output returned.';
    const serialized = typeof output === 'string' ? output : JSON.stringify(output, null, 2);
    return serialized.length <= 360 ? serialized : `${serialized.slice(0, 360)}...`;
  }

  // ---------------------------------------------------------------------------
  // File parsing
  // ---------------------------------------------------------------------------

  private parseBenchmarkDatasetPayload(fileName: string, payload: unknown): any[] {
    if (typeof payload === 'string') {
      const parsedByContent = this.parseDatasetStringByContent(payload);
      if (parsedByContent) {
        return parsedByContent;
      }
      return this.parseBatchInputFile(fileName, payload);
    }

    const normalizedPayload = this.unwrapJsonLdValue(payload);
    if (Array.isArray(normalizedPayload)) {
      return normalizedPayload;
    }

    if (normalizedPayload && typeof normalizedPayload === 'object') {
      const record = normalizedPayload as Record<string, any>;
      if (Array.isArray(record.rows)) return record.rows;
      if (Array.isArray(record.data)) return record.data;
      if (Array.isArray(record.samples)) return record.samples;
      return [record];
    }

    throw new Error('Benchmark dataset metadata must be an object, array, or CSV/JSON string.');
  }

  private parseDatasetStringByContent(content: string): any[] | null {
    const trimmed = content.trim();
    if (!trimmed.length) {
      return [];
    }

    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      let parsed: any;
      try {
        parsed = JSON.parse(trimmed);
      } catch {
        return null;
      }
      if (Array.isArray(parsed)) return parsed;
      if (parsed && typeof parsed === 'object') {
        if (Array.isArray(parsed.rows)) return parsed.rows;
        if (Array.isArray(parsed.data)) return parsed.data;
        if (Array.isArray(parsed.samples)) return parsed.samples;
        return [parsed];
      }
    }

    return null;
  }

  private normalizeBenchmarkDatasetRows(rows: any[]): any[] {
    return rows.map(row => this.unwrapJsonLdValue(row));
  }

  private unwrapJsonLdValue(value: any): any {
    if (Array.isArray(value)) {
      return value.map(item => this.unwrapJsonLdValue(item));
    }

    if (!value || typeof value !== 'object') {
      return value;
    }

    const keys = Object.keys(value);
    if (value['@value'] !== undefined && keys.length <= 2) {
      return this.unwrapJsonLdValue(value['@value']);
    }
    if (value.value !== undefined && keys.length <= 2) {
      return this.unwrapJsonLdValue(value.value);
    }

    const normalized: Record<string, any> = {};
    keys.forEach(key => {
      normalized[key] = this.unwrapJsonLdValue(value[key]);
    });
    return normalized;
  }

  private readFileAsText(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('Unable to read file content.'));
      reader.readAsText(file);
    });
  }

  private parseBatchInputFile(fileName: string, content: string): any[] {
    const lowerName = fileName.toLowerCase();
    if (lowerName.endsWith('.jsonl')) {
      return content.split('\n').map(l => l.trim()).filter(l => !!l).map((line, index) => {
        try { return JSON.parse(line); } catch { throw new Error(`JSONL parse error at line ${index + 1}.`); }
      });
    }
    if (lowerName.endsWith('.json')) {
      const parsed = JSON.parse(content);
      if (Array.isArray(parsed)) return parsed;
      if (parsed && typeof parsed === 'object') {
        if (Array.isArray(parsed.rows)) return parsed.rows;
        if (Array.isArray(parsed.data)) return parsed.data;
        if (Array.isArray(parsed.samples)) return parsed.samples;
        return [parsed];
      }
      throw new Error('JSON dataset must be an object or an array of objects.');
    }
    if (lowerName.endsWith('.csv')) return this.parseCsvToObjects(content);
    throw new Error('Unsupported file format. Use CSV, JSON, or JSONL.');
  }

  private parseCsvToObjects(content: string): any[] {
    const lines = content.split(/\r?\n/).map(l => l.trim()).filter(l => !!l);
    if (lines.length < 2) throw new Error('CSV dataset must include header and at least one data row.');
    const headers = this.splitCsvLine(lines[0]).map(h => h.trim());
    const rows: any[] = [];
    for (let i = 1; i < lines.length; i++) {
      const columns = this.splitCsvLine(lines[i]);
      const row: any = {};
      headers.forEach((header, index) => { row[header] = this.coerceCsvValue(header, columns[index] ?? ''); });
      rows.push(row);
    }
    return rows;
  }

  private splitCsvLine(line: string): string[] {
    const values: string[] = [];
    let current = '';
    let insideQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const char = line[i];
      if (char === '"') {
        if (insideQuotes && line[i + 1] === '"') { current += '"'; i++; } else { insideQuotes = !insideQuotes; }
        continue;
      }
      if (char === ',' && !insideQuotes) { values.push(current); current = ''; } else { current += char; }
    }
    values.push(current);
    return values;
  }

  private coerceCsvValue(header: string, rawValue: string): any {
    const trimmed = rawValue.trim();
    if (trimmed === '') return '';
    if (this.shouldPreserveCsvValueAsString(header)) return trimmed;
    if (trimmed.toLowerCase() === 'true') return true;
    if (trimmed.toLowerCase() === 'false') return false;
    const numeric = Number(trimmed);
    if (!Number.isNaN(numeric) && trimmed !== '') return numeric;
    return trimmed;
  }

  private shouldPreserveCsvValueAsString(header: string): boolean {
    const normalized = header.trim().toLowerCase();
    return normalized === 'id'
      || normalized.endsWith('_id')
      || normalized.endsWith('id')
      || normalized.includes('identifier')
      || normalized.includes('uuid');
  }

  // ---------------------------------------------------------------------------
  // CSV/download helpers
  // ---------------------------------------------------------------------------

  private convertObjectsToCsv(rows: any[]): string {
    if (!rows || rows.length === 0) return 'index\n';
    const normalizedRows = rows.map((row, index) => {
      if (!row || typeof row !== 'object' || Array.isArray(row)) return { index: index + 1, value: row };
      return { index: index + 1, ...row };
    });
    const headers: string[] = Array.from<string>(normalizedRows.reduce((set, row) => { Object.keys(row).forEach(key => set.add(key)); return set; }, new Set<string>()));
    const csvRows: string[] = [headers.join(',')];
    normalizedRows.forEach(row => { csvRows.push(headers.map(h => this.escapeCsvValue(row[h])).join(',')); });
    return csvRows.join('\n');
  }

  private escapeCsvValue(value: any): string {
    if (value === undefined || value === null) return '""';
    const normalized = typeof value === 'object' ? JSON.stringify(value) : String(value);
    return `"${normalized.replace(/"/g, '""')}"`;
  }

  private sanitizeFileName(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'model';
  }

  private downloadContent(content: string, fileName: string, mimeType: string): void {
    const blob = new Blob([content], { type: mimeType });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', fileName);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }
}
