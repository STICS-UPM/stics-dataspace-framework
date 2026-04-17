import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AiModelExecutionComponent } from './ai-model-execution/ai-model-execution.component';

const routes: Routes = [
  { path: '', component: AiModelExecutionComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AiModelExecutionRoutingModule { }
