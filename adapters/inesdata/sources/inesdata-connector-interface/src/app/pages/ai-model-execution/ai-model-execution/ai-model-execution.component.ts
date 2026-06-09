import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import {
  AiModelExecutionInputFeature,
  AiModelExecutionItem,
  ModelExecutionResponsePayload
} from 'src/app/shared/models/ai-model-execution-item';
import { ModelExecutionService } from 'src/app/shared/services/model-execution.service';
import { ModelObserverJournalService } from 'src/app/shared/services/model-observer-journal.service';
import { NotificationService } from 'src/app/shared/services/notification.service';

interface InputFieldState {
  spec: AiModelExecutionInputFeature;
  value: any;
}

interface ExecutionResultView {
  executionId: string;
  status: 'success' | 'error';
  assetId: string;
  output?: unknown;
  rawBody?: string;
  contentType?: string;
  statusCode?: number;
  error?: {
    message: string;
    code: string;
    httpStatus?: number;
    details?: unknown;
  };
  timestamp: string;
  executionTimeMs?: number;
}

interface ExecutionHistoryEntry {
  executionId: string;
  assetId: string;
  status: 'success' | 'error';
  createdAt: string;
  executionTimeMs?: number;
  inputPayload: unknown;
  outputPayload?: unknown;
  errorMessage?: string;
}

@Component({
  selector: 'app-ai-model-execution',
  templateUrl: './ai-model-execution.component.html',
  styleUrls: ['./ai-model-execution.component.scss']
})
export class AiModelExecutionComponent implements OnInit {
  loading = false;
  loadingAssets = false;
  executing = false;
  lastExecutionCorrelationId = '';

  executableAssets: AiModelExecutionItem[] = [];
  localAssets: AiModelExecutionItem[] = [];
  externalAssets: AiModelExecutionItem[] = [];
  selectedAsset?: AiModelExecutionItem;
  selectedAssetId = '';

  inputMode: 'form' | 'json' = 'json';
  inputFields: InputFieldState[] = [];
  inputJson = '{}';
  inputError = '';

  selectedMethod = 'POST';
  executionPath = '';

  executionResult: ExecutionResultView | null = null;
  executionHistory: ExecutionHistoryEntry[] = [];
  activeTab: 'input' | 'output' | 'history' = 'input';

  constructor(
    private readonly modelExecutionService: ModelExecutionService,
    private readonly modelObserverJournalService: ModelObserverJournalService,
    private readonly notificationService: NotificationService,
    private readonly route: ActivatedRoute,
    private readonly router: Router
  ) {
  }

  ngOnInit(): void {
    const preselectedAssetId = this.route.snapshot.queryParamMap.get('assetId') || '';
    this.loadModels(preselectedAssetId);
  }

  loadModels(preselectedAssetId = ''): void {
    this.loading = true;
    this.loadingAssets = true;

    this.modelExecutionService.getExecutableModels().subscribe({
      next: models => {
        this.executableAssets = models;
        this.localAssets = models.filter(model => model.isLocal);
        this.externalAssets = models.filter(model => !model.isLocal);
        this.loadingAssets = false;

        if (preselectedAssetId) {
          const matchingModel = models.find(model => model.id === preselectedAssetId);
          if (matchingModel) {
            this.selectedAssetId = matchingModel.id;
            this.selectAsset(matchingModel);
          }
        }
      },
      error: error => {
        this.loading = false;
        this.loadingAssets = false;
        this.notificationService.showError('Error loading executable AI models');
        console.error(error);
      },
      complete: () => {
        this.loading = false;
        this.loadingAssets = false;
      }
    });
  }

  onAssetSelect(event: Event): void {
    const assetId = (event.target as HTMLSelectElement).value;
    this.selectedAssetId = assetId;

    if (!assetId) {
      this.clearSelection();
      return;
    }

    const asset = this.executableAssets.find(item => item.id === assetId);
    if (!asset) {
      this.clearSelection();
      return;
    }

    this.selectAsset(asset);
  }

