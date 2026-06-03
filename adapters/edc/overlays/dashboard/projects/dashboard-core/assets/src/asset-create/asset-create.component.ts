/*
 *  Copyright (c) 2025 Fraunhofer-Gesellschaft zur Förderung der angewandten Forschung e.V.
 *
 *  This program and the accompanying materials are made available under the
 *  terms of the Apache License, Version 2.0 which is available at
 *  https://www.apache.org/licenses/LICENSE-2.0
 *
 *  SPDX-License-Identifier: Apache-2.0
 *
 *  Contributors:
 *       Fraunhofer-Gesellschaft zur Förderung der angewandten Forschung e.V. - initial API and implementation
 *
 */

import { Component, EventEmitter, Input, OnChanges, Output, inject } from '@angular/core';
import {
  Asset,
  AssetInput,
  BaseDataAddress,
  compact,
  DataAddress,
  EdcConnectorClientError,
  IdResponse,
} from '@think-it-labs/edc-connector-client';
import { NgClass } from '@angular/common';
import { AssetService } from '../asset.service';
import {
  AlertComponent,
  DataAddressFormComponent,
  DataTypeInputComponent,
  JsonObjectInputComponent,
  JsonObjectTableComponent,
} from '@eclipse-edc/dashboard-core';
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { JsonValue } from '@angular-devkit/core';
import { OntologyAssetFieldsComponent } from '../ontology-asset-fields/ontology-asset-fields.component';
import { NEW_SHACLE_FILE_VALUE, OntologyAssetSelection } from '../models/ontology';
import { isLikelySemanticRdfFile, resolveRdfFormat } from '../utils/rdf-format.util';

type MlMultiSelectControl = 'mlModality' | 'mlKeywords' | 'mlRuntime' | 'mlLanguages';
type SchemaBuilderTextKey = 'path' | 'description' | 'example';

interface SchemaBuilderField {
  id: number;
  path: string;
  type: string;
  required: boolean;
  description: string;
  example: string;
}

interface SchemaTemplatePreset {
  id: string;
  label: string;
  draft: string;
  schema: Record<string, unknown>;
  example: unknown;
}

const DAIMO_METADATA_KEYS = {
  shortDescription: ['daimo:short_description', 'https://pionera.ai/edc/daimo#short_description'],
  version: ['daimo:model_version', 'https://pionera.ai/edc/daimo#model_version'],
  assetKind: ['daimo:asset_kind', 'https://pionera.ai/edc/daimo#asset_kind', 'asset:prop:kind'],
  task: ['daimo:pipeline_tag', 'https://pionera.ai/edc/daimo#pipeline_tag'],
  modality: ['daimo:modality', 'https://pionera.ai/edc/daimo#modality'],
  keywords: ['daimo:tags', 'https://pionera.ai/edc/daimo#tags'],
  license: ['daimo:license', 'https://pionera.ai/edc/daimo#license'],
  maturityStatus: ['daimo:maturity_status', 'https://pionera.ai/edc/daimo#maturity_status'],
  runtime: ['daimo:library_name', 'https://pionera.ai/edc/daimo#library_name'],
  languages: ['daimo:language', 'https://pionera.ai/edc/daimo#language'],
  architecture: ['daimo:architecture_family', 'https://pionera.ai/edc/daimo#architecture_family'],
  baseModel: ['daimo:base_model', 'https://pionera.ai/edc/daimo#base_model'],
  format: ['daimo:format', 'https://pionera.ai/edc/daimo#format'],
  inferencePath: ['daimo:inference_path', 'https://pionera.ai/edc/daimo#inference_path'],
  inputSchemaDraft: ['daimo:input_schema_draft', 'https://pionera.ai/edc/daimo#input_schema_draft'],
  inputSchema: ['daimo:input_schema', 'https://pionera.ai/edc/daimo#input_schema'],
  inputFeatures: ['daimo:input_features', 'https://pionera.ai/edc/daimo#input_features'],
  inputExample: ['daimo:input_example', 'https://pionera.ai/edc/daimo#input_example'],
  parameterCount: ['daimo:parameter_count', 'https://pionera.ai/edc/daimo#parameter_count'],
  artifactSize: ['daimo:artifact_size_mb', 'https://pionera.ai/edc/daimo#artifact_size_mb'],
  quantization: ['daimo:quantization', 'https://pionera.ai/edc/daimo#quantization'],
  performanceMetric: ['daimo:performance_metric', 'https://pionera.ai/edc/daimo#performance_metric'],
  performanceDataset: [
    'daimo:performance_dataset',
    'https://pionera.ai/edc/daimo#performance_dataset',
    'daimo:datasets',
    'https://pionera.ai/edc/daimo#datasets',
  ],
  performanceReport: ['daimo:performance_report', 'https://pionera.ai/edc/daimo#performance_report'],
  intendedUse: ['daimo:intended_use', 'https://pionera.ai/edc/daimo#intended_use'],
  limitations: ['daimo:limitations', 'https://pionera.ai/edc/daimo#limitations'],
  piiSafe: ['daimo:pii_safe', 'https://pionera.ai/edc/daimo#pii_safe'],
  regulatedDomain: ['daimo:regulated_domain', 'https://pionera.ai/edc/daimo#regulated_domain'],
  humanInLoop: ['daimo:human_in_the_loop_required', 'https://pionera.ai/edc/daimo#human_in_the_loop_required'],
  latencyP95: ['daimo:latency_p95_ms', 'https://pionera.ai/edc/daimo#latency_p95_ms'],
  throughput: ['daimo:throughput_rps', 'https://pionera.ai/edc/daimo#throughput_rps'],
  rateLimits: ['daimo:rate_limits', 'https://pionera.ai/edc/daimo#rate_limits'],
  availabilityTier: ['daimo:availability_tier', 'https://pionera.ai/edc/daimo#availability_tier'],
} as const;

const DEFAULT_ML_TASK_OPTIONS = [
  'text-classification',
  'token-classification',
  'question-answering',
  'summarization',
  'translation',
  'text-generation',
  'chat-completion',
  'text-embedding',
  'feature-extraction',
  'information-retrieval',
  'reranking',
  'image-classification',
  'object-detection',
  'image-segmentation',
  'image-generation',
  'image-captioning',
  'ocr',
  'audio-classification',
  'automatic-speech-recognition',
  'text-to-speech',
  'speaker-diarization',
  'tabular-classification',
  'tabular-regression',
  'time-series-forecasting',
  'anomaly-detection',
  'recommendation',
];

const DEFAULT_ML_MODALITY_OPTIONS = ['tabular', 'text', 'image', 'audio', 'video', 'multimodal'];

const DEFAULT_ML_KEYWORD_OPTIONS = [
  'classification',
  'regression',
  'forecasting',
  'anomaly-detection',
  'inference',
  'embedding',
  'chat',
  'recommendation',
  'rag',
  'vision',
  'speech',
  'demo',
];

const DEFAULT_ML_RUNTIME_OPTIONS = [
  'transformers',
  'onnxruntime',
  'tensorflow',
  'pytorch',
  'xgboost',
  'scikit-learn',
  'lightgbm',
  'mlflow',
  'custom-python',
  'other',
];

