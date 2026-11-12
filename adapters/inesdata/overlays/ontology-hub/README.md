# Ontology Hub STICS overlay

Versioned STICS-specific customizations applied at build time onto the
synced upstream source (`https://github.com/ProyectoPIONERA/Ontology-Hub`,
checked out at `adapters/inesdata/sources/Ontology-Hub`, git-ignored in this
repo since it is a separate upstream checkout, not framework code).

Without this overlay, a fresh `git clone` of that upstream repo — and any
image rebuilt from it — reverts to PIONERA's own branding and funding
acknowledgment, since neither is parameterized upstream.

## Apply manually

```bash
cd adapters/inesdata
bash scripts/apply_ontology_hub_overlay.sh --apply
```

Run this after (re-)cloning the upstream source and before building the
`ontology-hub:local` image, so the built image already contains these files.

## Files

| File | Change |
| --- | --- |
| `config/config.example.js` | Development block: `app_name_shorcut` `Pionera` → `STICS`. Production block: reads the same environment variables as the development block (Elasticsearch host and credentials, `SELF_HOST_URL`, scripts and pattern paths) instead of the upstream hardcoded `localhost` and `/home/user/...` values, and sets `app_name` to `Ontology Hub` and `app_name_shorcut` to `STICS`. This becomes `config.js` at image build time (`Dockerfile` copies it verbatim). |
| `app/views/layout/footer.jade` | STICS (Slovakia, NextGenerationEU) funding acknowledgment and banner first. The PIONERA origin of the software stays below it as a credit strip (Ontology Engineering Group logo, short English statement and PIONERA funding logos). The contact link points only to the STICS contact, not to the original LOV authors. |
| `public/img/stics-funding-acknowledgement.png` | STICS funding banner shown in the footer. |
| `public/img/pionera-funding-label.png` | PIONERA funding logos shown in the credit strip. Same file as `docs/funding_label.png`. |

## Production deployments

The STICS Ontology Hub that partners use is `https://lov4ds.stics.linkeddata.es/dataset`.
It is a manually managed Docker Compose deployment that runs the upstream
image, with `/app` (including `config/config.js` and the views) in a named
volume. A new image or this overlay therefore does not change it by itself:
the overlay files have to be copied into the volume by hand.

The branding change of 2026-11-11 was applied that way:

1. Back up `app/views/layout/footer.jade` and `config/config.js` next to the
   originals (`*.bak.<timestamp>`).
2. Copy `footer.jade` and the two images into the container (`app/views/layout/`
   and `public/img/`).
3. Set `app_name` and `app_name_shorcut` in the **production** block of
   `config/config.js`.
4. `docker restart` the `lov_server` container. Views and `config.js` live in
   the volume, so a restart is enough.

To roll back, copy the `.bak` files over the current ones and restart again.

The earlier `demo-ontology-hub` deployment in the `components` namespace of
the k3s cluster no longer serves users: its ingress answers `308` and sends
every request to the URL above. It had been patched with two `ConfigMap`s
(`ontology-hub-config-override`, `ontology-hub-footer-override`) that mount
the same footer and configuration. They are not needed anymore, but they are
harmless while that deployment exists.
