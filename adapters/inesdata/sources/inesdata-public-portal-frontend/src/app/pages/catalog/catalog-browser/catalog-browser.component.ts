import { Component, OnInit, ViewChild } from '@angular/core';
import { CatalogBrowserService } from "../../../shared/services/catalog-browser.service";
import { Router } from '@angular/router';

import { DataOffer } from 'src/app/shared/models/data-offer';
import { QuerySpec } from '@think-it-labs/edc-connector-client';
import { ASSET_TYPES } from 'src/app/shared/utils/app.constants';
import { VocabulariesService } from 'src/app/shared/services/vocabularies.service';
import { Vocabulary } from 'src/app/shared/models/vocabulary';
import { FormBuilder, FormControl, FormGroup } from '@angular/forms';


@Component({
	selector: 'app-catalog-browser',
	templateUrl: './catalog-browser.component.html',
	styleUrls: ['./catalog-browser.component.scss']
})
export class CatalogBrowserComponent implements OnInit {
	datasets: DataOffer[];

	// Pagination
	pageSize = 10;
	currentPage = 0;
	paginatorLength = 0;
	offset = 0;

	selectedValues: string[] = [];
	vocabulariesDefinition: Vocabulary[] = [];

	forms: FormGroup[] = [];

	schemas: any[] = [];
	allFormValues: any[] = [];
	searchText: String = undefined;
	filterExpression: any[] = [];

	isPreviousNavigation = false;

	constructor(private catalogService: CatalogBrowserService, private vocabulariesService: VocabulariesService,
		private router: Router, private fb: FormBuilder) {
		const navigation = this.router.getCurrentNavigation();
		if (navigation.previousNavigation && navigation?.extras?.state) {
			this.isPreviousNavigation = true;
			this.currentPage = navigation.extras.state.currentPage;
			this.pageSize = navigation.extras.state.pageSize;
			this.allFormValues = navigation.extras.state.formValues;
			this.searchText = navigation.extras.state.searchText;
			this.filterExpression = navigation.extras.state.filterExpression;
			this.vocabulariesDefinition = navigation.extras.state.vocabulariesDefinition;
		}
	}

	ngOnInit(): void {
		this.offset = this.currentPage * this.pageSize;
		this.loadDatasets();

		if (this.isPreviousNavigation) {
			this.createForms();
			this.retrieveFormValues();
		} else {
			this.loadVocabulariesDefinition();
		}


	}
	createForms() {
		this.vocabulariesDefinition.forEach(schema => {
			const form = this.fb.group({});
			const jschema = JSON.parse(schema['jsonSchema'])
			this.schemas.push(jschema)
			this.buildForm(jschema.properties, form)
			this.forms.push(form);
			if(!this.isPreviousNavigation) {
				this.allFormValues.push(form.value);
			}
		});
	}

	loadVocabulariesDefinition() {
		this.vocabulariesService.getVocabularies()
			.subscribe(results => {
				this.vocabulariesDefinition = results;
				this.createForms();
			});
	}

	private retrieveFormValues() {
		for (let index = 0; index < this.forms.length; index++) {
			this.forms[index].setValue(this.allFormValues[index]);
		}
	}

	loadDatasets() {
		const querySpec: QuerySpec = {
			offset: this.offset,
			limit: this.pageSize,
			sortField: "id",
			sortOrder: "ASC",
			filterExpression: this.filterExpression
		}

		this.catalogService.getPaginatedDataOffers(querySpec)
			.subscribe(results => {
				this.datasets = results.datasets;
				this.paginatorLength = results.totalElements;
			});
	}

	changePage(event) {
		this.offset = event.page * event.rows;
		this.pageSize = event.rows;
		this.currentPage = event.page;
		this.loadDatasets();
	}

	viewDetails(dataset: DataOffer) {
		this.router.navigate(['/catalog', dataset.properties.participantId, dataset.assetId], {
			state: {
				currentPage: this.currentPage,
				pageSize: this.pageSize,
				formValues: this.allFormValues,
				searchText: this.searchText,
				filterExpression: this.filterExpression,
				vocabulariesDefinition: this.vocabulariesDefinition,
			}
		});
	}