const DEFAULT_ML_LANGUAGE_OPTIONS = ['en', 'es', 'de', 'fr', 'it', 'pt', 'zh', 'ja', 'ar', 'hi'];

const DEFAULT_ML_LICENSE_OPTIONS = [
  'Apache-2.0',
  'MIT',
  'BSD-3-Clause',
  'MPL-2.0',
  'GPL-3.0-only',
  'AGPL-3.0-only',
  'CC-BY-4.0',
  'CC-BY-SA-4.0',
  'Proprietary',
];

const DEFAULT_ML_MATURITY_OPTIONS = ['experimental', 'validated', 'production', 'deprecated'];

const DEFAULT_ML_FORMAT_OPTIONS = ['onnx', 'safetensors', 'pt', 'pth', 'tensorflow-savedmodel', 'pickle', 'joblib', 'json'];
const DEFAULT_ML_INFERENCE_PATH_OPTIONS = ['/infer', '/predict', '/score', '/classify', '/v1/predict'];
const DEFAULT_ML_SCHEMA_DRAFT_OPTIONS = ['2020-12', '2019-09', 'draft-07'];
const DEFAULT_SCHEMA_FIELD_TYPES = ['string', 'number', 'integer', 'boolean', 'object', 'array', 'enum', 'any'];
const DEFAULT_ML_QUANTIZATION_OPTIONS = ['none', 'fp16', 'int8', 'int4', 'gptq', 'awq'];

const DEFAULT_ML_DATASET_OPTIONS = [
  'iris',
  'housing',
  'mteb',
  'squad',
  'imagenet',
  'coco',
  'librispeech',
  'custom',
];

const DEFAULT_ML_METRIC_OPTIONS = [
  'accuracy',
  'f1',
  'precision',
  'recall',
  'roc-auc',
  'bleu',
  'rouge-l',
  'wer',
  'mae',
  'rmse',
  'latency',
  'custom',
];

const DEFAULT_ML_AVAILABILITY_OPTIONS = ['bronze', 'silver', 'gold', 'platinum', 'internal'];
const DEFAULT_ML_ASSET_KIND_OPTIONS = ['model', 'dataset'];

const SCHEMA_TEMPLATE_PRESETS: SchemaTemplatePreset[] = [
  {
    id: 'text-classification',
    label: 'Text Classification',
    draft: '2020-12',
    schema: {
      type: 'object',
      properties: {
        text: { type: 'string', description: 'Input text to classify.' },
        language: { type: 'string', description: 'Optional ISO-639-1 code (for example "en").' },
      },
      required: ['text'],
      additionalProperties: false,
    },
    example: {
      text: 'The service quality was excellent and fast.',
      language: 'en',
    },
  },
  {
    id: 'embeddings',
    label: 'Text Embeddings',
    draft: '2020-12',
    schema: {
      type: 'object',
      properties: {
        input: { type: 'string', description: 'Input text to vectorize.' },
        normalize: { type: 'boolean', description: 'Return normalized vectors.' },
      },
      required: ['input'],
      additionalProperties: false,
    },
    example: {
      input: 'Industrial predictive maintenance handbook',
      normalize: true,
    },
  },
  {
    id: 'chat-completion',
    label: 'Chat Completion',
    draft: '2020-12',
    schema: {
      type: 'object',
      properties: {
        messages: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              role: { type: 'string', description: 'system | user | assistant' },
              content: { type: 'string', description: 'Message content.' },
            },
            required: ['role', 'content'],
          },
        },
        temperature: { type: 'number', description: 'Sampling temperature.' },
        max_tokens: { type: 'integer', description: 'Maximum output tokens.' },
      },
      required: ['messages'],
      additionalProperties: false,
    },
    example: {
      messages: [
        { role: 'system', content: 'You are a concise assistant.' },
        { role: 'user', content: 'Summarize this document in three bullets.' },
      ],
      temperature: 0.2,
      max_tokens: 256,
    },
  },
  {
    id: 'tabular-regression',
    label: 'Tabular Regression',
    draft: '2020-12',
    schema: {
      type: 'object',
      properties: {
        features: {
          type: 'object',
          properties: {
            age: { type: 'integer', description: 'User age in years.' },
            income: { type: 'number', description: 'Annual income.' },
            tenure_months: { type: 'integer', description: 'Customer tenure in months.' },
          },
          required: ['age', 'income'],
        },
      },
      required: ['features'],
      additionalProperties: false,
    },
    example: {
      features: {
        age: 42,
        income: 72000.5,
        tenure_months: 18,
      },
    },
  },
];

@Component({
  selector: 'lib-asset-create',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    AlertComponent,
    JsonObjectTableComponent,
    NgClass,
    DataTypeInputComponent,
    JsonObjectInputComponent,
    DataAddressFormComponent,
    OntologyAssetFieldsComponent,
  ],
  templateUrl: './asset-create.component.html',
  styleUrl: './asset-create.component.css',
})
export class AssetCreateComponent implements OnChanges {
  private readonly assetService = inject(AssetService);
  private readonly formBuilder = inject(FormBuilder);

  @Input() asset?: Asset;
  @Output() created = new EventEmitter<IdResponse>();
  @Output() updated = new EventEmitter<void>();
  mode: 'create' | 'update' = 'create';

  errorMsg = '';

  ontologyTestRunning = false;
  ontologyTestMessage = '';
  ontologyTestSuccess = false;
  showOntologyTestButton = false;
  ontologySelection: OntologyAssetSelection = this.emptyOntologySelection();
  private rdfTestFile?: File;

  properties: Record<string, JsonValue> = {};
  privateProperties: Record<string, JsonValue> = {};
  dataAddress?: DataAddress;

  mlTaskOptions = [...DEFAULT_ML_TASK_OPTIONS];
  mlModalityOptions = [...DEFAULT_ML_MODALITY_OPTIONS];
  mlKeywordOptions = [...DEFAULT_ML_KEYWORD_OPTIONS];
  mlRuntimeOptions = [...DEFAULT_ML_RUNTIME_OPTIONS];
  mlLanguageOptions = [...DEFAULT_ML_LANGUAGE_OPTIONS];
  mlLicenseOptions = [...DEFAULT_ML_LICENSE_OPTIONS];
  mlMaturityOptions = [...DEFAULT_ML_MATURITY_OPTIONS];
  mlFormatOptions = [...DEFAULT_ML_FORMAT_OPTIONS];
  mlInferencePathOptions = [...DEFAULT_ML_INFERENCE_PATH_OPTIONS];
  mlSchemaDraftOptions = [...DEFAULT_ML_SCHEMA_DRAFT_OPTIONS];
  schemaFieldTypeOptions = [...DEFAULT_SCHEMA_FIELD_TYPES];
  schemaTemplatePresets = [...SCHEMA_TEMPLATE_PRESETS];
  mlQuantizationOptions = [...DEFAULT_ML_QUANTIZATION_OPTIONS];
  mlDatasetOptions = [...DEFAULT_ML_DATASET_OPTIONS];
  mlMetricOptions = [...DEFAULT_ML_METRIC_OPTIONS];
  mlAvailabilityOptions = [...DEFAULT_ML_AVAILABILITY_OPTIONS];
  mlAssetKindOptions = [...DEFAULT_ML_ASSET_KIND_OPTIONS];

