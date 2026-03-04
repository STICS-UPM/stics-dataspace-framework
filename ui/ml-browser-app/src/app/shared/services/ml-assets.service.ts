import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { MlBrowserService } from './ml-browser.service';
import { MLAsset } from '../models/ml-asset';

export interface MLAssetFilter {
  searchTerm?: string;
  tasks?: string[];
  subtasks?: string[];
  algorithms?: string[];
  libraries?: string[];
  frameworks?: string[];
  storageTypes?: string[];
  software?: string[];
  assetSources?: string[]; // 'Local Asset' or 'External Asset'
  formats?: string[];
}

@Injectable({
  providedIn: 'root'
})
export class MlAssetsService {

  private readonly mlBrowserService = inject(MlBrowserService);

  /**
   * Retrieves IA assets using server-side filtering extension.
   */
  getMachinelearningAssets(filters?: MLAssetFilter, searchTerm?: string): Observable<MLAsset[]> {
    console.log('[IA Assets Service] Calling mlBrowserService.getPaginatedMLAssets()...');
    return this.mlBrowserService.getPaginatedMLAssets(filters, searchTerm);
  }

  /**
   * Counts total IA assets
   */
  count(): Observable<number> {
    return this.mlBrowserService.count();
  }

  /**
   * Client-side filter (kept for fallback usage)
   */
  filterAssets(assets: MLAsset[], filters: MLAssetFilter): MLAsset[] {
    let filtered = [...assets];

    if (filters.searchTerm && filters.searchTerm.trim() !== '') {
      const searchLower = filters.searchTerm.toLowerCase();
      filtered = filtered.filter(asset =>
        asset.name.toLowerCase().includes(searchLower) ||
        asset.description.toLowerCase().includes(searchLower) ||
        asset.shortDescription.toLowerCase().includes(searchLower) ||
        asset.keywords.some(k => k.toLowerCase().includes(searchLower))
      );
    }

    if (filters.tasks && filters.tasks.length > 0) {
      filtered = filtered.filter(asset =>
        asset.tasks.some(t => filters.tasks!.includes(t))
      );
    }

    if (filters.subtasks && filters.subtasks.length > 0) {
      filtered = filtered.filter(asset =>
        asset.subtasks.some(s => filters.subtasks!.includes(s))
      );
    }

    if (filters.algorithms && filters.algorithms.length > 0) {
      filtered = filtered.filter(asset =>
        asset.algorithms.some(a => filters.algorithms!.includes(a))
      );
    }

    if (filters.libraries && filters.libraries.length > 0) {
      filtered = filtered.filter(asset =>
        asset.libraries.some(l => filters.libraries!.includes(l))
      );
    }

    if (filters.frameworks && filters.frameworks.length > 0) {
      filtered = filtered.filter(asset =>
        asset.frameworks.some(f => filters.frameworks!.includes(f))
      );
    }

    if (filters.storageTypes && filters.storageTypes.length > 0) {
      filtered = filtered.filter(asset =>
        !!asset.storageType && filters.storageTypes!.includes(asset.storageType)
      );
    }

    if (filters.software && filters.software.length > 0) {
      filtered = filtered.filter(asset => {
        const tags = new Set<string>([...asset.libraries, ...asset.frameworks]);
        return Array.from(tags).some(tag => filters.software!.includes(tag));
      });
    }

    if (filters.assetSources && filters.assetSources.length > 0) {
      filtered = filtered.filter(asset => {
        const assetType = asset.isLocal ? 'Local Asset' : 'External Asset';
        return filters.assetSources!.includes(assetType);
      });
    }

    if (filters.formats && filters.formats.length > 0) {
      filtered = filtered.filter(asset =>
        !!asset.format && filters.formats!.includes(asset.format)
      );
    }

    return filtered;
  }

  extractUniqueTasks(assets: MLAsset[]): string[] {
    const tasks = new Set<string>();
    assets.forEach(asset => {
      asset.tasks.forEach(task => tasks.add(task));
    });
    return Array.from(tasks).sort();
  }

  extractUniqueSubtasks(assets: MLAsset[]): string[] {
    const subtasks = new Set<string>();
    assets.forEach(asset => {
      asset.subtasks.forEach(subtask => subtasks.add(subtask));
    });
    return Array.from(subtasks).sort();
  }

  extractUniqueAlgorithms(assets: MLAsset[]): string[] {
    const algorithms = new Set<string>();
    assets.forEach(asset => {
      asset.algorithms.forEach(algo => algorithms.add(algo));
    });
    return Array.from(algorithms).sort();
  }

  extractUniqueLibraries(assets: MLAsset[]): string[] {
    const libraries = new Set<string>();
    assets.forEach(asset => {
      asset.libraries.forEach(lib => libraries.add(lib));
    });
    return Array.from(libraries).sort();
  }

  extractUniqueFrameworks(assets: MLAsset[]): string[] {
    const frameworks = new Set<string>();
    assets.forEach(asset => {
      asset.frameworks.forEach(fw => frameworks.add(fw));
    });
    return Array.from(frameworks).sort();
  }

  extractUniqueStorageTypes(assets: MLAsset[]): string[] {
    const storage = new Set<string>();
    assets.forEach(asset => {
      if (asset.storageType) storage.add(asset.storageType);
    });
    return Array.from(storage).sort();
  }

  extractUniqueSoftware(assets: MLAsset[]): string[] {
    const software = new Set<string>();
    assets.forEach(asset => {
      asset.libraries.forEach(lib => software.add(lib));
      asset.frameworks.forEach(fw => software.add(fw));
    });
    return Array.from(software).sort();
  }

  extractUniqueAssetSources(assets: MLAsset[]): string[] {
    const sources = new Set<string>();
    assets.forEach(asset => {
      sources.add(asset.isLocal ? 'Local Asset' : 'External Asset');
    });
    return Array.from(sources).sort();
  }

  extractUniqueFormats(assets: MLAsset[]): string[] {
    const formats = new Set<string>();
    assets.forEach(asset => {
      if (asset.format) formats.add(asset.format);
    });
    return Array.from(formats).sort();
  }
}
