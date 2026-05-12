import {Injectable} from '@angular/core';
import {PolicyMapper} from './policy-mapper';
import { PolicyDefinitionDto } from './policy-definition-dto';
import { PolicyCard } from './policy-card';
import { ContractOffer } from '../contract-offer';

@Injectable({providedIn: 'root'})
export class PolicyCardBuilder {
  constructor(private policyMapper: PolicyMapper) {}
  buildPolicyCardsFromPolicyDefinitions(policyDefinitions: PolicyDefinitionDto[]): PolicyCard[] {
    return policyDefinitions.map((policyDefinition) =>
      this.buildPolicyCardFromPolicyDefinition(policyDefinition),
    );
  }

  buildPolicyCardFromPolicyDefinition(policyDefinition: PolicyDefinitionDto): PolicyCard {
    const irregularities = policyDefinition.policy?.errors ?? [];
    const expression = this.policyMapper.buildPolicy(
      policyDefinition.policy.expression!,
    );
    return {
      id: policyDefinition.policyDefinitionId,
      isRegular: !irregularities.length,
      irregularities,
      expression,
      searchText: JSON.stringify(expression),
      objectForJson: JSON.parse(policyDefinition.policy.policyJsonLd),
    };
  }

  buildPolicyCardsFromContractOffers(contractOffers: ContractOffer[]): PolicyCard[] {
    return contractOffers.map((contractOffer) =>
      this.buildPolicyCardFromContractOffer(contractOffer),
    );
  }

  buildPolicyCardFromContractOffer(contractOffer: ContractOffer): PolicyCard {
    const irregularities = contractOffer.policy?.errors ?? [];
    const expression = this.policyMapper.buildPolicy(
      contractOffer.policy.expression!,
    );
    return {
      id: contractOffer.contractOfferId,
      isRegular: !irregularities.length,
      irregularities,
      expression,
      searchText: JSON.stringify(expression),
      objectForJson: JSON.parse(contractOffer.policy.policyJsonLd),
    };
  }
}
