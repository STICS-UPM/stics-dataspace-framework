import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { lastValueFrom } from 'rxjs';
import {
  AiModelExecutionInputFeature,
  AiModelExecutionItem,
  ModelExecutionResponsePayload
} from 'src/app/shared/models/ai-model-execution-item';
import { ModelExecutionService } from 'src/app/shared/services/model-execution.service';
import { ModelObserverJournalService } from 'src/app/shared/services/model-observer-journal.service';
import { NotificationService } from 'src/app/shared/services/notification.service';

type InputMode = 'single' | 'dataset';
type ModelTask = 'classification' | 'regression' | 'nlp' | 'vision' | 'other';
type DownloadFormat = 'csv' | 'json';

interface BenchmarkAsset {
  id: string;
  name: string;
  task: string;
  algorithm: string;
  framework: string;
  source: string;
  provider: string;
  hasAgreement: boolean;
  isLocal: boolean;
  inputFeatures: AiModelExecutionInputFeature[];
  inputSchema: any;
  inputExample?: any;
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
  cost: number;
  compositeScore?: number;
  top?: boolean;
  errorMessage?: string;
}

interface InputExecutionResult {
  modelId: string;
  modelName: string;
  status: 'success' | 'partial' | 'error';
  latencyMs: number;
  processedInputs: number;
  successfulOutputs: number;
  failedOutputs: number;
  output: any;
  outputPreview: string;
  errorMessage?: string;
}

interface InputValidationResult {
  isValid: boolean;
  errors: string[];
  normalizedInput?: any;
}

interface PrimaryOutputInfo {
  value: string;
  confidence: string;
}

interface SuggestedDataset {
  id: string;
  name: string;
  description: string;
  fileName: string;
  csvContent: string;
  rows: any[];
}

@Component({
  selector: 'app-ai-model-benchmarking',
  templateUrl: './ai-model-benchmarking.component.html',
  styleUrls: ['./ai-model-benchmarking.component.scss']
})
export class AiModelBenchmarkingComponent implements OnInit {

  // Input mode
  inputMode: InputMode = 'single';
  sampleInput = '';
  selectedFileName = '';
  datasetBatchInputs: any[] = [];
  standardizedInputFields: SchemaField[] = [];
  standardizedInputValues: Record<string, any> = {};

  // Outputs
  isObtainingOutputs = false;
  outputStatusMessage = 'No outputs generated yet.';
  modelInputOutputs: InputExecutionResult[] = [];
  outputMode: InputMode | null = null;
  globalDatasetDownloadFormat: DownloadFormat = 'json';
  datasetDownloadFormatByModel: Record<string, DownloadFormat> = {};

  // Execution state
  isRunning = false;
  statusMessage = 'Select models and configure benchmark settings to begin.';
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
  suggestedValidationDatasets: SuggestedDataset[] = [];
  selectedSuggestedDatasetId = '';

  // Ranking
  rankingRows: RankingRow[] = [];
  recommendationMetric = '';
  lastBenchmarkRunId = '';

  // Cost configuration
  costPerSecond = 0.00001;
  private readonly benchmarkBatchSize = 300;
  private readonly benchmarkRequestTimeoutMs = 10000;
  private validationDatasetSource: 'manual' | 'preset' | null = null;

  private readonly metricsConfig: Record<ModelTask, string[]> = {
    classification: ['AUC', 'GINI', 'Precision', 'Recall', 'F1 Score'],
    regression: ['RMSE', 'MAE', 'MSE', 'R2'],
    nlp: ['Accuracy', 'F1 Score', 'BLEU', 'Perplexity', 'ROUGE'],
    vision: ['Accuracy', 'Precision', 'Recall', 'mAP', 'IoU'],
    other: ['Accuracy', 'Custom Score']
  };

  constructor(
    private readonly modelExecutionService: ModelExecutionService,
    private readonly modelObserverJournalService: ModelObserverJournalService,
    private readonly notificationService: NotificationService,
    private readonly router: Router
  ) {}

  ngOnInit(): void {
    this.loadModels();
  }

  get selectedCount(): number {
    return this.selectedAssetIds.length;
  }

  get canRunBenchmark(): boolean {
    return this.selectedAssetIds.length >= 2
      && this.selectedMetrics.length > 0
      && this.validationDatasetRows.length > 0
      && !this.isRunning;
  }

  get observerAssetId(): string {
    return this.rankingRows[0]?.modelId || this.selectedAssetIds[0] || '';
  }

