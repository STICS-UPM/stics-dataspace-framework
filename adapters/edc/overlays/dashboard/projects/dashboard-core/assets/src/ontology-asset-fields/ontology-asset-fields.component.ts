import { Component, EventEmitter, OnInit, Output, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  NEW_SHACLE_FILE_VALUE,
  Ontology,
  OntologyAssetSelection,
  OntologyVersion,
} from '../models/ontology';
import { OntologyService } from '../services/ontology.service';

@Component({
  selector: 'lib-ontology-asset-fields',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './ontology-asset-fields.component.html',
  styleUrl: './ontology-asset-fields.component.css',
})
export class OntologyAssetFieldsComponent implements OnInit {
  private readonly ontologyService = inject(OntologyService);

  @Output() selectionChange = new EventEmitter<OntologyAssetSelection>();

  readonly newShacleOption = NEW_SHACLE_FILE_VALUE;

  ontologies: Ontology[] = [];
  filteredOntologies: Ontology[] = [];
  ontologyVersions: OntologyVersion[] = [];
  ontologyShacls: string[] = [];

  ontologyUri = '';
  ontologyVersion = '';
  ontologyShacl = '';

  ontologySearch = '';
  loadError = '';
  listLoading = true;
  uploadRunning = false;
  uploadMessage = '';
  shaclPendingFile?: File;

  ngOnInit(): void {
    this.ontologyService.getOntologyLists().subscribe({
      next: res => {
        this.ontologies = res ?? [];
        this.filteredOntologies = this.ontologies;
        this.listLoading = false;
      },
      error: () => {
        this.loadError = 'Could not load ontologies from Ontology Hub.';
        this.listLoading = false;
      },
    });
  }

  onSearchOntology(event: Event): void {
    const value = (event.target as HTMLInputElement).value.toLowerCase();
    this.ontologySearch = value;
    this.filteredOntologies = this.ontologies.filter(ontology => {
      const title = ontology.titles?.[0]?.value?.toLowerCase() ?? '';
      return title.includes(value) || ontology.uri.toLowerCase().includes(value);
    });
  }

  onOntologySelected(uri: string): void {
    this.ontologyUri = uri;
    this.fillVersions(uri);
    this.emitSelection();
  }

  onVersionSelected(issued: string): void {
    this.ontologyVersion = issued;
    this.emitSelection();
  }

  onShaclSelected(shacl: string): void {
    this.ontologyShacl = shacl;
    this.uploadMessage = '';
    if (shacl !== NEW_SHACLE_FILE_VALUE) {
      this.shaclPendingFile = undefined;
    }
    this.emitSelection();
  }

  onShaclFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.shaclPendingFile = input.files?.[0];
    this.uploadMessage = '';
    this.emitSelection();
  }

  uploadShacleFile(): void {
    if (
      this.ontologyShacl !== NEW_SHACLE_FILE_VALUE ||
      !this.shaclPendingFile ||
      !this.ontologyUri
    ) {
      return;
    }
    const selectedOntology = this.resolveSelectedOntology(this.ontologyUri);
    if (!selectedOntology) {
      this.uploadMessage = 'Select a valid ontology before uploading SHACL.';
      return;
    }

    this.uploadRunning = true;
    this.uploadMessage = '';
    this.ontologyService
      .postUploadShacl(this.shaclPendingFile, selectedOntology.prefix, selectedOntology.uri)
      .subscribe({
        next: () => {
          this.ontologyService.getOntologyLists().subscribe({
            next: res => {
              this.ontologies = res ?? [];
              this.applySearchFilter();
              const updated = this.resolveSelectedOntology(this.ontologyUri);
              this.ontologyShacls = updated?.artifacts?.shapes ?? [];
              this.ontologyShacl = '';
              this.shaclPendingFile = undefined;
              this.uploadRunning = false;
              this.uploadMessage = 'SHACL file uploaded successfully. Select it from the list.';
              this.emitSelection();
            },
            error: () => {
              this.uploadRunning = false;
              this.uploadMessage = 'SHACL uploaded but failed to refresh ontology list.';
            },
          });
        },
        error: () => {
          this.uploadRunning = false;
          this.uploadMessage = 'Error uploading SHACL file.';
        },
      });
  }

  ontologyTitle(ontology: Ontology): string {
    return ontology.titles?.[0]?.value || ontology.prefix || ontology.uri;
  }

  private fillVersions(uri: string): void {
    const selectedOntology = this.resolveSelectedOntology(uri);
    this.ontologyVersions = selectedOntology?.versions ?? [];
    this.ontologyShacls = selectedOntology?.artifacts?.shapes ?? [];

    if (this.ontologyVersions.length === 1) {
      this.ontologyVersion = this.ontologyVersions[0].issued;
    } else {
      this.ontologyVersion = '';
    }

    if (this.ontologyShacls.length === 1) {
      this.ontologyShacl = this.ontologyShacls[0];
    } else {
      this.ontologyShacl = '';
    }
  }

  private applySearchFilter(): void {
    const value = this.ontologySearch.toLowerCase();
    if (!value) {
      this.filteredOntologies = this.ontologies;
      return;
    }
    this.filteredOntologies = this.ontologies.filter(ontology => {
      const title = ontology.titles?.[0]?.value?.toLowerCase() ?? '';
      return title.includes(value) || ontology.uri.toLowerCase().includes(value);
    });
  }

  private resolveSelectedOntology(uri: string): Ontology | undefined {
    const normalized = this.normalizeOntologyUri(uri);
    return this.ontologies.find(o => this.normalizeOntologyUri(o.uri) === normalized);
  }

  private normalizeOntologyUri(uri: string): string {
    return (uri || '').trim().replace(/\/+$/, '');
  }

  private emitSelection(): void {
    this.selectionChange.emit(this.buildSelection());
  }

  buildSelection(): OntologyAssetSelection {
    const empty: OntologyAssetSelection = {
      ontologyUri: this.ontologyUri,
      ontologyVersion: this.ontologyVersion,
      ontologyShacl: this.ontologyShacl,
      ontologyDownloadUrl: '',
      shaclDownloadUrl: '',
      isOntologyComplete: false,
    };

    if (!this.ontologyUri || !this.ontologyVersion || !this.ontologyShacl) {
      return empty;
    }
    if (this.ontologyShacl === NEW_SHACLE_FILE_VALUE) {
      return empty;
    }

    const selected = this.resolveSelectedOntology(this.ontologyUri);
    const prefix = (selected?.prefix || '').trim();
    if (!prefix) {
      return empty;
    }

    const ontologyVersionDate = this.ontologyVersion.split('T')[0];
    const ontologyDownloadUrl = this.ontologyService.buildUrl(prefix, 'ontology', ontologyVersionDate);
    const shaclDownloadUrl = this.ontologyService.buildUrl(prefix, 'shacl', this.ontologyShacl);

    return {
      ontologyUri: this.ontologyUri,
      ontologyVersion: this.ontologyVersion,
      ontologyShacl: this.ontologyShacl,
      ontologyDownloadUrl,
      shaclDownloadUrl,
      isOntologyComplete: !!(ontologyDownloadUrl && shaclDownloadUrl),
    };
  }
}
