import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { AiModelBrowserComponent } from './ai-model-browser/ai-model-browser.component';

const routes: Routes = [
  { path: '', component: AiModelBrowserComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AiModelBrowserRoutingModule { }
