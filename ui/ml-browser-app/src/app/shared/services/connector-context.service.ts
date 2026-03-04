import { Injectable, inject } from '@angular/core';
import { environment } from '../../../environments/environment';
import { AuthService } from './auth.service';

export type ConnectorRole = 'consumer' | 'provider';

@Injectable({
  providedIn: 'root'
})
export class ConnectorContextService {
  private readonly authService = inject(AuthService);

  getCurrentRole(): ConnectorRole {
    return this.authService.getUserRole();
  }

  getManagementApiUrl(): string {
    return this.getCurrentRole() === 'provider'
      ? (environment.runtime.providerManagementUrl || environment.runtime.managementApiUrl)
      : environment.runtime.consumerManagementUrl;
  }

  getCounterPartyProtocolUrl(): string {
    return this.getCurrentRole() === 'provider'
      ? environment.runtime.consumerProtocolUrl
      : environment.runtime.providerProtocolUrl;
  }

  getApiUrl(): string {
    return this.getCurrentRole() === 'provider'
      ? (environment.runtime.providerApiUrl || 'http://localhost:19191')
      : environment.runtime.consumerApiUrl;
  }

  getInferApiUrl(): string {
    return `${this.getApiUrl()}/api/infer`;
  }
}
