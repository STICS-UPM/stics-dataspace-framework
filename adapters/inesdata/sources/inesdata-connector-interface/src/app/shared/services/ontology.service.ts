'use strict';

import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from "src/environments/environment";
import { Ontology } from '../models/ontology';

const DEFAULT_LOCAL_BASE_URL = 'http://ontology-hub-demo.dev.ds.dataspaceunit.upm';

@Injectable({
  providedIn: 'root'
})
export class OntologyService{

    public constructor(private http: HttpClient){

    }

    get ontologyBaseUrl(): string {
        return environment.runtime.ontologyUrl || (environment.production ? '' : DEFAULT_LOCAL_BASE_URL);
    }

    public getOntologyLists(): Observable<Ontology[]> {
        const url = `${this.ontologyBaseUrl}/dataset/api/v2/vocabulary/list`;
        return this.http.get<Ontology[]>(url);
    }

    public postUploadShacl(file: File, prefix: string, vocabUrl: string): Observable<any> {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('prefix', prefix);
        formData.append('vocabUrl', vocabUrl);

        const adminUser = `${environment.runtime.ontologyAdminUser || ''}`.trim();
        const adminPassword = `${environment.runtime.ontologyAdminPassword || ''}`.trim();
        if (adminUser) {
            formData.append('user', adminUser);
        }
        if (adminPassword) {
            formData.append('password', adminPassword);
        }

        const url = `${this.ontologyBaseUrl}/dataset/api/v2/vocabulary/artifacts/shapes`;
        return this.http.post(url, formData);
    }

    /**
     * Builds Ontology Hub public URLs for ontology and SHACL artifacts.
     */
    public buildUrl(prefix: string, type: "ontology" | "shacl", version: string|null):string{
        let url = `${this.ontologyBaseUrl}/dataset/vocabs/${prefix}`;
        if(type === 'ontology'){
            url += `/versions/${version}.n3`;
        }else if(type === 'shacl' ){
            url += `/artifacts/shapes/${version}`;
        }
        return url;
    }
}
