# Production Readiness (What is Missing)

This project is a local development scaffold. The extensions are functional, but the runtime is not production-ready. Below is a concrete checklist of what is missing and why it matters.

---

## 1) Persistence and state

Current state:
- In-memory stores for assets, policies, agreements, transfers, and EDRs
- Contract definition sequence allocator persists to local file (`./.state/contract-sequences.json`)

Production requirement:
- Database-backed stores (Postgres or equivalent)
- Durable transfer state and retry
- Persistent EDR cache
- Shared/transactional sequence source for contract IDs in multi-instance deployments

## 2) Security and identity

Current state:
- Mock IAM
- No OAuth/OIDC for management or protocol APIs

Production requirement:
- OAuth2/OIDC integration (Keycloak or equivalent)
- Token validation, audience checks, and scopes
- Management API protected by auth

## 3) Vault and key management

Current state:
- Seeded keys inside `SeedVaultExtension`

Production requirement:
- External vault (HashiCorp, AWS KMS, Azure Key Vault)
- Key rotation and secret injection

## 4) Data plane and storage

Current state:
- HTTP proxy only
- No cloud storage integration

Production requirement:
- Real data plane runtime
- S3, Azure Blob, MinIO, or custom storage
- TLS everywhere

## 5) Observability

Current state:
- Console logs only

Production requirement:
- Centralized logging
- Metrics and tracing
- Alerting on failed transfers

## 6) API contracts and validation

Current state:
- No strict schema validation on inference payloads
- Dev auth in UI
- Slash-style technical asset IDs (`user/model`) cause path-parameter lookup issues on `/v3/assets/{id}` in this runtime

Production requirement:
- Validate inference schema
- Consistent error codes
- Pagination and rate limits
- Real auth in UI
- Adopt a path-safe technical ID format (for example `user--model`) and keep slash style as display metadata only

## 7) Deployment

Current state:
- Single-machine, local ports

Production requirement:
- Containers and orchestration
- Environment-specific configs
- Load balancing
- Secrets management

## 8) Summary

The filtering and inference extensions are compatible with production runtimes, but they depend on secure management APIs, persistent stores, a real IAM stack, and a hardened data plane. Once those are in place, the extensions can be deployed without major redesign.
