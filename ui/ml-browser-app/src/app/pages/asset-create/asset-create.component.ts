import { Component, inject, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatTabsModule } from '@angular/material/tabs';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { firstValueFrom } from 'rxjs';

import { AssetService } from '../../shared/services/asset.service';
import { NotificationService } from '../../shared/services/notification.service';
import { VocabularyService, VocabularyOptions } from '../../shared/services/vocabulary.service';
import { AuthService } from '../../shared/services/auth.service';
import {
  AssetFormData,
  AssetInput,
  convertFormDataToAssetInput,
  validateAssetFormData
} from '../../shared/models/asset-input';
import {
  ASSET_TYPES,
  DEFAULT_ASSET_TYPE,
  MLMetadata
} from '../../shared/models/ml-metadata';
import {
  DATA_ADDRESS_TYPES,
  STORAGE_TYPES,
  HttpDataAddress,
  AmazonS3DataAddress,
  DataSpacePrototypeStoreAddress,
  DataAddress
} from '../../shared/models/data-address';

/**
 * Asset Create Component
 * 
 * Allows users to create new IA assets with:
 * - Basic asset information (id, name, version, description)
 * - ML metadata from JS_Pionera_Ontology
 * - Storage configuration (HTTP, S3, or DataSpacePrototypeStore)
 */
@Component({
  selector: 'app-asset-create',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatTabsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatSlideToggleModule
  ],
  templateUrl: './asset-create.component.html',
  styleUrl: './asset-create.component.scss'
})
export class AssetCreateComponent implements OnInit {
  private assetService = inject(AssetService);
  private notificationService = inject(NotificationService);
  private router = inject(Router);
  private vocabularyService = inject(VocabularyService);
  private authService = inject(AuthService);
  
  // Vocabulary options loaded from JS_Pionera_Ontology
  vocabularyOptions = signal<VocabularyOptions>({
    task: [],
    subtask: [],
    algorithm: [],
    library: [],
    framework: [],
    software: [],
    format: []
  });
  
  // Expose constants for template
  readonly DATA_ADDRESS_TYPES = DATA_ADDRESS_TYPES;

  // Asset type options
  assetTypes = Object.entries(ASSET_TYPES);
  
  // Storage type options
  storageTypes = STORAGE_TYPES;

  // Common content types for ML assets
  contentTypes: string[] = [
    'application/octet-stream',
    'application/json',
    'application/x-pickle',
    'application/onnx',
    'application/x-hdf5',
    'application/x-parquet',
    'text/csv',
    'text/plain'
  ];
  
  // Basic asset information
  name = '';
  version = '1.0';
  contenttype = 'application/octet-stream';
  assetType = DEFAULT_ASSET_TYPE;
  shortDescription = '';
  description = '';
  keywords = '';
  byteSize = '';
  format = '';
  
  // ML Metadata
  mlMetadata: MLMetadata = {
    task: [],
    subtask: [],
    algorithm: [],
    library: [],
    framework: [],
    software: [],
    format: ''
  };
  
  // Storage configuration
  storageTypeId: string = DATA_ADDRESS_TYPES.httpData;
  
  httpDataAddress: HttpDataAddress = {
    '@type': 'HttpData',
    type: 'HttpData',
    name: '',
    baseUrl: '',
    path: '',
    authKey: '',
    authCode: '',
    secretName: '',
    contentType: '',
    proxyBody: 'false',
    proxyPath: 'false',
    proxyQueryParams: 'false',
    proxyMethod: 'false'
  };
  
  amazonS3DataAddress: AmazonS3DataAddress = {
    '@type': 'AmazonS3',
    type: 'AmazonS3',
    region: '',
    bucketName: '',
    accessKeyId: '',
    secretAccessKey: '',
    endpointOverride: '',
    keyPrefix: '',
    folderName: ''
  };
  
  dataSpacePrototypeStoreAddress: DataSpacePrototypeStoreAddress = {
    '@type': 'DataSpacePrototypeStore',
    type: 'DataSpacePrototypeStore',
    folder: ''
  };

  // Loading state
  isSubmitting = signal(false);

  /**
   * Initialize component and load vocabulary options
   */
  ngOnInit(): void {
    // Load vocabulary options from JS_Pionera_Ontology
    this.vocabularyService.getVocabularyOptions().subscribe({
      next: (options) => {
        this.vocabularyOptions.set(options);
      },
      error: (error) => {
        console.error('Error loading vocabulary options:', error);
        this.notificationService.showError('Error loading ML metadata options');
      }
    });
  }

