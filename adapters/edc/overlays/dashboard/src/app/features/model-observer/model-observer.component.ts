import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { DashboardStateService, EdcConfig } from '@eclipse-edc/dashboard-core';
import { Subject, combineLatest, firstValueFrom, take, takeUntil } from 'rxjs';

type ModelObserverRuntimeConfig = {
  modelObserverUrl?: string;
};

type AppConfigWithRuntime = {
  runtime?: ModelObserverRuntimeConfig;
};

type ObserverCheck = {
  label: string;
  url: string;
  status: 'passed' | 'failed';
  message: string;
};

@Component({
  selector: 'app-model-observer',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './model-observer.component.html',
})
export class ModelObserverComponent implements OnInit, OnDestroy {
  private readonly http = inject(HttpClient);
  private readonly state = inject(DashboardStateService);
  private readonly destroy$ = new Subject<void>();

  connectorName = '';
  observerBaseUrl = '';
  loading = false;
  errorMessage = '';
  checks: ObserverCheck[] = [];

  ngOnInit(): void {
    this.loadObserverEvidence();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  get healthyChecks(): number {
    return this.checks.filter(check => check.status === 'passed').length;
  }

  get totalChecks(): number {
    return this.checks.length;
  }

  get participantId(): string {
    return this.connectorName || 'selected connector';
  }

  loadObserverEvidence(): void {
    this.loading = true;
    this.errorMessage = '';
    this.checks = [];

    combineLatest([this.state.currentEdcConfig$, this.state.appConfig$])
      .pipe(take(1), takeUntil(this.destroy$))
      .subscribe({
        next: ([connectorConfig, appConfig]) => {
          this.connectorName = connectorConfig?.connectorName || '';
          this.observerBaseUrl = this.resolveObserverBaseUrl(connectorConfig, appConfig as AppConfigWithRuntime);
          void this.fetchChecks();
        },
        error: error => {
          this.loading = false;
          this.errorMessage = this.toErrorMessage(error, 'AI Model Observer runtime configuration is not available.');
        },
      });
  }

  private async fetchChecks(): Promise<void> {
    if (!this.observerBaseUrl) {
      this.loading = false;
      this.errorMessage = 'AI Model Observer endpoint is not configured for this dashboard.';
      return;
    }

    const endpoints = [
      { label: 'Health evidence', path: 'health' },
      { label: 'Readiness evidence', path: 'readiness' },
      { label: 'Liveness evidence', path: 'liveness' },
    ];

    this.checks = await Promise.all(
      endpoints.map(async endpoint => this.fetchCheck(endpoint.label, `${this.observerBaseUrl}/${endpoint.path}`)),
    );
    this.loading = false;
  }

  private async fetchCheck(label: string, url: string): Promise<ObserverCheck> {
    try {
      const payload = await firstValueFrom(this.http.get<Record<string, unknown>>(url));
      const healthy = payload?.['isSystemHealthy'] === true;
      return {
        label,
        url,
        status: healthy ? 'passed' : 'failed',
        message: healthy ? 'Evidence endpoint is healthy' : 'Evidence endpoint returned an unhealthy state',
      };
    } catch (error) {
      return {
        label,
        url,
        status: 'failed',
        message: this.toErrorMessage(error, 'Evidence endpoint is not reachable.'),
      };
    }
  }

  private resolveObserverBaseUrl(connectorConfig: EdcConfig | undefined, appConfig: AppConfigWithRuntime): string {
    const runtimeUrl = (appConfig?.runtime?.modelObserverUrl || '').trim();
    if (runtimeUrl) {
      return runtimeUrl.replace(/\/$/, '');
    }

    const defaultUrl = (connectorConfig?.defaultUrl || '').replace(/\/$/, '');
    if (!defaultUrl) {
      return '';
    }
    return defaultUrl.endsWith('/api') ? `${defaultUrl}/check` : `${defaultUrl}/api/check`;
  }

  private toErrorMessage(error: unknown, fallback: string): string {
    if (!error || typeof error !== 'object') {
      return fallback;
    }

    const record = error as Record<string, unknown>;
    const message = record['message'];
    if (typeof message === 'string' && message.trim().length > 0) {
      return message;
    }

    return fallback;
  }
}
