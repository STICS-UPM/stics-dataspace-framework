import { NgModule } from '@angular/core';
import { SharedModule } from '../../shared/shared.module';
import { ModelEventCardComponent } from '../../shared/components/model-observer/model-event-card/model-event-card.component';
import { ModelObserverBadgeComponent } from '../../shared/components/model-observer/model-observer-badge/model-observer-badge.component';
import { ModelTimelineFilterComponent } from '../../shared/components/model-observer/model-timeline-filter/model-timeline-filter.component';
import { ModelObserverAgreementComponent } from './model-observer-agreement/model-observer-agreement.component';
import { ModelObserverBenchmarkHistoryComponent } from './model-observer-benchmark-history/model-observer-benchmark-history.component';
import { ModelObserverHomeComponent } from './model-observer-home/model-observer-home.component';
import { ModelObserverParticipantSummaryComponent } from './model-observer-participant-summary/model-observer-participant-summary.component';
import { ModelObserverRoutingModule } from './model-observer-routing.module';
import { ModelObserverTimelineComponent } from './model-observer-timeline/model-observer-timeline.component';

@NgModule({
  declarations: [
    ModelObserverHomeComponent,
    ModelObserverTimelineComponent,
    ModelObserverAgreementComponent,
    ModelObserverBenchmarkHistoryComponent,
    ModelObserverParticipantSummaryComponent,
    ModelEventCardComponent,
    ModelTimelineFilterComponent,
    ModelObserverBadgeComponent
  ],
  imports: [
    SharedModule,
    ModelObserverRoutingModule
  ]
})
export class ModelObserverModule {}