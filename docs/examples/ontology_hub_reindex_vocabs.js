// Rebuild the Elasticsearch index of an Ontology Hub from MongoDB + the stored version files.
// It repeats exactly the indexing block of createVocab() in app/controllers/vocabularies.js
// (vocabulary doc + one doc per class/property/datatype/individual) but never writes to MongoDB
// and never deletes anything. Idempotent: documents use the same ids, so re-running overwrites.
//
// usage (inside the lov_server container, see docs/51_stics_ontology_hub.md):
//   NODE_PATH=/app/node_modules node /tmp/reindex_vocabs.js            -> dry run
//   NODE_PATH=/app/node_modules node /tmp/reindex_vocabs.js --apply    -> write to ES
//   NODE_PATH=/app/node_modules node /tmp/reindex_vocabs.js --apply citser   -> only that prefix
process.chdir("/app");
const fs = require("fs");
const path = require("path");
const mongoose = require("mongoose");

const env = process.env.NODE_ENV || "development";
const config = require("/app/config/config")[env];
require("/app/app/models/vocabulary");
const Vocabulary = mongoose.model("Vocabulary");
const { ElasticService } = require("/app/app/elastic/index");
const rdfExtractor = require("/app/app/services/rdfExtractor");
const lovWrapper = require("/app/app/services/lovWrapper");

const APPLY = process.argv.includes("--apply");
const ONLY = process.argv.slice(2).find((a) => !a.startsWith("--"));
const CATEGORY = { classes: "class", properties: "property", datatypes: "datatype", individuals: "individual" };

function latestVersionFile(dir) {
  if (!fs.existsSync(dir)) return null;
  const files = fs.readdirSync(dir).filter((f) => f.endsWith(".n3") && fs.statSync(path.join(dir, f)).isFile());
  files.sort();
  return files.length ? path.join(dir, files[files.length - 1]) : null;
}

(async () => {
  console.log(`NODE_ENV=${env} mode=${APPLY ? "APPLY" : "DRY-RUN"}`);
  await mongoose.connect(config.db);
  const vocabs = await Vocabulary.find(ONLY ? { prefix: ONLY } : {});
  let total = 0;
  for (const vocab of vocabs) {
    const file = latestVersionFile("./versions/" + vocab._id);
    if (!file) { console.log(`[skip] ${vocab.prefix}: no .n3 under versions/${vocab._id}`); continue; }
    const extracted = await rdfExtractor.extractAllTerms(file);
    const vocabDoc = vocab.toObject();
    const counts = Object.keys(CATEGORY).map((c) => `${c}=${(extracted[c] || []).length}`).join(" ");
    console.log(`[${APPLY ? "index" : "plan"}] ${vocab.prefix} (${vocab._id}) file=${file} ${counts}`);
    if (!APPLY) continue;
    await ElasticService.upsert("vocabulary", vocab._id.toString(), vocabDoc);
    for (const [plural, type] of Object.entries(CATEGORY)) {
      for (const term of extracted[plural] || []) {
        await ElasticService.upsert(type, Buffer.from(term.uri).toString("base64"), lovWrapper.wrap(term, vocabDoc));
        total++;
      }
    }
  }
  console.log(`done, terms indexed: ${total}`);
  await mongoose.disconnect();
  process.exit(0);
})().catch((e) => { console.error("FAILED:", e); process.exit(1); });
