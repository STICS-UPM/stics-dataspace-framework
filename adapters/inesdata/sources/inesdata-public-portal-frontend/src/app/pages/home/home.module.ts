import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TranslateModule } from '@ngx-translate/core';
import { HomeRoutingModule } from './home-routing.module';
import { HomeComponent } from './home.component';
import { CardModule } from 'primeng/card';
import { MarkdownModule } from 'ngx-markdown';

/**
 * Home component module
 */
@NgModule({
  declarations: [HomeComponent],
  imports: [
    CommonModule,
    HomeRoutingModule,
    TranslateModule,
		CardModule,
		MarkdownModule.forRoot()
  ]
})
export class HomeModule { }
