import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from 'src/environments/environment';
import { ModelObserverApiService } from './model-observer-api.service';

describe('ModelObserverApiService', () => {
  let service: ModelObserverApiService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule]
    });

    service = TestBed.inject(ModelObserverApiService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should POST observer events to the events endpoint', () => {
    const payload = {
      eventType: 'MODEL_DETAIL_VIEWED',
      sourceComponent: 'unit-test',
      assetId: 'asset-1'
    };

    service.createEvent(payload).subscribe();

    const request = httpMock.expectOne(`${environment.runtime.strapiUrl}/api/model-observer/events`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(payload);
    request.flush({ ok: true });
  });

  it('should encode the asset id and ignore empty timeline filter values', () => {
    service.getTimeline('asset/with spaces', {
      eventType: 'MODEL_EXECUTION_COMPLETED',
      status: 'COMPLETED',
      participantId: '',
      agreementId: undefined,
      from: null as unknown as string,
      limit: 20
    }).subscribe();

    const request = httpMock.expectOne((req) => req.url === `${environment.runtime.strapiUrl}/api/model-observer/timeline/asset%2Fwith%20spaces`);
    expect(request.request.method).toBe('GET');
    expect(request.request.params.get('eventType')).toBe('MODEL_EXECUTION_COMPLETED');
    expect(request.request.params.get('status')).toBe('COMPLETED');
    expect(request.request.params.get('limit')).toBe('20');
    expect(request.request.params.has('participantId')).toBeFalse();
    expect(request.request.params.has('agreementId')).toBeFalse();
    expect(request.request.params.has('from')).toBeFalse();
    request.flush({ items: [], total: 0, limit: 20, offset: 0 });
  });

  it('should request agreement, benchmark, and participant observer endpoints', () => {
    service.getAgreementTimeline('agreement id', { status: 'COMPLETED' }).subscribe();
    service.getBenchmarkTimeline('benchmark/id', { eventType: 'BENCHMARK_STARTED' }).subscribe();
    service.getParticipantSummary('connector-c1').subscribe();

    const agreementRequest = httpMock.expectOne((req) => req.url === `${environment.runtime.strapiUrl}/api/model-observer/agreements/agreement%20id`);
    expect(agreementRequest.request.params.get('status')).toBe('COMPLETED');
    agreementRequest.flush({ items: [], total: 0, limit: 100, offset: 0 });

    const benchmarkRequest = httpMock.expectOne((req) => req.url === `${environment.runtime.strapiUrl}/api/model-observer/benchmarks/benchmark%2Fid`);
    expect(benchmarkRequest.request.params.get('eventType')).toBe('BENCHMARK_STARTED');
    benchmarkRequest.flush({ items: [], total: 0, limit: 100, offset: 0 });

    const summaryRequest = httpMock.expectOne(`${environment.runtime.strapiUrl}/api/model-observer/participants/connector-c1/summary`);
    expect(summaryRequest.request.method).toBe('GET');
    summaryRequest.flush({ participantId: 'connector-c1', totalsByEventType: {}, recentFailures: 0, latestEvent: null });
  });
});