  selectAsset(asset: AiModelExecutionItem): void {
    this.selectedAsset = asset;
    this.lastExecutionCorrelationId = '';
    this.selectedMethod = asset.httpMethodDefault || 'POST';
    this.executionPath = asset.executionPath || '';
    this.executionResult = null;
    this.inputError = '';
    this.activeTab = 'input';
    this.initializeInput(asset);
  }

  toggleInputMode(): void {
    this.setInputMode(this.inputMode === 'form' ? 'json' : 'form');
  }

  setInputMode(mode: 'form' | 'json'): void {
    if (mode === this.inputMode) {
      return;
    }

    if (mode === 'json') {
      this.inputJson = JSON.stringify(this.buildPayloadFromFields(false), null, 2);
      this.inputMode = 'json';
      this.inputError = '';
      return;
    }

    if (this.inputFields.length === 0) {
      return;
    }

    try {
      const parsedPayload = JSON.parse(this.inputJson);
      this.inputFields.forEach(field => {
        const nextValue = this.readPayloadValue(parsedPayload, field.spec.name);
        if (nextValue !== undefined) {
          field.value = nextValue;
        }
      });
      this.inputMode = 'form';
      this.inputError = '';
    } catch {
      this.inputError = 'Cannot switch to form mode because the JSON payload is invalid.';
    }
  }

  executeModel(): void {
    if (!this.selectedAsset) {
      this.inputError = 'Please select a model first.';
      return;
    }

    if (!this.validateInput()) {
      return;
    }

    const payload = this.normalizePayloadForExecution(this.buildPayload());
    const startedAt = Date.now();
    const correlationId = this.modelObserverJournalService.createId('corr');
    this.lastExecutionCorrelationId = correlationId;

    this.executing = true;
    this.executionResult = null;
    this.activeTab = 'output';

    this.modelExecutionService.executeModel({
      assetId: this.selectedAsset.id,
      method: this.selectedMethod,
      path: this.executionPath,
      payload,
      correlationId,
      modelName: this.selectedAsset.name
    }).subscribe({
      next: response => {
        const executionTimeMs = Date.now() - startedAt;
        const result = this.buildSuccessResult(response, executionTimeMs);
        this.executionResult = result;
        this.prependHistoryEntry(result, payload);
        this.executing = false;
        this.notificationService.showInfo('Model execution completed successfully');
      },
      error: error => {
        const executionTimeMs = Date.now() - startedAt;
        const result = this.buildErrorResult(error, executionTimeMs);
        this.executionResult = result;
        this.prependHistoryEntry(result, payload);
        this.executing = false;
        this.notificationService.showError(result.error?.message || 'Model execution failed.');
      }
    });
  }

  viewHistory(): void {
    this.activeTab = 'history';
  }

  goBack(): void {
    this.router.navigate(['/ai-model-browser']);
  }

  openSelectedAssetObserverTimeline(): void {
    if (!this.selectedAsset?.id) {
      return;
    }

    this.router.navigate(['/ai-model-observer/timeline', this.selectedAsset.id], {
      queryParams: this.lastExecutionCorrelationId ? { correlationId: this.lastExecutionCorrelationId } : undefined
    });
  }

  asPrettyJson(value: unknown): string {
    if (value === undefined || value === null) {
      return '';
    }

    if (typeof value === 'string') {
      try {
        return JSON.stringify(JSON.parse(value), null, 2);
      } catch {
        return value;
      }
    }

    return JSON.stringify(value, null, 2);
  }

  getStatusClass(status: string): string {
    switch (status) {
      case 'success':
        return 'badge-success';
      case 'error':
        return 'badge-error';
      default:
        return 'badge-secondary';
    }
  }

  formatExecutionTime(ms?: number): string {
    if (!ms && ms !== 0) {
      return 'N/A';
    }

    if (ms < 1000) {
      return `${ms}ms`;
    }

    return `${(ms / 1000).toFixed(2)}s`;
  }

  get selectedExecutionHistory(): ExecutionHistoryEntry[] {
    if (!this.selectedAsset) {
      return [];
    }

    return this.executionHistory.filter(entry => entry.assetId === this.selectedAsset?.id);
  }

  getSourceLabel(asset: AiModelExecutionItem): string {
    return asset.isLocal ? 'Local Asset' : 'External Asset';
  }