  get canObtainOutputs(): boolean {
    const hasSingleInput = this.inputMode === 'single'
      && (this.sampleInput.trim().length > 0 || this.standardizedInputFields.length > 0);
    const hasDatasetInput = this.inputMode === 'dataset' && this.datasetBatchInputs.length > 0;
    return this.selectedAssetIds.length > 0
      && !this.isRunning
      && !this.isObtainingOutputs
      && (hasSingleInput || hasDatasetInput);
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

  private mapToBenchmarkAsset(item: AiModelExecutionItem): BenchmarkAsset {
    return {
      id: item.id,
      name: item.name,
      task: item.tasks?.[0] || 'Unknown',
      algorithm: item.algorithms?.[0] || '',
      framework: item.frameworks?.[0] || '',
      source: item.source,
      provider: item.provider,
      hasAgreement: item.hasAgreement,
      isLocal: item.isLocal,
      inputFeatures: item.inputFeatures || [],
      inputSchema: item.inputSchema,
      inputExample: item.inputExample
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
      pool = pool.filter(model => this.inferModelTask(model) === this.activeFilter);
    }

    if (this.searchKeyword.trim()) {
      const keyword = this.searchKeyword.trim().toLowerCase();
      pool = pool.filter(m =>
        m.name.toLowerCase().includes(keyword)
        || m.task.toLowerCase().includes(keyword)
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
    if (!asset.isLocal && !asset.hasAgreement) {
      this.notificationService.showWarning('This federated model is visible in the pool, but it needs a finalized agreement before benchmarking.');
      return;
    }

    if (!this.isAssetSelected(asset) && !this.isCompatibleWithCurrentSelection(asset)) {
      const anchorModel = this.getSelectionAnchorModel();
      const anchorName = anchorModel?.name || 'the first selected model';
      this.notificationService.showWarning(`This model does not share the same input schema as ${anchorName}.`);
      return;
    }

    const index = this.selectedAssetIds.indexOf(asset.id);
    if (index >= 0) {
      this.selectedAssetIds.splice(index, 1);
    } else {
      this.selectedAssetIds.push(asset.id);
    }
    this.updateTaskAndMetrics();
  }

  private updateTaskAndMetrics(): void {
    const selectedModels = this.modelPoolAssets.filter(m => this.selectedAssetIds.includes(m.id));

    if (selectedModels.length === 0) {
      this.detectedTask = null;
      this.availableMetrics = [];
      this.selectedMetrics = [];
      this.standardizedInputFields = [];
      this.standardizedInputValues = {};
      this.clearSuggestedValidationDatasets();
      this.filterModelPool();
      return;
    }

    this.detectedTask = this.detectModelTask(selectedModels);
    this.availableMetrics = this.metricsConfig[this.detectedTask] || this.metricsConfig.other;
    this.selectedMetrics = [...this.availableMetrics];
    this.recommendationMetric = this.selectedMetrics[0] || '';
    this.initializeStandardizedSingleInput(selectedModels);

    if (this.validationDatasetRows.length > 0) {
      this.revalidateLoadedValidationDataset(selectedModels);
    }

    this.syncSuggestedValidationDatasets(selectedModels);
    this.filterModelPool();
  }

  private inferModelTask(model: BenchmarkAsset): ModelTask {
    const task = model.task.toLowerCase();
    const algorithm = model.algorithm.toLowerCase();

    if (task.includes('natural') && task.includes('language')) return 'nlp';
    if (task.includes('nlp') || task.includes('text') || task.includes('sentiment')) return 'nlp';
    if (task.includes('computer') && task.includes('vision')) return 'vision';
    if (task.includes('vision') || task.includes('image') || task.includes('detection')) return 'vision';
    if (task.includes('regress') || algorithm.includes('regress') || this.getPreferredRegressionKeys(model).length > 0) return 'regression';
    if (task.includes('classif') || task.includes('tabular') || task.includes('predictive') || algorithm.includes('classif') || this.getPreferredClassificationKeys(model).length > 0) return 'classification';

    return 'other';
  }

  private detectModelTask(models: BenchmarkAsset[]): ModelTask {
    const tasks = models.map(m => this.inferModelTask(m));
    const uniqueTasks = [...new Set(tasks)];

    return uniqueTasks.length === 1 ? uniqueTasks[0] : 'other';
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
    if (!this.selectedMetrics.includes(this.recommendationMetric) && this.selectedMetrics.length > 0) {
      this.recommendationMetric = this.selectedMetrics[0];
    }
  }

  getAssetMeta(asset: BenchmarkAsset): string {
    const parts = [asset.task, asset.algorithm, asset.provider].filter(Boolean);
    return parts.length > 0 ? parts.join(' · ') : 'HTTP Model';
  }

  getModelPoolSubtitle(): string {
    const anchorModel = this.getSelectionAnchorModel();
    if (!anchorModel) {
      return 'Select 2+ HTTP models with compatible inputs';
    }

    return `Compatible input models for ${anchorModel.name}`;
  }

  getValidationDatasetSubtitle(): string {
    const anchorModel = this.getSelectionAnchorModel();
    if (!anchorModel) {
      return 'Upload a validation dataset for Run Benchmark';
    }

    return `Suggested CSV datasets aligned to ${anchorModel.name}, with manual upload still available.`;
  }

  // ---------------------------------------------------------------------------
  // Input modes
  // ---------------------------------------------------------------------------

  setInputMode(mode: InputMode): void {
    this.inputMode = mode;
  }

  onSingleFieldValueChange(field: SchemaField, value: any): void {
    if (field.type === 'number' || field.type === 'integer') {
      this.standardizedInputValues[field.name] = Number(value);
    } else {
      this.standardizedInputValues[field.name] = value;
    }
    this.syncSampleInputFromStandardizedValues();
  }

  getSingleFieldInputType(field: SchemaField): string {
    if (field.type === 'number' || field.type === 'integer') return 'number';
    return 'text';
  }

  getFieldConstraintsText(field: SchemaField): string {
    const parts: string[] = [field.type];
    if (field.required) parts.push('required');
    if (field.min !== undefined) parts.push(`min: ${field.min}`);
    if (field.max !== undefined) parts.push(`max: ${field.max}`);
    if (field.description) parts.push(field.description);
    return parts.join(' · ');
  }

  // ---------------------------------------------------------------------------
  // File handling
  // ---------------------------------------------------------------------------

  async handleFileSelection(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    this.selectedFileName = file ? file.name : '';

    if (!file) {
      this.datasetBatchInputs = [];
      return;
    }

    try {
      const content = await this.readFileAsText(file);
      const parsed = this.parseBatchInputFile(file.name, content);
      if (parsed.length === 0) {
        throw new Error('The uploaded dataset has no rows.');
      }
      this.datasetBatchInputs = parsed;
      this.outputStatusMessage = `Dataset loaded: ${parsed.length} row(s) ready for validation/execution.`;
      this.notificationService.showInfo(`Dataset loaded (${parsed.length} rows)`);
    } catch (error: any) {
      this.datasetBatchInputs = [];
      this.outputStatusMessage = 'Dataset parsing failed. Please upload a valid CSV, JSON, or JSONL file.';
      this.notificationService.showError(error?.message || 'Could not parse dataset file');
    }
  }

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

      const validationErrors = this.validateValidationDatasetRows(parsedRows, selectedModels);
      if (validationErrors.length > 0) {
        this.notificationService.showError(`Validation dataset invalid: ${validationErrors[0]}`);
        this.statusMessage = `Validation dataset invalid: ${validationErrors[0]}`;
        input.value = '';
        return;
      }

      this.validationDatasetRows = parsedRows;
      this.validationDatasetFileName = file.name;
      this.validationDatasetSource = 'manual';
      this.statusMessage = `Validation dataset loaded and validated (${parsedRows.length} rows).`;
      this.notificationService.showInfo(`Validation dataset valid (${parsedRows.length} rows)`);
    } catch (error: any) {
      this.validationDatasetRows = [];
      this.validationDatasetFileName = '';
      this.validationDatasetSource = null;
      this.notificationService.showError(error?.message || 'Could not load validation dataset');
      this.statusMessage = 'Could not load validation dataset.';
      input.value = '';
    }
  }

  selectSuggestedDataset(dataset: SuggestedDataset): void {
    this.applySuggestedDataset(dataset, true);
  }

  downloadSuggestedDataset(dataset: SuggestedDataset, event?: Event): void {
    event?.stopPropagation();
    this.downloadContent(dataset.csvContent, dataset.fileName, 'text/csv;charset=utf-8;');
  }

  isSuggestedDatasetSelected(dataset: SuggestedDataset): boolean {
    return this.selectedSuggestedDatasetId === dataset.id;
  }

  // ---------------------------------------------------------------------------
  // Suggested datasets and compatibility
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

    const referenceFields = this.getSchemaFieldsFromModel(referenceModel);
    const candidateFields = this.getSchemaFieldsFromModel(candidateModel);
    if (referenceFields.length > 0 || candidateFields.length > 0) {
      return this.areSchemaFieldsEquivalent(referenceFields, candidateFields);
    }

    const referenceSignature = this.buildInputSignature(referenceModel);
    const candidateSignature = this.buildInputSignature(candidateModel);
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

  private syncSuggestedValidationDatasets(selectedModels: BenchmarkAsset[]): void {
    const anchorModel = selectedModels[0];
    const nextDatasets = this.buildSuggestedDatasetsForModel(anchorModel);
    this.suggestedValidationDatasets = nextDatasets;

    if (nextDatasets.length === 0) {
      this.clearSuggestedValidationDatasets();
      return;
    }

    const currentDataset = nextDatasets.find(dataset => dataset.id === this.selectedSuggestedDatasetId)
      || nextDatasets.find(dataset => dataset.id === `${anchorModel.id}-comparison`)
      || nextDatasets[0];
    if (!this.validationDatasetRows.length || this.validationDatasetSource === 'preset') {
      this.applySuggestedDataset(currentDataset, false);
    }
  }

  private clearSuggestedValidationDatasets(): void {
    this.suggestedValidationDatasets = [];
    this.selectedSuggestedDatasetId = '';

    if (this.validationDatasetSource === 'preset') {
      this.validationDatasetRows = [];
      this.validationDatasetFileName = '';
      this.validationDatasetSource = null;
    }
  }

  private applySuggestedDataset(dataset: SuggestedDataset, notifyUser: boolean): void {
    const selectedModels = this.modelPoolAssets.filter(model => this.selectedAssetIds.includes(model.id));
    const clonedRows = dataset.rows.map(row => ({ ...row }));
    const validationErrors = this.validateValidationDatasetRows(clonedRows, selectedModels);
    if (validationErrors.length > 0) {
      this.notificationService.showWarning(`Suggested dataset ${dataset.name} is not compatible with the current selection.`);
      return;
    }

    this.selectedSuggestedDatasetId = dataset.id;
    this.validationDatasetRows = clonedRows;
    this.validationDatasetFileName = dataset.fileName;
    this.validationDatasetSource = 'preset';
    this.statusMessage = `Suggested validation dataset loaded (${clonedRows.length} rows).`;

    if (notifyUser) {
      this.notificationService.showInfo(`Suggested dataset selected: ${dataset.name}`);
    }
  }

  private buildSuggestedDatasetsForModel(model: BenchmarkAsset): SuggestedDataset[] {
    const fullRows = this.buildSuggestedDatasetRows(model);
    if (fullRows.length === 0) {
      return [];
    }

    const baseFileName = `${this.sanitizeFileName(model.name)}-benchmark-sample`;
    const comparisonRows = fullRows.slice(0, Math.min(200, fullRows.length));
    const starterRows = comparisonRows.slice(0, Math.min(25, comparisonRows.length));

    return [
      this.createSuggestedDataset(
        `${model.id}-starter`,
        'Starter CSV',
        `Small coherent dataset aligned to ${model.name}.`,
        `${baseFileName}-starter.csv`,
        starterRows
      ),
      this.createSuggestedDataset(
        `${model.id}-comparison`,
        'Comparison CSV',
        `Extended dataset aligned to ${model.name} for quick comparisons.`,
        `${baseFileName}-comparison.csv`,
        comparisonRows
      )
    ];
  }

  private createSuggestedDataset(id: string, name: string, description: string, fileName: string, rows: any[]): SuggestedDataset {
    const clonedRows = rows.map(row => ({ ...row }));
    return {
      id,
      name,
      description,
      fileName,
      rows: clonedRows,
      csvContent: this.convertDatasetRowsToCsv(clonedRows)
    };
  }

  private buildSuggestedDatasetRows(model: BenchmarkAsset): any[] {
    const signature = this.buildInputSignature(model);

    switch (signature) {
      case 'height_m|weight_kg':
        return this.buildHealthSuggestedRows(model);
      case 'text':
        return this.buildTextSuggestedRows(model);
      case 'petal_length|petal_width|sepal_length|sepal_width':
        return this.buildFloraSuggestedRows(model);
      case 'amount|location|merchant_category|timestamp':
        return this.buildFraudSuggestedRows(model);
      case 'image_size|image_url':
        return this.buildVisionSuggestedRows(model);
      default:
        return [];
    }
  }

  private buildInputSignature(model: BenchmarkAsset): string {
    const fields = this.getSchemaFieldsFromModel(model);
    if (fields.length > 0) {
      return [...fields].map(field => field.name).sort().join('|');
    }

    const example = this.parseObjectLikeValue(model.inputExample);
    if (!example) {
      return '';
    }

    return Object.keys(example).sort().join('|');
  }

  private buildHealthSuggestedRows(model: BenchmarkAsset): any[] {
    return Array.from({ length: 200 }, (_, index) => {
      const height_m = this.roundNumber(1.48 + (((index * 7) % 39) / 100) + ((index % 4) * 0.005), 2);
      const weight_kg = Math.round(this.boundNumber(47 + ((index * 11) % 63) + ((index % 5) * 0.6), 45, 125));
      const seed = { weight_kg, height_m };
      const bmi = this.roundNumber(seed.weight_kg / (seed.height_m ** 2), 2);
      const bodyFat = this.roundNumber(this.boundNumber((1.2 * bmi) + (0.23 * 30) - 5.4, 5, 50), 1);
      const bmr = Math.round((10 * seed.weight_kg) + ((seed.height_m * 100) * 6.25) - (5 * 30) + 5);
      const idealWeight = this.roundNumber(this.boundNumber(48 + (2.7 * (((seed.height_m * 100) - 152.4) / 2.54)), 45, 120), 1);
      const riskScore = bmi < 18.5 ? 30 : bmi >= 30 ? 70 : bmi >= 25 ? 40 : 10;

      const row: Record<string, string | number | boolean> = {
        ...seed,
        bmi,
        body_fat_percentage: bodyFat,
        bmr_calories: bmr,
        ideal_weight_kg: idealWeight,
        risk_score: riskScore,
        label: 0
      };

      row.label = this.resolveSuggestedDatasetLabel(model, row);
      return row;
    });
  }

  private buildTextSuggestedRows(model: BenchmarkAsset): any[] {
    const scenarios = [
      {
        sentiment: 'positive',
        review_sentiment: 'very_positive',
        customer_sentiment: 'satisfied',
        social_sentiment: 'positive',
        phrases: ['excellent', 'fast', 'useful', 'stable']
      },
      {
        sentiment: 'negative',
        review_sentiment: 'very_negative',
        customer_sentiment: 'dissatisfied',
        social_sentiment: 'negative',
        phrases: ['poor', 'broken', 'slow', 'frustrating']
      },
      {
        sentiment: 'neutral',
        review_sentiment: 'neutral',
        customer_sentiment: 'neutral',
        social_sentiment: 'neutral',
        phrases: ['acceptable', 'consistent', 'predictable', 'standard']
      },
      {
        sentiment: 'positive',
        review_sentiment: 'positive',
        customer_sentiment: 'satisfied',
        social_sentiment: 'mixed',
        phrases: ['unexpected', 'useful', 'helpful', 'innovative']
      },
      {
        sentiment: 'negative',
        review_sentiment: 'negative',
        customer_sentiment: 'dissatisfied',
        social_sentiment: 'negative',
        phrases: ['refund', 'delay', 'support', 'issue']
      }
    ];
    const products = ['analytics workflow', 'benchmark dashboard', 'model browser', 'connector interface', 'validation wizard'];

    return Array.from({ length: 200 }, (_, index) => {
      const scenario = scenarios[index % scenarios.length];
      const product = products[index % products.length];
      const phraseA = scenario.phrases[index % scenario.phrases.length];
      const phraseB = scenario.phrases[(index + 2) % scenario.phrases.length];
      const row = {
        text: `Sample ${index + 1}: The ${product} feels ${phraseA} and ${phraseB} for daily operations.`,
        sentiment: scenario.sentiment,
        review_sentiment: scenario.review_sentiment,
        customer_sentiment: scenario.customer_sentiment,
        social_sentiment: scenario.social_sentiment
      };

      return {
        ...row,
        label: this.resolveSuggestedDatasetLabel(model, row)
      };
    });
  }

  private buildFloraSuggestedRows(model: BenchmarkAsset): any[] {
    const irisClusters = [
      { iris_prediction: 'setosa', sepal_length: 5.0, sepal_width: 3.5, petal_length: 1.5, petal_width: 0.2 },
      { iris_prediction: 'versicolor', sepal_length: 5.9, sepal_width: 2.8, petal_length: 4.3, petal_width: 1.3 },
      { iris_prediction: 'virginica', sepal_length: 6.5, sepal_width: 3.0, petal_length: 5.5, petal_width: 2.0 }
    ];
    const flowerPredictions = ['Daisy', 'Rose', 'Sunflower', 'Lily', 'Tulip'];
    const plantPredictions = ['Pothos', 'Snake Plant', 'Ficus', 'Peace Lily', 'Monstera'];
    const families = ['Asteraceae', 'Rosaceae', 'Fabaceae', 'Solanaceae', 'Lamiaceae'];
    const categories = ['Grass', 'Succulent', 'Flowering Plant', 'Fern', 'Tropical'];

    return Array.from({ length: 200 }, (_, index) => {
      const cluster = irisClusters[index % irisClusters.length];
      const delta = (index % 10) * 0.03;
      const row = {
        sepal_length: this.roundNumber(cluster.sepal_length + delta, 1),
        sepal_width: this.roundNumber(cluster.sepal_width + ((index % 5) * 0.02), 1),
        petal_length: this.roundNumber(cluster.petal_length + ((index % 7) * 0.04), 1),
        petal_width: this.roundNumber(cluster.petal_width + ((index % 4) * 0.03), 1),
        iris_prediction: cluster.iris_prediction,
        flower_prediction: flowerPredictions[index % flowerPredictions.length],
        plant_prediction: plantPredictions[(index + 1) % plantPredictions.length],
        family: families[(index + 2) % families.length],
        category: categories[(index + 3) % categories.length]
      };

      return {
        ...row,
        label: this.resolveSuggestedDatasetLabel(model, row)
      };
    });
  }

  private buildFraudSuggestedRows(model: BenchmarkAsset): any[] {
    const merchantCategories = ['retail', 'travel', 'crypto', 'grocery', 'luxury', 'gaming'];
    const locations = ['local', 'international', 'cross-border', 'offshore'];
    const fraudTypes = ['Legitimate', 'Suspicious', 'Card Fraud', 'Identity Theft'];

    return Array.from({ length: 200 }, (_, index) => {
      const amount = Math.round(35 + ((index * 137) % 6900) + ((index % 9) * 3.5));
      const merchant_category = merchantCategories[index % merchantCategories.length];
      const location = locations[index % locations.length];
      const hour = (index * 3) % 24;
      const timestamp = `2026-05-${String((index % 28) + 1).padStart(2, '0')}T${String(hour).padStart(2, '0')}:${String((index * 7) % 60).padStart(2, '0')}:00Z`;
      const riskBand = amount > 2500 || location !== 'local' || merchant_category === 'crypto' ? 'High' : amount > 900 ? 'Medium' : 'Low';
      const isFraud = riskBand === 'High';
      const isAnomaly = isFraud || merchant_category === 'gaming';
      const decision = isFraud ? (amount > 5000 ? 'Block' : 'Review') : 'Approve';
      const fraud_type = isFraud ? fraudTypes[(index % (fraudTypes.length - 1)) + 1] : fraudTypes[0];
      const row = {
        amount,
        merchant_category,
        location,
        timestamp,
        is_fraud: isFraud,
        is_anomaly: isAnomaly,
        decision,
        risk_band: riskBand,
        fraud_type
      };

      return {
        ...row,
        label: this.resolveSuggestedDatasetLabel(model, row)
      };
    });
  }

  private buildVisionSuggestedRows(model: BenchmarkAsset): any[] {
    const predictions = ['Normal', 'Pneumonia', 'Positive', 'Lung Cancer', 'TB_Suspected'];
    const sizes = ['512x512', '768x768', '900x900', '1024x1024', '1400x1200'];

    return Array.from({ length: 200 }, (_, index) => {
      const prediction = predictions[index % predictions.length];
      const row = {
        image_url: `https://example.org/benchmark/scan-${String(index + 1).padStart(3, '0')}.png`,
        image_size: sizes[index % sizes.length],
        vision_prediction: prediction,
        has_nodule: prediction === 'Lung Cancer'
      };

      return {
        ...row,
        label: this.resolveSuggestedDatasetLabel(model, row)
      };
    });
  }

  private resolveSuggestedDatasetLabel(model: BenchmarkAsset, row: Record<string, any>): string | number | boolean {
    const preferredKeys = this.detectModelTask([model]) === 'regression'
      ? this.getPreferredRegressionKeys(model)
      : this.getPreferredClassificationKeys(model);
    const preferredValue = this.findComparableValue(row, preferredKeys);
    if (preferredValue !== undefined) {
      return preferredValue;
    }

    return row.label ?? row.sentiment ?? row.vision_prediction ?? row.flower_prediction ?? row.bmi ?? '';
  }

  private getPreferredRegressionKeys(model: BenchmarkAsset): string[] {
    const identity = this.getModelIdentity(model);

    if (identity.includes('bmi')) return ['bmi'];
    if (identity.includes('body fat') || identity.includes('body-fat')) return ['body_fat_percentage'];
    if (identity.includes('bmr')) return ['bmr_calories'];
    if (identity.includes('ideal weight') || identity.includes('ideal-weight')) return ['ideal_weight_kg'];
    if (identity.includes('health risk') || identity.includes('risk assessment') || identity.includes('risk-assessment')) return ['risk_score'];

    return [];
  }

  private getPreferredClassificationKeys(model: BenchmarkAsset): string[] {
    const identity = this.getModelIdentity(model);

    if (identity.includes('customer feedback') || identity.includes('customer-feedback')) return ['customer_sentiment', 'sentiment'];
    if (identity.includes('product review') || identity.includes('product-review')) return ['review_sentiment', 'sentiment'];
    if (identity.includes('social media') || identity.includes('social-media')) return ['social_sentiment', 'sentiment'];
    if (identity.includes('fraud/transaction') || identity.includes('fraud detector') || identity.includes('fraud-transaction')) return ['is_fraud'];
    if (identity.includes('credit card') || identity.includes('credit-card')) return ['decision'];
    if (identity.includes('anomaly')) return ['is_anomaly'];
    if (identity.includes('risk scorer') || identity.includes('risk-scorer')) return ['risk_band'];
    if (identity.includes('fraud classifier') || identity.includes('fraud/classifier')) return ['fraud_type'];
    if (identity.includes('lung nodule') || identity.includes('lung-nodule')) return ['has_nodule'];
    if (identity.includes('iris')) return ['iris_prediction'];
    if (identity.includes('flower')) return ['flower_prediction'];
    if (identity.includes('plant')) return ['plant_prediction'];
    if (identity.includes('flora')) return ['category'];
    if (identity.includes('botanical')) return ['family'];
    if (identity.includes('sentiment')) return ['sentiment'];
    if (identity.includes('vision') || identity.includes('x-ray') || identity.includes('pneumonia') || identity.includes('covid') || identity.includes('tuberculosis')) return ['vision_prediction', 'prediction'];

    return [];
  }

  private getModelIdentity(model: BenchmarkAsset): string {
    return `${model.id} ${model.name}`.toLowerCase();
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

  private roundNumber(value: number, decimals: number): number {
    const factor = 10 ** decimals;
    return Math.round(value * factor) / factor;
  }

  private boundNumber(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
  }

  private convertDatasetRowsToCsv(rows: any[]): string {
    if (!rows || rows.length === 0) {
      return 'label\n';
    }

    const headers: string[] = Array.from(rows.reduce<Set<string>>((set, row) => {
      Object.keys(row || {}).forEach(key => set.add(key));
      return set;
    }, new Set<string>()));

    const csvRows: string[] = [headers.join(',')];
    rows.forEach(row => {
      csvRows.push(headers.map(header => this.escapeCsvValue(row?.[header])).join(','));
    });

    return csvRows.join('\n');
  }

  // ---------------------------------------------------------------------------
  // Validate schema
  // ---------------------------------------------------------------------------

  validateSchema(): void {
    const validation = this.validateCurrentInput();
    if (validation.isValid) {
      this.statusMessage = 'Input validated successfully against selected model schema.';
      this.outputStatusMessage = 'Input validation passed. You can now obtain outputs.';
      this.notificationService.showInfo('Input is valid for selected model(s)');
    } else {
      const firstError = validation.errors[0] || 'Invalid input.';
      const moreErrors = validation.errors.length > 1 ? ` (+${validation.errors.length - 1} more)` : '';
      this.statusMessage = `Input validation failed: ${firstError}${moreErrors}`;
      this.outputStatusMessage = `Input validation failed: ${firstError}${moreErrors}`;
      this.notificationService.showError(`Validation failed: ${firstError}`);
    }
  }

  // ---------------------------------------------------------------------------
  // Obtain Outputs
  // ---------------------------------------------------------------------------

  async obtainOutputs(): Promise<void> {
    if (!this.canObtainOutputs) {
      this.notificationService.showWarning('Select model(s) and provide input data first');
      return;
    }

    const validation = this.validateCurrentInput();
    if (!validation.isValid) {
      this.outputStatusMessage = `Cannot execute: ${validation.errors[0] || 'Invalid input.'}`;
      this.notificationService.showError(`Validation failed: ${validation.errors[0] || 'Invalid input.'}`);
      return;
    }

    const selectedModels = this.modelPoolAssets.filter(m => this.selectedAssetIds.includes(m.id));
    const normalizedInput = validation.normalizedInput;

    this.isObtainingOutputs = true;
    this.modelInputOutputs = [];
    this.outputMode = this.inputMode;
    this.datasetDownloadFormatByModel = {};
    this.outputStatusMessage = 'Executing selected model(s) with Benchmark Inputs...';

    try {
      for (const model of selectedModels) {
        const startTime = Date.now();

        if (this.inputMode === 'single') {
          try {
            const response = await this.executeModel(model.id, normalizedInput);
            const output = this.extractExecutionOutput(response);
            this.modelInputOutputs.push({
              modelId: model.id, modelName: model.name, status: 'success',
              latencyMs: Date.now() - startTime, processedInputs: 1,
              successfulOutputs: 1, failedOutputs: 0,
              output, outputPreview: this.buildOutputPreview(output)
            });
          } catch (error: any) {
            this.modelInputOutputs.push({
              modelId: model.id, modelName: model.name, status: 'error',
              latencyMs: Date.now() - startTime, processedInputs: 1,
              successfulOutputs: 0, failedOutputs: 1,
              output: null, outputPreview: 'Execution failed.',
              errorMessage: error?.message || 'Unknown execution error'
            });
          }
        } else {
          const rows = Array.isArray(normalizedInput) ? normalizedInput : [];
          const outputs: any[] = [];
          let successfulOutputs = 0;
          let failedOutputs = 0;
          let firstErrorMessage = '';

          for (const row of rows) {
            try {
              const response = await this.executeModel(model.id, row);
              outputs.push(this.extractExecutionOutput(response));
              successfulOutputs += 1;
            } catch (error: any) {
              failedOutputs += 1;
              if (!firstErrorMessage) {
                firstErrorMessage = error?.message || 'Unknown execution error';
              }
            }
          }

          const status: 'success' | 'partial' | 'error' =
            failedOutputs === 0 ? 'success' : successfulOutputs > 0 ? 'partial' : 'error';

          this.modelInputOutputs.push({
            modelId: model.id, modelName: model.name, status,
            latencyMs: Date.now() - startTime, processedInputs: rows.length,
            successfulOutputs, failedOutputs,
            output: outputs, outputPreview: this.buildOutputPreview(outputs),
            errorMessage: firstErrorMessage || undefined
          });
        }
      }

      const successCount = this.modelInputOutputs.filter(r => r.status === 'success').length;
      const partialCount = this.modelInputOutputs.filter(r => r.status === 'partial').length;
      const errorCount = this.modelInputOutputs.filter(r => r.status === 'error').length;
      this.outputStatusMessage = `Outputs ready. Success: ${successCount}, Partial: ${partialCount}, Errors: ${errorCount}.`;
      this.notificationService.showInfo('Model outputs generated');
    } catch (error: any) {
      this.outputStatusMessage = `Output execution failed: ${error?.message || 'Unknown error'}`;
      this.notificationService.showError('Failed to obtain outputs');
    } finally {
      this.isObtainingOutputs = false;
    }
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
      const datasetValidationErrors = this.validateValidationDatasetRows(datasetRows, selectedModels);
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
            cost: benchmarkResult.cost
          });
        } catch (error: any) {
          results.push({
            rank: 0, modelId: model.id, modelName: model.name,
            metrics: {}, latency: 0, cost: 0,
            errorMessage: error?.message || 'Benchmark execution failed.'
          });
        }
      }

      const successfulResultCount = results.filter(row => this.getMetricValue(row, this.recommendationMetric) !== null).length;
      if (successfulResultCount === 0) {
        throw new Error('All selected models failed during benchmark execution. Review the execution errors shown in Outputs or connector logs.');
      }

      this.rankingRows = this.rankResults(results);
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
  ): Promise<{ metrics: Record<string, number>; averageLatency: number; cost: number; successCount: number }> {
    const totalRows = datasetRows.length;
    const batchSize = Math.max(1, Math.min(this.benchmarkBatchSize, totalRows));
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

      const settledBatch = await Promise.all(
        batchRows.map(async (row, rowOffset) => {
          const startedAt = Date.now();
          try {
            const result = await this.executeModel(model.id, row, this.benchmarkRequestTimeoutMs, benchmarkRunId, correlationId, model.name);
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

    const comparablePairCount = this.detectedTask === 'regression'
      ? this.buildRegressionPairs(model, datasetRows, predictions).length
      : this.buildClassificationPairs(model, datasetRows, predictions).length;
    if (comparablePairCount === 0) {
      throw new Error(`No comparable predictions were produced for ${model.name}. Ensure the validation dataset contains the expected target field.`);
    }

    const metrics = this.calculateMetrics(model, datasetRows, predictions, this.detectedTask!);

    return {
      metrics,
      averageLatency: totalRows > 0 ? totalLatency / totalRows : 0,
      cost: this.calculateCost(totalLatency),
      successCount
    };
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

  // ---------------------------------------------------------------------------
  // Metrics calculation (simulated)
  // ---------------------------------------------------------------------------

  private calculateMetrics(model: BenchmarkAsset, datasetRows: any[], predictions: any[], taskType: ModelTask): Record<string, number> {
    const metrics: Record<string, number> = {};

    const regressionPairs = this.buildRegressionPairs(model, datasetRows, predictions);
    const classificationPairs = this.buildClassificationPairs(model, datasetRows, predictions);

    const accuracy = this.computeClassificationAccuracy(classificationPairs);
    const precision = this.computeMacroPrecision(classificationPairs);
    const recall = this.computeMacroRecall(classificationPairs);
    const f1Score = this.computeMacroF1(classificationPairs);
    const auc = this.computeBinaryAuc(classificationPairs);
    const mae = this.computeMae(regressionPairs);
    const mse = this.computeMse(regressionPairs);
    const rmse = Math.sqrt(mse);
    const r2 = this.computeR2(regressionPairs);
    const rankingScore = taskType === 'regression'
      ? (Number.isFinite(rmse) ? 1 / (1 + rmse) : 0)
      : accuracy;

    this.selectedMetrics.forEach(metric => {
      switch (metric) {
        case 'AUC':
          metrics['AUC'] = auc;
          break;
        case 'GINI':
          metrics['GINI'] = (2 * auc) - 1;
          break;
        case 'Precision':
          metrics['Precision'] = precision;
          break;
        case 'Recall':
          metrics['Recall'] = recall;
          break;
        case 'F1 Score':
          metrics['F1 Score'] = f1Score;
          break;
        case 'RMSE':
          metrics['RMSE'] = rmse;
          break;
        case 'MAE':
          metrics['MAE'] = mae;
          break;
        case 'MSE':
          metrics['MSE'] = mse;
          break;
        case 'R2':
          metrics['R2'] = r2;
          break;
        case 'BLEU':
          metrics['BLEU'] = accuracy;
          break;
        case 'Perplexity':
          metrics['Perplexity'] = classificationPairs.length > 0 ? 1 / Math.max(accuracy, 0.0001) : 0;
          break;
        case 'ROUGE':
          metrics['ROUGE'] = recall;
          break;
        case 'mAP':
          metrics['mAP'] = precision;
          break;
        case 'IoU':
          metrics['IoU'] = this.computeIntersectionOverUnion(classificationPairs);
          break;
        case 'Accuracy':
          metrics['Accuracy'] = accuracy;
          break;
        case 'Custom Score':
          metrics['Custom Score'] = rankingScore;
          break;
        default:
          metrics[metric] = rankingScore;
      }
    });

    return metrics;
  }

  private buildClassificationPairs(
    model: BenchmarkAsset,
    datasetRows: any[],
    predictions: any[]
  ): Array<{ actual: string; predicted: string; score: number }> {
    const excludedKeys = new Set(this.getSchemaFieldsFromModel(model).map(field => field.name));
    const pairs: Array<{ actual: string; predicted: string; score: number }> = [];

    datasetRows.forEach((row, index) => {
      const actual = this.extractExpectedClassificationValue(model, row, excludedKeys);
      const predicted = this.extractComparableClassificationValue(model, predictions[index]);
      if (!actual || !predicted) {
        return;
      }

      pairs.push({
        actual,
        predicted,
        score: this.extractPredictionScore(predictions[index], predicted)
      });
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
    const preferredValue = this.findComparableValue(row, this.getPreferredClassificationKeys(model));
    if (preferredValue !== undefined) {
      return this.normalizeClassificationValue(preferredValue);
    }

    return this.normalizeClassificationValue(this.findComparableValue(row, [
      'label', 'target', 'expected', 'ground_truth', 'groundTruth', 'actual', 'y',
      'prediction', 'sentiment', 'category', 'risk_level', 'fraud_type', 'decision',
      'is_fraud', 'is_anomaly', 'has_nodule', 'nodule_type', 'family', 'risk_band',
      'recommended_action', 'engagement_prediction', 'action_required', 'edible',
      'requires_investigation'
    ], excludedKeys));
  }

  private extractExpectedRegressionValue(model: BenchmarkAsset, row: any, excludedKeys: Set<string>): number {
    const preferredValue = this.findComparableValue(row, this.getPreferredRegressionKeys(model));
    if (preferredValue !== undefined) {
      return this.readNumericValue(preferredValue);
    }

    return this.readNumericValue(this.findComparableValue(row, [
      'label', 'target', 'expected', 'ground_truth', 'groundTruth', 'actual', 'y', 'value',
      'bmi', 'body_fat_percentage', 'bmr_calories', 'ideal_weight_kg', 'risk_score',
      'fraud_score', 'fraud_probability', 'anomaly_score', 'rating_prediction',
      'satisfaction_score', 'virality_score', 'deviation_percentage'
    ], excludedKeys));
  }

  private extractComparableClassificationValue(model: BenchmarkAsset, output: any): string | null {
    if (output === undefined || output === null) {
      return null;
    }

    if (typeof output !== 'object' || Array.isArray(output)) {
      return this.normalizeClassificationValue(output);
    }

    const preferredValue = this.findComparableValue(output, this.getPreferredClassificationKeys(model));
    if (preferredValue !== undefined) {
      return this.normalizeClassificationValue(preferredValue);
    }

    return this.normalizeClassificationValue(this.findComparableValue(output, [
      'prediction', 'sentiment', 'category', 'risk_level', 'fraud_type', 'decision', 'is_fraud',
      'is_anomaly', 'has_nodule', 'nodule_type', 'family', 'risk_band', 'recommended_action',
      'engagement_prediction', 'action_required', 'edible', 'requires_investigation', 'value'
    ]));
  }

  private extractComparableRegressionValue(model: BenchmarkAsset, output: any): number {
    if (output === undefined || output === null) {
      return Number.NaN;
    }

    if (typeof output !== 'object' || Array.isArray(output)) {
      return this.readNumericValue(output);
    }

    const preferredValue = this.findComparableValue(output, this.getPreferredRegressionKeys(model));
    if (preferredValue !== undefined) {
      return this.readNumericValue(preferredValue);
    }

    return this.readNumericValue(this.findComparableValue(output, [
      'value', 'prediction', 'bmi', 'body_fat_percentage', 'bmr_calories', 'ideal_weight_kg',
      'risk_score', 'fraud_score', 'fraud_probability', 'anomaly_score', 'rating_prediction',
      'satisfaction_score', 'virality_score', 'deviation_percentage'
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

    return String(value).trim().toLowerCase();
  }

  private readNumericValue(value: any): number {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : Number.NaN;
    }

    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : Number.NaN;
  }

  private extractPredictionScore(output: any, predictedValue: string): number {
    if (!output || typeof output !== 'object' || Array.isArray(output)) {
      return predictedValue ? 1 : 0;
    }

    const confidence = this.readNumericValue(output.confidence ?? output.probability ?? output.score ?? output.fraud_probability ?? output.fraud_score ?? output.anomaly_score);
    if (Number.isFinite(confidence)) {
      if (confidence > 1) {
        return Math.max(0, Math.min(1, confidence / 100));
      }
      return Math.max(0, Math.min(1, confidence));
    }

    return predictedValue ? 1 : 0;
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

  private computeIntersectionOverUnion(pairs: Array<{ actual: string; predicted: string }>): number {
    const labels = this.collectDistinctLabels(pairs);
    if (labels.length === 0) {
      return 0;
    }

    const total = labels.reduce((sum, label) => {
      const intersection = pairs.filter(pair => pair.actual === label && pair.predicted === label).length;
      const union = pairs.filter(pair => pair.actual === label || pair.predicted === label).length;
      return sum + (union === 0 ? 0 : intersection / union);
    }, 0);

    return total / labels.length;
  }

  private computeBinaryAuc(pairs: Array<{ actual: string; predicted: string; score: number }>): number {
    const labels = this.collectDistinctLabels(pairs);
    if (labels.length !== 2) {
      return this.computeClassificationAccuracy(pairs);
    }

    const positiveLabel = this.choosePositiveLabel(labels);
    const scoredPairs = pairs.map(pair => ({
      actual: pair.actual === positiveLabel ? 1 : 0,
      score: pair.predicted === positiveLabel ? pair.score : 1 - pair.score
    }));

    const positives = scoredPairs.filter(pair => pair.actual === 1);
    const negatives = scoredPairs.filter(pair => pair.actual === 0);
    if (positives.length === 0 || negatives.length === 0) {
      return this.computeClassificationAccuracy(pairs);
    }

    let wins = 0;
    let ties = 0;
    positives.forEach(positive => {
      negatives.forEach(negative => {
        if (positive.score > negative.score) {
          wins += 1;
        } else if (positive.score === negative.score) {
          ties += 1;
        }
      });
    });

    return (wins + (ties * 0.5)) / (positives.length * negatives.length);
  }

  private choosePositiveLabel(labels: string[]): string {
    const preferred = ['positive', 'true', '1', 'yes', 'high', 'fraud', 'malignant', 'approved', 'block'];
    const match = labels.find(label => preferred.some(token => label.includes(token)));
    return match || [...labels].sort()[labels.length - 1];
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

  private calculateCost(latencyMs: number): number {
    return (latencyMs / 1000) * this.costPerSecond;
  }

  // ---------------------------------------------------------------------------
  // Ranking
  // ---------------------------------------------------------------------------

  private rankResults(results: RankingRow[]): RankingRow[] {
    const lowerIsBetter = ['RMSE', 'MAE', 'MSE', 'Perplexity'].includes(this.recommendationMetric);
    const validMetricValues = results
      .map(row => this.getMetricValue(row, this.recommendationMetric))
      .filter((value): value is number => value !== null);
    const maxLatency = Math.max(...results.map(r => r.latency), 1);
    const maxCost = Math.max(...results.map(r => r.cost), 0.000001);
    const maxMetric = Math.max(...validMetricValues, 1);

    results.forEach(row => {
      const metricValue = this.getMetricValue(row, this.recommendationMetric);
      if (metricValue === null) {
        row.compositeScore = 0;
        return;
      }

      const normalizedLatency = 1 - (row.latency / maxLatency);
      const normalizedCost = 1 - (row.cost / maxCost);

      const normalizedMetric = lowerIsBetter
        ? 1 - (metricValue / maxMetric)
        : metricValue / maxMetric;

      row.compositeScore = (normalizedMetric * 0.6) + (normalizedLatency * 0.25) + (normalizedCost * 0.15);
    });

    const sorted = results.sort((a, b) => (b.compositeScore || 0) - (a.compositeScore || 0));
    sorted.forEach((row, index) => {
      row.rank = index + 1;
      row.top = index === 0;
    });

    return sorted;
  }

  getTopModel(): RankingRow | null {
    return this.rankingRows.find(row => row.top) || null;
  }

  getBestModelByMetric(): RankingRow | null {
    if (this.rankingRows.length === 0) return null;
    const lowerIsBetter = ['RMSE', 'MAE', 'MSE', 'Perplexity'].includes(this.recommendationMetric);
    const comparableRows = this.rankingRows.filter(row => this.getMetricValue(row, this.recommendationMetric) !== null);
    if (comparableRows.length === 0) {
      return null;
    }

    const sorted = [...comparableRows].sort((a, b) => {
      const aVal = this.getMetricValue(a, this.recommendationMetric) || 0;
      const bVal = this.getMetricValue(b, this.recommendationMetric) || 0;
      return lowerIsBetter ? aVal - bVal : bVal - aVal;
    });
    return sorted[0];
  }

  formatMetricValue(value: number | null | undefined, metric: string): string {
    if (!Number.isFinite(value ?? Number.NaN)) {
      return 'N/A';
    }
    if (['RMSE', 'MAE', 'MSE'].includes(metric)) return value.toFixed(4);
    return value.toFixed(3);
  }

  private getMetricValue(row: RankingRow, metric: string): number | null {
    const value = row.metrics[metric];
    return Number.isFinite(value) ? value : null;
  }

  formatCost(cost: number): string { return `$${cost.toFixed(6)}`; }
  formatLatency(ms: number): string { return `${ms}ms`; }

  getSelectedDatasetName(): string {
    return this.validationDatasetFileName || 'validation dataset';
  }

  // ---------------------------------------------------------------------------
  // Outputs helpers
  // ---------------------------------------------------------------------------

  isSingleOutputMode(): boolean { return this.outputMode === 'single'; }
  isDatasetOutputMode(): boolean { return this.outputMode === 'dataset'; }

  getPrimaryOutputValue(result: InputExecutionResult): string {
    return this.extractPrimaryOutputInfo(result.output, result.modelId).value;
  }

  getPrimaryOutputConfidence(result: InputExecutionResult): string {
    return this.extractPrimaryOutputInfo(result.output, result.modelId).confidence;
  }

  getDatasetOutputSummary(result: InputExecutionResult): string {
    if (!Array.isArray(result.output) || result.output.length === 0) return 'No dataset outputs';
    const preview = this.extractPrimaryOutputInfo(result.output[0], result.modelId).value;
    return `${result.output.length} rows · First: ${preview}`;
  }

  getDatasetDownloadFormat(modelId: string): DownloadFormat {
    return this.datasetDownloadFormatByModel[modelId] || 'csv';
  }

  setDatasetDownloadFormat(modelId: string, format: DownloadFormat): void {
    this.datasetDownloadFormatByModel[modelId] = format;
  }

  // ---------------------------------------------------------------------------
  // Download
  // ---------------------------------------------------------------------------

  downloadDatasetModelOutput(result: InputExecutionResult): void {
    const format = this.getDatasetDownloadFormat(result.modelId);
    if (!Array.isArray(result.output) || result.output.length === 0) {
      this.notificationService.showWarning('No dataset outputs available for this model');
      return;
    }
    if (format === 'json') {
      this.downloadContent(JSON.stringify(result.output, null, 2), `${this.sanitizeFileName(result.modelName)}-dataset-outputs-${Date.now()}.json`, 'application/json;charset=utf-8;');
    } else {
      this.downloadContent(this.convertObjectsToCsv(result.output), `${this.sanitizeFileName(result.modelName)}-dataset-outputs-${Date.now()}.csv`, 'text/csv;charset=utf-8;');
    }
  }

  downloadAllDatasetOutputs(): void {
    if (!this.isDatasetOutputMode() || this.modelInputOutputs.length === 0) {
      this.notificationService.showWarning('No dataset outputs available to download');
      return;
    }
    if (this.globalDatasetDownloadFormat === 'json') {
      const allResults = this.modelInputOutputs.map(r => ({
        modelId: r.modelId, modelName: r.modelName, status: r.status,
        processedInputs: r.processedInputs, successfulOutputs: r.successfulOutputs,
        failedOutputs: r.failedOutputs, latencyMs: r.latencyMs,
        outputs: Array.isArray(r.output) ? r.output : []
      }));
      this.downloadContent(JSON.stringify(allResults, null, 2), `dataset-outputs-all-models-${Date.now()}.json`, 'application/json;charset=utf-8;');
    } else {
      const flattenedRows: any[] = [];
      this.modelInputOutputs.forEach(result => {
        const outputs = Array.isArray(result.output) ? result.output : [];
        outputs.forEach((outputRow: any, index: number) => {
          if (outputRow && typeof outputRow === 'object' && !Array.isArray(outputRow)) {
            flattenedRows.push({ modelId: result.modelId, modelName: result.modelName, status: result.status, rowIndex: index + 1, ...outputRow });
          } else {
            flattenedRows.push({ modelId: result.modelId, modelName: result.modelName, status: result.status, rowIndex: index + 1, outputValue: outputRow });
          }
        });
      });
      this.downloadContent(this.convertObjectsToCsv(flattenedRows), `dataset-outputs-all-models-${Date.now()}.csv`, 'text/csv;charset=utf-8;');
    }
  }

  exportResults(): void {
    if (this.rankingRows.length === 0) return;

    const headers = ['Rank', 'Model Name', 'Model ID'];
    this.selectedMetrics.forEach(m => headers.push(m));
    headers.push('Latency (ms)', 'Cost ($)', 'Composite Score');

    const csvRows: string[] = [headers.join(',')];
    this.rankingRows.forEach(row => {
      const rowData: string[] = [row.rank.toString(), `"${row.modelName}"`, `"${row.modelId}"`];
      this.selectedMetrics.forEach(metric => {
        const value = row.metrics[metric];
        rowData.push(Number.isFinite(value) ? value.toFixed(4) : 'N/A');
      });
      rowData.push(row.latency.toFixed(2), row.cost.toFixed(6), (row.compositeScore || 0).toFixed(4));
      csvRows.push(rowData.join(','));
    });

    csvRows.push('', `Generated,${new Date().toISOString()}`, `Task Type,${this.detectedTask || 'Unknown'}`,
      `Dataset,${this.validationDatasetFileName || 'N/A'}`, `Validation Rows,${this.validationDatasetRows.length}`,
      `Models Compared,${this.rankingRows.length}`);

    this.downloadContent(csvRows.join('\n'), `model-benchmark-results-${Date.now()}.csv`, 'text/csv;charset=utf-8;');
  }

  // ---------------------------------------------------------------------------
  // Standardized input
  // ---------------------------------------------------------------------------

  private initializeStandardizedSingleInput(models: BenchmarkAsset[]): void {
    if (!models || models.length === 0) {
      this.standardizedInputFields = [];
      this.standardizedInputValues = {};
      this.sampleInput = '';
      return;
    }

    const referenceFields = this.getSchemaFieldsFromModel(models[0]);
    if (referenceFields.length === 0) {
      this.standardizedInputFields = [];
      this.standardizedInputValues = {};
      this.generateSampleInput(models);
      return;
    }

    const hasIncompatibleSelection = models.some(model => {
      const fields = this.getSchemaFieldsFromModel(model);
      return !this.areSchemaFieldsEquivalent(referenceFields, fields);
    });

    if (hasIncompatibleSelection) {
      this.standardizedInputFields = [];
      this.standardizedInputValues = {};
      this.sampleInput = '';
      this.statusMessage = 'Selected models do not share a unified input schema.';
      return;
    }

    this.standardizedInputFields = referenceFields;
    const exampleValues = this.extractExampleValues(models[0], referenceFields);
    const nextValues: Record<string, any> = {};
    referenceFields.forEach(field => {
      const existing = this.standardizedInputValues[field.name];
      if (existing !== undefined && existing !== null && existing !== '') {
        nextValues[field.name] = existing;
      } else if (exampleValues[field.name] !== undefined) {
        nextValues[field.name] = exampleValues[field.name];
      } else {
        nextValues[field.name] = this.getDefaultValueForSchemaField(field);
      }
    });
    this.standardizedInputValues = nextValues;
    this.syncSampleInputFromStandardizedValues();
  }

  private generateSampleInput(models: BenchmarkAsset[]): void {
    const firstModel = models[0];
    if (firstModel.inputExample) {
      this.sampleInput = typeof firstModel.inputExample === 'string'
        ? firstModel.inputExample
        : JSON.stringify(firstModel.inputExample, null, 2);
      return;
    }
    if (!firstModel.inputFeatures || firstModel.inputFeatures.length === 0) {
      this.sampleInput = '{\n  "feature_1": 0.5,\n  "feature_2": 1.0\n}';
      return;
    }
    const sampleObj: any = {};
    firstModel.inputFeatures.forEach(f => {
      if (f.type === 'string' || f.type === 'text') sampleObj[f.name] = 'sample text';
      else if (f.type === 'int' || f.type === 'integer') sampleObj[f.name] = f.minValue || 0;
      else if (f.type === 'float' || f.type === 'number') sampleObj[f.name] = f.minValue || 0.0;
      else if (f.type === 'boolean' || f.type === 'bool') sampleObj[f.name] = true;
      else sampleObj[f.name] = null;
    });
    this.sampleInput = JSON.stringify(sampleObj, null, 2);
  }

  private getDefaultValueForSchemaField(field: SchemaField): any {
    if (field.type === 'boolean') return false;
    if (field.type === 'integer') return field.min !== undefined ? Math.trunc(field.min) : 0;
    if (field.type === 'number') return field.min !== undefined ? field.min : 0;
    return '';
  }

  private extractExampleValues(model: BenchmarkAsset, fields: SchemaField[]): Record<string, any> {
    const example = this.parseObjectLikeValue(model.inputExample);
    if (!example) {
      return {};
    }

    return fields.reduce<Record<string, any>>((result, field) => {
      const rawValue = example[field.name];
      if (rawValue === undefined || rawValue === null || rawValue === '') {
        return result;
      }

      result[field.name] = this.normalizeExampleValue(field, rawValue);
      return result;
    }, {});
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

    return String(value);
  }

  private syncSampleInputFromStandardizedValues(): void {
    this.sampleInput = JSON.stringify(this.standardizedInputValues, null, 2);
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
    const nestedKeys = ['input', 'payload', 'body', 'requestBody'];
    for (const key of nestedKeys) {
      const nested = this.asSchemaRecord(schemaRecord[key]);
      if (nested?.properties && typeof nested.properties === 'object') {
        return nested;
      }
    }

    return schemaRecord;
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
    if (typeof value === 'boolean') {
      return 'boolean';
    }

    if (typeof value === 'number') {
      return Number.isInteger(value) ? 'integer' : 'number';
    }

    return 'string';
  }

  private areSchemaFieldsEquivalent(fields1: SchemaField[], fields2: SchemaField[]): boolean {
    if (fields1.length !== fields2.length) return false;
    const sorted1 = [...fields1].sort((a, b) => a.name.localeCompare(b.name));
    const sorted2 = [...fields2].sort((a, b) => a.name.localeCompare(b.name));
    return sorted1.every((field, index) => {
      const other = sorted2[index];
      return field.name === other.name && field.type === other.type && field.required === other.required;
    });
  }

  private normalizeFieldType(type: any): string {
    const normalized = String(type || 'string').toLowerCase();
    if (['float', 'double', 'number', 'numeric'].includes(normalized)) return 'number';
    if (['int', 'integer', 'long'].includes(normalized)) return 'integer';
    if (['bool', 'boolean'].includes(normalized)) return 'boolean';
    return 'string';
  }

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  private validateCurrentInput(): InputValidationResult {
    if (this.selectedAssetIds.length === 0) {
      return { isValid: false, errors: ['Select at least one model first.'] };
    }

    const selectedModels = this.modelPoolAssets.filter(m => this.selectedAssetIds.includes(m.id));
    const errors: string[] = [];
    let normalizedInput: any;

    if (this.inputMode === 'single') {
      if (this.standardizedInputFields.length > 0) {
        normalizedInput = { ...this.standardizedInputValues };
        this.syncSampleInputFromStandardizedValues();
      } else {
        if (!this.sampleInput.trim()) return { isValid: false, errors: ['Single input is empty.'] };
        try { normalizedInput = JSON.parse(this.sampleInput); } catch { return { isValid: false, errors: ['Single input must be valid JSON.'] }; }
        if (!normalizedInput || typeof normalizedInput !== 'object' || Array.isArray(normalizedInput)) {
          return { isValid: false, errors: ['Single input must be a JSON object (key-value).'] };
        }
      }
    } else {
      if (this.datasetBatchInputs.length === 0) return { isValid: false, errors: ['Dataset batch has no loaded rows. Upload a valid file first.'] };
      normalizedInput = this.datasetBatchInputs;
    }

    for (const model of selectedModels) {
      const schemaFields = this.getSchemaFieldsFromModel(model);
      if (schemaFields.length === 0) continue;
      if (this.inputMode === 'single') {
        errors.push(...this.validateRecordAgainstSchema(normalizedInput, schemaFields, model.name));
      } else {
        normalizedInput.forEach((row: any, index: number) => {
          errors.push(...this.validateRecordAgainstSchema(row, schemaFields, `${model.name} row #${index + 1}`));
        });
      }
    }

    const uniqueErrors = [...new Set(errors)];
    return { isValid: uniqueErrors.length === 0, errors: uniqueErrors, normalizedInput };
  }

  private validateRecordAgainstSchema(record: any, schemaFields: SchemaField[], context: string): string[] {
    const errors: string[] = [];
    if (!record || typeof record !== 'object' || Array.isArray(record)) {
      return [`${context}: input must be a JSON object.`];
    }
    for (const field of schemaFields) {
      const value = record[field.name];
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
    }
    return errors;
  }

  private validateValidationDatasetRows(rows: any[], selectedModels: BenchmarkAsset[]): string[] {
    if (!Array.isArray(rows) || rows.length === 0) return ['Validation dataset must contain at least one row.'];
    const errors: string[] = [];
    for (const model of selectedModels) {
      const schemaFields = this.getSchemaFieldsFromModel(model);
      const excludedKeys = new Set(schemaFields.map(field => field.name));
      const modelTask = this.detectModelTask([model]);
      if (schemaFields.length === 0) continue;
      rows.forEach((row, index) => {
        errors.push(...this.validateRecordAgainstSchema(row, schemaFields, `${model.name} row #${index + 1}`));
        if (modelTask === 'regression') {
          if (!Number.isFinite(this.extractExpectedRegressionValue(model, row, excludedKeys))) {
            errors.push(`${model.name} row #${index + 1}: validation dataset must include a numeric target/label field for benchmarking.`);
          }
        } else if (!this.extractExpectedClassificationValue(model, row, excludedKeys)) {
          errors.push(`${model.name} row #${index + 1}: validation dataset must include a label/target field for benchmarking.`);
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
      this.notificationService.showWarning(`Validation dataset (${previousFileName}) discarded — incompatible with current input schema.`);
    }
  }

  // ---------------------------------------------------------------------------
  // Output helpers
  // ---------------------------------------------------------------------------

  private buildOutputPreview(output: any): string {
    if (output === undefined || output === null) return 'No output returned.';
    const serialized = typeof output === 'string' ? output : JSON.stringify(output, null, 2);
    return serialized.length <= 360 ? serialized : `${serialized.slice(0, 360)}...`;
  }

  private extractPrimaryOutputInfo(output: any, modelId?: string): PrimaryOutputInfo {
    if (output === undefined || output === null) return { value: 'No output', confidence: '-' };
    if (Array.isArray(output)) {
      if (output.length === 0) return { value: '0 rows', confidence: '-' };
      return this.extractPrimaryOutputInfo(output[0], modelId);
    }
    if (typeof output !== 'object') return { value: String(output), confidence: '-' };

    const model = modelId ? this.modelPoolAssets.find(item => item.id === modelId) : undefined;
    const priorityKeys = model
      ? [
        ...this.getPreferredRegressionKeys(model),
        ...this.getPreferredClassificationKeys(model),
        'prediction', 'sentiment', 'category', 'risk_level', 'fraud_type', 'decision', 'is_fraud',
        'bmi', 'body_fat_percentage', 'bmr_calories', 'ideal_weight_kg', 'risk_score', 'value'
      ]
      : ['prediction', 'sentiment', 'category', 'risk_level', 'fraud_type', 'decision', 'is_fraud', 'bmi', 'body_fat_percentage', 'bmr_calories', 'ideal_weight_kg', 'risk_score', 'value'];
    let value = '';
    for (const key of priorityKeys) {
      if (output[key] !== undefined && output[key] !== null) { value = `${key}: ${String(output[key])}`; break; }
    }
    if (!value) {
      const keys = Object.keys(output);
      if (keys.length === 0) value = 'Empty object';
      else value = `${keys[0]}: ${String(output[keys[0]])}`;
    }

    const confidenceRaw = output.confidence ?? output.probability ?? output.score ?? null;
    const confidence = typeof confidenceRaw === 'number' ? confidenceRaw.toFixed(3) : confidenceRaw !== null ? String(confidenceRaw) : '-';
    return { value, confidence };
  }

  // ---------------------------------------------------------------------------
  // File parsing
  // ---------------------------------------------------------------------------

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
      if (parsed && typeof parsed === 'object') { if (Array.isArray(parsed.data)) return parsed.data; return [parsed]; }
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
      headers.forEach((header, index) => { row[header] = this.coerceCsvValue(columns[index] ?? ''); });
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

  private coerceCsvValue(rawValue: string): any {
    const trimmed = rawValue.trim();
    if (trimmed === '') return '';
    if (trimmed.toLowerCase() === 'true') return true;
    if (trimmed.toLowerCase() === 'false') return false;
    const numeric = Number(trimmed);
    if (!Number.isNaN(numeric) && trimmed !== '') return numeric;
    return trimmed;
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
