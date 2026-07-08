import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { compact } from 'jsonld';
import { EDC_CONTEXT } from '@think-it-labs/edc-connector-client';
import { lastValueFrom } from 'rxjs';
import { AiModelBrowserItem, AiModelBrowserSource } from 'src/app/shared/models/ai-model-browser-item';
import { NotificationService } from 'src/app/shared/services/notification.service';
import { AiModelBrowserQuery, AiModelBrowserService } from 'src/app/shared/services/ai-model-browser.service';
import { ModelObserverJournalEvent, ModelObserverJournalService } from 'src/app/shared/services/model-observer-journal.service';

interface ModelCardMetadata {
  label: string;
  value: string;
}

@Component({
  selector: 'app-ai-model-browser',
  templateUrl: './ai-model-browser.component.html',
  styleUrls: ['./ai-model-browser.component.scss']
})
export class AiModelBrowserComponent implements OnInit {
  readonly ownSource = 'own';
  readonly federatedSource = 'federated';
  readonly localAssetLabel = 'Local Asset';
  readonly externalAssetLabel = 'External Asset';

  readonly context = {
    '@vocab': EDC_CONTEXT,
    description: 'http://purl.org/dc/terms/description',
    format: 'http://purl.org/dc/terms/format',
    byteSize: 'http://www.w3.org/ns/dcat#byteSize',
    keywords: 'http://www.w3.org/ns/dcat#keyword'
  };

  readonly expandedSections = {
    source: true,
    tasks: true,
    taskTypes: true,
    modalities: true,
    subtasks: false,
    endpointBehaviors: true,
    libraries: false,
    languages: false,
    licenses: false,
    storage: true,
    format: true
  };

  loading = false;

  allModels: AiModelBrowserItem[] = [];
  filteredModels: AiModelBrowserItem[] = [];

  searchTerm = '';

  selectedSources: string[] = [];
  selectedTasks: string[] = [];
  selectedTaskTypes: string[] = [];
  selectedModalities: string[] = [];
  selectedSubtasks: string[] = [];
  selectedEndpointBehaviors: string[] = [];
  selectedLibraries: string[] = [];
  selectedLanguages: string[] = [];
  selectedLicenses: string[] = [];
  selectedStorageTypes: string[] = [];
  selectedFormats: string[] = [];

  availableSources: string[] = [];
  availableTasks: string[] = [];
  availableTaskTypes: string[] = [];
  availableModalities: string[] = [];
  availableSubtasks: string[] = [];
  availableEndpointBehaviors: string[] = [];
  availableLibraries: string[] = [];
  availableLanguages: string[] = [];
  availableLicenses: string[] = [];
  availableStorageTypes: string[] = [];
  availableFormats: string[] = [];

  private searchPublishTimer: ReturnType<typeof setTimeout> | null = null;
  private modelReloadTimer: ReturnType<typeof setTimeout> | null = null;
  private lastPublishedSearchTerm = '';

  constructor(
    private readonly aiModelBrowserService: AiModelBrowserService,
    private readonly notificationService: NotificationService,
    private readonly modelObserverJournalService: ModelObserverJournalService,
    private readonly router: Router
  ) {
  }

  ngOnInit(): void {
    this.loadModels();
  }

  loadModels(): void {
    if (this.modelReloadTimer) {
      clearTimeout(this.modelReloadTimer);
      this.modelReloadTimer = null;
    }

    this.loading = true;

    this.aiModelBrowserService.getModels(this.buildServerQuery()).subscribe({
      next: models => {
        this.allModels = models;
        this.updateAvailableFilters();
        this.applyFilters();
      },
      error: error => {
        this.notificationService.showError('Error loading AI model browser data');
        console.error(error);
        this.loading = false;
      },
      complete: () => {
        this.loading = false;
      }
    });
  }