  getSelectorLabel(asset: AiModelExecutionItem): string {
    const detail = asset.algorithms[0] || asset.tasks[0] || 'ML Model';
    return `${asset.name} (${detail})`;
  }

  isBooleanField(field: InputFieldState): boolean {
    return this.normalizeType(field.spec.type) === 'boolean';
  }

  isNumericField(field: InputFieldState): boolean {
    const normalized = this.normalizeType(field.spec.type);
    return normalized === 'integer' || normalized === 'number';
  }

  getNumericStep(field: InputFieldState): string {
    return this.normalizeType(field.spec.type) === 'integer' ? '1' : '0.1';
  }

  get canUseGeneratedForm(): boolean {
    return this.inputFields.length > 0;
  }

  private clearSelection(): void {
    this.selectedAsset = undefined;
    this.lastExecutionCorrelationId = '';
    this.inputFields = [];
    this.inputJson = '{}';
    this.inputError = '';
    this.executionResult = null;
    this.activeTab = 'input';
  }

  private initializeInput(asset: AiModelExecutionItem): void {
    const examplePayload = asset.inputExample !== undefined ? asset.inputExample : {};

    if (asset.inputFeatures.length > 0) {
      const exampleRecord = examplePayload && typeof examplePayload === 'object' && !Array.isArray(examplePayload)
        ? examplePayload as Record<string, unknown>
        : {};

      this.inputMode = 'form';
      this.inputFields = asset.inputFeatures.map(feature => ({
        spec: feature,
        value: this.readPayloadValue(exampleRecord, feature.name) !== undefined
          ? this.readPayloadValue(exampleRecord, feature.name)
          : this.defaultValueForFeature(feature)
      }));
      this.inputJson = JSON.stringify(this.buildPayloadFromFields(false), null, 2);
      return;
    }

    this.inputMode = 'json';
    this.inputFields = [];
    const initialPayload = examplePayload && Object.keys(this.asRecord(examplePayload)).length > 0
      ? examplePayload
      : {};
    this.inputJson = JSON.stringify(initialPayload, null, 2);
  }

  private validateInput(): boolean {
    this.inputError = '';

    if (this.inputMode === 'json') {
      try {
        const parsedPayload = JSON.parse(this.inputJson);
        const error = this.validatePayloadAgainstFields(parsedPayload, true);
        if (error) {
          this.inputError = error;
          return false;
        }
        return true;
      } catch {
        this.inputError = 'Invalid JSON format.';
        return false;
      }
    }

    for (const field of this.inputFields) {
      if (field.spec.required && (field.value === '' || field.value === null || field.value === undefined)) {
        this.inputError = `Field "${field.spec.name}" is required.`;
        return false;
      }

      if (!this.validateFieldType(field, false)) {
        return false;
      }

      if (this.isNumericField(field) && field.value !== '' && field.value !== null && field.value !== undefined) {
        const numericValue = Number(field.value);
        if (!Number.isFinite(numericValue)) {
          this.inputError = `Field "${field.spec.name}" must be numeric.`;
          return false;
        }
        if (field.spec.minValue !== undefined && numericValue < field.spec.minValue) {
          this.inputError = `Field "${field.spec.name}" must be >= ${field.spec.minValue}.`;
          return false;
        }
        if (field.spec.maxValue !== undefined && numericValue > field.spec.maxValue) {
          this.inputError = `Field "${field.spec.name}" must be <= ${field.spec.maxValue}.`;
          return false;
        }
      }
    }

    return true;
  }

  private buildPayload(): unknown {
    if (this.inputMode === 'json') {
      return JSON.parse(this.inputJson);
    }

    return this.buildPayloadFromFields();
  }

  private normalizePayloadForExecution(payload: unknown): unknown {
    if (this.selectedAsset?.requestShape === 'batch' && !Array.isArray(payload)) {
      return [payload];
    }

    return payload;
  }

  private buildPayloadFromFields(validateRequired = true): Record<string, unknown> {
    const payload: Record<string, unknown> = {};

    for (const field of this.inputFields) {
      if (validateRequired && field.spec.required && (field.value === '' || field.value === null || field.value === undefined)) {
        throw new Error(`Field "${field.spec.name}" is required.`);
      }

      this.assignPayloadValue(payload, field.spec.name, this.castFieldValue(field));
    }

    return payload;
  }

