import { Component } from '@angular/core';
import { BehaviorSubject, Observable, switchMap } from 'rxjs';
import { DataOffer } from 'src/app/shared/models/data-offer';
import { LandingPage } from 'src/app/shared/models/landing-page';
import { LandingPageService } from '../../shared/services/landing-page.service';
import { CatalogBrowserService } from '../../shared/services/catalog-browser.service';
import { QuerySpec } from '@think-it-labs/edc-connector-client';
import { Router } from '@angular/router';

/**
 * Home component
 */
@Component({
	selector: 'app-home',
	templateUrl: './home.component.html',
	styleUrls: ['./home.component.scss']
})
export class HomeComponent {

	landingPageContent$: Observable<LandingPage>;
	datasets: DataOffer[];
	private fetch$ = new BehaviorSubject(null);
	background: any;

	/**
	 * Component constructor
	 */
	constructor(private landingPageService: LandingPageService,
		private catalogService: CatalogBrowserService,
		private router: Router) { }

	ngOnInit() {
		this.landingPageContent$ = this.fetch$
			.pipe(
				switchMap(() => {
					return this.landingPageService.getLandingPageContent();
				}));


		this.loadDatasets();
	}

	loadDatasets() {
		const querySpec: QuerySpec = {
			offset: 0,
			limit: 5,
			filterExpression: []
		}

		this.catalogService.getPaginatedDataOffers(querySpec)
			.subscribe(results => {
				this.datasets = results.datasets;
			});
	}

	viewDataset(dataset: DataOffer) {
		this.router.navigate(['/catalog', dataset.properties.participantId, dataset.assetId]);
	}
}
