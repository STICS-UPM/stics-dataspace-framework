import { Component, Inject, OnInit, QueryList, ViewChildren } from '@angular/core';
import { HttpDataAddress, DataAddress } from '@think-it-labs/edc-connector-client';
import { JsonDoc } from "../../../shared/models/json-doc";
import { StorageType } from "../../../shared/models/storage-type";
import { AmazonS3DataAddress } from "../../../shared/models/amazon-s3-data-address";
import { Vocabulary } from "../../../shared/models/vocabulary";
import { NotificationService } from 'src/app/shared/services/notification.service';
import { DATA_ADDRESS_TYPES, ASSET_TYPES } from 'src/app/shared/utils/app.constants';
import { CKEDITOR_CONFIG } from 'src/app/shared/utils/ckeditor.utils';
import { LoadingService } from 'src/app/shared/services/loading.service';
import { createAjv } from '@jsonforms/core';
import { angularMaterialRenderers } from '@jsonforms/angular-material';
import * as jsonld from 'jsonld';
import { VocabularyService } from 'src/app/shared/services/vocabulary.service';
import { JsonFormData } from 'src/app/shared/models/json-form-data';
import { InesDataStoreAddress } from 'src/app/shared/models/ines-data-store-address';
import ClassicEditor from '@ckeditor/ckeditor5-build-classic';
import { AssetService } from 'src/app/shared/services/asset.service';
import { BehaviorSubject } from 'rxjs';
import { Router } from '@angular/router';
import { MatSlideToggleChange } from '@angular/material/slide-toggle';
import { NgModel } from '@angular/forms';


@Component({
  selector: 'app-asset-create',
  templateUrl: './asset-create.component.html',
  styleUrls: ['./asset-create.component.scss']
})
export class AssetCreateComponent implements OnInit {

  readonly uischemaComplete = {
    type: 'VerticalLayout',
    elements: [
      {
        type: 'Control',
        scope: '#/'
      }
    ]
  };

  // Dynamic forms from vocabylary variables
  vocabularies: Vocabulary[];
  selectedVocabularies: Vocabulary[]
  defaultVocabularies: Vocabulary[]

  renderers = angularMaterialRenderers;
  uischema = this.uischemaComplete;
  schema: any = {
    type: 'object',
    properties: {
      loading: {
        "type": "string",
        "title": "Default asset"
      },
    },
    required: [],
  };
  data = {};
  ajv = createAjv({
    allErrors: true,
    verbose: true,
    strict: false,
  });
  validator: any;

  // Default asset properties
  id: string = '';
  version: string = '';
  name: string = '';
  contenttype: string = '';
  storageTypeId: string = '';
  shortDescription: string = '';
  description: string = '';
  keywords: string = '';
  format: string = '';
  byteSize: string = '';

  // Storage information
  amazonS3DataAddress: AmazonS3DataAddress = {
    type: 'AmazonS3',
    region: ''
  };

  httpDataAddress: HttpDataAddress = {
    type: 'HttpData'
  };

  inesDataStoreAddress: InesDataStoreAddress = {
    type: 'InesDataStore'
  };

  assetType: any;
  assetTypes = Object.entries(ASSET_TYPES);
  defaultForms: JsonFormData[];
  selectedForms: JsonFormData[];
  @ViewChildren(NgModel) formControls: QueryList<NgModel>;

  inesDataStoreFiles: File[]

  // Text Editor
  editor = ClassicEditor;
  config = CKEDITOR_CONFIG
  selectedAssetTypeVocabularies: Vocabulary[]

  private fetch$ = new BehaviorSubject(null);

  ngOnInit(): void {
    this.validator = this.ajv.compile(this.schema);
    this.defaultForms = []
    this.selectedForms = []
    this.selectedAssetTypeVocabularies = []

    this.vocabularyService.requestVocabularies().subscribe({
      next: (res: Vocabulary[]) => {
        this.vocabularies = res;
        this.setDefaultVocabularyAndTabs();
        if (this.defaultVocabularies?.length > 0) {
          this.defaultVocabularies.forEach(d => {
            this.initVocabularyForm(d, true)
          })
        }
        if (this.selectedVocabularies?.length > 0) {
          this.selectedVocabularies.forEach(s => {
            if (this.selectedAssetTypeVocabularies.find(satv => satv['@id'] === s['@id'])) {
              this.initVocabularyForm(s, false)
            }
          })
        }
      },
    });
  }

  /**
   * Sets default values for vocabulary and tabs
   */
  setDefaultVocabularyAndTabs() {

    if (this.vocabularies.length > 0) {
      this.assetType = this.assetTypes[0][0];
      this.selectedVocabularies = this.vocabularies.filter(v => v.category !== 'default' && v.category === this.assetType)
      this.defaultVocabularies = this.vocabularies.filter(v => v.category === 'default')
    } else {
      this.selectedVocabularies = []
      this.defaultVocabularies = []
    }
  }