  /**
   * Save and create the asset
   */
  async onSave(): Promise<void> {
    const generatedId = this.buildGeneratedAssetId(this.name);
    if (!generatedId) {
      this.notificationService.showError('Asset ID could not be generated. Please enter a valid name.');
      return;
    }

    const duplicateNameExists = await this.hasDuplicateNameForCurrentUser(this.name);
    if (duplicateNameExists) {
      this.notificationService.showError(`An asset with name "${this.name.trim()}" already exists for this user.`);
      return;
    }

    // Validate required fields
    const formData: AssetFormData = {
      id: generatedId,
      name: this.name,
      version: this.version,
      contenttype: this.contenttype,
      assetType: this.assetType,
      shortDescription: this.shortDescription,
      description: this.description,
      keywords: this.keywords,
      byteSize: this.byteSize,
      format: this.format,
      mlMetadata: this.mlMetadata,
      storageTypeId: this.storageTypeId,
      dataAddress: this.getCurrentDataAddress()
    };
    
    const validation = validateAssetFormData(formData);
    
    if (!validation.valid) {
      this.notificationService.showError(`Validation errors: ${validation.errors.join(', ')}`);
      return;
    }
    
    // Additional storage-specific validation
    if (!this.validateDataAddress()) {
      this.notificationService.showError('Please fill all required storage fields');
      return;
    }
    
    this.isSubmitting.set(true);
    
    try {
      // Convert form data to asset input
      const assetInput = convertFormDataToAssetInput(formData);
      
      // Handle DataSpacePrototypeStore file upload
      const storageType = this.storageTypeId as string;
      if (storageType === DATA_ADDRESS_TYPES.dataSpacePrototypeStore && this.dataSpacePrototypeStoreAddress.file) {
        await this.createAssetWithFileUpload(assetInput, this.dataSpacePrototypeStoreAddress.file);
      } else {
        await this.createAsset(assetInput);
      }
    } catch (error: any) {
      this.notificationService.showError(`Error creating asset: ${error.message || 'Unknown error'}`);
      this.isSubmitting.set(false);
    }
  }

  /**
   * Create asset without file upload
   */
  private async createAsset(assetInput: AssetInput): Promise<void> {
    this.assetService.createAsset(assetInput as any).subscribe({
      next: () => {
        this.notificationService.showInfo('Asset created successfully');
        this.navigateToAssets();
      },
      error: (error) => {
        this.notificationService.showError(`Error creating asset: ${error.error?.[0]?.message || error.message}`);
        this.isSubmitting.set(false);
      },
      complete: () => {
        this.isSubmitting.set(false);
      }
    });
  }