  schemaBuilderFields: SchemaBuilderField[] = [];
  schemaBuilderMessage = '';
  private schemaBuilderNextId = 1;

  assetForm: FormGroup;

  constructor() {
    this.assetForm = this.formBuilder.group({
      id: [''],
      name: [''],
      contenttype: [''],
      mlEnabled: [false],
      mlDescription: [''],
      mlVersion: [''],
      mlAssetKind: ['model'],
      mlTask: [''],
      mlModality: [[]],
      mlKeywords: [[]],
      mlLicense: [''],
      mlMaturity: [''],
      mlRuntime: [[]],
      mlLanguages: [[]],
      mlArchitecture: [''],
      mlBaseModel: [''],
      mlFormat: [''],
      mlInferencePath: [''],
      mlInputSchemaDraft: [''],
      mlInputSchema: [''],
      mlInputExample: [''],
      mlParameterCount: [''],
      mlArtifactSize: [''],
      mlQuantization: [''],
      mlPerformanceMetric: [''],
      mlPerformanceDataset: [''],
      mlPerformanceReport: [''],
      mlIntendedUse: [''],
      mlLimitations: [''],
      mlPiiSafe: [false],
      mlRegulatedDomain: [false],
      mlHumanInLoop: [false],
      mlLatencyP95: [''],
      mlThroughput: [''],
      mlRateLimits: [''],
      mlAvailabilityTier: [''],
    });
  }

  async ngOnChanges() {
    if (this.asset) {
      this.mode = 'update';
      await this.updateAssetAndSyncForm();
      this.assetForm.get('id')?.disable();
    }
  }

  toggleMultiValue(controlName: MlMultiSelectControl, value: string): void {
    const control = this.assetForm.get(controlName);
    if (!control) {
      return;
    }

    const currentValues = this.getMultiValues(controlName);
    const nextValues = currentValues.includes(value)
      ? currentValues.filter(current => current !== value)
      : [...currentValues, value];

    control.setValue(nextValues);
    control.markAsDirty();
  }

  isMultiValueSelected(controlName: MlMultiSelectControl, value: string): boolean {
    return this.getMultiValues(controlName).includes(value);
  }

  hasTextModalitySelected(): boolean {
    const modalities = this.getMultiValues('mlModality');
    return modalities.includes('text') || modalities.includes('multimodal');
  }

  addSchemaBuilderField(prefill?: Partial<SchemaBuilderField>): void {
    const field: SchemaBuilderField = {
      id: this.schemaBuilderNextId++,
      path: (prefill?.path || '').trim(),
      type: this.normalizeSchemaFieldType(prefill?.type || 'string'),
      required: prefill?.required === true,
      description: (prefill?.description || '').trim(),
      example: (prefill?.example || '').trim(),
    };

    this.schemaBuilderFields = [...this.schemaBuilderFields, field];
    this.trySyncSchemaFromBuilder(false);
  }

  removeSchemaBuilderField(fieldId: number): void {
    this.schemaBuilderFields = this.schemaBuilderFields.filter(field => field.id !== fieldId);
    this.trySyncSchemaFromBuilder(false);
  }

  clearSchemaBuilder(): void {
    this.schemaBuilderFields = [];
    this.schemaBuilderMessage = 'Input field builder cleared. Existing JSON schema remains unchanged.';
  }

  onSchemaFieldTextInput(fieldId: number, key: SchemaBuilderTextKey, event: Event): void {
    const value = (event.target as HTMLInputElement | HTMLTextAreaElement | null)?.value || '';
    this.schemaBuilderFields = this.schemaBuilderFields.map(field => {
      if (field.id !== fieldId) {
        return field;
      }

      if (key === 'path') {
        return { ...field, path: value };
      }
      if (key === 'description') {
        return { ...field, description: value };
      }
      return { ...field, example: value };
    });
    this.trySyncSchemaFromBuilder(false);
  }

  onSchemaFieldTypeInput(fieldId: number, event: Event): void {
    const value = (event.target as HTMLSelectElement | null)?.value || 'string';
    this.schemaBuilderFields = this.schemaBuilderFields.map(field =>
      field.id === fieldId ? { ...field, type: this.normalizeSchemaFieldType(value) } : field,
    );
    this.trySyncSchemaFromBuilder(false);
  }

  onSchemaFieldRequiredInput(fieldId: number, event: Event): void {
    const checked = (event.target as HTMLInputElement | null)?.checked === true;
    this.schemaBuilderFields = this.schemaBuilderFields.map(field =>
      field.id === fieldId ? { ...field, required: checked } : field,
    );
    this.trySyncSchemaFromBuilder(false);
  }

  syncSchemaFromBuilder(): void {
    this.trySyncSchemaFromBuilder(true);
  }

  generateExampleFromBuilder(): void {
    const validFields = this.getValidSchemaBuilderFields();
    if (validFields.length === 0) {
      this.schemaBuilderMessage = 'Add at least one valid input field before generating an example.';
      return;
    }

    try {
      const result: Record<string, unknown> = {};
      validFields.forEach(field => {
        const segments = this.parseSchemaPath(field.path);
        const value = this.resolveExampleValue(field);
        this.setValueAtPath(result, segments, value);
      });

      this.assetForm.get('mlInputExample')?.setValue(JSON.stringify(result, null, 2));
      this.assetForm.get('mlInputExample')?.markAsDirty();
      this.schemaBuilderMessage = `Input example generated from ${validFields.length} field(s).`;
    } catch (error) {
      this.schemaBuilderMessage =
        error instanceof Error ? `Cannot generate example: ${error.message}` : 'Cannot generate example.';
    }
  }

  applySchemaTemplate(templateId: string): void {
    const preset = this.schemaTemplatePresets.find(item => item.id === templateId);
    if (!preset) {
      this.schemaBuilderMessage = 'Unknown schema template.';
      return;
    }

    this.assetForm.get('mlInputSchemaDraft')?.setValue(preset.draft);
    this.assetForm.get('mlInputSchema')?.setValue(JSON.stringify(preset.schema, null, 2));
    this.assetForm.get('mlInputExample')?.setValue(JSON.stringify(preset.example, null, 2));
    this.loadSchemaBuilderFromCurrentSchema();
    this.schemaBuilderMessage = `Template "${preset.label}" applied.`;
  }

  loadSchemaBuilderFromCurrentSchema(): void {
    const schemaText = this.asTrimmedString(this.assetForm.get('mlInputSchema')?.value);
    if (!schemaText) {
      this.schemaBuilderFields = [];
      this.schemaBuilderMessage = 'No JSON schema to load.';
      return;
    }

    try {
      const schema = this.parseJsonObject(schemaText, 'Input schema');
      const features = this.extractInputFeaturesFromSchema(schema);
      const parsedExample = this.tryParseJsonText(this.asTrimmedString(this.assetForm.get('mlInputExample')?.value));

      this.schemaBuilderFields = features.map(feature => ({
        id: this.schemaBuilderNextId++,
        path: this.toStringValue(feature['name']),
        type: this.normalizeSchemaFieldType(this.toStringValue(feature['type']) || 'string'),
        required: feature['required'] === true,
        description: this.toStringValue(feature['description']),
        example: this.stringifyExampleValue(this.getValueAtSchemaPath(parsedExample, this.toStringValue(feature['name']))),
      }));

      if (this.schemaBuilderFields.length === 0) {
        this.schemaBuilderMessage = 'Schema loaded, but no feature fields were found.';
      } else {
        this.schemaBuilderMessage = `Loaded ${this.schemaBuilderFields.length} input field(s) from JSON schema.`;
      }
    } catch (error) {
      this.schemaBuilderMessage =
        error instanceof Error ? `Cannot load builder from schema: ${error.message}` : 'Cannot load builder from schema.';
    }
  }

