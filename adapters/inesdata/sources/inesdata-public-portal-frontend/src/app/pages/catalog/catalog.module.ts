import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { CatalogRoutingModule } from './catalog-routing.module';
import { TranslateModule } from '@ngx-translate/core';
import { CardModule } from 'primeng/card';
import { PaginatorModule } from 'primeng/paginator';
import { InputTextModule } from 'primeng/inputtext';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { AccordionModule } from 'primeng/accordion';
import { TabViewModule } from 'primeng/tabview';
import { EditorModule } from 'primeng/editor';

import { CatalogBrowserComponent } from './catalog-browser/catalog-browser.component';
import { AssetDetailsComponent } from './asset-details/asset-details.component';
import { ReactiveFormsModule } from '@angular/forms';
import { CalendarModule } from 'primeng/calendar';

@NgModule({
  declarations: [
    CatalogBrowserComponent,
		AssetDetailsComponent
  ],
  imports: [
    CommonModule,
    CatalogRoutingModule,
		CardModule,
		TranslateModule,
		PaginatorModule,
		InputTextModule,
		ButtonModule,
		AccordionModule,
		CheckboxModule,
		CalendarModule,
		TabViewModule,
    ReactiveFormsModule,
		EditorModule
  ]
})
export class CatalogModule { }
