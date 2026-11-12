# 51. STICS Ontology Hub: deployment, operation and known limits

This document describes the Ontology Hub that STICS partners use, how it is
deployed, what was wrong with it and how it was fixed, and how to operate it
without breaking it. It was written after the November 2026 clean-up of the
hub.

Every statement was checked against the running hub or the upstream source
(`ProyectoPIONERA/Ontology-Hub`, commit `94cb600`, the commit deployed on both
hubs). Statements that were not checked are marked **(not verified)**.

## 1. Which hub is the official one

| URL | What it is | Role |
| --- | --- | --- |
| `https://lov4ds.stics.linkeddata.es/dataset` | Manually managed Docker Compose deployment on its own VM. Holds the STICS vocabularies `citser` and `md`. | **Official STICS Ontology Hub.** |
| `https://ontology-hub-demo.dev.linkeddata.es/dataset` | `components/demo-ontology-hub` in the k3s cluster. Data in an `emptyDir`, no backup, no vocabularies. | Old URL. Its ingress answers **HTTP 308** and sends every request to the official hub, keeping path and query string. |

The demo hub was first given to partners as the official URL, but it was an
empty and non-persistent replica. Instead of consolidating the data into k3s,
the maintained hub was repaired and the old URL was redirected to it.

A `308` (not `301`/`302`) keeps the HTTP method, so `POST` calls such as
`vocabulary/artifacts/shapes` keep working through the redirect. The redirect
response carries `Access-Control-Allow-Origin: *`, so browser clients that
still use the old URL are not blocked.

### The redirect

It is one annotation on the ingress `demo-ontology-hub` (namespace
`components`), using a server snippet. This works because the cluster's
ingress-nginx has `allow-snippet-annotations: true`.

```text
nginx.ingress.kubernetes.io/server-snippet: return 308 https://lov4ds.stics.linkeddata.es$request_uri;
```

Roll it back:

```bash
kubectl -n components annotate ingress demo-ontology-hub nginx.ingress.kubernetes.io/server-snippet-
```

> The annotation lives **only in the cluster**, not in the Helm chart. A
> `helm upgrade` of `demo-ontology-hub` would remove it and the old URL would
> serve the empty demo hub again. Re-apply it, or move it into the chart
> values (`.Values.ingress.annotations`, which the chart template already
> supports), if that release is ever upgraded.

Check it (the cluster ingress uses an internal certificate, hence `-k`):

```bash
curl -sk -o /dev/null -w '%{http_code} -> %{redirect_url}\n' \
  --resolve ontology-hub-demo.dev.linkeddata.es:443:<ingress-ip> \
  https://ontology-hub-demo.dev.linkeddata.es/dataset/about
# 308 -> https://lov4ds.stics.linkeddata.es/dataset/about
```

### What the connector interface needs from the hub

The connector web interface (`ontology.service.ts`) uses only
`GET vocabulary/list` and `POST vocabulary/artifacts/shapes`, plus links shown
in the browser. The STICS interface and the partner guide leave `ONTOLOGY_URL`
empty, so partners do not depend on the old URL unless they set it themselves.
The Postman toolbox variable `ontologyHubUrl` still points to the old URL and
works through the redirect.

## 2. How the official hub is deployed

| Item | Value |
| --- | --- |
| Compose project | `/var/www/Ontology-Hub`, file `docker-compose-prod.yml`, variables in `.env` and `.env.production` |
| Containers | `lov_server` (Node app **and** an embedded Jena Fuseki 1.1.1), `mongodb`, `elasticsearch` |
| Data | Named volumes for MongoDB (`ontology-hub_mongodb_data`), Elasticsearch (`ontology-hub_elastic_data`) and the app folder (`ontology_hub_folder`, mounted at `/app`) |
| Runtime | `NODE_ENV=production`, restart policy `unless-stopped` |
| TLS | Terminated upstream of the VM. The VM's nginx only listens on port 80. |

Two points matter for operation:

- `/app` is a volume. The files `config/config.js`, the views and
  `public/img/` **live in the volume**. Changing the image does not change
  them, and editing them needs only a container restart.
- `.env` and `.env.production` are read when the container is **created**.
  `docker restart` does not reload them. After editing them use:

  ```bash
  cd /var/www/Ontology-Hub
  docker compose -f docker-compose-prod.yml up -d --no-deps lov_server
  ```

## 3. What was wrong and how it was fixed