  private async updateAssetAndSyncForm() {
    this.properties = await compact(this.asset!.properties);
    this.privateProperties = await compact(this.asset!.privateProperties);
    this.dataAddress = (await compact(this.asset!.dataAddress)) as unknown as BaseDataAddress;

    const shortDescription = this.readFirstString(DAIMO_METADATA_KEYS.shortDescription);
    const version = this.readFirstString(DAIMO_METADATA_KEYS.version);
    const assetKind = this.readFirstString(DAIMO_METADATA_KEYS.assetKind) || 'model';
    const task = this.readFirstString(DAIMO_METADATA_KEYS.task);
    const modalities = this.readStringList(DAIMO_METADATA_KEYS.modality);
    const keywords = this.readStringList(DAIMO_METADATA_KEYS.keywords);
    const license = this.readFirstString(DAIMO_METADATA_KEYS.license);
    const maturity = this.readFirstString(DAIMO_METADATA_KEYS.maturityStatus);
    const runtime = this.readStringList(DAIMO_METADATA_KEYS.runtime);
    const languages = this.readStringList(DAIMO_METADATA_KEYS.languages);
    const architecture = this.readFirstString(DAIMO_METADATA_KEYS.architecture);
    const baseModel = this.readFirstString(DAIMO_METADATA_KEYS.baseModel);
    const format = this.readFirstString(DAIMO_METADATA_KEYS.format);
    const inferencePath = this.readFirstString(DAIMO_METADATA_KEYS.inferencePath);
    const inputSchemaDraft = this.readFirstString(DAIMO_METADATA_KEYS.inputSchemaDraft);
    const inputSchema = this.readJsonText(DAIMO_METADATA_KEYS.inputSchema);
    const inputExample = this.readJsonText(DAIMO_METADATA_KEYS.inputExample);
    const parameterCount = this.readFirstString(DAIMO_METADATA_KEYS.parameterCount);
    const artifactSize = this.readFirstString(DAIMO_METADATA_KEYS.artifactSize);
    const quantization = this.readFirstString(DAIMO_METADATA_KEYS.quantization);
    const performanceMetric = this.readFirstString(DAIMO_METADATA_KEYS.performanceMetric);
    const performanceDataset = this.readFirstString(DAIMO_METADATA_KEYS.performanceDataset);
    const performanceReport = this.readFirstString(DAIMO_METADATA_KEYS.performanceReport);
    const intendedUse = this.readFirstString(DAIMO_METADATA_KEYS.intendedUse);
    const limitations = this.readFirstString(DAIMO_METADATA_KEYS.limitations);
    const piiSafe = this.readBoolean(DAIMO_METADATA_KEYS.piiSafe);
    const regulatedDomain = this.readBoolean(DAIMO_METADATA_KEYS.regulatedDomain);
    const humanInLoop = this.readBoolean(DAIMO_METADATA_KEYS.humanInLoop);
    const latencyP95 = this.readFirstString(DAIMO_METADATA_KEYS.latencyP95);
    const throughput = this.readFirstString(DAIMO_METADATA_KEYS.throughput);
    const rateLimits = this.readFirstString(DAIMO_METADATA_KEYS.rateLimits);
    const availabilityTier = this.readFirstString(DAIMO_METADATA_KEYS.availabilityTier);

    const hasMlMetadata =
      [
        shortDescription,
        version,
        assetKind,
        task,
        license,
        maturity,
        architecture,
        baseModel,
        format,
        inferencePath,
        inputSchemaDraft,
        inputSchema,
        inputExample,
        parameterCount,
        artifactSize,
        quantization,
        performanceMetric,
        performanceDataset,
        performanceReport,
        intendedUse,
        limitations,
        latencyP95,
        throughput,
        rateLimits,
        availabilityTier,
      ].some(value => !!value) ||
      modalities.length > 0 ||
      keywords.length > 0 ||
      runtime.length > 0 ||
      languages.length > 0 ||
      piiSafe ||
      regulatedDomain ||
      humanInLoop;

    this.ensureOption(this.mlTaskOptions, task);
    this.ensureOption(this.mlLicenseOptions, license);
    this.ensureOption(this.mlMaturityOptions, maturity);
    this.ensureOption(this.mlFormatOptions, format);
    this.ensureOption(this.mlInferencePathOptions, inferencePath);
    this.ensureOption(this.mlSchemaDraftOptions, inputSchemaDraft);
    this.ensureOption(this.mlQuantizationOptions, quantization);
    this.ensureOption(this.mlMetricOptions, performanceMetric);
    this.ensureOption(this.mlDatasetOptions, performanceDataset);
    this.ensureOption(this.mlAvailabilityOptions, availabilityTier);

    this.ensureOptions(this.mlModalityOptions, modalities);
    this.ensureOptions(this.mlKeywordOptions, keywords);
    this.ensureOptions(this.mlRuntimeOptions, runtime);
    this.ensureOptions(this.mlLanguageOptions, languages);

    this.assetForm.get('id')?.setValue(this.asset!.id);
    this.assetForm.get('name')?.setValue(this.properties['name']);
    this.assetForm.get('contenttype')?.setValue(this.properties['contenttype']);
    this.assetForm.patchValue({
      mlEnabled: hasMlMetadata,
      mlDescription: shortDescription,
      mlVersion: version,
      mlAssetKind: assetKind,
      mlTask: task,
      mlModality: modalities,
      mlKeywords: keywords,
      mlLicense: license,
      mlMaturity: maturity,
      mlRuntime: runtime,
      mlLanguages: languages,
      mlArchitecture: architecture,
      mlBaseModel: baseModel,
      mlFormat: format,
      mlInferencePath: inferencePath,
      mlInputSchemaDraft: inputSchemaDraft,
      mlInputSchema: inputSchema,
      mlInputExample: inputExample,
      mlParameterCount: parameterCount,
      mlArtifactSize: artifactSize,
      mlQuantization: quantization,
      mlPerformanceMetric: performanceMetric,
      mlPerformanceDataset: performanceDataset,
      mlPerformanceReport: performanceReport,
      mlIntendedUse: intendedUse,
      mlLimitations: limitations,
      mlPiiSafe: piiSafe,
      mlRegulatedDomain: regulatedDomain,
      mlHumanInLoop: humanInLoop,
      mlLatencyP95: latencyP95,
      mlThroughput: throughput,
      mlRateLimits: rateLimits,
      mlAvailabilityTier: availabilityTier,
    });

    if (inputSchema) {
      this.loadSchemaBuilderFromCurrentSchema();
    } else {
      this.schemaBuilderFields = [];
      this.schemaBuilderMessage = '';
    }
  }

