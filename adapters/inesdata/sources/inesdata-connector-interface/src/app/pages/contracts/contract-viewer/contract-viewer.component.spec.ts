import { of } from 'rxjs';

import { ContractViewerComponent } from './contract-viewer.component';

describe('ContractViewerComponent', () => {
  it('retries federated catalog lookup when the exact match has no endpoint URL', async () => {
    const catalogService = {
      getPaginatedDataOffers: jasmine.createSpy('getPaginatedDataOffers').and.returnValues(
        of([
          {
            assetId: 'asset-1',
            endpointUrl: '',
            properties: { participantId: 'provider-1' },
            contractOffers: [],
            originator: 'provider-1'
          }
        ]),
        of([
          {
            assetId: 'asset-1',
            endpointUrl: 'https://provider.example/protocol',
            properties: { participantId: 'provider-1' },
            contractOffers: [],
            originator: 'provider-1'
          }
        ])
      )
    };
    const component = new ContractViewerComponent(
      {} as any,
      {} as any,
      catalogService as any,
      {} as any,
      {} as any,
      {} as any
    );

    const offer = await (component as any).getDatasetFromFederatedCatalog('asset-1', 'provider-1');

    expect(offer.endpointUrl).toBe('https://provider.example/protocol');
    expect(catalogService.getPaginatedDataOffers).toHaveBeenCalledTimes(2);
    expect(catalogService.getPaginatedDataOffers.calls.argsFor(1)[0]).toEqual(jasmine.objectContaining({
      offset: 0,
      limit: 25
    }));
  });

  it('fails before transfer creation when the catalog offer has no endpoint URL', async () => {
    const catalogService = {
      getPaginatedDataOffers: jasmine.createSpy('getPaginatedDataOffers').and.returnValues(
        of([
          {
            assetId: 'asset-1',
            endpointUrl: '',
            properties: { participantId: 'provider-1' },
            contractOffers: [],
            originator: 'provider-1'
          }
        ]),
        of([]),
        of([])
      )
    };
    const component = new ContractViewerComponent(
      {} as any,
      {} as any,
      catalogService as any,
      {} as any,
      {} as any,
      {} as any
    );

    await expectAsync(
      (component as any).getDatasetFromFederatedCatalog('asset-1', 'provider-1')
    ).toBeRejectedWithError(/No endpoint URL found/);
  });
});
