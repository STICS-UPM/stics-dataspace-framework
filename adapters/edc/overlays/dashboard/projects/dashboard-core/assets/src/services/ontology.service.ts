import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { DashboardStateService } from '@eclipse-edc/dashboard-core';
import { Ontology } from '../models/ontology';

const DEFAULT_ONTOLOGY_URL = 'http://ontology-hub-demo.dev.ds.dataspaceunit.upm';

type OntologyRuntimeConfig = {
  ontologyUrl?: string;
  ontologyPublicUrl?: string;
  ontologyAdminUser?: string;
  ontologyAdminPassword?: string;
};

type AppConfigWithRuntime = {
  runtime?: OntologyRuntimeConfig;
};

@Injectable({
  providedIn: 'root',
})
export class OntologyService {
  private readonly http = inject(HttpClient);
  private readonly stateService = inject(DashboardStateService);
  private runtime: OntologyRuntimeConfig = {};

  constructor() {
    this.stateService.appConfig$.subscribe(config => {
      this.runtime = ((config as AppConfigWithRuntime | undefined)?.runtime || {});
    });
  }

  get ontologyBaseUrl(): string {
    const url = this.runtime.ontologyPublicUrl || this.runtime.ontologyUrl || DEFAULT_ONTOLOGY_URL;
    return url.replace(/\/$/, '');
  }

  get ontologyApiBaseUrl(): string {
    const url = this.runtime.ontologyUrl || this.runtime.ontologyPublicUrl || DEFAULT_ONTOLOGY_URL;
    return url.replace(/\/$/, '');
  }

  getOntologyLists(): Observable<Ontology[]> {
    const url = `${this.ontologyApiBaseUrl}/dataset/api/v2/vocabulary/list`;
    return this.http.get<Ontology[]>(url);
  }

  postUploadShacl(file: File, prefix: string, vocabUrl: string): Observable<unknown> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('prefix', prefix);
    formData.append('vocabUrl', vocabUrl);

    const adminUser = `${this.runtime.ontologyAdminUser || ''}`.trim();
    const adminPassword = `${this.runtime.ontologyAdminPassword || ''}`.trim();
    if (adminUser) {
      formData.append('user', adminUser);
    }
    if (adminPassword) {
      formData.append('password', adminPassword);
    }

    const url = `${this.ontologyApiBaseUrl}/dataset/api/v2/vocabulary/artifacts/shapes`;
    return this.http.post(url, formData);
  }

  buildUrl(prefix: string, type: 'ontology' | 'shacl', version: string | null): string {
    let url = `${this.ontologyBaseUrl}/dataset/vocabs/${prefix}`;
    if (type === 'ontology') {
      url += `/versions/${version}.n3`;
    } else if (type === 'shacl') {
      url += `/artifacts/shapes/${version}`;
    }
    return url;
  }
}