  createAsset(): void {
    if (this.assetForm.valid) {
      const ontologyError = this.validateOntologySelection();
      if (ontologyError) {
        this.errorMsg = ontologyError;
        return;
      }

      let assetInput: AssetInput;
      try {
        assetInput = this.createAssetInput();
      } catch (error) {
        this.errorMsg = error instanceof Error ? error.message : 'Invalid ML metadata JSON.';
        return;
      }

      if (this.mode === 'create') {
        this.assetService
          .createAsset(assetInput)
          .then((idResponse: IdResponse) => {
            this.created.emit(idResponse);
          })
          .catch((err: EdcConnectorClientError) => {
            this.errorMsg = err.message;
          });
      } else if (this.mode === 'update') {
        this.assetService
          .updateAsset(assetInput)
          .then(() => this.updated.emit())
          .catch((err: EdcConnectorClientError) => (this.errorMsg = err.message));
      }
    } else {
      console.error('Create asset called with invalid form');
    }
  }

  private createAssetInput(): AssetInput {
    const properties = { ...this.properties };
    const privateProperties = { ...this.privateProperties };
    this.applyMlMetadata(properties);
    this.applyOntologyMetadata(properties);

    const asset: AssetInput = {
      dataAddress: this.dataAddress!,
      properties,
      privateProperties,
    };
    if (this.assetForm.value.id) {
      asset['@id'] = this.assetForm.value.id;
    }
    if (this.assetForm.value.name) {
      asset.properties['name'] = this.assetForm.value.name;
    }
    if (this.assetForm.value.contenttype) {
      asset.properties['contenttype'] = this.assetForm.value.contenttype;
    }
    return asset;
  }

  private applyMlMetadata(properties: Record<string, JsonValue>): void {
    this.clearMlMetadata(properties);

    if (!this.assetForm.value.mlEnabled) {
      return;
    }

    const shortDescription = this.asTrimmedString(this.assetForm.value.mlDescription);
    const version = this.asTrimmedString(this.assetForm.value.mlVersion);
    const assetKind = this.asTrimmedString(this.assetForm.value.mlAssetKind).toLowerCase() === 'dataset' ? 'dataset' : 'model';
    const task = this.asTrimmedString(this.assetForm.value.mlTask);
    const modalities = this.asStringArray(this.assetForm.value.mlModality);
    const keywords = this.asStringArray(this.assetForm.value.mlKeywords);
    const license = this.asTrimmedString(this.assetForm.value.mlLicense);
    const maturity = this.asTrimmedString(this.assetForm.value.mlMaturity);
    const runtime = this.asStringArray(this.assetForm.value.mlRuntime);
    const languages = this.asStringArray(this.assetForm.value.mlLanguages);
    const architecture = this.asTrimmedString(this.assetForm.value.mlArchitecture);
    const baseModel = this.asTrimmedString(this.assetForm.value.mlBaseModel);
    const format = this.asTrimmedString(this.assetForm.value.mlFormat);
    const inferencePath = this.asTrimmedString(this.assetForm.value.mlInferencePath);
    const inputSchemaDraft = this.asTrimmedString(this.assetForm.value.mlInputSchemaDraft);
    const existingSchemaText = this.asTrimmedString(this.assetForm.value.mlInputSchema);
    if (!existingSchemaText) {
      this.trySyncSchemaFromBuilder(false);
    }
    const inputSchemaText = this.asTrimmedString(this.assetForm.get('mlInputSchema')?.value);
    const inputExampleText = this.asTrimmedString(this.assetForm.get('mlInputExample')?.value);
    const parameterCount = this.asTrimmedString(this.assetForm.value.mlParameterCount);
    const artifactSize = this.asTrimmedString(this.assetForm.value.mlArtifactSize);
    const quantization = this.asTrimmedString(this.assetForm.value.mlQuantization);
    const performanceMetric = this.asTrimmedString(this.assetForm.value.mlPerformanceMetric);
    const performanceDataset = this.asTrimmedString(this.assetForm.value.mlPerformanceDataset);
    const performanceReport = this.asTrimmedString(this.assetForm.value.mlPerformanceReport);
    const intendedUse = this.asTrimmedString(this.assetForm.value.mlIntendedUse);
    const limitations = this.asTrimmedString(this.assetForm.value.mlLimitations);
    const latencyP95 = this.asTrimmedString(this.assetForm.value.mlLatencyP95);
    const throughput = this.asTrimmedString(this.assetForm.value.mlThroughput);
    const rateLimits = this.asTrimmedString(this.assetForm.value.mlRateLimits);
    const availabilityTier = this.asTrimmedString(this.assetForm.value.mlAvailabilityTier);

    if (shortDescription) {
      properties['daimo:short_description'] = shortDescription;
    }
    if (version) {
      properties['daimo:model_version'] = version;
    }
    properties['daimo:asset_kind'] = assetKind;
    properties['asset:prop:kind'] = assetKind;
    if (task) {
      properties['daimo:pipeline_tag'] = task;
    }
    if (modalities.length > 0) {
      properties['daimo:modality'] = modalities;
    }
    if (keywords.length > 0) {
      properties['daimo:tags'] = keywords;
    }
    if (license) {
      properties['daimo:license'] = license;
    }
    if (maturity) {
      properties['daimo:maturity_status'] = maturity;
    }
    if (runtime.length > 0) {
      properties['daimo:library_name'] = runtime;
    }
    if (languages.length > 0) {
      properties['daimo:language'] = languages;
    }
    if (architecture) {
      properties['daimo:architecture_family'] = architecture;
    }
    if (baseModel) {
      properties['daimo:base_model'] = baseModel;
    }
    if (format) {
      properties['daimo:format'] = format;
    }
    if (inferencePath) {
      properties['daimo:inference_path'] = inferencePath;
    }
    if (inputSchemaDraft) {
      properties['daimo:input_schema_draft'] = inputSchemaDraft;
    }
    if (inputSchemaText) {
      const parsedSchema = this.parseJsonObject(inputSchemaText, 'Input schema');
      properties['daimo:input_schema'] = parsedSchema as JsonValue;

      const schemaDraft = this.extractSchemaDraft(parsedSchema);
      if (!inputSchemaDraft && schemaDraft) {
        properties['daimo:input_schema_draft'] = schemaDraft;
      }

      const inputFeatures = this.extractInputFeaturesFromSchema(parsedSchema);
      if (inputFeatures.length > 0) {
        properties['daimo:input_features'] = inputFeatures as JsonValue;
      }
    }
    if (inputExampleText) {
      const parsedExample = this.parseJsonValue(inputExampleText, 'Input example');
      properties['daimo:input_example'] = parsedExample as JsonValue;
    }
    if (parameterCount) {
      properties['daimo:parameter_count'] = parameterCount;
    }
    if (artifactSize) {
      properties['daimo:artifact_size_mb'] = artifactSize;
    }
    if (quantization) {
      properties['daimo:quantization'] = quantization;
    }
    if (performanceMetric) {
      properties['daimo:performance_metric'] = performanceMetric;
    }
    if (performanceDataset) {
      properties['daimo:performance_dataset'] = performanceDataset;
      properties['daimo:datasets'] = [performanceDataset];
    }
    if (performanceReport) {
      properties['daimo:performance_report'] = performanceReport;
    }
    if (intendedUse) {
      properties['daimo:intended_use'] = intendedUse;
    }
    if (limitations) {
      properties['daimo:limitations'] = limitations;
    }
    if (this.assetForm.value.mlPiiSafe) {
      properties['daimo:pii_safe'] = true;
    }
    if (this.assetForm.value.mlRegulatedDomain) {
      properties['daimo:regulated_domain'] = true;
    }
    if (this.assetForm.value.mlHumanInLoop) {
      properties['daimo:human_in_the_loop_required'] = true;
    }
    if (latencyP95) {
      properties['daimo:latency_p95_ms'] = latencyP95;
    }
    if (throughput) {
      properties['daimo:throughput_rps'] = throughput;
    }
    if (rateLimits) {
      properties['daimo:rate_limits'] = rateLimits;
    }
    if (availabilityTier) {
      properties['daimo:availability_tier'] = availabilityTier;
    }
  }

