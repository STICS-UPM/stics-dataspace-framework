import { Component, OnInit, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatExpansionModule } from '@angular/material/expansion';

import { MLAssetFilter } from '../../../../shared/services/ml-assets.service';

@Component({
  selector: 'app-ml-filters',
  standalone: true,
  imports: [
    CommonModule,
    MatIconModule,
    MatButtonModule,
    MatCheckboxModule,
    MatExpansionModule
  ],
  templateUrl: './ml-filters.component.html',
  styleUrl: './ml-filters.component.scss'
})
export class MlFiltersComponent implements OnInit {
  @Input() availableTasks: string[] = [];
  @Input() availableSubtasks: string[] = [];
  @Input() availableAlgorithms: string[] = [];
  @Input() availableLibraries: string[] = [];
  @Input() availableFrameworks: string[] = [];
  @Input() availableStorageTypes: string[] = [];
  @Input() availableSoftware: string[] = [];
  @Input() availableAssetSources: string[] = [];
  @Input() availableFormats: string[] = [];

  @Output() filterChange = new EventEmitter<MLAssetFilter>();

  selectedTasks = new Set<string>();
  selectedSubtasks = new Set<string>();
  selectedAlgorithms = new Set<string>();
  selectedLibraries = new Set<string>();
  selectedFrameworks = new Set<string>();
  selectedStorageTypes = new Set<string>();
  selectedSoftware = new Set<string>();
  selectedAssetSources = new Set<string>();
  selectedFormats = new Set<string>();

  selectedCategory = 'main';

  expandedSections = {
    source: true,
    tasks: true,
    subtasks: false,
    algorithms: false,
    libraries: false,
    frameworks: false,
    storage: true,
    software: false,
    format: true
  };

  ngOnInit(): void {
  }

  toggleTask(task: string): void {
    if (this.selectedTasks.has(task)) {
      this.selectedTasks.delete(task);
    } else {
      this.selectedTasks.add(task);
    }
    this.emitFilters();
  }

  toggleSubtask(subtask: string): void {
    if (this.selectedSubtasks.has(subtask)) {
      this.selectedSubtasks.delete(subtask);
    } else {
      this.selectedSubtasks.add(subtask);
    }
    this.emitFilters();
  }

  toggleAlgorithm(algorithm: string): void {
    if (this.selectedAlgorithms.has(algorithm)) {
      this.selectedAlgorithms.delete(algorithm);
    } else {
      this.selectedAlgorithms.add(algorithm);
    }
    this.emitFilters();
  }

  toggleLibrary(library: string): void {
    if (this.selectedLibraries.has(library)) {
      this.selectedLibraries.delete(library);
    } else {
      this.selectedLibraries.add(library);
    }
    this.emitFilters();
  }

  toggleFramework(framework: string): void {
    if (this.selectedFrameworks.has(framework)) {
      this.selectedFrameworks.delete(framework);
    } else {
      this.selectedFrameworks.add(framework);
    }
    this.emitFilters();
  }

  toggleStorageType(type: string): void {
    if (this.selectedStorageTypes.has(type)) {
      this.selectedStorageTypes.delete(type);
    } else {
      this.selectedStorageTypes.add(type);
    }
    this.emitFilters();
  }

  toggleSoftware(tag: string): void {
    if (this.selectedSoftware.has(tag)) {
      this.selectedSoftware.delete(tag);
    } else {
      this.selectedSoftware.add(tag);
    }
    this.emitFilters();
  }

  toggleAssetSource(source: string): void {
    if (this.selectedAssetSources.has(source)) {
      this.selectedAssetSources.delete(source);
    } else {
      this.selectedAssetSources.add(source);
    }
    this.emitFilters();
  }

  toggleFormat(format: string): void {
    if (this.selectedFormats.has(format)) {
      this.selectedFormats.delete(format);
    } else {
      this.selectedFormats.add(format);
    }
    this.emitFilters();
  }

  isTaskSelected(task: string): boolean {
    return this.selectedTasks.has(task);
  }

  isSubtaskSelected(subtask: string): boolean {
    return this.selectedSubtasks.has(subtask);
  }

  isAlgorithmSelected(algorithm: string): boolean {
    return this.selectedAlgorithms.has(algorithm);
  }

  isLibrarySelected(library: string): boolean {
    return this.selectedLibraries.has(library);
  }

  isFrameworkSelected(framework: string): boolean {
    return this.selectedFrameworks.has(framework);
  }

  isStorageTypeSelected(type: string): boolean {
    return this.selectedStorageTypes.has(type);
  }

  isSoftwareSelected(tag: string): boolean {
    return this.selectedSoftware.has(tag);
  }

  isAssetSourceSelected(source: string): boolean {
    return this.selectedAssetSources.has(source);
  }

  isFormatSelected(format: string): boolean {
    return this.selectedFormats.has(format);
  }

  clearFilters(): void {
    this.selectedTasks.clear();
    this.selectedSubtasks.clear();
    this.selectedAlgorithms.clear();
    this.selectedLibraries.clear();
    this.selectedFrameworks.clear();
    this.selectedStorageTypes.clear();
    this.selectedSoftware.clear();
    this.selectedAssetSources.clear();
    this.selectedFormats.clear();
    this.emitFilters();
  }

  private emitFilters(): void {
    const filters: MLAssetFilter = {
      tasks: Array.from(this.selectedTasks),
      subtasks: Array.from(this.selectedSubtasks),
      algorithms: Array.from(this.selectedAlgorithms),
      libraries: Array.from(this.selectedLibraries),
      frameworks: Array.from(this.selectedFrameworks),
      storageTypes: Array.from(this.selectedStorageTypes),
      software: Array.from(this.selectedSoftware),
      assetSources: Array.from(this.selectedAssetSources),
      formats: Array.from(this.selectedFormats)
    };
    this.filterChange.emit(filters);
  }

  get hasActiveFilters(): boolean {
    return this.selectedTasks.size > 0 || 
           this.selectedSubtasks.size > 0 ||
           this.selectedAlgorithms.size > 0 ||
           this.selectedLibraries.size > 0 ||
           this.selectedFrameworks.size > 0 ||
           this.selectedStorageTypes.size > 0 ||
           this.selectedSoftware.size > 0 ||
           this.selectedAssetSources.size > 0 ||
           this.selectedFormats.size > 0;
  }

  toggleSection(section: keyof typeof this.expandedSections): void {
    this.expandedSections[section] = !this.expandedSections[section];
  }

  selectCategory(key: string): void {
    this.selectedCategory = key;
  }
}