	getAssetTypeIconClass(assetType: string) {
		if (ASSET_TYPES.machineLearning == assetType) {
			return 'pi-machinelearning';
		} else if (ASSET_TYPES.service == assetType) {
			return 'pi-briefcase';
		} else {
			return 'pi-box';
		}
	}

	buildForm(properties: any, form: FormGroup, parentKey?: string): void {
		for (const key in properties) {
			if (properties.hasOwnProperty(key)) {
				const property = properties[key];
				const controlKey = parentKey ? `${parentKey}.${key}` : key;
				if (property.type === 'object') {
					this.buildForm(property.properties, form, controlKey);
				} else if (property.type === 'array' && property.items.type === 'object') {
					this.buildForm(property.items.properties, form, controlKey);
				} else {
					form.addControl(controlKey, new FormControl('', []));
				}
			}
		}
	}

	getKeys(obj: any): string[] {
		return Object.keys(obj);
	}

	getType(format: string): string {
		switch (format) {
			case 'date':
				return 'date';
			default:
				return 'text';
		}
	}

	search() {
		this.allFormValues = this.forms.map(form => form.value);
		this.allFormValues.forEach(formValue => {
			Object.keys(formValue).forEach(key => {
				const oldValue = formValue[key]
				if (oldValue instanceof Date) {
					formValue[key] = this.formatDateToYYMMDD(oldValue)
				}
				if(oldValue == null){
					formValue[key] = ""
				}
			});
		});
		this.createFilterExpression();
		this.loadDatasets();
	}


	filterProperties(object: { [key: string]: any }, schema: any, vocabulary: Vocabulary): { [key: string]: any } {
		let result: { [key: string]: any } = {};

		const context = schema["@context"] || {};

		for (const key in object) {
			if (object.hasOwnProperty(key) && object[key] !== '') {
				const parts = key.split('.')
				const transformedParts = parts.map((part, index) => {
					const [prefix, rest] = part.split(/:(.+)/);
					const namespace = context[prefix];
					if (index === 0 && !namespace) {
						return `'https://w3id.org/edc/v0.0.1/ns/${part}'`;
					} else {
						return namespace ? `'${namespace}${rest}'` : `'${part}'`;
					}
				});

				const newKey = `'https://w3id.org/edc/v0.0.1/ns/${vocabulary['@id']}'.${transformedParts.join('.')}`;
				result[newKey] = object[key];

			}

		}

		return result;
	}

	formatDateToYYMMDD(date) {
		const year = date.getFullYear().toString(); // Obtener los últimos 2 dígitos del año
		const month = (date.getMonth() + 1).toString().padStart(2, '0'); // Obtener el mes (0-11) y añadir cero al principio si es necesario
		const day = date.getDate().toString().padStart(2, '0'); // Obtener el día y añadir cero al principio si es necesario

		return `${year}-${month}-${day}`;
	}

	private createFilterExpression() {
		this.filterExpression = []
		if (this.searchText) {
			this.filterExpression.push({
				operandLeft: "genericSearch",
				operator: "LIKE",
				operandRight: `%${this.searchText}%`
			})
		}
		const allFormValuesNotEmpty: any[] = []
		this.allFormValues.forEach((f, index) => {
			const newValuesObject = this.filterProperties(f, this.schemas[index], this.vocabulariesDefinition[index])
			if (Object.keys(newValuesObject).length > 0) {
				allFormValuesNotEmpty.push(newValuesObject)
			}
		})
		allFormValuesNotEmpty.forEach(form => {
			Object.keys(form).forEach(key => {
				const value = form[key]
				if (value !== '') {
					this.filterExpression.push({
						operandLeft: `'https://w3id.org/edc/v0.0.1/ns/assetData'.${key}`,
						operator: "=",
						operandRight: value
					});
				}
			})
		})
	}

}
