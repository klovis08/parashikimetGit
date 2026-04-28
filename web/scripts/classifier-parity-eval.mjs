import * as fs from "node:fs";
import {
  classifyNearMiss,
  classifySoftwareBroad,
  classifySoftwareStrict,
  mixedItBundleSignal,
} from "../src/lib/registryClassifier.ts";

const path = process.argv[2];
if (!path) {
  console.error(
    "Usage: node --experimental-strip-types scripts/classifier-parity-eval.mjs <vectors.json>",
  );
  process.exit(1);
}

const vectors = JSON.parse(fs.readFileSync(path, "utf-8"));
const out = vectors.map((entry) => {
  const record = entry?.record ?? {};
  const broad = classifySoftwareBroad(record);
  const strict = classifySoftwareStrict(record);
  const mixed = mixedItBundleSignal(record);
  const nearMiss = classifyNearMiss(record);
  return {
    name: String(entry?.name ?? ""),
    broad_ok: broad.ok,
    broad_reasons: broad.reasons,
    strict_ok: strict.ok,
    strict_excluded_reasons: strict.excludedReasons,
    mixed_it_bundle: mixed.ok,
    mixed_reasons: mixed.reasons,
    near_miss_ok: nearMiss.ok,
    near_miss_reasons: nearMiss.reasons,
  };
});

console.log(JSON.stringify(out));
