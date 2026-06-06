import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { Subject, takeUntil } from 'rxjs';
import { Ontology, OntologyVersion } from '../../../models/ontology';
import { OntologyService } from '../../../services/ontology.service';

@Component({
  selector: 'app-ontology-viewer',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './ontology-viewer.component.html',
})
export class OntologyViewerComponent implements OnInit, OnDestroy {
  private readonly ontologyService = inject(OntologyService);
  private readonly destroy$ = new Subject<void>();

  baseUrl = '';
  ontologies: Ontology[] = [];
  loading = false;
  errorMessage = '';

  ngOnInit(): void {
    this.loadOntologies();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  loadOntologies(): void {
    this.baseUrl = this.ontologyService.ontologyBaseUrl;
    this.loading = true;
    this.errorMessage = '';

    this.ontologyService
      .getOntologyLists()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: ontologies => {
          this.ontologies = ontologies || [];
          this.loading = false;
        },
        error: error => {
          this.ontologies = [];
          this.loading = false;
          this.errorMessage = this.toErrorMessage(error, 'Ontology Hub could not be reached.');
        },
      });
  }

  get editionUrl(): string {
    return `${this.baseUrl}/edition`;
  }

  titleOf(ontology: Ontology): string {
    return ontology.titles?.find(title => title.value)?.value || ontology.prefix || ontology.uri || 'Untitled ontology';
  }

  latestVersionOf(ontology: Ontology): OntologyVersion | undefined {
    const versions = ontology.versions || [];
    return versions.length > 0 ? versions[versions.length - 1] : undefined;
  }

  ontologyUrl(ontology: Ontology): string {
    return `${this.baseUrl}/dataset/vocabs/${ontology.prefix}`;
  }

  versionUrl(ontology: Ontology, version?: OntologyVersion): string {
    if (!version?.name) {
      return this.ontologyUrl(ontology);
    }
    return this.ontologyService.buildUrl(ontology.prefix, 'ontology', version.name);
  }

  shapeUrls(ontology: Ontology): string[] {
    return (ontology.artifacts?.shapes || []).map(shape =>
      this.ontologyService.buildUrl(ontology.prefix, 'shacl', shape),
    );
  }

  private toErrorMessage(error: unknown, fallback: string): string {
    if (!error || typeof error !== 'object') {
      return fallback;
    }

    const record = error as Record<string, unknown>;
    const message = record['message'];
    if (typeof message === 'string' && message.trim().length > 0) {
      return message;
    }

    const nested = record['error'];
    if (nested && typeof nested === 'object') {
      const nestedRecord = nested as Record<string, unknown>;
      const nestedMessage = nestedRecord['message'];
      if (typeof nestedMessage === 'string' && nestedMessage.trim().length > 0) {
        return nestedMessage;
      }
    }

    return fallback;
  }
}
