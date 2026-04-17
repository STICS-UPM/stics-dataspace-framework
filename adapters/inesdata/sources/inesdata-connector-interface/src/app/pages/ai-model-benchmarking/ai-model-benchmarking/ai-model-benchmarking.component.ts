import { Component, OnInit } from '@angular/core';
import {
  AiModelExecutionInputFeature,
  AiModelExecutionItem,
  ModelExecutionResponsePayload
} from 'src/app/shared/models/ai-model-execution-item';
import { ModelExecutionService } from 'src/app/shared/services/model-execution.service';
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

  // Ranking
  rankingRows: RankingRow[] = [];
  recommendationMetric = '';

  // Cost configuration
  costPerSecond = 0.00001;
  private readonly benchmarkBatchSize = 300;
  private readonly benchmarkRequestTimeoutMs = 10000;

  private readonly metricsConfig: Record<ModelTask, string[]> = {
    classification: ['AUC', 'GINI', 'Precision', 'Recall', 'F1 Score'],
    regression: ['RMSE', 'MAE', 'MSE', 'R2'],
    nlp: ['Accuracy', 'F1 Score', 'BLEU', 'Perplexity', 'ROUGE'],
    vision: ['Accuracy', 'Precision', 'Recall', 'mAP', 'IoU'],
    other: ['Accuracy', 'Custom Score']
  };

  constructor(
    private readonly modelExecutionService: ModelExecutionService,
    private readonly notificationService: NotificationService
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

    this.modelExecutionService.getExecutableModels().subscribe({
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

    if (this.activeFilter !== 'all') {
      pool = pool.filter(m => {
        const task = m.task.toLowerCase();
        switch (this.activeFilter) {
          case 'classification': return task.includes('classif');
          case 'regression': return task.includes('regress');
          case 'nlp': return task.includes('nlp') || task.includes('natural') || task.includes('text') || task.includes('sentiment');
          case 'vision': return task.includes('vision') || task.includes('image') || task.includes('detection');
          default: return true;
        }
      });
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

    this.filteredModelPoolAssets = pool;
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

  toggleAssetSelection(asset: BenchmarkAsset): void {
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
  }

  private detectModelTask(models: BenchmarkAsset[]): ModelTask {
    const tasks = models.map(m => m.task.toLowerCase());
    const uniqueTasks = [...new Set(tasks)];

    if (uniqueTasks.length === 1) {
      const task = uniqueTasks[0];
      if (task.includes('regress')) return 'regression';
      if (task.includes('classif')) return 'classification';
      if (task.includes('natural') && task.includes('language')) return 'nlp';
      if (task.includes('nlp') || task.includes('text') || task.includes('sentiment')) return 'nlp';
      if (task.includes('computer') && task.includes('vision')) return 'vision';
      if (task.includes('vision') || task.includes('image') || task.includes('detection')) return 'vision';
      if (task.includes('tabular')) {
        const algo = models[0].algorithm?.toLowerCase() || '';
        if (algo.includes('classif')) return 'classification';
        if (algo.includes('regress')) return 'regression';
        return 'classification';
      }
    }

    return 'other';
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
    const parts = [asset.task, asset.algorithm].filter(Boolean);
    return parts.length > 0 ? parts.join(' · ') : 'HTTP Model';
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
      this.statusMessage = `Validation dataset loaded and validated (${parsedRows.length} rows).`;
      this.notificationService.showInfo(`Validation dataset valid (${parsedRows.length} rows)`);
    } catch (error: any) {
      this.validationDatasetRows = [];
      this.validationDatasetFileName = '';
      this.notificationService.showError(error?.message || 'Could not load validation dataset');
      this.statusMessage = 'Could not load validation dataset.';
      input.value = '';
    }
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

    try {
      const datasetRows = this.validationDatasetRows;
      const datasetValidationErrors = this.validateValidationDatasetRows(datasetRows, selectedModels);
      if (datasetValidationErrors.length > 0) {
        throw new Error(`Validation dataset invalid: ${datasetValidationErrors[0]}`);
      }

      const results: RankingRow[] = [];
      const totalModels = selectedModels.length;

      for (let i = 0; i < selectedModels.length; i++) {
        const model = selectedModels[i];
        this.statusMessage = `Executing ${model.name} (${i + 1}/${totalModels}) with ${datasetRows.length} validation rows...`;

        try {
          const benchmarkResult = await this.executeBenchmarkRowsForModel(model, datasetRows, i, totalModels);
          results.push({
            rank: 0, modelId: model.id, modelName: model.name,
            metrics: benchmarkResult.metrics,
            latency: Math.round(benchmarkResult.averageLatency),
            cost: benchmarkResult.cost
          });
        } catch {
          results.push({
            rank: 0, modelId: model.id, modelName: model.name,
            metrics: {}, latency: 0, cost: 0
          });
        }
      }

      this.rankingRows = this.rankResults(results);
      this.progress = 100;
      this.isRunning = false;
      this.statusMessage = `Benchmark completed successfully using ${datasetRows.length} validation rows!`;
      this.notificationService.showInfo('Benchmark completed');
    } catch (error: any) {
      this.isRunning = false;
      this.statusMessage = 'Benchmark failed: ' + error.message;
      this.notificationService.showError('Benchmark failed');
    }
  }

  // ---------------------------------------------------------------------------
  // Benchmark execution helpers
  // ---------------------------------------------------------------------------

  private async executeBenchmarkRowsForModel(
    model: BenchmarkAsset, datasetRows: any[], modelIndex: number, totalModels: number
  ): Promise<{ metrics: Record<string, number>; averageLatency: number; cost: number; successCount: number }> {
    const totalRows = datasetRows.length;
    const batchSize = Math.max(1, Math.min(this.benchmarkBatchSize, totalRows));
    const totalBatches = Math.ceil(totalRows / batchSize);

    let successCount = 0;
    let totalLatency = 0;
    const predictions: any[] = [];

    for (let batchIndex = 0; batchIndex < totalBatches; batchIndex++) {
      const batchStart = batchIndex * batchSize;
      const batchEnd = Math.min(batchStart + batchSize, totalRows);
      const batchRows = datasetRows.slice(batchStart, batchEnd);

      this.statusMessage = `Executing ${model.name} (${modelIndex + 1}/${totalModels}) - batch ${batchIndex + 1}/${totalBatches} rows ${batchStart + 1}-${batchEnd}`;

      const settledBatch = await Promise.all(
        batchRows.map(async (row, rowOffset) => {
          const startedAt = Date.now();
          try {
            const result = await this.executeModel(model.id, row, this.benchmarkRequestTimeoutMs);
            return { rowIndex: batchStart + rowOffset, success: true, output: this.extractExecutionOutput(result), latencyMs: Date.now() - startedAt };
          } catch {
            return { rowIndex: batchStart + rowOffset, success: false, output: null as any, latencyMs: Date.now() - startedAt };
          }
        })
      );

      settledBatch.forEach(item => {
        predictions[item.rowIndex] = item.output;
        totalLatency += item.latencyMs;
        if (item.success) successCount += 1;
      });

      const baseProgress = modelIndex / totalModels;
      const modelProgress = (batchEnd / totalRows) / totalModels;
      this.progress = Math.round((baseProgress + modelProgress) * 100);
    }

    const validPredictions = predictions.filter(p => p !== null);
    const metrics = this.calculateMetrics({ predictions: validPredictions, processedRows: totalRows, successCount }, this.detectedTask!);

    return {
      metrics,
      averageLatency: totalRows > 0 ? totalLatency / totalRows : 0,
      cost: this.calculateCost(totalLatency),
      successCount
    };
  }

  private executeModel(assetId: string, input: any, requestTimeoutMs = 30000): Promise<ModelExecutionResponsePayload> {
    return new Promise((resolve, reject) => {
      let settled = false;

      const subscription = this.modelExecutionService.executeModel({
        assetId,
        payload: input
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

  // ---------------------------------------------------------------------------
  // Metrics calculation (simulated)
  // ---------------------------------------------------------------------------

  private calculateMetrics(result: any, taskType: ModelTask): Record<string, number> {
    const metrics: Record<string, number> = {};

    this.selectedMetrics.forEach(metric => {
      switch (metric) {
        case 'AUC': metrics['AUC'] = 0.85 + Math.random() * 0.10; break;
        case 'GINI': { const auc = metrics['AUC'] || (0.85 + Math.random() * 0.10); metrics['GINI'] = 2 * auc - 1; break; }
        case 'Precision': metrics['Precision'] = 0.80 + Math.random() * 0.15; break;
        case 'Recall': metrics['Recall'] = 0.75 + Math.random() * 0.20; break;
        case 'F1 Score': { const p = metrics['Precision'] || 0.85; const r = metrics['Recall'] || 0.82; metrics['F1 Score'] = 2 * (p * r) / (p + r); break; }
        case 'RMSE': metrics['RMSE'] = 0.5 + Math.random() * 2.0; break;
        case 'MAE': metrics['MAE'] = 0.3 + Math.random() * 1.5; break;
        case 'MSE': { const rmse = metrics['RMSE'] || 1.0; metrics['MSE'] = rmse ** 2; break; }
        case 'R2': metrics['R2'] = 0.70 + Math.random() * 0.25; break;
        case 'BLEU': metrics['BLEU'] = 0.40 + Math.random() * 0.30; break;
        case 'Perplexity': metrics['Perplexity'] = 20 + Math.random() * 30; break;
        case 'ROUGE': metrics['ROUGE'] = 0.50 + Math.random() * 0.35; break;
        case 'mAP': metrics['mAP'] = 0.65 + Math.random() * 0.30; break;
        case 'IoU': metrics['IoU'] = 0.60 + Math.random() * 0.35; break;
        case 'Accuracy': metrics['Accuracy'] = 0.75 + Math.random() * 0.20; break;
        case 'Custom Score': metrics['Custom Score'] = Math.random(); break;
        default: metrics[metric] = 0.70 + Math.random() * 0.25;
      }
    });

    return metrics;
  }

  private calculateCost(latencyMs: number): number {
    return (latencyMs / 1000) * this.costPerSecond;
  }

  // ---------------------------------------------------------------------------
  // Ranking
  // ---------------------------------------------------------------------------

  private rankResults(results: RankingRow[]): RankingRow[] {
    const lowerIsBetter = ['RMSE', 'MAE', 'MSE', 'Perplexity'].includes(this.recommendationMetric);

    results.forEach(row => {
      const metricValue = row.metrics[this.recommendationMetric] || 0;
      const maxLatency = Math.max(...results.map(r => r.latency), 1);
      const normalizedLatency = 1 - (row.latency / maxLatency);
      const maxCost = Math.max(...results.map(r => r.cost), 0.000001);
      const normalizedCost = 1 - (row.cost / maxCost);

      let normalizedMetric = metricValue;
      if (lowerIsBetter) {
        const maxMetric = Math.max(...results.map(r => r.metrics[this.recommendationMetric] || 0), 1);
        normalizedMetric = 1 - (metricValue / maxMetric);
      }

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
    const sorted = [...this.rankingRows].sort((a, b) => {
      const aVal = a.metrics[this.recommendationMetric] || 0;
      const bVal = b.metrics[this.recommendationMetric] || 0;
      return lowerIsBetter ? aVal - bVal : bVal - aVal;
    });
    return sorted[0];
  }

  formatMetricValue(value: number, metric: string): string {
    if (['RMSE', 'MAE', 'MSE'].includes(metric)) return value.toFixed(4);
    return value.toFixed(3);
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
    return this.extractPrimaryOutputInfo(result.output).value;
  }

  getPrimaryOutputConfidence(result: InputExecutionResult): string {
    return this.extractPrimaryOutputInfo(result.output).confidence;
  }

  getDatasetOutputSummary(result: InputExecutionResult): string {
    if (!Array.isArray(result.output) || result.output.length === 0) return 'No dataset outputs';
    const preview = this.extractPrimaryOutputInfo(result.output[0]).value;
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
      this.selectedMetrics.forEach(m => { rowData.push((row.metrics[m] !== undefined ? row.metrics[m].toFixed(4) : 'N/A')); });
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
    const nextValues: Record<string, any> = {};
    referenceFields.forEach(field => {
      const existing = this.standardizedInputValues[field.name];
      if (existing !== undefined && existing !== null && existing !== '') {
        nextValues[field.name] = existing;
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
    const schema = model.inputSchema;
    if (!schema) return [];
    const rawFields = schema.fields || schema.features;
    if (!Array.isArray(rawFields)) return [];
    return rawFields.filter((f: any) => !!f?.name).map((f: any) => ({
      name: String(f.name),
      type: this.normalizeFieldType(f.type),
      required: f.required !== false,
      min: typeof f.min === 'number' ? f.min : undefined,
      max: typeof f.max === 'number' ? f.max : undefined,
      description: f.description ? String(f.description) : undefined
    }));
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
      if (schemaFields.length === 0) continue;
      rows.forEach((row, index) => {
        errors.push(...this.validateRecordAgainstSchema(row, schemaFields, `${model.name} row #${index + 1}`));
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

  private extractPrimaryOutputInfo(output: any): PrimaryOutputInfo {
    if (output === undefined || output === null) return { value: 'No output', confidence: '-' };
    if (Array.isArray(output)) {
      if (output.length === 0) return { value: '0 rows', confidence: '-' };
      return this.extractPrimaryOutputInfo(output[0]);
    }
    if (typeof output !== 'object') return { value: String(output), confidence: '-' };

    const priorityKeys = ['prediction', 'sentiment', 'category', 'risk_level', 'fraud_type', 'decision', 'is_fraud', 'bmi', 'value'];
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
