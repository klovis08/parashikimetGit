import * as fs from "node:fs";
import {
  classifySoftwareBroad,
  classifySoftwareStrict,
} from "../src/lib/registryClassifier.ts";

const path = process.argv[2];
if (!path) {
  console.error("Usage: node --experimental-strip-types scripts/classifier-parity-once.mjs <rows.json>");
  process.exit(1);
}
const rows = JSON.parse(fs.readFileSync(path, "utf-8"));
const out = rows.map((r) => ({
  broad: classifySoftwareBroad(r).ok,
  strict: classifySoftwareStrict(r).ok,
}));
console.log(JSON.stringify(out));