  constructor(private assetService: AssetService,
    private vocabularyService: VocabularyService,
    private notificationService: NotificationService,
    @Inject('STORAGE_TYPES') public storageTypes: StorageType[],
    private router: Router,
    private loadingService: LoadingService) {
  }

  async onSave() {
    this.loadingService.showLoading();
    this.formControls.toArray().forEach(control => {
      control.control.markAsTouched();
    });
    // Check whether the asset is valid
    if (!this.checkVocabularyData() || !this.checkRequiredFields()) {
      this.notificationService.showError("Review the form fields");
      this.loadingService.hideLoading();
      return;
    }

    // Generate the asset properties
    let properties: JsonDoc = {};
    const forms: JsonFormData[] = [...this.defaultForms, ...this.selectedForms]

    let assetDataProperty: any = {}
    for (const f of forms) {
      if (f.schema && f.schema.hasOwnProperty("@context")) {
        // Add context if it is provided in the Json Schema
        const jsonSchema: JsonDoc = f.schema as JsonDoc;
        const context = jsonSchema["@context"];
        // Add default EDC vocabulary is none has been set up
        if (!f.schema["@context"].hasOwnProperty("@vocab")) {
          context["@vocab"] = "https://w3id.org/edc/v0.0.1/ns/"
        }
        let compacted: JsonDoc = f.data as JsonDoc;
        compacted["@context"] = context;
        assetDataProperty[f.id] = await jsonld.expand(compacted);
      } else {
        assetDataProperty[f.id] = f.data;
      }
    }

    properties["assetData"] = assetDataProperty

    // Add general information
    this.addInfoProperties(properties);

    // Generate the asset data address
    let dataAddress: DataAddress;

    if (this.storageTypeId === DATA_ADDRESS_TYPES.amazonS3) {
      dataAddress = this.amazonS3DataAddress;
    } else if (this.storageTypeId === DATA_ADDRESS_TYPES.httpData) {
      dataAddress = this.httpDataAddress;
    } else if (this.storageTypeId === DATA_ADDRESS_TYPES.inesDataStore) {
      dataAddress = this.inesDataStoreAddress;
    } else {
      this.notificationService.showError("Incorrect destination value");
      this.loadingService.hideLoading();
      return;
    }

    // Create EDC asset
    const assetInput: any = {
      "@id": this.id,
      properties: properties,
      dataAddress: dataAddress
    };

    if (this.storageTypeId === DATA_ADDRESS_TYPES.inesDataStore && this.inesDataStoreAddress?.file) {
      this.loadingService.showLoading('Processing the file...');
      const file = this.inesDataStoreAddress?.file;

      const chunkSize = 1024 * 1024;
      let offset = 0;
      const chunks: Blob[] = [];

      while (offset < file.size) {
        const slice = file.slice(offset, offset + chunkSize);
        const arrayBuffer = await slice.arrayBuffer();
        chunks.push(new Blob([arrayBuffer]));
        offset += chunkSize;
      }

      assetInput.blob = new Blob(chunks);
    }

    await this.createAsset(assetInput)
  }
  addInfoProperties(properties: JsonDoc) {
    // Add default information
    properties["name"] = this.name;
    properties["version"] = this.version;
    properties["contenttype"] = this.contenttype;
    properties["assetType"] = this.assetType;
    properties["shortDescription"] = this.shortDescription;
    properties["dcterms:description"] = this.description;
    properties["dcat:byteSize"] = this.byteSize;
    properties["dcterms:format"] = this.format;

    this.addKeywords(properties);
  }

  addKeywords(properties: JsonDoc) {
    const parsedKeywords: string[] = [];
    this.keywords.split(",").forEach(keyword => parsedKeywords.push(keyword.trim()));
    properties["dcat:keyword"] = parsedKeywords;
  }

  initVocabularyForm(vocabulary: Vocabulary, isDefault: boolean) {
    let schema = JSON.parse(vocabulary.jsonSchema);
    let validator = this.ajv.compile(schema);
    let uischema
    if (schema && schema.hasOwnProperty("@uischema")) {
      // Get uischema from json schema definition
      uischema = schema["@uischema"];
    } else {
      uischema = this.uischemaComplete;
    }
    const form = {
      id: vocabulary['@id'],
      name: vocabulary.name,
      uischema,
      schema,
      data: {},
      validator,
      renderers: this.renderers
    }
    if (isDefault) {
      this.defaultForms.push(form)
    } else {
      this.selectedForms.push(form)
    }
  }

  /**
   * Checks the required fields
   *
   * @returns true if required fields have been filled
   */
  private checkRequiredFields(): boolean {
    if (!this.id || !this.storageTypeId || !this.name || !this.version || !this.description || !this.keywords || !this.shortDescription || !this.assetType) {
      return false;
    } else {
      if (this.storageTypeId === DATA_ADDRESS_TYPES.httpData && (!this.httpDataAddress.name || !this.httpDataAddress.baseUrl || !this.validateUrl())) {
        return false;
      }
      if (this.storageTypeId === DATA_ADDRESS_TYPES.amazonS3 && (!this.amazonS3DataAddress.region || !this.amazonS3DataAddress.accessKeyId || !this.amazonS3DataAddress.secretAccessKey || !this.amazonS3DataAddress.bucketName || !this.amazonS3DataAddress.endpointOverride)) {
        return false;
      } else if (this.storageTypeId === DATA_ADDRESS_TYPES.inesDataStore && !this.inesDataStoreAddress.file) {
        return false;
      } else {
        return true;
      }
    }
  }

