import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { ModelObserverAgreementComponent } from './model-observer-agreement/model-observer-agreement.component';
import { ModelObserverBenchmarkHistoryComponent } from './model-observer-benchmark-history/model-observer-benchmark-history.component';
import { ModelObserverHomeComponent } from './model-observer-home/model-observer-home.component';
import { ModelObserverParticipantSummaryComponent } from './model-observer-participant-summary/model-observer-participant-summary.component';
import { ModelObserverTimelineComponent } from './model-observer-timeline/model-observer-timeline.component';

const routes: Routes = [
  { path: '', component: ModelObserverHomeComponent },
  { path: 'timeline/:assetId', component: ModelObserverTimelineComponent },
  { path: 'agreements/:agreementId', component: ModelObserverAgreementComponent },
  { path: 'benchmarks/:benchmarkRunId', component: ModelObserverBenchmarkHistoryComponent },
  { path: 'participants/:participantId', component: ModelObserverParticipantSummaryComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class ModelObserverRoutingModule {}