#!/usr/bin/env node
/**
 * Check the generated document before anyone relies on it.
 *
 * Three things are worth verifying, and none of them need Word:
 *
 *   1. the package is a well-formed OOXML zip that Word will open;
 *   2. every source file section 7 claims to embed is there in full — a listing
 *      truncated halfway is the kind of defect nobody notices until the one
 *      reader who needed that function goes looking for it;
 *   3. the figures on the cover match the generated inputs, so the document
 *      cannot assert a scope it does not contain.
 */
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const DOCS = __dirname;
const REPO = path.resolve(DOCS, "..");
const DOC = path.join(DOCS, "PayrollCheck-Architecture-Reference.docx");

const problems = [];
const checks = [];
const ok = (msg) => checks.push(msg);
const bad = (msg) => problems.push(msg);

// ---------------------------------------------------------------- unzip
/** Minimal reader for the stored/deflated entries docx-js produces. */
function readZipEntry(buf, name) {
  for (let i = 0; i < buf.length - 4; i += 1) {
    if (buf.readUInt32LE(i) !== 0x04034b50) continue;
    const method = buf.readUInt16LE(i + 8);
    const compressed = buf.readUInt32LE(i + 18);
    const nameLen = buf.readUInt16LE(i + 26);
    const extraLen = buf.readUInt16LE(i + 28);
    const entryName = buf.subarray(i + 30, i + 30 + nameLen).toString("utf8");
    if (entryName !== name) continue;
    const start = i + 30 + nameLen + extraLen;
    const data = buf.subarray(start, start + compressed);
    return method === 0 ? data : zlib.inflateRawSync(data);
  }
  return null;
}

if (!fs.existsSync(DOC)) {
  console.error(`error: ${path.relative(REPO, DOC)} does not exist. Run the build first.`);
  process.exit(1);
}

const buf = fs.readFileSync(DOC);

// ---------------------------------------------------------------- 1. package
for (const required of ["[Content_Types].xml", "word/document.xml", "word/styles.xml"]) {
  if (!readZipEntry(buf, required)) bad(`the package is missing ${required}`);
}
const xml = readZipEntry(buf, "word/document.xml");
if (!xml) {
  console.error("error: word/document.xml is missing — the document is not readable.");
  process.exit(1);
}
const body = xml.toString("utf8");
if (!body.includes("</w:document>")) bad("word/document.xml is truncated");
else ok("package is a well-formed OOXML container");

// Strip tags once; everything below reads the document's visible text.
const text = body
  .replace(/<w:p[ >]/g, "\n<w:p ")
  .replace(/<[^>]+>/g, "")
  .replace(/&amp;/g, "&")
  .replace(/&lt;/g, "<")
  .replace(/&gt;/g, ">")
  .replace(/&quot;/g, '"')
  .replace(/&apos;/g, "'");

const paragraphs = (body.match(/<w:p [^>]*>|<w:p>/g) || []).length;
const tables = (body.match(/<w:tbl>/g) || []).length;
ok(`${paragraphs.toLocaleString("en-GB")} paragraphs, ${tables} tables`);

// ---------------------------------------------------------------- 2. listings
const listed = [...body.matchAll(/<w:t[^>]*>((?:backend|frontend)\/[^<]+\.(?:py|tsx|ts))<\/w:t>/g)]
  .map((m) => m[1]);
const embedded = [...new Set(listed)].filter((rel) => fs.existsSync(path.join(REPO, rel)));

let checkedLines = 0;
for (const rel of embedded) {
  const src = fs.readFileSync(path.join(REPO, rel), "utf8").replace(/\s+$/, "");
  const lines = src.split("\n").filter((l) => l.trim());
  if (!lines.length) continue;
  const first = lines[0].trim().slice(0, 60);
  const last = lines[lines.length - 1].trim().slice(0, 60);
  if (!text.includes(first)) bad(`${rel}: first line is missing from the document`);
  else if (!text.includes(last)) bad(`${rel}: last line is missing — the listing is truncated`);
  else checkedLines += src.split("\n").length;
}
if (embedded.length) {
  ok(`${embedded.length} source listings complete (${checkedLines.toLocaleString("en-GB")} lines)`);
}

// ---------------------------------------------------------------- 3. figures
const dataFile = (name) => JSON.parse(fs.readFileSync(path.join(DOCS, "data", name), "utf8"));
try {
  const schema = dataFile("schema.json");
  const rules = dataFile("rules.json");
  const tests = dataFile("tests.json");
  const meta = dataFile("meta.json");
  const endpoints = fs
    .readFileSync(path.join(DOCS, "data", "api.tsv"), "utf8")
    .trim().split("\n").length;

  const expected = {
    tables: Object.keys(schema).length,
    endpoints,
    rules: Object.values(rules).reduce((n, ids) => n + ids.length, 0),
    tests: tests.total,
  };

  const scope = `${expected.tables} tables · ${expected.endpoints} endpoints · ${expected.rules} rules`;
  if (!text.includes(scope)) {
    bad(`the cover does not state the expected scope "${scope}" — figures and content disagree`);
  } else {
    ok(`cover scope matches the inputs (${scope})`);
  }

  if (!text.includes(meta.commit)) bad(`the document does not name commit ${meta.commit}`);
  else ok(`provenance names commit ${meta.commit}${meta.dirty ? " (modified tree)" : ""}`);

  // Every rule family in the source must appear in the catalogue.
  const missingFamilies = Object.keys(rules).filter((f) => !text.includes(`${f}-`));
  if (missingFamilies.length) bad(`rule families absent from the catalogue: ${missingFamilies.join(", ")}`);
  else ok(`all ${Object.keys(rules).length} rule families present`);

  // Every suite pytest collected must appear in the test section.
  const missingSuites = Object.keys(tests.suites).filter((f) => !text.includes(f));
  if (missingSuites.length) bad(`test suites absent from section 8: ${missingSuites.join(", ")}`);
  else ok(`all ${Object.keys(tests.suites).length} test suites present`);

  // Every table in the schema must have its own subsection.
  const missingTables = Object.keys(schema).filter((t) => !text.includes(t));
  if (missingTables.length) bad(`tables absent from section 3: ${missingTables.join(", ")}`);
  else ok(`all ${Object.keys(schema).length} tables documented`);
} catch (e) {
  bad(`could not compare against docs/data (${e.message})`);
}

// ---------------------------------------------------------------- report
console.log(`\nValidating ${path.relative(REPO, DOC)}`);
for (const c of checks) console.log(`  ok    ${c}`);
for (const pr of problems) console.log(`  FAIL  ${pr}`);

if (problems.length) {
  console.error(`\n${problems.length} problem(s) found.`);
  process.exit(1);
}
console.log("\nAll checks passed.");
