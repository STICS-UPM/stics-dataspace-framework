import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { environment } from 'src/environments/environment';
import { GenericPage } from '../models/generic-page';

/**
 * Service to get the landing page content from the Strapi API
 */
@Injectable({
	providedIn: 'root'
})
export class GenericPageService {

  private readonly BASE_URL = `${environment.runtime.strapiUrl}`;
  private readonly GENERIC_PAGE_PATH = `${environment.runtime.service.strapi.getGenericPage}`;

	constructor(private httpClient: HttpClient) {
	}

	getGenericPageContent(id: String): Observable<GenericPage> {
		const fullUrl = `${this.BASE_URL}${this.GENERIC_PAGE_PATH}${id}`
		return this.httpClient.get<any>(fullUrl).pipe(
			map((response: any) => {
				const genericPage: GenericPage = {
					title: response['data']['attributes']['Title'],
					content: response['data']['attributes']['Content']
				}
				return genericPage;
			})
		);
	}
}
