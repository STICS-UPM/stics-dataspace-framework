/*
 *  Copyright (c) 2025 Fraunhofer-Gesellschaft zur Förderung der angewandten Forschung e.V.
 *
 *  This program and the accompanying materials are made available under the
 *  terms of the Apache License, Version 2.0 which is available at
 *  https://www.apache.org/licenses/LICENSE-2.0
 *
 *  SPDX-License-Identifier: Apache-2.0
 *
 *  Contributors:
 *       Fraunhofer-Gesellschaft zur Förderung der angewandten Forschung e.V. - initial API and implementation
 *
 */

import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { DashboardStateService, EdcClientService, EdcConfig } from '@eclipse-edc/dashboard-core';
import { Asset, AssetInput, IdResponse } from '@think-it-labs/edc-connector-client';
import { filter, firstValueFrom, timeout } from 'rxjs';

/**
 * Service to manage and retrieve assets.
 */
@Injectable({
  providedIn: 'root',
})
export class AssetService {
  private readonly edc = inject(EdcClientService);
  private readonly http = inject(HttpClient);
  private readonly state = inject(DashboardStateService);

  /**
   * Retrieves all assets from the management API.
   * @returns A promise that resolves to an array of assets.
   */
  public async getAllAssets(): Promise<Asset[]> {
    return (await this.edc.getClient()).management.assets.queryAll();
  }

  /**
   * Creates a new asset using the provided asset input.
   * @param assetInput - The input data required to create a new asset.
   * @returns A promise that resolves to the ID response of the created asset.
   */
  public async createAsset(assetInput: AssetInput): Promise<IdResponse> {
    return (await this.edc.getClient()).management.assets.create(assetInput);
  }

  /**
   * Updates an existing asset with the provided asset input.
   * @param assetInput - The input data required to update the asset.
   * @returns A promise that resolves when the asset is successfully updated.
   */
  public async updateAsset(assetInput: AssetInput): Promise<void> {
    return (await this.edc.getClient()).management.assets.update(assetInput);
  }

  /**
   * Deletes an asset based on the provided ID.
   * @param id - The unique identifier of the asset to be deleted.
   * @returns A promise that resolves when the asset is successfully deleted.
   */
  public async deleteAsset(id: string): Promise<void> {
    return (await this.edc.getClient()).management.assets.delete(id);
  }

  /**
   * Runs the EDC RDF validation API against a sample RDF file before creating an asset.
   */
  public async testRdfAsset(ontologyUrl: string, shaclUrl: string, rdfFile: File, format: string): Promise<void> {
    const config = await firstValueFrom(
      this.state.currentEdcConfig$.pipe(
        filter((value): value is EdcConfig => !!value),
        timeout(1000),
      ),
    );
    const formData = new FormData();
    formData.append('ontologyUrl', ontologyUrl);
    formData.append('shaclUrl', shaclUrl);
    formData.append('rdf', rdfFile, rdfFile.name);
    formData.append('format', format || 'turtle');

    const headers = config.apiToken ? new HttpHeaders({ 'x-api-key': config.apiToken }) : undefined;
    await firstValueFrom(
      this.http.post(`${this.trimTrailingSlash(config.managementUrl)}/validation/rdf_asset`, formData, {
        headers,
        responseType: 'text',
      }),
    );
  }

  private trimTrailingSlash(value: string): string {
    return (value || '').replace(/\/+$/, '');
  }
}