  private clearMlMetadata(properties: Record<string, JsonValue>): void {
    Object.values(DAIMO_METADATA_KEYS)
      .flat()
      .forEach(key => {
        delete properties[key];
      });
  }

  private readFirstString(keys: readonly string[]): string {
    return this.readStringList(keys)[0] || '';
  }

  private readStringList(keys: readonly string[]): string[] {
    const values = keys.flatMap(key => this.extractStrings(this.properties[key]));
    return this.uniqueStrings(values);
  }

  private readBoolean(keys: readonly string[]): boolean {
    for (const key of keys) {
      const value = this.extractScalar(this.properties[key]);
      if (typeof value === 'boolean') {
        return value;
      }
      if (typeof value === 'string') {
        const normalized = value.trim().toLowerCase();
        if (normalized === 'true') {
          return true;
        }
        if (normalized === 'false') {
          return false;
        }
      }
    }
    return false;
  }

  private readJsonText(keys: readonly string[]): string {
    for (const key of keys) {
      const rawValue = this.properties[key];
      const parsed = this.extractJsonValue(rawValue);
      if (parsed === undefined) {
        continue;
      }
      if (typeof parsed === 'string') {
        const trimmed = parsed.trim();
        if (!trimmed) {
          continue;
        }
        try {
          const parsedString = JSON.parse(trimmed) as unknown;
          return JSON.stringify(parsedString, null, 2);
        } catch {
          return trimmed;
        }
      }
      return JSON.stringify(parsed, null, 2);
    }
    return '';
  }

  private ensureOption(options: string[], value: string): void {
    if (!value || options.includes(value)) {
      return;
    }
    options.push(value);
    options.sort((a, b) => a.localeCompare(b));
  }

  private ensureOptions(options: string[], values: string[]): void {
    values.forEach(value => this.ensureOption(options, value));
  }

  private getMultiValues(controlName: MlMultiSelectControl): string[] {
    return this.asStringArray(this.assetForm.get(controlName)?.value);
  }

  private extractScalar(value: unknown): unknown {
    if (Array.isArray(value)) {
      return this.extractScalar(value[0]);
    }
    if (value && typeof value === 'object') {
      const record = value as Record<string, unknown>;
      if (record['@value'] !== undefined) {
        return record['@value'];
      }
    }
    return value;
  }

  private extractStrings(value: unknown): string[] {
    if (value == null) {
      return [];
    }
    if (Array.isArray(value)) {
      return value.flatMap(item => this.extractStrings(item));
    }
    if (typeof value === 'string') {
      const normalized = value.trim();
      return normalized ? [normalized] : [];
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
      return [String(value)];
    }
    if (typeof value === 'object') {
      const record = value as Record<string, unknown>;
      if (record['@value'] !== undefined) {
        return this.extractStrings(record['@value']);
      }
      return [];
    }
    return [];
  }

  private asTrimmedString(value: unknown): string {
    if (typeof value !== 'string') {
      return '';
    }
    return value.trim();
  }

  private asStringArray(value: unknown): string[] {
    if (Array.isArray(value)) {
      return this.uniqueStrings(value.map(item => this.asTrimmedString(item)).filter(item => !!item));
    }

    const normalized = this.asTrimmedString(value);
    return normalized ? [normalized] : [];
  }

  private extractJsonValue(value: unknown): unknown {
    if (Array.isArray(value)) {
      return this.extractJsonValue(value[0]);
    }
    if (value && typeof value === 'object') {
      const record = value as Record<string, unknown>;
      if (record['@value'] !== undefined) {
        return this.extractJsonValue(record['@value']);
      }
      return record;
    }
    return value;
  }

  private parseJsonValue(text: string, fieldName: string): unknown {
    try {
      return JSON.parse(text) as unknown;
    } catch {
      throw new Error(`${fieldName} must be valid JSON.`);
    }
  }

  private parseJsonObject(text: string, fieldName: string): Record<string, unknown> {
    const parsed = this.parseJsonValue(text, fieldName);
    if (!this.isRecord(parsed)) {
      throw new Error(`${fieldName} must be a JSON object.`);
    }
    return parsed;
  }

  private extractSchemaDraft(schema: Record<string, unknown>): string {
    const schemaId = schema['$schema'];
    if (typeof schemaId !== 'string') {
      return '';
    }
    const normalized = schemaId.toLowerCase();
    if (normalized.includes('2020-12')) {
      return '2020-12';
    }
    if (normalized.includes('2019-09')) {
      return '2019-09';
    }
    if (normalized.includes('draft-07')) {
      return 'draft-07';
    }
    return '';
  }

  private extractInputFeaturesFromSchema(schema: Record<string, unknown>): Array<Record<string, JsonValue>> {
    const result: Array<Record<string, JsonValue>> = [];
    this.collectSchemaFeatures(schema, '', result);
    return result;
  }

  private collectSchemaFeatures(
    schemaNode: Record<string, unknown>,
    prefix: string,
    target: Array<Record<string, JsonValue>>,
  ): void {
    const propertiesNode = schemaNode['properties'];
    if (!this.isRecord(propertiesNode)) {
      return;
    }

    const requiredFields = new Set(this.readRequiredArray(schemaNode['required']));
    Object.entries(propertiesNode).forEach(([propertyName, propertySchema]) => {
      const path = prefix ? `${prefix}.${propertyName}` : propertyName;
      const propertyRecord = this.isRecord(propertySchema) ? propertySchema : {};
      const type = this.inferSchemaFieldType(propertyRecord);

      target.push({
        name: path,
        type,
        required: requiredFields.has(propertyName),
        description: typeof propertyRecord['description'] === 'string' ? propertyRecord['description'] : '',
      });

      if (type === 'object' && this.isRecord(propertyRecord['properties'])) {
        this.collectSchemaFeatures(propertyRecord, path, target);
      }

      if (type === 'array' && this.isRecord(propertyRecord['items'])) {
        const itemSchema = propertyRecord['items'] as Record<string, unknown>;
        if (this.isRecord(itemSchema['properties'])) {
          this.collectSchemaFeatures(itemSchema, `${path}[]`, target);
        }
      }
    });
  }

