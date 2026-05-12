import { NgModule } from '@angular/core';
import { SharedModule } from 'src/app/shared/shared.module';
import { AiModelBenchmarkingRoutingModule } from './ai-model-benchmarking-routing.module';
import { AiModelBenchmarkingComponent } from './ai-model-benchmarking/ai-model-benchmarking.component';

@NgModule({
  declarations: [
    AiModelBenchmarkingComponent
  ],
  imports: [
    SharedModule,
    AiModelBenchmarkingRoutingModule
  ]
})
export class AiModelBenchmarkingModule { }
