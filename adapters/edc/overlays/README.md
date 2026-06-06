# EDC RDF validation overlays

Versioned overlays applied at build time onto synced upstream sources (`asset-filter-template` connector and `DataDashboard`).

## Apply manually

```bash
cd adapters/edc
bash scripts/apply_overlays.sh --apply --target connector   # Java extensions + Gradle patches
bash scripts/apply_overlays.sh --apply --target dashboard   # Ontology Hub UI route + runtime parity
bash scripts/apply_overlays.sh --apply --target all
```

Build scripts invoke this automatically after source sync:

- `scripts/build_image.sh --apply` → connector overlay
- `scripts/build_dashboard_image.sh --apply` → dashboard overlay

## Connector modules

| Module | Role |
|--------|------|
| `edc-rdf-validator` | `POST /management/validation/rdf_asset` (asset-create RDF test) |
| `edc-rdf-validator-dataplane` | SHACL validation in dataplane + callback `/public/validation/rdf` |
| `edc-rdf-validation-api` | Mirror `POST /public/validation/rdf-mirror` + Management API transformer |

Packages: `org.eclipse.edc.validation.rdf.*` — no Inesdata names in the port.

## Persistence keys

- **Write:** `edc.rdf.validation.*` in `edc_transfer_process.private_properties` (JSONB merge).
- **Read (legacy):** transformer, persistence loader, and dashboard table also accept `inesdata.rdf.validation.*` for existing rows.

## Production

1. Rebuild connector image: `bash scripts/build_image.sh --apply --sync-subdir asset-filter-template`
2. Rebuild dashboard image when UI overlay changes: `bash scripts/build_dashboard_image.sh --apply`
3. Deploy via existing Helm/deployer flow; do not compile on production nodes if using registry images.

## Operational notes

- **Same data space:** RDF validation expects provider/consumer MinIO in the same space (`AmazonS3-PUSH` flows).
- **CORS:** Ontology Hub must allow the EDC dashboard origin for `/ontologies` and asset-create ontology pickers.
- **Dashboard UI:** the dashboard overlay adds the `Ontologies` menu entry, route, runtime `ontologyUrl` support, and a read-only Ontology Hub browser.
- **Ingress:** Provider dataplane must reach consumer `POST /public/validation/rdf-mirror` (configure `rdfValidationCallbackUrl` on transfer create — dashboard sets this automatically for push transfers).
- **SQL:** Overlay adds `transfer-process-store-sql`, transaction datasource, and PostgreSQL driver to `final-connector` so validation snapshots persist when `edc.datasource.default.*` is configured (see `deployers/edc/connector/config/connector-configuration.properties.tpl`).

## Optional compile check (dev/CI)

```bash
cd adapters/edc
bash scripts/apply_overlays.sh --apply --target connector
cd sources/connector
./gradlew :final-connector:shadowJar -x test
```