  applyFilters(): void {
    const query = this.searchTerm.trim().toLowerCase();

    this.filteredModels = this.allModels.filter(model => {
      if (this.selectedSources.length > 0 && !this.selectedSources.includes(this.getSourceFilterLabel(model))) {
        return false;
      }

      if (!this.matchesMultiValueFilter(model.tasks, this.selectedTasks)) {
        return false;
      }

      if (!this.matchesMultiValueFilter(model.taskTypes, this.selectedTaskTypes)) {
        return false;
      }

      if (!this.matchesMultiValueFilter(model.modalities, this.selectedModalities)) {
        return false;
      }

      if (!this.matchesMultiValueFilter(model.subtasks, this.selectedSubtasks)) {
        return false;
      }

      if (!this.matchesMultiValueFilter(model.endpointBehaviors, this.selectedEndpointBehaviors)) {
        return false;
      }

      if (!this.matchesMultiValueFilter(model.libraries, this.selectedLibraries)) {
        return false;
      }

      if (!this.matchesMultiValueFilter(model.languages, this.selectedLanguages)) {
        return false;
      }

      if (!this.matchesMultiValueFilter(model.licenses, this.selectedLicenses)) {
        return false;
      }

      if (!this.matchesSingleValueFilter(model.storageType, this.selectedStorageTypes)) {
        return false;
      }

      if (!this.matchesSingleValueFilter(model.format, this.selectedFormats)) {
        return false;
      }

      if (!query) {
        return true;
      }

      const haystack = [
        model.id,
        model.name,
        model.description,
        model.shortDescription,
        model.provider,
        model.contentType,
        model.format,
        model.storageType,
        model.fileName,
        ...model.keywords,
        ...model.tasks,
        ...model.taskTypes,
        ...model.modalities,
        ...model.subtasks,
        ...model.endpointBehaviors,
        ...model.libraries,
        ...model.languages,
        ...model.licenses
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();

      return haystack.includes(query);
    });
  }

  onSearchTermChange(): void {
    this.applyFilters();
    this.scheduleSearchEvent();
    this.scheduleModelReload();
  }

  clearSearchTerm(): void {
    if (!this.searchTerm.trim()) {
      return;
    }

    if (this.searchPublishTimer) {
      clearTimeout(this.searchPublishTimer);
      this.searchPublishTimer = null;
    }

    this.searchTerm = '';
    this.applyFilters();
    this.loadModels();
    this.publishSearchEvent('CLEARED');
  }

  clearFilters(): void {
    const hadActiveFilters = this.hasActiveFilters();
    const previousFilters = this.buildSelectedFilters();

    this.selectedSources = [];
    this.selectedTasks = [];
    this.selectedTaskTypes = [];
    this.selectedModalities = [];
    this.selectedSubtasks = [];
    this.selectedEndpointBehaviors = [];
    this.selectedLibraries = [];
    this.selectedLanguages = [];
    this.selectedLicenses = [];
    this.selectedStorageTypes = [];
    this.selectedFormats = [];
    this.applyFilters();
    this.loadModels();

    if (hadActiveFilters) {
      this.publishBrowserEvent({
        eventType: 'MODEL_BROWSER_FILTERED',
        status: 'CLEARED',
        details: {
          searchTerm: this.searchTerm.trim(),
          resultCount: this.filteredModels.length,
          filters: this.buildSelectedFilters(),
          previousFilters
        }
      });
    }
  }

  toggleFilter(collection: string[], value: string, checked: boolean): void {
    const index = collection.indexOf(value);

    if (checked && index === -1) {
      collection.push(value);
    }

    if (!checked && index >= 0) {
      collection.splice(index, 1);
    }

    this.applyFilters();
    if (this.isServerBackedFilter(collection)) {
      this.scheduleModelReload();
    }
    this.publishBrowserEvent({
      eventType: 'MODEL_BROWSER_FILTERED',
      status: 'APPLIED',
      details: {
        searchTerm: this.searchTerm.trim(),
        resultCount: this.filteredModels.length,
        filters: this.buildSelectedFilters(),
        changedFilter: this.resolveFilterName(collection),
        changedValue: value,
        checked
      }
    });
  }

  isSelected(collection: string[], value: string): boolean {
    return collection.includes(value);
  }

  async viewDetails(model: AiModelBrowserItem): Promise<void> {
    this.publishBrowserEvent({
      eventType: 'MODEL_DETAIL_VIEWED',
      status: 'VIEWED',
      assetId: model.id,
      modelName: model.name,
      taskType: model.taskTypes[0] || undefined,
      details: {
        source: model.source,
        provider: model.provider,
        searchTerm: this.searchTerm.trim(),
        resultCount: this.filteredModels.length,
        filters: this.buildSelectedFilters()
      }
    });

    if (model.source === this.ownSource && model.rawAsset) {
      try {
        const compactedAsset: any = await compact(model.rawAsset as any, this.context);

        this.router.navigate(['/assets/view'], {
          state: {
            assetDetailData: {
              assetId: compactedAsset['@id'],
              properties: compactedAsset.properties,
              privateProperties: compactedAsset.privateProperties,
              dataAddress: compactedAsset.dataAddress,
              isCatalogView: false,
              returnUrl: 'ai-model-browser'
            }
          }
        });
      } catch (error) {
        this.notificationService.showError('Error opening model detail');
        console.error(error);
      }

      return;
    }

    if (model.source === this.federatedSource && model.rawOffer) {
      this.navigateToFederatedViewer(model, 'details');
    }
  }

  goToPrimaryAction(model: AiModelBrowserItem): void {
    if (model.source === this.ownSource) {
      this.router.navigate(['/contract-definitions/create']);
      return;
    }

    this.navigateToFederatedViewer(model, 'offers');
  }

  getPrimaryActionLabel(model: AiModelBrowserItem): string {
    return model.source === this.ownSource ? 'Create contract' : 'Negotiate';
  }

  getPrimaryActionIcon(model: AiModelBrowserItem): string {
    return model.source === this.ownSource ? 'rule' : 'compare_arrows';
  }

  getSourceFilterLabel(model: AiModelBrowserItem): string {
    return model.source === this.ownSource ? this.localAssetLabel : this.externalAssetLabel;
  }

  getSourceBadgeLabel(model: AiModelBrowserItem): string {
    return model.source === this.ownSource ? 'Local' : 'External';
  }

  getPrimaryValue(values: string[], fallback = 'Unknown'): string {
    return values.length > 0 ? values[0] : fallback;
  }

  getDisplayKeywords(model: AiModelBrowserItem): string[] {
    return model.keywords.slice(0, 2);
  }

  getHiddenKeywordsCount(model: AiModelBrowserItem): number {
    return Math.max(model.keywords.length - 2, 0);
  }

  getVersionLabel(model: AiModelBrowserItem): string {
    return model.version && model.version !== 'N/A' ? `v${model.version}` : 'vN/A';
  }

  getFormatLabel(model: AiModelBrowserItem): string {
    return model.format && model.format !== 'Unknown' ? model.format : 'Unknown';
  }

  getStorageTypeLabel(model: AiModelBrowserItem): string {
    return model.storageType && model.storageType !== 'Unknown' ? model.storageType : 'Unknown';
  }

  getFileNameLabel(model: AiModelBrowserItem): string {
    return model.fileName && model.fileName !== 'Unknown' ? model.fileName : 'Unknown';
  }

  getCardMetadata(model: AiModelBrowserItem): ModelCardMetadata[] {
    const metadata: ModelCardMetadata[] = [
      { label: 'Category', value: this.getPrimaryValue(model.tasks, '') },
      { label: 'Type', value: this.getPrimaryValue(model.taskTypes, '') },
      { label: 'Modality', value: model.modalities.join(', ') },
      { label: 'Subtask', value: this.getPrimaryValue(model.subtasks, '') },
      { label: 'Library', value: this.getPrimaryValue(model.libraries, '') },
      { label: 'Endpoint', value: this.getPrimaryValue(model.endpointBehaviors, '') },
      { label: 'Language', value: this.getPrimaryValue(model.languages, '') },
      { label: 'License', value: this.getPrimaryValue(model.licenses, '') }
    ];

    return metadata.filter(item => item.value.trim().length > 0);
  }

  getContractBadgeLabel(model: AiModelBrowserItem): string {
    return model.source === this.ownSource
      ? (model.hasContract ? 'Contract published' : 'Contract pending')
      : 'Contract available';
  }

  hasActiveFilters(): boolean {
    return [
      this.selectedSources,
      this.selectedTasks,
      this.selectedTaskTypes,
      this.selectedModalities,
      this.selectedSubtasks,
      this.selectedEndpointBehaviors,
      this.selectedLibraries,
      this.selectedLanguages,
      this.selectedLicenses,
      this.selectedStorageTypes,
      this.selectedFormats
    ].some(collection => collection.length > 0);
  }

  private matchesMultiValueFilter(modelValues: string[], selectedValues: string[]): boolean {
    if (selectedValues.length === 0) {
      return true;
    }

    return modelValues.some(value => selectedValues.includes(value));
  }

  private matchesSingleValueFilter(modelValue: string, selectedValues: string[]): boolean {
    if (selectedValues.length === 0) {
      return true;
    }

    return selectedValues.includes(modelValue);
  }

  private updateAvailableFilters(): void {
    this.availableSources = this.collectUniqueValues(this.allModels.map(model => this.getSourceFilterLabel(model)));
    this.availableTasks = this.collectUniqueValues(this.collectModelValues('tasks'));
    this.availableTaskTypes = this.collectUniqueValues(this.collectModelValues('taskTypes'));
    this.availableModalities = this.collectUniqueValues(this.collectModelValues('modalities'));
    this.availableSubtasks = this.collectUniqueValues(this.collectModelValues('subtasks'));
    this.availableEndpointBehaviors = this.collectUniqueValues(this.collectModelValues('endpointBehaviors'));
    this.availableLibraries = this.collectUniqueValues(this.collectModelValues('libraries'));
    this.availableLanguages = this.collectUniqueValues(this.collectModelValues('languages'));
    this.availableLicenses = this.collectUniqueValues(this.collectModelValues('licenses'));
    this.availableStorageTypes = this.collectUniqueValues(this.allModels.map(model => model.storageType).filter(value => value && value !== 'Unknown'));
    this.availableFormats = this.collectUniqueValues(this.allModels.map(model => model.format).filter(value => value && value !== 'Unknown'));
  }

  private collectModelValues(field: 'tasks' | 'taskTypes' | 'modalities' | 'subtasks' | 'endpointBehaviors' | 'libraries' | 'languages' | 'licenses'): string[] {
    return this.allModels.reduce((accumulator: string[], model: AiModelBrowserItem) => {
      return accumulator.concat(model[field]);
    }, []);
  }

  private collectUniqueValues(values: string[]): string[] {
    return Array.from(new Set(values.filter(value => value && value.trim().length > 0))).sort((left, right) => left.localeCompare(right));
  }

  private buildServerQuery(): AiModelBrowserQuery {
    return {
      searchTerm: this.searchTerm.trim(),
      sources: this.buildSelectedSources(),
      tasks: [...this.selectedTasks],
      taskTypes: [...this.selectedTaskTypes],
      modalities: [...this.selectedModalities],
      subtasks: [...this.selectedSubtasks],
      endpointBehaviors: [...this.selectedEndpointBehaviors],
      libraries: [...this.selectedLibraries],
      languages: [...this.selectedLanguages],
      licenses: [...this.selectedLicenses],
      formats: [...this.selectedFormats]
    };
  }

  private buildSelectedSources(): AiModelBrowserSource[] {
    const sources: AiModelBrowserSource[] = [];
    if (this.selectedSources.includes(this.localAssetLabel)) {
      sources.push('own');
    }
    if (this.selectedSources.includes(this.externalAssetLabel)) {
      sources.push('federated');
    }
    return sources;
  }

  private isServerBackedFilter(collection: string[]): boolean {
    return collection === this.selectedSources
      || collection === this.selectedTasks
      || collection === this.selectedTaskTypes
      || collection === this.selectedModalities
      || collection === this.selectedSubtasks
      || collection === this.selectedEndpointBehaviors
      || collection === this.selectedLibraries
      || collection === this.selectedLanguages
      || collection === this.selectedLicenses
      || collection === this.selectedFormats;
  }

  private scheduleModelReload(): void {
    if (this.modelReloadTimer) {
      clearTimeout(this.modelReloadTimer);
    }

    this.modelReloadTimer = setTimeout(() => {
      this.modelReloadTimer = null;
      this.loadModels();
    }, 300);
  }

  private navigateToFederatedViewer(model: AiModelBrowserItem, startTab: 'details' | 'offers'): void {
    const offer = model.rawOffer;
    if (!offer) {
      return;
    }

    this.router.navigate(['/catalog/datasets/view'], {
      state: {
        assetDetailData: {
          assetId: offer.assetId,
          contractOffers: offer.contractOffers,
          endpointUrl: offer.endpointUrl,
          properties: offer.properties,
          isCatalogView: true,
          returnUrl: 'ai-model-browser',
          startTab
        }
      }
    });
  }

  private scheduleSearchEvent(): void {
    if (this.searchPublishTimer) {
      clearTimeout(this.searchPublishTimer);
    }

    const normalizedSearchTerm = this.searchTerm.trim();
    if (!normalizedSearchTerm) {
      return;
    }

    this.searchPublishTimer = setTimeout(() => {
      this.searchPublishTimer = null;
      if (normalizedSearchTerm === this.lastPublishedSearchTerm) {
        return;
      }

      this.publishSearchEvent('SEARCHED');
    }, 400);
  }

  private publishSearchEvent(status: 'SEARCHED' | 'CLEARED'): void {
    const normalizedSearchTerm = this.searchTerm.trim();
    if (status === 'SEARCHED' && !normalizedSearchTerm) {
      return;
    }

    this.lastPublishedSearchTerm = normalizedSearchTerm;
    this.publishBrowserEvent({
      eventType: 'MODEL_BROWSER_SEARCHED',
      status,
      details: {
        searchTerm: normalizedSearchTerm,
        resultCount: this.filteredModels.length,
        filters: this.buildSelectedFilters()
      }
    });
  }

  private publishBrowserEvent(event: ModelObserverJournalEvent): void {
    void lastValueFrom(this.modelObserverJournalService.publish({
      sourceComponent: 'connector-interface:ai-model-browser',
      ...event
    }));
  }

  private buildSelectedFilters(): Record<string, string[]> {
    const filters: Record<string, string[]> = {};

    if (this.selectedSources.length > 0) {
      filters.sources = [...this.selectedSources];
    }

    if (this.selectedTasks.length > 0) {
      filters.tasks = [...this.selectedTasks];
    }

    if (this.selectedTaskTypes.length > 0) {
      filters.taskTypes = [...this.selectedTaskTypes];
    }

    if (this.selectedModalities.length > 0) {
      filters.modalities = [...this.selectedModalities];
    }

    if (this.selectedSubtasks.length > 0) {
      filters.subtasks = [...this.selectedSubtasks];
    }

    if (this.selectedEndpointBehaviors.length > 0) {
      filters.endpointBehaviors = [...this.selectedEndpointBehaviors];
    }

    if (this.selectedLibraries.length > 0) {
      filters.libraries = [...this.selectedLibraries];
    }

    if (this.selectedLanguages.length > 0) {
      filters.languages = [...this.selectedLanguages];
    }

    if (this.selectedLicenses.length > 0) {
      filters.licenses = [...this.selectedLicenses];
    }

    if (this.selectedStorageTypes.length > 0) {
      filters.storageTypes = [...this.selectedStorageTypes];
    }

    if (this.selectedFormats.length > 0) {
      filters.formats = [...this.selectedFormats];
    }

    return filters;
  }

  private resolveFilterName(collection: string[]): string {
    if (collection === this.selectedSources) {
      return 'source';
    }

    if (collection === this.selectedTasks) {
      return 'taskCategory';
    }

    if (collection === this.selectedTaskTypes) {
      return 'taskType';
    }

    if (collection === this.selectedModalities) {
      return 'modality';
    }

    if (collection === this.selectedSubtasks) {
      return 'subtask';
    }

    if (collection === this.selectedEndpointBehaviors) {
      return 'endpointBehavior';
    }

    if (collection === this.selectedLibraries) {
      return 'library';
    }

    if (collection === this.selectedLanguages) {
      return 'language';
    }

    if (collection === this.selectedStorageTypes) {
      return 'storageType';
    }

    if (collection === this.selectedLicenses) {
      return 'license';
    }

    if (collection === this.selectedFormats) {
      return 'format';
    }

    return 'unknown';
  }
}
