import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ConnectorContextService } from './connector-context.service';

export interface ContractSequenceResponse {
  userId: string;
  index: number;
  contractDefinitionId: string;
}

@Injectable({
  providedIn: 'root'
})
export class ContractSequenceService {
  private readonly http = inject(HttpClient);
  private readonly connectorContextService = inject(ConnectorContextService);

  peekNextContractDefinitionId(userId: string): Observable<ContractSequenceResponse> {
    return this.http.post<ContractSequenceResponse>(
      `${this.connectorContextService.getApiUrl()}/api/contract-sequences/peek`,
      { userId }
    );
  }

  getNextContractDefinitionId(userId: string): Observable<ContractSequenceResponse> {
    return this.http.post<ContractSequenceResponse>(
      `${this.connectorContextService.getApiUrl()}/api/contract-sequences/next`,
      { userId }
    );
  }

  commitContractDefinitionId(userId: string, index: number): Observable<{ userId: string; committedIndex: number }> {
    return this.http.post<{ userId: string; committedIndex: number }>(
      `${this.connectorContextService.getApiUrl()}/api/contract-sequences/commit`,
      { userId, index }
    );
  }
}