  private inferSchemaFieldType(schema: Record<string, unknown>): string {
    const typeNode = schema['type'];
    if (typeof typeNode === 'string') {
      return typeNode.toLowerCase();
    }

    if (Array.isArray(typeNode)) {
      const firstString = typeNode.find(item => typeof item === 'string');
      if (typeof firstString === 'string') {
        return firstString.toLowerCase();
      }
    }

    if (Array.isArray(schema['enum'])) {
      return 'enum';
    }
    if (this.isRecord(schema['properties'])) {
      return 'object';
    }
    if (this.isRecord(schema['items'])) {
      return 'array';
    }

    return 'any';
  }

  private readRequiredArray(value: unknown): string[] {
    if (!Array.isArray(value)) {
      return [];
    }
    return value
      .filter(item => typeof item === 'string' && item.trim().length > 0)
      .map(item => (item as string).trim());
  }

  private trySyncSchemaFromBuilder(showMessage: boolean): boolean {
    const validFields = this.getValidSchemaBuilderFields();
    if (validFields.length === 0) {
      if (showMessage) {
        this.schemaBuilderMessage = 'Add at least one field with a valid path to generate JSON schema.';
      }
      return false;
    }

    try {
      const schema = this.buildSchemaFromBuilder(validFields);
      this.assetForm.get('mlInputSchema')?.setValue(JSON.stringify(schema, null, 2));
      this.assetForm.get('mlInputSchema')?.markAsDirty();
      if (showMessage) {
        this.schemaBuilderMessage = `JSON schema updated from ${validFields.length} field(s).`;
      }
      return true;
    } catch (error) {
      if (showMessage) {
        this.schemaBuilderMessage =
          error instanceof Error ? `Cannot generate JSON schema: ${error.message}` : 'Cannot generate JSON schema.';
      }
      return false;
    }
  }

  private getValidSchemaBuilderFields(): SchemaBuilderField[] {
    const seen = new Set<string>();
    const valid: SchemaBuilderField[] = [];

    this.schemaBuilderFields.forEach(field => {
      const normalizedPath = field.path.trim();
      if (!normalizedPath) {
        return;
      }

      const normalizedType = this.normalizeSchemaFieldType(field.type);
      const key = `${normalizedPath.toLowerCase()}|${normalizedType}|${field.required ? '1' : '0'}`;
      if (seen.has(key)) {
        return;
      }
      seen.add(key);

      valid.push({
        ...field,
        path: normalizedPath,
        type: normalizedType,
        description: field.description.trim(),
        example: field.example.trim(),
      });
    });

    return valid;
  }

  private buildSchemaFromBuilder(fields: SchemaBuilderField[]): Record<string, unknown> {
    const root: Record<string, unknown> = {
      type: 'object',
      properties: {},
      additionalProperties: false,
    };

    const draft = this.asTrimmedString(this.assetForm.get('mlInputSchemaDraft')?.value);
    const draftUri = this.resolveDraftUri(draft);
    if (draftUri) {
      root['$schema'] = draftUri;
    }

    fields.forEach(field => {
      const segments = this.parseSchemaPath(field.path);
      let currentNode = root;

      segments.forEach((segment, index) => {
        this.ensureObjectSchemaNode(currentNode);
        const properties = currentNode['properties'] as Record<string, unknown>;
        const existingNode = properties[segment.key];
        const propertyNode = this.isRecord(existingNode) ? existingNode : {};
        properties[segment.key] = propertyNode;

        if (field.required) {
          this.addRequiredField(currentNode, segment.key);
        }

        const isLeaf = index === segments.length - 1;
        if (segment.isArray) {
          propertyNode['type'] = 'array';
          const existingItems = propertyNode['items'];
          const itemsNode = this.isRecord(existingItems) ? existingItems : {};
          propertyNode['items'] = itemsNode;

          if (isLeaf) {
            this.applyLeafSchema(itemsNode, field);
          } else {
            this.ensureObjectSchemaNode(itemsNode);
            currentNode = itemsNode;
          }
          return;
        }

        if (isLeaf) {
          this.applyLeafSchema(propertyNode, field);
          return;
        }

        this.ensureObjectSchemaNode(propertyNode);
        currentNode = propertyNode;
      });
    });

    return root;
  }

  private parseSchemaPath(path: string): Array<{ key: string; isArray: boolean }> {
    const segments = path
      .split('.')
      .map(segment => segment.trim())
      .filter(segment => segment.length > 0);

    if (segments.length === 0) {
      throw new Error('Field path cannot be empty.');
    }

    return segments.map(segment => {
      const isArray = segment.endsWith('[]');
      const key = isArray ? segment.slice(0, -2).trim() : segment;
      if (!key) {
        throw new Error(`Invalid field path segment "${segment}".`);
      }
      return { key, isArray };
    });
  }

  private ensureObjectSchemaNode(node: Record<string, unknown>): void {
    if (!this.isRecord(node['properties'])) {
      node['properties'] = {};
    }
    node['type'] = 'object';
  }

  private addRequiredField(node: Record<string, unknown>, key: string): void {
    const existingRequired = this.readRequiredArray(node['required']);
    if (!existingRequired.includes(key)) {
      node['required'] = [...existingRequired, key];
    }
  }

  private applyLeafSchema(node: Record<string, unknown>, field: SchemaBuilderField): void {
    const normalizedType = this.normalizeSchemaFieldType(field.type);

    if (normalizedType === 'enum') {
      node['type'] = 'string';
      const enumValues = this.parseEnumValues(field.example);
      if (enumValues.length > 0) {
        node['enum'] = enumValues;
      } else {
        delete node['enum'];
      }
    } else {
      node['type'] = normalizedType;
      delete node['enum'];
    }

    if (normalizedType === 'array' && !this.isRecord(node['items'])) {
      node['items'] = { type: 'string' };
    }
    if (field.description) {
      node['description'] = field.description;
    } else {
      delete node['description'];
    }
  }

  private parseEnumValues(example: string): string[] {
    const trimmed = example.trim();
    if (!trimmed) {
      return [];
    }

    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (Array.isArray(parsed)) {
        return parsed
          .map(item => (typeof item === 'string' ? item.trim() : String(item)))
          .filter(value => value.length > 0);
      }
    } catch {
      // ignore and fallback to delimited parsing
    }

