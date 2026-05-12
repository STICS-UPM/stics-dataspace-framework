import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { DataOffer } from '../models/data-offer';
import { FederatedCatalog } from '../models/federated-catalog';


import { QuerySpec } from "../models/edc-connector-entities";
import { environment } from 'src/environments/environment';
import { JSON_LD_DEFAULT_CONTEXT } from '@think-it-labs/edc-connector-client';

/**
 * Combines several services that are used from the {@link CatalogBrowserComponent}
 */
@Injectable({
	providedIn: 'root'
})
export class CatalogBrowserService {


	private readonly BASE_URL = `${environment.runtime.strapiUrl}`;
	private readonly CATALOG_URL = `${environment.runtime.service.strapi.getFederatedCatalog}`;

	constructor(private httpClient: HttpClient) {
	}

	/**
	 * Gets all data offers (datasets) according to a particular query
	 * @param querySpec
	 */
	getPaginatedDataOffers(querySpec: QuerySpec): Observable<FederatedCatalog> {
		let body;

		if (querySpec) {
			body = {
				...querySpec,
				"@context": JSON_LD_DEFAULT_CONTEXT,
			}
		}

		return this.httpClient.post<any>(`${this.BASE_URL}${this.CATALOG_URL}`, body)
			.pipe(
				map(response => {
					const datasets = response.catalogs
						.map(catalog => this.mapCatalog(catalog))
						.reduce((acc, val) => acc.concat(val), []);

					return {
						datasets: datasets,
						totalElements: response.totalElements
					};
				})
			);
	}

	private mapCatalog(catalog: any) {
		const arr = Array<DataOffer>();
		let datasets = catalog["http://www.w3.org/ns/dcat#dataset"];
		if (!Array.isArray(datasets)) {
			datasets = [datasets];
		}

		for (const dataset of datasets) {
			const properties: { [key: string]: string; } = {
				id: dataset["id"],
				name: dataset["name"],
				version: dataset["version"],
				assetType: dataset["assetType"],
				contentType: dataset["contenttype"],
				assetData: dataset["assetData"],
				description: dataset["http://purl.org/dc/terms/description"],
				shortDescription: dataset["shortDescription"],
				byteSize: dataset["http://www.w3.org/ns/dcat#byteSize"],
				format: dataset["http://purl.org/dc/terms/format"],
				keywords: dataset["http://www.w3.org/ns/dcat#keyword"],
				participantId: dataset["participantId"]
			}
			const assetId = dataset["@id"];

			const dataOffer = {
				assetId: assetId,
				properties: properties,
				context: catalog["@context"],
				originalJson: dataset
			}

			arr.push(dataOffer);
		}
		return arr;
	}

}