| Symptom | Cause | Fix |
| --- | --- | --- |
| Search returned errors (`ECONNREFUSED`) | Under `NODE_ENV=production` the hub reads the `production` block of `config/config.js`, a copy of upstream `config.example.js` taken at image build. That block has `es.host: 'localhost'` and `lov: 'http://localhost:3333'` written literally, so `.env` was ignored. A plain restart does not fix it. | The block now reads `ELASTIC_SEARCH_HOST`, `ELASTIC_SEARCH_USER`, `ELASTIC_SEARCH_PASSWORD`, `SELF_HOST_URL`, `SCRIPTS_PATH`, `PATTERN_PATHS` and `PYTHON_PATTERNS_PATH`. The container was recreated. |
| The `.n3` download link of every vocabulary pointed to `http://localhost:3333/...` | Same cause: `SELF_HOST_URL` was `http://localhost:3333`. | `SELF_HOST_URL=https://lov4ds.stics.linkeddata.es` in `.env` and `.env.production`. |
| Elasticsearch had no terms, so term search was empty | Upstream indexes terms **only** while a vocabulary is created through the UI (`createVocab` in `app/controllers/vocabularies.js`). Editing a vocabulary reindexes only the vocabulary document, and no reindex tool exists upstream. | Reindex script, section 5. Result: 116 terms (39 classes, 67 properties, 2 vocabularies; see the limits in section 7). |
| Licence empty | The imported records had no licence. | Both ontologies declare CC BY 4.0 in their source files. It was set on both. |
| Review author was a placeholder (`yourName`) | The hub seeds an agent called `yourName`. | Reviewer set to María Poveda-Villalón. The seeded agent was **renamed** "Ontology Hub administrator" instead of deleted (section 6). |
| Home page bubble chart empty | The chart reads the MongoDB collection `statvocabularies`. The UI import never fills it. | Section 5, `statsonevocab`. Two bubbles now render (`citser`, `md`). |
| Dead paths for scripts and patterns (`/home/user/...`) | Same hardcoded production block. They would break creating vocabularies from the UI. | Now read from the environment variables listed above. |
| Footer and names showed only OEG/PIONERA, "Lov" and "4DS" | Upstream branding, plus `app_name` and `app_name_shorcut` in the production block. | STICS overlay, section 8. |

Backups of `config.js` and `footer.jade` made before each change sit next to
the originals inside the volume (`*.bak.<timestamp>`).

## 4. Backups

A daily job at 03:15 backs up MongoDB, Elasticsearch and the version files:

| Item | Value |
| --- | --- |
| Script (on the hub VM) | `/home/stics2/ontology-hub-tools/backup_ontology_hub.sh` |
| Schedule | user crontab, `15 3 * * *` |
| Output and log | `/home/stics2/backups/ontology-hub/`, log `backup.log` |
| Retention | 7 days |

Weak points, to decide with the project leads:

- The backups are on **the same disk** as the data, and that disk was at 85 %
  when this was written. Copy them somewhere else.
- A restore **has not been rehearsed (not verified)**. Do one on a scratch VM
  before relying on the backups.

Check that the job is running:

```bash
tail -n 20 ~/backups/ontology-hub/backup.log
ls -lh ~/backups/ontology-hub/
```

## 5. Operating the hub

### Adding or changing a vocabulary

The UI form *Create Vocabulary from Ontology Repository* (`/edition`) reads the
repository's root `.config` file through the unauthenticated GitHub API (public
repositories, default branch only, rate limit 60 requests per hour).