  /**
   * Create asset with chunked file upload for DataSpacePrototypeStore
   */
  private async createAssetWithFileUpload(assetInput: AssetInput, file: File): Promise<void> {
    const chunkSize = 5 * 1024 * 1024; // 5 MB chunks (S3 minimum)
    const totalChunks = Math.ceil(file.size / chunkSize);
    const fileName = file.name;
    const maxRetries = 3;

    try {
      // Step 1: Create asset first (required for S3 flow)
      this.notificationService.showInfo('Creating asset...');
      await this.createAsset(assetInput);
      const assetId = assetInput['@id'];
      console.log(`[Upload] Asset created: ${assetId}`);
      
      // Step 2: Initialize upload session
      this.notificationService.showInfo('Initializing file upload...');
      const { sessionId } = await this.assetService.initUpload(
        assetId,
        fileName,
        totalChunks,
        file.type || 'application/octet-stream'
      );
      
      console.log(`[Upload] Session created: ${sessionId}`);
      
      // Step 3: Upload chunks
      const parts: Array<{ PartNumber: number; ETag: string }> = [];
      
      for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
        const start = chunkIndex * chunkSize;
        const chunk = file.slice(start, start + chunkSize);
        
        const progressPercentage = Math.floor(((chunkIndex + 1) / totalChunks) * 100);
        this.notificationService.showInfo(`Uploading file: ${progressPercentage}% completed`);
        
        let attempt = 0;
        let success = false;
        let etag = '';
        
        while (attempt < maxRetries && !success) {
          try {
            const result = await this.assetService.uploadChunk(sessionId, chunkIndex + 1, chunk);
            etag = result.etag;
            success = true;
            console.log(`[Upload] Chunk ${chunkIndex + 1}/${totalChunks} uploaded, ETag: ${etag}`);
          } catch (error) {
            attempt++;
            console.error(`[Upload] Chunk ${chunkIndex + 1} failed (attempt ${attempt}):`, error);
            if (attempt >= maxRetries) {
              throw new Error(`Error uploading chunk ${chunkIndex + 1}. Maximum retries reached.`);
            }
            // Wait before retry (exponential backoff)
            await new Promise(resolve => setTimeout(resolve, 1000 * Math.pow(2, attempt - 1)));
          }
        }
        
        parts.push({
          PartNumber: chunkIndex + 1,
          ETag: etag
        });
      }
      
      // Step 4: Finalize upload (updates data_address with s3Key)
      this.notificationService.showInfo('Finalizing upload...');
      const { s3Key } = await this.assetService.finalizeUpload(sessionId, parts);
      console.log(`[Upload] Finalized: s3Key=${s3Key}`);
      
      this.notificationService.showInfo('Asset created successfully with file upload');
      this.navigateToAssets();
    } catch (error: any) {
      this.notificationService.showError(`Error uploading file: ${error.message}`);
    } finally {
      this.isSubmitting.set(false);
    }
  }

  /**
   * Get current data address based on selected storage type
   */
  private getCurrentDataAddress(): any {
    const storageType = this.storageTypeId as string;
    
    if (storageType === DATA_ADDRESS_TYPES.httpData) {
      return this.httpDataAddress;
    }
    
    if (storageType === DATA_ADDRESS_TYPES.amazonS3) {
      return this.amazonS3DataAddress;
    }
    
    if (storageType === DATA_ADDRESS_TYPES.dataSpacePrototypeStore) {
      return this.dataSpacePrototypeStoreAddress;
    }
    
    throw new Error('Invalid storage type');
  }

  /**
   * Validate data address based on storage type
   */
  private validateDataAddress(): boolean {
    const storageType = this.storageTypeId as string;
    
    if (storageType === DATA_ADDRESS_TYPES.httpData) {
      return !!(
        this.httpDataAddress.name &&
        this.httpDataAddress.baseUrl &&
        this.validateUrl(this.httpDataAddress.baseUrl)
      );
    }
    
    if (storageType === DATA_ADDRESS_TYPES.amazonS3) {
      return !!(
        this.amazonS3DataAddress.region &&
        this.amazonS3DataAddress.bucketName &&
        this.amazonS3DataAddress.accessKeyId &&
        this.amazonS3DataAddress.secretAccessKey &&
        this.amazonS3DataAddress.endpointOverride
      );
    }
    
    if (storageType === DATA_ADDRESS_TYPES.dataSpacePrototypeStore) {
      return !!this.dataSpacePrototypeStoreAddress.file;
    }
    
    return false;
  }

  /**
   * Validate URL format
   */
  private validateUrl(url: string): boolean {
    try {
      const urlObj = new URL(url);
      return urlObj.protocol === 'http:' || urlObj.protocol === 'https:';
    } catch {
      return false;
    }
  }

  /**
   * Handle toggle changes for HTTP proxy settings
   */
  onToggleChange(property: keyof HttpDataAddress, value: boolean): void {
    (this.httpDataAddress[property] as any) = value ? 'true' : 'false';
  }

  /**
   * Handle file selection for DataSpacePrototypeStore
   */
  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.dataSpacePrototypeStoreAddress.file = input.files[0];
    }
  }

  /**
   * Navigate back to assets list
   */
  navigateToAssets(): void {
    this.router.navigate(['/ml-assets']);
  }

  /**
   * Cancel and return to assets list
   */
  onCancel(): void {
    this.navigateToAssets();
  }

  get generatedAssetId(): string {
    return this.buildGeneratedAssetId(this.name);
  }

  private async hasDuplicateNameForCurrentUser(name: string): Promise<boolean> {
    const normalizedTargetName = this.normalizeName(name);
    if (!normalizedTargetName) {
      return false;
    }

    try {
      const assets = await firstValueFrom(this.assetService.requestAssets());
      return assets.some((asset: any) => {
        const existingName = this.extractAssetName(asset);
        return this.normalizeName(existingName) === normalizedTargetName;
      });
    } catch (error) {
      console.error('Error checking existing assets for duplicate names:', error);
      this.notificationService.showError('Could not validate duplicate names. Please try again.');
      return true;
    }
  }

  private extractAssetName(asset: any): string {
    const properties = asset?.properties || {};
    return String(
      properties['asset:prop:name'] ??
      properties['name'] ??
      asset?.name ??
      ''
    );
  }

  private buildGeneratedAssetId(assetName: string): string {
    const user = this.authService.getCurrentUser();
    const userIdRaw = String(user?.connectorId || user?.username || user?.id || 'user');
    const userId = this.slugify(userIdRaw);
    const namePart = this.slugify(assetName);

    if (!namePart) {
      return '';
    }
    return `${userId}~${namePart}`;
  }

  private normalizeName(name: string): string {
    return name.trim().replace(/\s+/g, ' ').toLowerCase();
  }

  private slugify(value: string): string {
    const slug = value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
    return slug || 'user';
  }
}