  private buildSuccessResult(response: ModelExecutionResponsePayload, executionTimeMs: number): ExecutionResultView {
    const timestamp = new Date().toISOString();
    return {
      executionId: this.generateExecutionId(),
      status: response.statusCode >= 200 && response.statusCode < 400 ? 'success' : 'error',
      assetId: this.selectedAsset?.id || '',
      output: response.parsedBody !== undefined ? response.parsedBody : response.body,
      rawBody: response.body,
      contentType: response.contentType,
      statusCode: response.statusCode,
      timestamp,
      executionTimeMs
    };
  }

  private buildErrorResult(error: unknown, executionTimeMs: number): ExecutionResultView {
    const timestamp = new Date().toISOString();

    if (error instanceof HttpErrorResponse) {
      const errorBody = typeof error.error === 'string' ? this.tryParseJson(error.error) : error.error;
      return {
        executionId: this.generateExecutionId(),
        status: 'error',
        assetId: this.selectedAsset?.id || '',
        statusCode: error.status,
        contentType: error.headers?.get('content-type') || 'application/json',
        rawBody: typeof error.error === 'string' ? error.error : JSON.stringify(error.error, null, 2),
        error: {
          message: this.resolveErrorMessage(errorBody, error),
          code: 'EXECUTION_FAILED',
          httpStatus: error.status,
          details: errorBody || error.message
        },
        timestamp,
        executionTimeMs
      };
    }

    const fallbackMessage = error instanceof Error ? error.message : 'Unknown execution error.';
    return {
      executionId: this.generateExecutionId(),
      status: 'error',
      assetId: this.selectedAsset?.id || '',
      error: {
        message: fallbackMessage,
        code: 'EXECUTION_FAILED',
        details: error
      },
      timestamp,
      executionTimeMs
    };
  }

  private prependHistoryEntry(result: ExecutionResultView, payload: unknown): void {
    this.executionHistory = [
      {
        executionId: result.executionId,
        assetId: result.assetId,
        status: result.status,
        createdAt: result.timestamp,
        executionTimeMs: result.executionTimeMs,
        inputPayload: payload,
        outputPayload: result.output,
        errorMessage: result.error?.message
      },
      ...this.executionHistory
    ].slice(0, 20);
  }

  private defaultValueForFeature(feature: AiModelExecutionInputFeature): unknown {
    switch (this.normalizeType(feature.type)) {
      case 'boolean':
        return false;
      case 'integer':
      case 'number':
        return '';
      default:
        return '';
    }
  }

  private castFieldValue(field: InputFieldState): unknown {
    switch (this.normalizeType(field.spec.type)) {
      case 'integer':
        return field.value === '' ? null : Number.parseInt(`${field.value}`, 10);
      case 'number':
        return field.value === '' ? null : Number(`${field.value}`);
      case 'boolean':
        return field.value === true || `${field.value}`.toLowerCase() === 'true';
      default:
        return field.value;
    }
  }

  private validatePayloadAgainstFields(payload: unknown, strictTypes: boolean): string | null {
    if (this.inputFields.length === 0) {
      return null;
    }

    if (Array.isArray(payload)) {
      if (this.selectedAsset?.requestShape !== 'batch') {
        return 'The JSON payload must be an object that matches the model input schema.';
      }

      for (const [index, item] of payload.entries()) {
        const error = this.validatePayloadRecordAgainstFields(item, strictTypes);
        if (error) {
          return `Row #${index + 1}: ${error}`;
        }
      }

      return null;
    }

    return this.validatePayloadRecordAgainstFields(payload, strictTypes);
  }

  private validatePayloadRecordAgainstFields(payload: unknown, strictTypes: boolean): string | null {
    const payloadRecord = this.asRecord(payload);
    if (Object.keys(payloadRecord).length === 0 && !this.isRecord(payload)) {
      return 'The JSON payload must be an object that matches the model input schema.';
    }

    for (const field of this.inputFields) {
      const value = this.readPayloadValue(payloadRecord, field.spec.name);

      if (field.spec.required && (value === '' || value === null || value === undefined)) {
        return `Field "${field.spec.name}" is required.`;
      }

      if (value === '' || value === null || value === undefined) {
        continue;
      }

      const validationMessage = this.validateValueAgainstType(field.spec, value, strictTypes);
      if (validationMessage) {
        return validationMessage;
      }
    }

    return null;
  }

