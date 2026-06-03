import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { DashboardStateService } from '@eclipse-edc/dashboard-core';
import { Ontology } from '../models/ontology';

const DEFAULT_ONTOLOGY_URL = 'http://ontology-hub-demo.dev.ds.dataspaceunit.upm';

@Injectable({
  providedIn: 'root',
})
export class OntologyService {
  private readonly http = inject(HttpClient);
  private readonly stateService = inject(DashboardStateService);

  get ontologyBaseUrl(): string {
    const runtime = this.stateService.getAppConfig()?.runtime;
    const url = runtime?.ontologyUrl || DEFAULT_ONTOLOGY_URL;
    return url.replace(/\/$/, '');
  }

  public getOntologyLists(): Observable<Ontology[]> {
    const url = `${this.ontologyBaseUrl}/dataset/api/v2/vocabulary/list`;
    return this.http.get<Ontology[]>(url);
  }

  public postUploadShacl(file: File, prefix: string, vocabUrl: string): Observable<unknown> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('prefix', prefix);
    formData.append('vocabUrl', vocabUrl);

    const runtime = this.stateService.getAppConfig()?.runtime;
    const adminUser = `${runtime?.ontologyAdminUser || ''}`.trim();
    const adminPassword = `${runtime?.ontologyAdminPassword || ''}`.trim();
    if (adminUser) {
      formData.append('user', adminUser);
    }
    if (adminPassword) {
      formData.append('password', adminPassword);
    }

    const url = `${this.ontologyBaseUrl}/dataset/api/v2/vocabulary/artifacts/shapes`;
    return this.http.post(url, formData);
  }

  public buildUrl(prefix: string, type: 'ontology' | 'shacl', version: string | null): string {
    let url = `${this.ontologyBaseUrl}/dataset/vocabs/${prefix}`;
    if (type === 'ontology') {
      url += `/versions/${version}.n3`;
    } else if (type === 'shacl') {
      url += `/artifacts/shapes/${version}`;
    }
    return url;
  }
}