    return trimmed
      .split('|')
      .map(value => value.trim())
      .filter(value => value.length > 0);
  }

  private normalizeSchemaFieldType(type: string): string {
    const normalized = (type || '').trim().toLowerCase();
    if (!normalized) {
      return 'string';
    }
    if (normalized === 'int') {
      return 'integer';
    }
    if (normalized === 'float' || normalized === 'double') {
      return 'number';
    }
    return this.schemaFieldTypeOptions.includes(normalized) ? normalized : 'string';
  }

  private resolveDraftUri(draft: string): string {
    switch (draft) {
      case '2020-12':
        return 'https://json-schema.org/draft/2020-12/schema';
      case '2019-09':
        return 'https://json-schema.org/draft/2019-09/schema';
      case 'draft-07':
        return 'http://json-schema.org/draft-07/schema#';
      default:
        return '';
    }
  }

  private resolveExampleValue(field: SchemaBuilderField): unknown {
    const customExample = field.example.trim();
    if (customExample) {
      try {
        return JSON.parse(customExample);
      } catch {
        if (/^(true|false)$/i.test(customExample)) {
          return customExample.toLowerCase() === 'true';
        }
        if (/^[-+]?\d+(\.\d+)?$/.test(customExample)) {
          return Number(customExample);
        }
        return customExample;
      }
    }

    switch (this.normalizeSchemaFieldType(field.type)) {
      case 'integer':
        return 0;
      case 'number':
        return 0.0;
      case 'boolean':
        return true;
      case 'array':
        return [];
      case 'object':
        return {};
      case 'enum':
        return 'value';
      case 'any':
        return 'value';
      default:
        return 'text';
    }
  }

  private setValueAtPath(
    target: Record<string, unknown>,
    segments: Array<{ key: string; isArray: boolean }>,
    value: unknown,
  ): void {
    let cursor: Record<string, unknown> = target;

    segments.forEach((segment, index) => {
      const isLeaf = index === segments.length - 1;

      if (segment.isArray) {
        if (!Array.isArray(cursor[segment.key])) {
          cursor[segment.key] = [];
        }
        const arrayRef = cursor[segment.key] as unknown[];

        if (isLeaf) {
          arrayRef.splice(0, arrayRef.length, value);
          return;
        }

        if (!this.isRecord(arrayRef[0])) {
          arrayRef[0] = {};
        }
        cursor = arrayRef[0] as Record<string, unknown>;
        return;
      }

      if (isLeaf) {
        cursor[segment.key] = value;
        return;
      }

      if (!this.isRecord(cursor[segment.key])) {
        cursor[segment.key] = {};
      }
      cursor = cursor[segment.key] as Record<string, unknown>;
    });
  }

  private getValueAtSchemaPath(source: unknown, path: string): unknown {
    if (!this.isRecord(source)) {
      return undefined;
    }

    const segments = this.parseSchemaPath(path);
    let current: unknown = source;

    for (const segment of segments) {
      if (!this.isRecord(current) || !(segment.key in current)) {
        return undefined;
      }
      current = current[segment.key];

      if (segment.isArray) {
        if (!Array.isArray(current) || current.length === 0) {
          return undefined;
        }
        current = current[0];
      }
    }

    return current;
  }

  private stringifyExampleValue(value: unknown): string {
    if (value === undefined || value === null) {
      return '';
    }
    if (typeof value === 'string') {
      return value;
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
      return String(value);
    }
    return JSON.stringify(value);
  }

  private tryParseJsonText(text: string): unknown {
    if (!text) {
      return undefined;
    }
    try {
      return JSON.parse(text);
    } catch {
      return undefined;
    }
  }

  private toStringValue(value: unknown): string {
    return typeof value === 'string' ? value : '';
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }

  private uniqueStrings(values: string[]): string[] {
    const seen = new Set<string>();
    const uniqueValues: string[] = [];

    values.forEach(value => {
      if (!seen.has(value)) {
        seen.add(value);
        uniqueValues.push(value);
      }
    });

    return uniqueValues;
  }

  onDataAddressChange(address: DataAddress): void {
    this.dataAddress = address;
  }

  onOntologySelectionChange(selection: OntologyAssetSelection): void {
    this.ontologySelection = selection;
    this.updateOntologyTestButtonVisibility();
  }

  onRdfTestFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.rdfTestFile = input.files?.[0];
    this.ontologyTestMessage = '';
    this.updateOntologyTestButtonVisibility();
  }

  async runOntologyTest(): Promise<void> {
    const { ontologyDownloadUrl, shaclDownloadUrl, isOntologyComplete } = this.ontologySelection;
    if (!isOntologyComplete || !ontologyDownloadUrl || !shaclDownloadUrl || !this.rdfTestFile) {
      this.ontologyTestSuccess = false;
      this.ontologyTestMessage = 'Select ontology, version, SHACL, and an RDF test file.';
      return;
    }
    this.ontologyTestRunning = true;
    this.ontologyTestMessage = '';
    try {
      await this.assetService.testRdfAsset(
        ontologyDownloadUrl,
        shaclDownloadUrl,
        this.rdfTestFile,
        resolveRdfFormat(this.rdfTestFile),
      );
      this.ontologyTestSuccess = true;
      this.ontologyTestMessage = 'RDF validation test completed.';
    } catch (error) {
      this.ontologyTestSuccess = false;
      this.ontologyTestMessage = this.extractRdfValidationError(error);
    } finally {
      this.ontologyTestRunning = false;
    }
  }

  private applyOntologyMetadata(properties: Record<string, JsonValue>): void {
    const { ontologyDownloadUrl, shaclDownloadUrl, isOntologyComplete } = this.ontologySelection;
    if (isOntologyComplete && ontologyDownloadUrl && shaclDownloadUrl) {
      properties['ontologyDownloadUrl'] = ontologyDownloadUrl;
      properties['shaclDownloadUrl'] = shaclDownloadUrl;
    }
  }

  private validateOntologySelection(): string | null {
    const { ontologyUri, ontologyVersion, ontologyShacl } = this.ontologySelection;
    const started = !!(ontologyUri || ontologyVersion || ontologyShacl);
    if (!started) {
      return null;
    }
    if (!ontologyUri || !ontologyVersion || !ontologyShacl) {
      return 'Complete ontology, version, and SHACL selection, or clear all ontology fields.';
    }
    if (ontologyShacl === NEW_SHACLE_FILE_VALUE) {
      return 'Upload the new SHACL file and select it from the list before creating the asset.';
    }
    if (!this.ontologySelection.isOntologyComplete) {
      return 'Unable to build ontology download URLs. Re-select the ontology.';
    }
    return null;
  }

  private updateOntologyTestButtonVisibility(): void {
    this.showOntologyTestButton =
      this.ontologySelection.isOntologyComplete &&
      !!this.rdfTestFile &&
      isLikelySemanticRdfFile(this.rdfTestFile);
  }

  private extractRdfValidationError(error: unknown): string {
    if (error && typeof error === 'object') {
      const record = error as Record<string, unknown>;
      const body = record['error'] ?? record;
      if (Array.isArray(body)) {
        return body
          .map(entry => (typeof entry === 'string' ? entry : (entry as { message?: string })?.message))
          .filter(Boolean)
          .join('\n');
      }
      if (body && typeof body === 'object') {
        const message = (body as { message?: string }).message;
        if (message) {
          return message;
        }
      }
      if (typeof record['message'] === 'string') {
        return record['message'];
      }
    }
    return error instanceof Error ? error.message : 'RDF validation test failed (asset creation is not blocked).';
  }

  private emptyOntologySelection(): OntologyAssetSelection {
    return {
      ontologyUri: '',
      ontologyVersion: '',
      ontologyShacl: '',
      ontologyDownloadUrl: '',
      shaclDownloadUrl: '',
      isOntologyComplete: false,
    };
  }
}