  /**
   * Checks the vocabulary data is compilant with the json schema
   *
   * @returns true there is no vocabulary in the connector or the data is validated
   */
  private checkVocabularyData(): boolean {
    let isDefaultValid = true
    if (this.defaultForms.length > 0) {
      this.defaultForms.forEach(f => {
        isDefaultValid = isDefaultValid && f.validator(f.data)
      })
    }
    let isSelectedValid = true
    if (this.selectedForms.length > 0) {
      this.selectedForms.forEach(f => {
        isSelectedValid = isSelectedValid && f.validator(f.data)
      })
    }
    return this.vocabularies?.length < 1 || (isDefaultValid && isSelectedValid);
  }

  assetTypeChange() {
    this.selectedVocabularies = []
    this.selectedVocabularies = this.vocabularies.filter(v => v.category === this.assetType)
    this.selectedForms = []
    this.selectedAssetTypeVocabularies = []

    if (this.selectedVocabularies.length > 0) {
      this.selectedVocabularies.forEach(s => {
        if (this.selectedAssetTypeVocabularies.find(satv => satv['@id'] === s['@id'])) {
          this.initVocabularyForm(s, false)
        }
      })
    }
  }

  /**
   * Transform to text asset type value
   * @returns asset type text
   */
  getAssetTypeText() {
    return this.assetType ? ASSET_TYPES[this.assetType as keyof typeof ASSET_TYPES] : '';
  }

  setFiles(event: File[]) {
    if (event?.length > 0) {
      this.inesDataStoreAddress.file = event[0]
    } else {
      delete this.inesDataStoreAddress.file
    }
  }

  onSelectionChangeVocabulary() {
    this.selectedForms = []

    if (this.selectedVocabularies.length > 0) {
      this.selectedVocabularies.forEach(s => {
        if (this.selectedAssetTypeVocabularies.find(satv => satv['@id'] === s['@id'])) {
          this.initVocabularyForm(s, false)
        }
      })
    }
  }

  validateUrl(): boolean {
    try {
      var url = new URL(this.httpDataAddress.baseUrl);
    } catch (e) {
      return false;
    }
    return url.protocol === "http:" || url.protocol === "https:";
  }


  async createAsset(assetInput: any) {
    if (this.storageTypeId === DATA_ADDRESS_TYPES.inesDataStore && this.inesDataStoreAddress.file) {
      const file = this.inesDataStoreAddress.file;
      const chunkSize = 50 * 1024 * 1024; // 50 MB
      const totalChunks = Math.ceil(file.size / chunkSize);
      const fileName = file.name;
      const maxRetries = 3;

      for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
        const start = chunkIndex * chunkSize;
        const chunk = file.slice(start, start + chunkSize);

        let attempt = 0;
        let success = false;

        const progressPercentage = Math.floor(((chunkIndex + 1) / totalChunks) * 100);

        while (attempt < maxRetries && !success) {
          try {
            this.loadingService.updateMessage(`Uploading file: ${progressPercentage}% completed`);

            await this.assetService.uploadChunk(assetInput, chunk, fileName, chunkIndex, totalChunks);
            success = true;
          } catch (error) {
            attempt++;
            if (attempt >= maxRetries) {
              this.loadingService.hideLoading();
              this.notificationService.showError(`Error uploading chunk ${chunkIndex + 1}. Maximum retries reached.`);
              return;
            }
          }
        }
      }

      try {
        await this.assetService.finalizeUpload(assetInput, fileName);
        this.loadingService.hideLoading();
        this.notificationService.showInfo('Asset created successfully');
        this.navigateToAsset();
      } catch (error: any) {
        this.loadingService.hideLoading();
        this.notificationService.showError('Error finalizing the asset creation: ' + error.error[0].message);
      }
    } else {
      this.assetService.createAsset(assetInput).subscribe({
        next: () => this.fetch$.next(null),
        error: (err) => {
          this.loadingService.hideLoading();
          this.showError(err, "Error creating the asset: " + err.error[0].message);
        },
        complete: () => {
          this.loadingService.hideLoading();
          this.notificationService.showInfo('Asset created successfully');
          this.navigateToAsset();
        },
      });
    }
  }


  private showError(error: string, errorMessage: string) {
    this.notificationService.showError(errorMessage);
    console.error(error);
    this.loadingService.hideLoading();
  }

  navigateToAsset() {
    this.router.navigate(['assets'])
  }

  onToggleChange(propertyName: string, event: MatSlideToggleChange): void {
    this.httpDataAddress[propertyName] = event ? 'true' : 'false';
  }
}