  private validateFieldType(field: InputFieldState, strictTypes: boolean): boolean {
    if (field.value === '' || field.value === null || field.value === undefined) {
      return true;
    }

    const validationMessage = this.validateValueAgainstType(field.spec, field.value, strictTypes);
    if (validationMessage) {
      this.inputError = validationMessage;
      return false;
    }

    return true;
  }

  private validateValueAgainstType(spec: AiModelExecutionInputFeature, value: unknown, strictTypes: boolean): string | null {
    const normalizedType = this.normalizeType(spec.type);

    if (normalizedType === 'string') {
      if (strictTypes && typeof value !== 'string') {
        return `Field "${spec.name}" must be a string.`;
      }
      return null;
    }

    if (normalizedType === 'boolean') {
      if (strictTypes) {
        return typeof value === 'boolean' ? null : `Field "${spec.name}" must be a boolean.`;
      }

      const normalized = `${value}`.trim().toLowerCase();
      return normalized === 'true' || normalized === 'false'
        ? null
        : `Field "${spec.name}" must be a boolean.`;
    }

    const numericValue = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(numericValue)) {
      return `Field "${spec.name}" must be numeric.`;
    }

    if (normalizedType === 'integer' && !Number.isInteger(numericValue)) {
      return `Field "${spec.name}" must be an integer.`;
    }

    if (spec.minValue !== undefined && numericValue < spec.minValue) {
      return `Field "${spec.name}" must be >= ${spec.minValue}.`;
    }

    if (spec.maxValue !== undefined && numericValue > spec.maxValue) {
      return `Field "${spec.name}" must be <= ${spec.maxValue}.`;
    }

    return null;
  }

  private assignPayloadValue(payload: Record<string, unknown>, path: string, value: unknown): void {
    const segments = this.pathSegments(path);
    if (segments.length === 0) {
      return;
    }

    let current: Record<string, unknown> = payload;
    segments.forEach((segment, index) => {
      if (index === segments.length - 1) {
        current[segment] = value;
        return;
      }

      const existing = current[segment];
      if (!this.isRecord(existing)) {
        current[segment] = {};
      }
      current = this.asRecord(current[segment]);
    });
  }

  private readPayloadValue(payload: unknown, path: string): unknown {
    const segments = this.pathSegments(path);
    let current: unknown = payload;

    for (const segment of segments) {
      if (!this.isRecord(current)) {
        return undefined;
      }
      current = current[segment];
    }

    return current;
  }

  private pathSegments(path: string): string[] {
    return `${path || ''}`
      .replace(/\[\]/g, '')
      .split('.')
      .map(segment => segment.trim())
      .filter(segment => segment.length > 0);
  }

  private normalizeType(type: string): 'string' | 'number' | 'integer' | 'boolean' {
    const normalized = `${type || 'string'}`.trim().toLowerCase();
    if (normalized === 'int' || normalized === 'integer') {
      return 'integer';
    }
    if (normalized === 'float' || normalized === 'double' || normalized === 'number') {
      return 'number';
    }
    if (normalized === 'bool' || normalized === 'boolean') {
      return 'boolean';
    }
    return 'string';
  }

  private generateExecutionId(): string {
    return `exec-${Date.now()}`;
  }

  private resolveErrorMessage(errorBody: any, error: HttpErrorResponse): string {
    if (typeof errorBody?.error === 'string') {
      return errorBody.error;
    }
    if (typeof errorBody?.message === 'string') {
      return errorBody.message;
    }
    if (typeof error.error === 'string' && error.error.trim()) {
      return error.error;
    }
    return error.message || 'Model execution failed.';
  }

  private tryParseJson(value: string): unknown {
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }

  private asRecord(value: unknown): Record<string, unknown> {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return {};
    }
    return value as Record<string, unknown>;
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }
}
