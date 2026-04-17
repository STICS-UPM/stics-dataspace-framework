import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AiModelBenchmarkingComponent } from './ai-model-benchmarking/ai-model-benchmarking.component';

const routes: Routes = [
  { path: '', component: AiModelBenchmarkingComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AiModelBenchmarkingRoutingModule { }
