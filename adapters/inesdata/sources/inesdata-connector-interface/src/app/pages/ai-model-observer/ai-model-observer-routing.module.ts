import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AiModelObserverAgreementComponent } from './ai-model-observer-agreement/ai-model-observer-agreement.component';
import { AiModelObserverBenchmarkComponent } from './ai-model-observer-benchmark/ai-model-observer-benchmark.component';
import { AiModelObserverHomeComponent } from './ai-model-observer-home/ai-model-observer-home.component';
import { AiModelObserverParticipantComponent } from './ai-model-observer-participant/ai-model-observer-participant.component';
import { AiModelObserverTimelineComponent } from './ai-model-observer-timeline/ai-model-observer-timeline.component';

const routes: Routes = [
  { path: '', component: AiModelObserverHomeComponent },
  { path: 'agreements/:agreementId', component: AiModelObserverAgreementComponent },
  { path: 'participants/:participantId', component: AiModelObserverParticipantComponent },
  { path: 'timeline/:assetId', component: AiModelObserverTimelineComponent },
  { path: 'benchmarks/:benchmarkRunId', component: AiModelObserverBenchmarkComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AiModelObserverRoutingModule {}