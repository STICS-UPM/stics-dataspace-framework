import { NgModule } from '@angular/core';
import { SharedModule } from 'src/app/shared/shared.module';
import { AiModelBrowserRoutingModule } from './ai-model-browser-routing.module';
import { AiModelBrowserComponent } from './ai-model-browser/ai-model-browser.component';

@NgModule({
  declarations: [
    AiModelBrowserComponent
  ],
  imports: [
    SharedModule,
    AiModelBrowserRoutingModule
  ]
})
export class AiModelBrowserModule { }
