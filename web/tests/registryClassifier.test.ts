import test from "node:test";
import assert from "node:assert/strict";
import {
  classifySoftwareBroad,
  classifySoftwareStrict,
} from "../src/lib/registryClassifier.ts";

test("registry classifier keeps antivirus repair out of strict", () => {
  const rec = {
    objekti_procedurave: "Mirembajtje antivirus dhe riparim printeresh",
    kodi_cpv_raw: "",
    tipi_procedures: "",
  };
  const broad = classifySoftwareBroad(rec);
  const strict = classifySoftwareStrict(rec);
  assert.equal(broad.ok, true);
  assert.equal(strict.ok, false);
});

test("registry classifier allows pure software development in strict", () => {
  const rec = {
    objekti_procedurave: "Zhvillim software per portalin digjital",
    kodi_cpv_raw: "72000000-5 - IT services",
    tipi_procedures: "",
  };
  const strict = classifySoftwareStrict(rec);
  assert.equal(strict.ok, true);
});
