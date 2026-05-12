import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';
import { Vocabulary } from '../models/vocabulary';

/**
 * Service for getting vocabularies definition
 */
@Injectable({
	providedIn: 'root'
})
export class VocabulariesService {


	private readonly BASE_URL = `${environment.runtime.strapiUrl}`;
	private readonly VOCABULARY_URL = `${environment.runtime.service.strapi.getVocabularies}`;

	constructor(private httpClient: HttpClient) {
	}

	/**
	 * Gets all vocabularies definition
	 */
	getVocabularies(): Observable<Vocabulary[]> {
		return this.httpClient.post<any>(`${this.BASE_URL}${this.VOCABULARY_URL}`, {})
			.pipe();
	}
}
