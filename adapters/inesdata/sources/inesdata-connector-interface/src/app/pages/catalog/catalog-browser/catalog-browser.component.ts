import { Component, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { CatalogBrowserService } from "../../../shared/services/catalog-browser.service";
import { DataOffer } from 'src/app/shared/models/data-offer';
import { PageEvent } from '@angular/material/paginator';
import { QuerySpec } from '@think-it-labs/edc-connector-client';
import { Router } from '@angular/router';



@Component({
  selector: 'app-catalog-browser',
  templateUrl: './catalog-browser.component.html',
  styleUrls: ['./catalog-browser.component.scss']
})
export class CatalogBrowserComponent implements OnInit {

  dataOffers: DataOffer[] = [];

  // Pagination
  pageSize = 10;
  currentPage = 0;
  paginatorLength = 0;

  constructor(private catalogService: CatalogBrowserService,
    public dialog: MatDialog, private router: Router) {
  }

  ngOnInit(): void {
    this.countDatasets();
    this.loadDataOffers(this.currentPage);
  }

  viewContractOffers(assetId: string, contractOffers: any, endpointUrl: string, properties: any) {
    this.router.navigate(['/catalog/datasets/view'],{
			state: {
        assetDetailData: {
          assetId: assetId,
          contractOffers: contractOffers,
          endpointUrl: endpointUrl,
          properties: properties,
          isCatalogView: true,
          returnUrl: 'catalog'
        }
			}
		})
  }

  changePage(event: PageEvent) {
    const offset = event.pageIndex * event.pageSize;
    this.pageSize = event.pageSize;
    this.currentPage = event.pageIndex;
    this.loadDataOffers(offset);
  }

  loadDataOffers(offset: number) {
    const querySpec: QuerySpec = {
      offset: offset,
      limit: this.pageSize
    }

    this.catalogService.getPaginatedDataOffers(querySpec)
      .subscribe(results => {
        this.dataOffers = results;
      });
  }

  countDatasets() {
    this.catalogService.count()
      .subscribe(result => {
        this.paginatorLength = result;
      });
  }
}
