import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

interface CatalogDetailData {
  assetId: string;
  properties: any;
  originator: string;
  contractOffers: any[];
  contractCount: number;
  catalogView?: boolean;
  returnUrl?: string;
  selectedTabIndex?: number;
}

/**
 * Service to share catalog item data between components
 * Used to pass data from catalog browser to catalog detail view
 */
@Injectable({
  providedIn: 'root'
})
export class CatalogStateService {
  private currentItemSubject = new BehaviorSubject<CatalogDetailData | null>(null);
  public currentItem$: Observable<CatalogDetailData | null> = this.currentItemSubject.asObservable();

  setCurrentItem(item: CatalogDetailData): void {
    console.log('[Catalog State Service] Setting current item:', item);
    this.currentItemSubject.next(item);
  }

  getCurrentItem(): CatalogDetailData | null {
    return this.currentItemSubject.value;
  }

  clearCurrentItem(): void {
    console.log('[Catalog State Service] Clearing current item');
    this.currentItemSubject.next(null);
  }
}
