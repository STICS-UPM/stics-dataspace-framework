import os
import unittest


VALIDATION_ROOT = os.path.dirname(os.path.dirname(__file__))
UI_ROOT = os.path.join(VALIDATION_ROOT, "validation", "ui")


def _read_ui_file(*parts):
    with open(os.path.join(UI_ROOT, *parts), "r", encoding="utf-8") as handle:
        return handle.read()


def _read_validation_file(*parts):
    with open(os.path.join(VALIDATION_ROOT, *parts), "r", encoding="utf-8") as handle:
        return handle.read()


class ConsumerCatalogReadinessGuardsTests(unittest.TestCase):
    def test_provider_bootstrap_exposes_non_blocking_catalog_probe(self):
        source = _read_ui_file("shared", "utils", "provider-bootstrap.ts")

        self.assertIn("type CatalogDatasetReadinessProbe", source)
        self.assertIn("export async function probeConsumerCatalogDatasetReadiness(", source)
        self.assertIn('status: "ready"', source)
        self.assertIn('status: "timeout"', source)
        self.assertIn("error instanceof Error ? error.message : String(error)", source)

    def test_edc_vm_single_catalog_readiness_uses_longer_default_timeout(self):
        source = _read_ui_file("shared", "utils", "provider-bootstrap.ts")

        self.assertIn("DEFAULT_EDC_VM_SINGLE_CATALOG_READINESS_TIMEOUT_MS = 360_000", source)
        self.assertIn("process.env.UI_CATALOG_READINESS_TIMEOUT_MS", source)
        self.assertIn('adapter === "edc" && topology === "vm-single"', source)

    def test_core_ui_specs_use_catalog_probe_instead_of_failing_before_ui_retries(self):
        expected_specs = [
            ("adapters", "inesdata", "specs", "04-consumer-catalog.spec.ts"),
            ("adapters", "inesdata", "specs", "05-consumer-negotiation.spec.ts"),
            ("adapters", "inesdata", "specs", "05-e2e-transfer-flow.spec.ts"),
            ("adapters", "inesdata", "specs", "06-consumer-transfer.spec.ts"),
            ("adapters", "inesdata", "specs", "07-semantic-virtualization-httpdata.spec.ts"),
            ("adapters", "inesdata", "specs", "09-ai-model-hub-httpdata.spec.ts"),
            ("adapters", "inesdata", "specs", "15-ai-model-external-execution.spec.ts"),
        ]

        for parts in expected_specs:
            source = _read_ui_file(*parts)
            self.assertIn("probeConsumerCatalogDatasetReadiness", source, "/".join(parts))
            self.assertNotIn("await waitForConsumerCatalogDatasetReadiness(", source, "/".join(parts))

    def test_inesdata_ai_model_hub_httpdata_uses_stable_model_catalog_metadata(self):
        source = _read_ui_file("adapters", "inesdata", "specs", "09-ai-model-hub-httpdata.spec.ts")

        self.assertIn("test.setTimeout(aiModelHubHttpDataTimeoutMs())", source)
        self.assertIn("UI_AI_MODEL_HUB_HTTPDATA_TIMEOUT_MS", source)
        self.assertIn('assetType: "machineLearning"', source)
        self.assertIn("...aiModelMetadataAliases(modelPath)", source)
        self.assertIn('contenttype: "application/json"', source)
        self.assertIn('format: "json"', source)
        self.assertIn('proxyBody: "true"', source)

    def test_dataspace_runtime_uses_shared_infrastructure_config_as_fallback(self):
        source = _read_ui_file("shared", "utils", "dataspace-runtime.ts")

        self.assertIn('"deployers", "infrastructure", "deployer.config"', source)
        self.assertIn("infrastructureConfig.KC_INTERNAL_URL", source)
        self.assertIn("infrastructureConfig.KC_URL", source)
        self.assertIn("infrastructureConfig.DS_DOMAIN_BASE", source)

    def test_dataspace_runtime_prefers_generated_public_access_urls(self):
        source = _read_ui_file("shared", "utils", "dataspace-runtime.ts")

        self.assertIn("public_access_urls", source)
        self.assertIn("access_urls", source)
        self.assertIn("UI_RUNTIME_DIR", source)
        self.assertIn("UI_TOPOLOGY", source)
        self.assertIn('"connectors", connectorName, "credentials.json"', source)
        self.assertIn("connector_interface_login", source)
        self.assertIn("connector_management_api", source)
        self.assertIn("connector_protocol_api", source)
        self.assertIn("keycloak_realm", source)
        self.assertIn("keycloak_account", source)
        self.assertIn("publicKeycloakUrlFromConnectorCredentials", source)
        self.assertIn("DS_1_CONNECTORS", source)
        self.assertIn("DS_1_VALIDATION_PAIRS", source)
        self.assertIn("UI_CONNECTOR_PROTOCOL_ADDRESS_MODE", source)

    def test_dataspace_runtime_applies_ingress_proxy_port_to_api_runtime_urls(self):
        source = _read_ui_file("shared", "utils", "dataspace-runtime.ts")

        self.assertIn("PLAYWRIGHT_INGRESS_PROXY_PORT", source)
        self.assertIn("withOptionalIngressPort(", source)
        self.assertIn("const managementBaseUrl = withOptionalIngressPort(", source)
        self.assertIn("const protocolBaseUrl = withOptionalIngressPort(", source)
        self.assertIn("const transferEndpointOverride = withOptionalIngressPort(", source)

    def test_dataspace_runtime_prefers_connector_minio_api_for_transfer_destination(self):
        source = _read_ui_file("shared", "utils", "dataspace-runtime.ts")

        self.assertIn("const credentialMinioApi = optionalUrl(", source)
        self.assertIn("publicAccessUrls.minio_api", source)
        self.assertIn("internalAccessUrls.minio_api", source)
        self.assertIn("function configuredTransferEndpoint(", source)
        self.assertIn("return credentialMinioApi || `${minioProtocol}://${minioHost}`", source)

    def test_dataspace_runtime_uses_internal_minio_service_for_vm_single_edc_transfer(self):
        source = _read_ui_file("shared", "utils", "dataspace-runtime.ts")

        self.assertIn("function vmSingleEdcTransferEndpoint(", source)
        self.assertIn("commonServicesNamespace(deployerConfig)", source)
        self.assertIn('"common-srvs-minio"', source)
        self.assertIn('"9000"', source)
        self.assertIn('adapter === "edc" && activeTopologyFromConfig(deployerConfig) === "vm-single"', source)
        self.assertIn("return vmSingleEdcTransferEndpoint(deployerConfig)", source)

    def test_edc_api_transfer_payload_matches_dashboard_s3_destination_fields(self):
        source = _read_ui_file("shared", "utils", "provider-bootstrap.ts")

        self.assertIn("objectName: transferObjectName", source)
        self.assertIn("accessKeyId: destination.accessKeyId", source)
        self.assertIn("secretAccessKey: destination.secretAccessKey", source)

    def test_edc_api_transfer_wait_uses_topology_aware_timeout(self):
        source = _read_ui_file("shared", "utils", "provider-bootstrap.ts")
        transfer_spec = _read_ui_file("adapters", "edc", "specs", "04-consumer-transfer.spec.ts")
        e2e_spec = _read_ui_file("adapters", "edc", "specs", "05-e2e-transfer-flow.spec.ts")
        transfer_history_page = _read_ui_file("adapters", "edc", "components", "edc-transfer-history.page.ts")

        self.assertIn("export function resolveConsumerTransferActiveTimeoutMs", source)
        self.assertIn('topology === "vm-single"', source)
        self.assertIn("return 300_000", source)
        self.assertIn('topology === "vm-distributed"', source)
        self.assertIn("return 420_000", source)
        self.assertIn("UI_CONSUMER_TRANSFER_ACTIVE_TIMEOUT_MS", source)
        self.assertIn("PIONERA_CONSUMER_TRANSFER_ACTIVE_TIMEOUT_MS", source)
        self.assertIn("Last observed state", source)
        self.assertIn("resolveConsumerTransferActiveTimeoutMs(dataspaceRuntime) + 120_000", transfer_spec)
        self.assertIn("waitForConsumerTransferReadinessForAssetAgreement", e2e_spec)
        self.assertIn("api-ready-history-lagging", e2e_spec)
        self.assertIn("No transfer id was returned by the UI or API readiness probe", e2e_spec)
        self.assertIn("Math.min(remainingMs, 1_000)", transfer_history_page)

    def test_edc_ui_transfer_start_returns_transfer_identifier(self):
        source = _read_ui_file("adapters", "edc", "components", "edc-contracts.page.ts")

        self.assertIn("export type EdcTransferStartResult", source)
        self.assertIn("transferId?: string", source)
        self.assertIn('responseBody?.["@id"]', source)
        self.assertIn("transferType: selectedTransferType", source)

    def test_edc_dashboard_transfer_history_handles_async_pagination_state(self):
        transfer_view = _read_validation_file(
            "adapters",
            "edc",
            "overlays",
            "dashboard",
            "projects",
            "dashboard-core",
            "transfer",
            "src",
            "transfer-history-view",
            "transfer-history-view.component.ts",
        )
        pagination = _read_validation_file(
            "adapters",
            "edc",
            "overlays",
            "dashboard",
            "projects",
            "dashboard-core",
            "src",
            "lib",
            "common",
            "pagination",
            "pagination.component.ts",
        )

        self.assertIn("new BehaviorSubject<TransferProcess[]>([])", transfer_view)
        self.assertIn("setCurrentPageTransferProcesses", transfer_view)
        self.assertIn("shareReplay({ bufferSize: 1, refCount: true })", transfer_view)
        self.assertIn("this.pageTransferProcessesSubject.next(pageItems ?? [])", transfer_view)
        self.assertIn("const items = this.items ?? []", pagination)
        self.assertNotIn("this.items!.slice", pagination)

    def test_edc_dashboard_ontology_services_use_proxy_api_and_public_links(self):
        service_paths = [
            (
                "adapters",
                "edc",
                "overlays",
                "dashboard",
                "src",
                "app",
                "services",
                "ontology.service.ts",
            ),
            (
                "adapters",
                "edc",
                "overlays",
                "dashboard",
                "projects",
                "dashboard-core",
                "assets",
                "src",
                "services",
                "ontology.service.ts",
            ),
        ]

        for parts in service_paths:
            source = _read_validation_file(*parts)
            self.assertIn("ontologyPublicUrl", source)
            self.assertIn("ontologyApiBaseUrl", source)
            self.assertIn("this.runtime.ontologyPublicUrl || this.runtime.ontologyUrl", source)
            self.assertIn("this.runtime.ontologyUrl || this.runtime.ontologyPublicUrl", source)
            self.assertIn("`${this.ontologyApiBaseUrl}/dataset/api/v2/vocabulary/list`", source)

    def test_minio_runtime_prefers_topology_scoped_connector_credentials(self):
        source = _read_ui_file("shared", "utils", "minio-console-runtime.ts")

        self.assertIn("UI_RUNTIME_DIR", source)
        self.assertIn("UI_TOPOLOGY", source)
        self.assertIn('"connectors", connectorName, "credentials.json"', source)
        self.assertIn("credentials-connector-${connectorName}.json", source)

    def test_dataspace_runtime_keeps_portal_urls_trailing_slash(self):
        source = _read_ui_file("shared", "utils", "dataspace-runtime.ts")

        self.assertIn("function optionalPortalUrl", source)
        self.assertIn("return withTrailingSlash(value.trim())", source)
        self.assertIn('"/inesdata-connector-interface/"', source)
        self.assertIn("connectorPublicPortalBaseUrl(adapter, publicAccessUrls)", source)

    def test_vm_distributed_ui_runtime_uses_public_protocol_addresses_only_as_default(self):
        source = _read_ui_file("shared", "utils", "dataspace-runtime.ts")

        self.assertIn('topology === "vm-distributed"', source)
        self.assertIn('return "public"', source)
        self.assertIn("deployerConfig.UI_CONNECTOR_PROTOCOL_ADDRESS_MODE", source)
        self.assertIn("deployerConfig.CONNECTOR_PROTOCOL_ADDRESS_MODE", source)

    def test_edc_dashboard_bridge_normalizes_catalog_request_runtime_addresses(self):
        source = _read_ui_file("shared", "utils", "edc-dashboard-route-bridge.ts")

        self.assertIn("normalizedCatalogRequestData", source)
        self.assertIn("counterPartyFromDashboardPath", source)
        self.assertIn("/edc-dashboard-api/connectors/", source)
        self.assertIn("counterParty.protocolBaseUrl", source)
        self.assertIn('payload["@type"]', source)
        self.assertIn('"CatalogRequest"', source)
        self.assertIn("payload.querySpec = defaultQuerySpec(payload.querySpec)", source)
        self.assertIn("UI_EDC_CATALOG_REQUEST_COMPAT_ALIASES", source)
        self.assertIn('delete payload["edc:counterPartyAddress"]', source)
        self.assertIn("EDC_COUNTER_PARTY_ADDRESS_IRI", source)
        self.assertIn("dataspace-protocol-http", source)

    def test_edc_dashboard_navigation_preserves_public_path_prefixes(self):
        source = _read_ui_file("adapters", "edc", "components", "edc-dashboard.page.ts")

        self.assertIn("function dashboardAbsolutePathUrl", source)
        self.assertIn('const marker = "/edc-dashboard"', source)
        self.assertIn("const publicPrefix = base.pathname.slice(0, markerIndex)", source)
        self.assertIn("base.pathname = `${publicPrefix}${path}`", source)
        self.assertIn("function navigationItemTextPattern", source)
        self.assertIn("filter({ hasText: sectionPattern })", source)
        self.assertIn("[a-z0-9_]+", source)
        self.assertNotIn('new RegExp(`(?:^|\\\\s)${escapeRegExp(sectionName)}', source)

    def test_edc_ml_assets_uses_configurable_page_size_before_polling_cards(self):
        source = _read_ui_file("adapters", "edc", "components", "edc-ml-components.page.ts")

        self.assertIn("UI_EDC_ML_ASSETS_PAGE_SIZE", source)
        self.assertIn("preferLargestPageSize", source)
        self.assertIn("scanRenderedPagesForAsset", source)
        self.assertIn("currentPageLabel", source)
        self.assertIn("function nowMs", source)
        self.assertIn("performance.now", source)
        self.assertIn("assetText(assetId)", source)

    def test_edc_ml_browser_search_contract_includes_asset_ids_and_visible_metadata(self):
        service = os.path.join(
            VALIDATION_ROOT,
            "adapters",
            "edc",
            "sources",
            "dashboard",
            "DataDashboard",
            "src",
            "app",
            "services",
            "dashboard-ml-browser.service.ts",
        )
        with open(service, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("(asset.id || '').toLowerCase().includes(term)", source)

        browser_spec = _read_ui_file("adapters", "edc", "specs", "11-ai-model-browser.spec.ts")
        self.assertIn("modelName: `EDC AI Model Browser sentiment model ${modelAssetId}`", browser_spec)
        self.assertIn("modelName: `EDC AI Model Browser forecast model ${comparisonAssetId}`", browser_spec)

        daimo_spec = _read_ui_file("adapters", "edc", "specs", "14-ai-model-daimo-vocabulary.spec.ts")
        self.assertIn("modelName: `EDC AI Model Hub DAIMO metadata model ${assetId}`", daimo_spec)
        self.assertIn("await mlAssetsPage.openDetails(assetId)", daimo_spec)
        self.assertIn('page.locator("app-ml-asset-details-modal")', daimo_spec)

    def test_ai_model_specs_build_model_urls_from_public_model_server_base(self):
        helper = _read_ui_file("shared", "utils", "model-server-url.ts")
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL", helper)
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_BASE_URL", helper)
        self.assertIn("UI_AI_MODEL_HUB_MODEL_SERVER_BASE_URL", helper)
        self.assertIn("VM_COMMON_HTTP_URL", helper)
        self.assertIn("UI_TOPOLOGY", helper)
        self.assertIn("vm-distributed", helper)
        self.assertIn("UI_DS_DOMAIN", helper)
        self.assertIn("org1.${domain}", helper)
        self.assertIn("model-server.${namespace}.svc.cluster.local", helper)
        self.assertIn("export function modelServerBaseUrlFromUrl", helper)

        expected_specs = [
            ("adapters", "inesdata", "specs", "09-ai-model-hub-httpdata.spec.ts"),
            ("adapters", "inesdata", "specs", "11-ai-model-browser.spec.ts"),
            ("adapters", "inesdata", "specs", "12-ai-model-execution.spec.ts"),
            ("adapters", "inesdata", "specs", "13-ai-model-benchmarking.spec.ts"),
            ("adapters", "inesdata", "specs", "15-ai-model-external-execution.spec.ts"),
        ]
        for parts in expected_specs:
            source = _read_ui_file(*parts)
            self.assertIn("modelServerUrlForPath", source, "/".join(parts))

    def test_edc_ai_model_assets_keep_model_base_url_separate_from_inference_path(self):
        helper = _read_ui_file("shared", "utils", "model-server-url.ts")
        edc_fixtures = _read_ui_file("adapters", "edc", "utils", "edc-component-fixtures.ts")

        self.assertIn("modelServerBaseUrlFromUrl", helper)
        self.assertIn("parsed.pathname.endsWith(normalizedPath)", helper)
        self.assertIn("modelServerBaseUrlFromUrl(modelUrl, modelPath)", edc_fixtures)
        self.assertIn('"daimo:inference_path": inferencePath', edc_fixtures)
        self.assertIn('"daimo:license": "Apache-2.0"', edc_fixtures)
        self.assertIn('"daimo:language": ["en"]', edc_fixtures)
        self.assertIn('"daimo:datasets": ["validation-controlled"]', edc_fixtures)
        self.assertIn('"daimo:base_model": "controlled-httpdata"', edc_fixtures)
        self.assertIn('proxyPath: "true"', edc_fixtures)

    def test_edc_ai_model_execution_specs_skip_when_model_server_is_disabled(self):
        edc_config = _read_ui_file("playwright.edc.config.ts")
        self.assertIn("UI_AI_MODEL_HUB_MODEL_SERVER_DEMO", edc_config)
        self.assertIn("adapters/edc/specs/12-ai-model-execution.spec.ts", edc_config)
        self.assertIn("adapters/edc/specs/13-ai-model-benchmarking.spec.ts", edc_config)
        self.assertIn("adapters/edc/specs/15-ai-model-external-execution.spec.ts", edc_config)

        expected_specs = [
            ("adapters", "edc", "specs", "12-ai-model-execution.spec.ts"),
            ("adapters", "edc", "specs", "13-ai-model-benchmarking.spec.ts"),
            ("adapters", "edc", "specs", "15-ai-model-external-execution.spec.ts"),
        ]
        for parts in expected_specs:
            source = _read_ui_file(*parts)
            self.assertIn("UI_AI_MODEL_HUB_MODEL_SERVER_DEMO", source, "/".join(parts))
            self.assertIn("UI_AI_MODEL_HUB_MODEL_SERVER_COVERAGE_STATUS", source, "/".join(parts))
            self.assertIn("UI_AI_MODEL_HUB_MODEL_SERVER_SKIP_REASON", source, "/".join(parts))

    def test_inesdata_ai_model_benchmarking_ui_is_explicit_demo(self):
        config = _read_ui_file("playwright.inesdata.config.ts")

        self.assertIn("UI_AI_MODEL_HUB_BENCHMARKING_DEMO", config)
        self.assertIn("aiModelHubBenchmarkingDemo", config)
        self.assertIn(
            "aiModelHubHttpDataDemo && aiModelHubModelServerDemo && aiModelHubBenchmarkingDemo",
            config,
        )

    def test_edc_asset_filter_searches_jsonld_dataset_ids(self):
        connector_filter = os.path.join(
            VALIDATION_ROOT,
            "adapters",
            "edc",
            "sources",
            "connector",
            "connector",
            "src",
            "main",
            "java",
            "com",
            "pionera",
            "assetfilter",
            "filter",
            "AssetFilterController.java",
        )
        final_connector_filter = connector_filter.replace(
            os.path.join("sources", "connector", "connector"),
            os.path.join("sources", "connector", "final-connector"),
        )

        for source_path in [connector_filter, final_connector_filter]:
            with open(source_path, "r", encoding="utf-8") as handle:
                source = handle.read()
            self.assertIn('containsValue(extractValues(dataset, "@id"), q)', source)
            self.assertIn('containsValue(extractValues(dataset, "id"), q)', source)
            self.assertIn("buildFilterResponse", source)
            self.assertIn('firstQueryValue(queryParams, "responseShape")', source)
            self.assertIn('"assets".equalsIgnoreCase(shape)', source)
            self.assertIn('"assetList".equalsIgnoreCase(shape)', source)
            self.assertIn("buildAssetList", source)
            self.assertIn("toDashboardAsset", source)

    def test_inesdata_playwright_suite_includes_minio_ops_by_default(self):
        source = _read_ui_file("playwright.inesdata.config.ts")

        self.assertIn("UI_MINIO_OPS_DEMO", source)
        self.assertIn("adapters/inesdata/specs/06b-minio-bucket-visibility.spec.ts", source)

    def test_provider_bootstrap_publishes_storage_type_metadata(self):
        source = _read_ui_file("shared", "utils", "provider-bootstrap.ts")

        self.assertIn("const dataAddress =", source)
        self.assertIn("const dataAddressType =", source)
        self.assertIn("const storageMetadata =", source)
        self.assertIn('edc: "https://w3id.org/edc/v0.0.1/ns/"', source)
        self.assertIn("storageType: dataAddressType", source)
        self.assertIn('"edc:dataAddressType": dataAddressType', source)
        self.assertIn('"https://w3id.org/edc/v0.0.1/ns/dataAddressType": dataAddressType', source)
        self.assertIn("...storageMetadata", source)
        self.assertIn("...(options.properties || {})", source)


if __name__ == "__main__":
    unittest.main()
