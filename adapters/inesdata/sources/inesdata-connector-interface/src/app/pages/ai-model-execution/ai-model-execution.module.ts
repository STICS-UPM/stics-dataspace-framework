import { NgModule } from '@angular/core';
import { SharedModule } from 'src/app/shared/shared.module';
import { AiModelExecutionRoutingModule } from './ai-model-execution-routing.module';
import { AiModelExecutionComponent } from './ai-model-execution/ai-model-execution.component';

@NgModule({
  declarations: [
    AiModelExecutionComponent
  ],
  imports: [
    SharedModule,
    AiModelExecutionRoutingModule
  ]
})
export class AiModelExecutionModule { }
