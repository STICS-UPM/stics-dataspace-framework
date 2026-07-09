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
| `config/config.example.js` | `app_name_shorcut` (development block): `Pionera` → `STICS`. This becomes `config.js` at image build time (`Dockerfile` copies it verbatim). |
| `app/views/layout/footer.jade` | Replaces the PIONERA (Spain) funding acknowledgment with the STICS (Slovakia, NextGenerationEU) one, and reduces the PIONERA credit to a short "Powered by PIONERA" line. |

## Already-running deployment

The currently-running `demo-ontology-hub` deployment in the `components`
namespace was patched directly with two `ConfigMap`s
(`ontology-hub-config-override`, `ontology-hub-footer-override`) mounted
over the equivalent paths inside the container, so the fix is live without
needing to rebuild or redeploy the image. If that image is ever rebuilt
from a freshly-synced source with this overlay applied, the `ConfigMap`
mounts become redundant (but harmless — they mount the same content either
way) and can be removed.
