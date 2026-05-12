import { Component, OnInit } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { Asset } from "../../../shared/models/edc-connector-entities";
import { AssetService } from "../../../shared/services/asset.service";
import { ConfirmationDialogComponent, ConfirmDialogModel } from "../../../shared/components/confirmation-dialog/confirmation-dialog.component";
import { NotificationService } from "../../../shared/services/notification.service";
import { PageEvent } from '@angular/material/paginator';
import { EDC_CONTEXT, QuerySpec } from '@think-it-labs/edc-connector-client';
import { compact } from 'jsonld';
import { Router } from '@angular/router';

@Component({
  selector: 'app-asset-viewer',
  templateUrl: './asset-viewer.component.html',
  styleUrls: ['./asset-viewer.component.scss']
})
export class AssetViewerComponent implements OnInit {

  assets: Asset[] = [];

  isTransferring = false;
  private fetch$ = new BehaviorSubject(null);

  // Pagination
  pageSize = 10;
  currentPage = 0;
  paginatorLength = 0;

  CONTEXT = {
    "@vocab": EDC_CONTEXT,
    "description": "http://purl.org/dc/terms/description",
    "format": "http://purl.org/dc/terms/format",
    "byteSize": "http://www.w3.org/ns/dcat#byteSize",
    "keywords": "http://www.w3.org/ns/dcat#keyword"
  }

  constructor(private assetService: AssetService,
    private notificationService: NotificationService,
    private readonly dialog: MatDialog,
    private router: Router) {
  }

  private showError(error: string, errorMessage: string) {
    this.notificationService.showError(errorMessage);
    console.error(error);
  }

  ngOnInit(): void {
    this.countAssets();
    this.loadAssets(this.currentPage);
  }

  isBusy() {
    return this.isTransferring;
  }

  onDelete(asset: Asset) {
    const dialogData = ConfirmDialogModel.forDelete("asset", `"${asset.id}"`)
    const ref = this.dialog.open(ConfirmationDialogComponent, { maxWidth: "30%", data: dialogData });

    ref.afterClosed().subscribe({
      next: res => {
        if (res) {
          this.assetService.removeAsset(asset.id).subscribe({
            next: () => this.fetch$.next(null),
            error: err => this.showError(err, "This asset cannot be deleted: " + err.error[0].message),
            complete: () => {
              this.countAssets();
              this.loadAssets(this.currentPage);
              this.notificationService.showInfo("Successfully deleted");
            }
          });
        }
      }
    });
  }

  viewAsset(asset: Asset) {
    compact(asset, this.CONTEXT).then(compactedAsset => {
    this.router.navigate(['/assets/view'],{
			state: {
        assetDetailData: {
          assetId: compactedAsset['@id'],
          properties: compactedAsset.properties,
          privateProperties: compactedAsset.privateProperties,
          dataAddress: compactedAsset.dataAddress,
          isCatalogView: false,
          returnUrl: 'assets'
        }
			}
		})
    })
    .catch(error => {
      this.notificationService.showError("Error compacting JsonLD");
  });

  }

  onCreate() {
    this.router.navigate(['assets/create'])
  }

  changePage(event: PageEvent) {
    const offset = event.pageIndex * event.pageSize;
    this.pageSize = event.pageSize;
    this.currentPage = event.pageIndex;
    this.loadAssets(offset);
  }

  loadAssets(offset: number) {

    const querySpec: QuerySpec = {
      offset: offset,
      limit: this.pageSize
    }

    this.assetService.requestAssets(querySpec)
      .subscribe(results => {
        this.assets = results;
      });
  }

  countAssets() {
    this.assetService.count()
      .subscribe(result => {
        this.paginatorLength = result;
      });
  }
}
