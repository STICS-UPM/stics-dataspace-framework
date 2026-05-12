import { Injectable } from '@angular/core';
import { MenuItem } from 'primeng/api';
import { environment } from 'src/environments/environment';
import { catchError, map, Observable, of } from 'rxjs';
import { HttpClient } from '@angular/common/http';

/**
 * Main menu service for main and user menus
 */
@Injectable({
	providedIn: 'root'
})
export class MenuService {
	// Menus
	mainMenu: MenuItem[] = [];
	userMenu: any;

	activeItem: MenuItem;

	userSubscription: any;
	languageSubscription: any;

	private readonly BASE_URL = `${environment.runtime.strapiUrl}`;
	private readonly GET_MENU_PATH = '/api/menus?filters[slug][$eq]=public-portal-menu&populate[items][populate]=related_content';

	/**
	 * Component constructor
	 *
	 * @param httpClient HTTP client
	 */
	constructor(
		private httpClient: HttpClient
	) {
		this.mainMenu.push({
			label: "Catálogo",
			routerLink: "/catalog",
			command: e => this.activeItem = e.item,
			title: "Catálogo"
		}, {
			label: "Model Observer",
			routerLink: "/model-observer",
			command: e => this.activeItem = e.item,
			title: "Model Observer"
		});
	}

	/**
	 * Gets the menu from Strapi
	 */
	getMenu(): Observable<MenuItem[]> {
		const fullUrl = `${this.BASE_URL}${this.GET_MENU_PATH}`;
		return this.httpClient.get<any>(fullUrl).pipe(
			map((response: any) => {
				if(response['data'] && Object.keys(response['data']).length > 0){
					response['data'][0]['attributes']['items']['data'].forEach(item => {
						let menuItem: MenuItem = {
							label: item['attributes']['title'],
							routerLink: item['attributes']['url'] ? null : `/dataspace/${item['attributes']['slug']}`,
							id: item['attributes']['related_content']['id'] ? item['attributes']['related_content']['id'] : null,
							command: e => {
								this.activeItem = e.item;
								if (item['attributes']['url']) {
									window.open(item['attributes']['url'], '_blank');
								}
							},
							slug: item['attributes']['slug'],
							target: item['attributes']['target']
						};

						if (item['attributes']['url'] !== "") {
							menuItem.externalLink = item['attributes']['url'];
						}

						this.mainMenu.push(menuItem);
					});
				}

				return this.mainMenu;
			}),
			catchError(() => of(this.mainMenu))
		);
	}
}
