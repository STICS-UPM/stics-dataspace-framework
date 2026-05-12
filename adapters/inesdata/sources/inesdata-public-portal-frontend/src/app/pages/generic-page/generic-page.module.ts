import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TranslateModule } from '@ngx-translate/core';
import { GenericPageRoutingModule } from './generic-page-routing.module';
import { GenericPageComponent } from './generic-page.component';
import { CardModule } from 'primeng/card';
import { EditorModule } from 'primeng/editor';
import { FormsModule } from '@angular/forms';

/**
 * Generic Page component module
 */
@NgModule({
  declarations: [GenericPageComponent],
  imports: [
    CommonModule,
    GenericPageRoutingModule,
    TranslateModule,
		CardModule,
		EditorModule,
		FormsModule
  ]
})
export class GenericPageModule { }
