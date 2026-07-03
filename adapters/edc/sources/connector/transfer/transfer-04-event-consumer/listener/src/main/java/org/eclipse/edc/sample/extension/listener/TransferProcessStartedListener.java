/*
 *  Copyright (c) 2021 Microsoft Corporation
 *
 *  This program and the accompanying materials are made available under the
 *  terms of the Apache License, Version 2.0 which is available at
 *  https://www.apache.org/licenses/LICENSE-2.0
 *
 *  SPDX-License-Identifier: Apache-2.0
 *
 *  Contributors:
 *       Microsoft Corporation - Initial implementation
 *
 */

package org.eclipse.edc.sample.extension.listener;

import org.eclipse.edc.connector.controlplane.transfer.spi.observe.TransferProcessListener;
import org.eclipse.edc.connector.controlplane.transfer.spi.types.TransferProcess;
import org.eclipse.edc.spi.monitor.Monitor;
import java.net.http.HttpClient;

import java.net.http.HttpRequest;

import java.net.http.HttpResponse;

import java.net.URI;
public class TransferProcessStartedListener implements TransferProcessListener {

    private final Monitor monitor;

    public TransferProcessStartedListener(Monitor monitor) {
        this.monitor = monitor;
    }

    /**
     * Callback invoked by the EDC framework when a transfer is about to be completed.
     *
     * @param process the transfer process that is about to be completed.
     */
    @Override
    public void preStarted(final TransferProcess process) {
String assetId = process.getAssetId();

String policyId = "5000"; //extractPolicyId(assetId);

    monitor.info("Evaluating policy for asset " + assetId + " (policyId=" + policyId + ")");



    try {

      String endpoint = "http://localhost:8000/api/policy/evaluate/" + policyId;

      HttpClient httpClient = HttpClient.newHttpClient();



      HttpRequest request = HttpRequest.newBuilder()

          .uri(URI.create(endpoint))

          .GET()

          .build();



      HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());


if (!response.body().contains("\"result\": true")) {

 monitor.warning("Policy conditions not met for asset " + assetId + ". Cancelling transfer.");

monitor.info("Policy evaluation failed");

} else {
monitor.info("Policy passed for asset " + assetId);

}



} catch (Exception e) {

 monitor.severe("Error evaluating policy: " + e.getMessage());

monitor.info("Policy evaluation error");

}        // do something meaningful before transfer start
    }
}