Known problem with the two STICS repositories (`Ontology-Citizens-Services`
and `Ontology-Metadata`): their `.config` declares `shapes = ./shacl-shapes`
and `examples = ./rdf-examples`, but the folders are named `shapes` and
`examples`. The hub then aborts the save with HTTP 500 "Cannot access artifact
folder" and **leaves a half-created vocabulary** (a MongoDB document with
`versions: []`, partial files under `/app/versions/<id>`, nothing in
Elasticsearch). A retry is blocked by "This vocabulary already exists". Fix the
`.config` in the repository (it needs the repository owners' agreement) or
correct the read-only shapes and examples URL fields before saving. After a
failed import, remove that MongoDB document and its `versions/<id>` folder.

After **every** vocabulary created or changed, run both steps:

1. **Bubble chart** (idempotent upsert of that vocabulary's statistics):

   ```bash
   docker exec lov_server /app/scripts/bin/statsonevocab /app/scripts/lov.config <vocabulary-uri>
   ```

   `<vocabulary-uri>` is the URI exactly as stored in the MongoDB `vocabularies`
   collection.

2. **Search index** with
   [`docs/examples/ontology_hub_reindex_vocabs.js`](./examples/ontology_hub_reindex_vocabs.js).
   It repeats the indexing block of `createVocab`, never writes to MongoDB and
   never deletes anything. It is idempotent because it uses the same document
   ids. It is a dry run unless `--apply` is given.

   ```bash
   docker cp docs/examples/ontology_hub_reindex_vocabs.js lov_server:/tmp/reindex_vocabs.js
   docker exec -e NODE_PATH=/app/node_modules lov_server node /tmp/reindex_vocabs.js            # dry run
   docker exec -e NODE_PATH=/app/node_modules lov_server node /tmp/reindex_vocabs.js --apply    # all vocabularies
   docker exec -e NODE_PATH=/app/node_modules lov_server node /tmp/reindex_vocabs.js --apply citser
   ```

   Without `NODE_PATH` the script fails with `MODULE_NOT_FOUND`.

### Commands that must NOT be run

All of them ship in `/app/scripts/bin/` or `setup/` and look useful:

| Command | Why not |
| --- | --- |
| `stats` | Drops `statvocabularies`, `statlanguages` and `stattags` before rebuilding them. The bubble chart would disappear. |
| `create-index` | Writes to an orphan `lov` index and has hardcoded development paths. It does not feed the index the application searches. |
| `mongo2rdf`, `index-lov` | They do not fill the SPARQL endpoint (checked by inspecting the jars on the hub VM). Do not expect them to. |

## 6. Seed data is re-imported on every start

The container entrypoint `setup/start.sh` runs `setup/importToMongo.sh` on
**every** start. It runs `mongoimport` in insert mode for `agents.json`,
`users.json`, languages and `stattags`, with fixed `_id` values. Existing
documents are skipped (`E11000`), but a **deleted seed document comes back**.

Consequences:

- Do not delete the seeded agent `yourName` (`_id 6655debc246d4eb07e1808fb`).
  It reappears after the next restart. Rename it in place, as was done.
- Do not delete the seed administrator user (`admin@gmail.com`). It would be
  recreated with the upstream default password. The password of the existing
  document was already changed. After any recreate, check that the default
  login still fails.

## 7. Known limits and open decisions

| Item | Status |
| --- | --- |
| **SPARQL endpoint** (`/dataset/sparql`) | It answers but is **empty** (0 triples). Fuseki loads its dataset only when the TDB files do not exist, so it serves a frozen snapshot from image build time. No script in the hub refills it. Decision needed: publish SPARQL or not. |
| **Shared properties** | Term documents use `base64(uri)` as id, not scoped to a vocabulary. The ten Dublin Core, VANN and OWL properties used by both ontologies are indexed once (67 properties instead of 77). This is an upstream design limit. |
| **Bubble chart** | With two vocabularies it shows two large circles, not the mosaic of the public LOV. |
| `term/autocomplete` | Returns `illegal_argument_exception`. The connector interface does not use it. Not investigated. |
| **Backups** | Same disk, restore not rehearsed (section 4). |
| **Demo hub in k3s** | Still deployed, only redirected. Decide whether to remove it. |
| **Image rebuild** | `config.example.js` upstream still has the broken production defaults. The overlay in this repository fixes them (section 8), but only if the image is built from the overlaid source. |

## 8. STICS branding (overlay)

The footer (STICS funding text and banner, PIONERA kept as the origin of the
software), the application names (`Ontology Hub` / `STICS`) and the production
configuration are versioned in
[`adapters/inesdata/overlays/ontology-hub/`](../adapters/inesdata/overlays/ontology-hub/README.md).
That README explains how the overlay is applied to a build and how it was copied
into the running hub by hand, with backups and rollback.

The "Contact" link in the footer points to `mpoveda@fi.upm.es` only. The
upstream link also listed the original LOV authors. That address still has to be
confirmed by the project lead **(not verified)**.

## 9. Quick health check

```bash
U=https://lov4ds.stics.linkeddata.es
curl -s $U/dataset | grep -o '<title>[^<]*</title>'                          # Ontology Hub
curl -s $U/dataset | grep -c '4DS'                                           # 0
curl -s "$U/dataset/api/v2/term/search?q=residence" | head -c 120            # total_results >= 1
curl -s "$U/dataset/api/v2/vocabulary/list"                                  # citser, md
curl -s -o /dev/null -w '%{http_code}\n' $U/img/stics-funding-acknowledgement.png   # 200
```

The home page must show two bubbles. After any restart, also confirm that the
search still works and the home page has no JavaScript errors.

## References

- Upstream source: `https://github.com/ProyectoPIONERA/Ontology-Hub`, commit `94cb600`
  (`app/controllers/vocabularies.js`, `setup/start.sh`, `setup/importToMongo.sh`,
  `config/config.example.js`, `app/models/statvocabulary.js`, `app/views/index.jade`).
- [11. Ontology Hub validation](./11_ontology_hub_validation.md) (ES): how the hub is covered by the validation suites.
- [Overlay README](../adapters/inesdata/overlays/ontology-hub/README.md).
