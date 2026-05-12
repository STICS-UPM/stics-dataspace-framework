import { NgModule } from '@angular/core';
import { SharedModule } from 'src/app/shared/shared.module';
import { AiModelObserverAgreementComponent } from './ai-model-observer-agreement/ai-model-observer-agreement.component';
import { AiModelObserverBenchmarkComponent } from './ai-model-observer-benchmark/ai-model-observer-benchmark.component';
import { AiModelObserverHomeComponent } from './ai-model-observer-home/ai-model-observer-home.component';
import { AiModelObserverParticipantComponent } from './ai-model-observer-participant/ai-model-observer-participant.component';
import { AiModelObserverRoutingModule } from './ai-model-observer-routing.module';
import { AiModelObserverTimelineComponent } from './ai-model-observer-timeline/ai-model-observer-timeline.component';

@NgModule({
  declarations: [
    AiModelObserverHomeComponent,
    AiModelObserverAgreementComponent,
    AiModelObserverTimelineComponent,
    AiModelObserverBenchmarkComponent,
    AiModelObserverParticipantComponent
  ],
  imports: [
    SharedModule,
    AiModelObserverRoutingModule
  ]
})
export class AiModelObserverModule {}