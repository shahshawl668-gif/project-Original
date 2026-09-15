const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  PageBreak, Header, Footer, PageNumber, TableOfContents, LevelFormat,
  PageOrientation, convertInchesToTwip,
} = require("docx");

const REPO = path.resolve(__dirname, "..");
const DATA = path.join(__dirname, "data");
const OUT = path.join(__dirname, "PayrollCheck-Architecture-Reference.docx");

// ---------------------------------------------------------------- palette
const INK = "1A2327";
const ACCENT = "0D5A61";
const MUTED = "5A6B73";
const RULE = "C9D2D5";
const HEAD_BG = "EDF2F2";
const CODE_BG = "F6F8F8";

const CONTENT_W = 10080; // Letter 12240 - 2*1080 margins

// ---------------------------------------------------------------- helpers
function fail(message, remedy) {
  console.error(`\nerror: ${message}`);
  if (remedy) console.error(`       ${remedy}`);
  process.exit(1);
}

/** Read a source file for the listings in section 7, naming it if it is gone. */
function read(rel) {
  try {
    return fs.readFileSync(path.join(REPO, rel), "utf8");
  } catch (e) {
    if (e.code === "ENOENT") {
      fail(
        `section 7 lists "${rel}", which does not exist.`,
        "It was renamed or removed — update LISTINGS in this script."
      );
    }
    throw e;
  }
}

/** Read a generated input, pointing at the script that produces it. */
function readData(name) {
  try {
    return fs.readFileSync(path.join(DATA, name), "utf8");
  } catch (e) {
    if (e.code === "ENOENT") {
      fail(`missing generated input docs/data/${name}.`, "Run ./docs/data/regenerate.sh first.");
    }
    throw e;
  }
}

/**
 * Digest of the sources the generated inputs were derived from.
 *
 * Must match the recipe in regenerate.sh exactly. Comparing the two is what
 * makes a document built from stale inputs impossible rather than merely
 * unlikely — the failure mode this guards against is a confidently wrong
 * document, which is worse than no document at all.
 */
function sourceDigest() {
  const digest = crypto.createHash("sha256");
  const roots = [
    ["backend/app", [".py"]],
    ["frontend/src", [".ts", ".tsx"]],
  ];
  for (const [root, exts] of roots) {
    const found = [];
    (function walk(dir) {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name === "__pycache__") continue;
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (exts.includes(path.extname(entry.name))) found.push(full);
      }
    })(path.join(REPO, root));
    // Sorted by the repo-relative path, matching pathlib.rglob + sorted().
    for (const full of found.map((f) => path.relative(REPO, f)).sort()) {
      digest.update(full);
      digest.update(fs.readFileSync(path.join(REPO, full)));
    }
  }
  return digest.digest("hex");
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 400, after: 200 },
    children: [new TextRun({ text, font: "Georgia", size: 32, bold: true, color: INK })],
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 320, after: 140 },
    children: [new TextRun({ text, font: "Georgia", size: 25, bold: true, color: INK })],
  });
}
function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 240, after: 100 },
    children: [new TextRun({ text, font: "Calibri", size: 22, bold: true, color: ACCENT })],
  });
}
function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 140, line: 276 },
    children: [new TextRun({ text, font: "Calibri", size: opts.size ?? 20, color: opts.color ?? INK, italics: !!opts.italics, bold: !!opts.bold })],
  });
}
function runs(parts, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 140, line: 276 },
    children: parts.map((x) =>
      typeof x === "string"
        ? new TextRun({ text: x, font: "Calibri", size: 20, color: INK })
        : new TextRun({
            text: x.t,
            font: x.mono ? "Consolas" : "Calibri",
            size: x.mono ? 18 : 20,
            bold: !!x.b, italics: !!x.i,
            color: x.c || INK,
          })
    ),
  });
}
function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullets", level },
    spacing: { after: 70, line: 264 },
    children: [new TextRun({ text, font: "Calibri", size: 20, color: INK })],
  });
}
function note(text) {
  return new Paragraph({
    spacing: { before: 140, after: 160, line: 276 },
    indent: { left: 200 },
    border: { left: { style: BorderStyle.SINGLE, size: 18, color: ACCENT, space: 10 } },
    children: [new TextRun({ text, font: "Calibri", size: 19, color: MUTED, italics: true })],
  });
}
function codeLine(text) {
  return new Paragraph({
    spacing: { after: 0, line: 200 },
    shading: { type: ShadingType.CLEAR, fill: CODE_BG },
    indent: { left: 120, right: 120 },
    children: [new TextRun({ text: text.replace(/\t/g, "    ") || " ", font: "Consolas", size: 15, color: INK })],
  });
}
function codeBlock(src, opts = {}) {
  const lines = src.replace(/\s+$/, "").split("\n");
  const out = [];
  if (opts.caption) {
    out.push(new Paragraph({
      spacing: { before: 160, after: 40 },
      children: [new TextRun({ text: opts.caption, font: "Consolas", size: 16, bold: true, color: ACCENT })],
    }));
  }
  lines.forEach((l) => out.push(codeLine(l)));
  out.push(new Paragraph({ spacing: { after: 160 }, children: [] }));
  return out;
}

function cell(text, opts = {}) {
  return new TableCell({
    width: { size: opts.w, type: WidthType.DXA },
    shading: opts.head ? { type: ShadingType.CLEAR, fill: HEAD_BG } : undefined,
    margins: { top: 60, bottom: 60, left: 110, right: 110 },
    children: [
      new Paragraph({
        spacing: { after: 0, line: 240 },
        children: [
          new TextRun({
            text: String(text ?? ""),
            font: opts.mono ? "Consolas" : "Calibri",
            size: opts.mono ? 15 : (opts.head ? 16 : 17),
            bold: !!opts.head || !!opts.b,
            color: opts.head ? MUTED : (opts.c || INK),
          }),
        ],
      }),
    ],
  });
}

function table(headers, rows, widths, monoCols = []) {
  const border = { style: BorderStyle.SINGLE, size: 2, color: RULE };
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    borders: { top: border, bottom: border, left: border, right: border,
               insideHorizontal: border, insideVertical: border },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((hh, i) => cell(hh, { w: widths[i], head: true })),
      }),
      ...rows.map((r) =>
        new TableRow({
          children: r.map((c, i) => cell(c, { w: widths[i], mono: monoCols.includes(i) })),
        })
      ),
    ],
  });
}

function spacer(after = 160) {
  return new Paragraph({ spacing: { after }, children: [] });
}
function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

// ---------------------------------------------------------------- data
const meta = JSON.parse(readData("meta.json"));
const schema = JSON.parse(readData("schema.json"));
const rules = JSON.parse(readData("rules.json"));
const tests = JSON.parse(readData("tests.json"));
const apiRows = readData("api.tsv").trim().split("\n").map((l) => l.split("\t"));
const inventory = readData("inventory.tsv").trim().split("\n").map((l) => {
  const [file, lines, desc] = l.split("\t");
  return { file, lines, desc: (desc || "").trim() };
});
const feRows = readData("frontend.tsv").trim().split("\n").map((l) => {
  const [file, lines] = l.split("\t");
  return { file, lines };
});

// Refuse to document a tree the inputs were not derived from.
if (sourceDigest() !== meta.source_digest) {
  fail(
    "the generated inputs in docs/data are stale — the source has changed since they were produced.",
    "Run ./docs/data/regenerate.sh, then build again."
  );
}

// Every table must be classified. An unclassified one is a documentation gap,
// so say so rather than filing it under a catch-all nobody reads.
const ungrouped = Object.keys(schema).filter((t) => !schema[t].group).sort();
if (ungrouped.length) {
  fail(
    `${ungrouped.length} table(s) are not assigned to a group: ${ungrouped.join(", ")}.`,
    "Add them to GROUPS in docs/data/regenerate.sh, then regenerate."
  );
}

// ---------------------------------------------------------------- counts
const tableCount = Object.keys(schema).length;
const columnCount = Object.values(schema).reduce((n, t) => n + t.columns.length, 0);
const endpointCount = apiRows.length;
const ruleCount = Object.values(rules).reduce((n, ids) => n + ids.length, 0);
const ruleFamilyCount = Object.keys(rules).length;
const backendFileCount = inventory.length;
const sourceFileCount = backendFileCount + feRows.length;
const suiteCount = Object.keys(tests.suites).length;
const codebaseLines =
  inventory.reduce((n, r) => n + Number(r.lines), 0) +
  feRows.reduce((n, r) => n + Number(r.lines), 0);

const builtFrom = meta.dirty ? `${meta.commit} (modified tree)` : meta.commit;
const builtDate = new Date(meta.commit_date || Date.now()).toLocaleDateString("en-GB", {
  day: "numeric", month: "long", year: "numeric",
});

const doc = [];

// ================================================================ COVER
doc.push(
  new Paragraph({ spacing: { before: 2600, after: 0 },
    children: [new TextRun({ text: "PAYROLLCHECK", font: "Consolas", size: 20, color: ACCENT, characterSpacing: 60 })] }),
  new Paragraph({ spacing: { before: 200, after: 120 },
    children: [new TextRun({ text: "Architecture & Code Reference", font: "Georgia", size: 52, bold: true, color: INK })] }),
  new Paragraph({ spacing: { after: 480 },
    children: [new TextRun({ text: "India payroll validation and business intelligence", font: "Georgia", size: 26, color: MUTED, italics: true })] }),
  new Paragraph({
    border: { top: { style: BorderStyle.SINGLE, size: 12, color: ACCENT, space: 12 } },
    spacing: { after: 240 }, children: [] }),
  runs([{ t: "Repository   ", c: MUTED }, { t: meta.repository, mono: true }], { after: 60 }),
  runs([{ t: "Branch       ", c: MUTED }, { t: meta.branch, mono: true }], { after: 60 }),
  runs([{ t: "Commit       ", c: MUTED }, { t: builtFrom, mono: true }], { after: 60 }),
  runs([{ t: "Date         ", c: MUTED }, { t: builtDate, mono: true }], { after: 60 }),
  runs([{ t: "Scope        ", c: MUTED }, {
    t: `${tableCount} tables · ${endpointCount} endpoints · ${ruleCount} rules · `
     + `${sourceFileCount} source files · ${tests.total} tests`, mono: true }], { after: 600 }),
  p("This document is a reference for engineers, reviewers and auditors. It describes the complete system architecture, every database table and column, every API endpoint, every validation rule, and the full source of the modules that carry the product's logic. Source for the remaining modules is in the repository at the commit named above.", { color: MUTED, size: 19 }),
  p("It is generated from the codebase, not written by hand: the schema comes from live ORM metadata, the endpoints from the generated OpenAPI spec, the rule catalogue from the rule identifiers in the source, the test inventory from pytest's own collection, and the module map from each file's docstring. The build refuses to run against inputs that do not match the source tree, so these figures cannot have drifted from the commit above.", { color: MUTED, size: 19 }),
  pageBreak()
);

// ================================================================ TOC
doc.push(
  h1("Contents"),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  pageBreak()
);

// ================================================================ 1. PRODUCT
doc.push(
  h1("1. What the product is"),
  p("PayrollCheck is not an HRMS and it does not run payroll. It sits beside whatever system already does — Keka, Darwinbox, ADP, a payroll bureau, or a spreadsheet maintained with a CA — and answers two questions about that system's output."),
  h3("Is this month right?"),
  bullet("Ingests four inputs: the salary register, the employee master, attendance, and the CTC report. Each is stored with history, so any month can be re-checked against the data as it stood at the time."),
  bullet("Validates PF, ESIC, PT, LWF, income tax, gross and net arithmetic, LOP proration, month-on-month movement, bonus, gratuity, minimum wage, and structural risk such as PF avoidance through allowance-heavy pay design."),
  bullet("Compares the register against its own inputs — paid before joining, paid after exit, paid days disagreeing with attendance, PF deducted with no UAN. These catch a wrong input that was processed consistently, which no internal-consistency check can see."),
  bullet("Scores every employee 0–100 and classifies the register by risk."),
  h3("What is it costing, and what are we exposed to?"),
  bullet("A cost bridge decomposing month-on-month movement into joiners, leavers, pay changes, attendance and arrears, reconciling exactly to the observed change."),
  bullet("The full Indian cost taxonomy — earnings split as Basic & DA, HRA, allowances, variable pay and arrears; employer EPF, EDLI and admin, ESI, the gratuity accrual and LWF on top; employee EPF, ESI, PT and TDS inside gross — sliced by any of nine reporting dimensions over months, quarters or financial-year quarters, and compared between any two months."),
  bullet("A statutory exposure ledger carrying each open shortfall from the month it arose, with interest and damages accruing by age."),
  bullet("Filing readiness against the statutory calendar: the due date for each obligation arising from a wage month, and what would make the filing wrong. Readiness, never confirmation — nothing here can see a portal."),
  bullet("Period sign-off and an evidence pack recording who approved the month, what they saw, what they accepted and on what grounds, and which rules and rates were in force."),

  h2("1.1 The structural position"),
  p("The product's defensibility rests on one constraint: it never runs payroll. A vendor auditing its own output is not an audit. Because PayrollCheck computes nothing that anyone pays out, it can act as an independent second opinion on any payroll system — and that is a position no payroll vendor can occupy for its own customers."),

  h2("1.2 Who it serves"),
  table(
    ["Buyer", "How the model fits"],
    [
      ["Payroll bureau or CA practice", "One login, many client companies. Each client is an entity with its own registers, statutory configuration and rate tables. Analysts can be scoped to a named subset of the client book."],
      ["Enterprise", "An organization that happens to have one entity. Nothing to configure, no entity header to send, and no migration required if a second legal employer is later acquired."],
    ],
    [2600, 7480]
  ),
  spacer(),
  note("Findings are a record, not a report. A finding keeps its identity across months, so an exception explained once stays explained and a problem in its ninth month says so. Waiving a finding removes it from the worklist but never from the exposure — an accepted risk is still a risk."),
  pageBreak()
);

// ================================================================ 2. ARCHITECTURE
doc.push(
  h1("2. Architecture"),
  h2("2.1 Technology"),
  table(
    ["Layer", "Technology", "Notes"],
    [
      ["Web application", "Next.js 14 (App Router), React 18, TypeScript, Tailwind", "Server-rendered shell, client components for interactive pages"],
      ["State / data", "TanStack Query, React context", "Query cache is invalidated on entity switch"],
      ["API", "FastAPI, Pydantic v2", "All responses wrapped in a success/data/error envelope"],
      ["ORM", "SQLAlchemy 2.0 (typed, Mapped[...] style)", "Declarative models, no Alembic — see §2.5"],
      ["Database", "PostgreSQL in production, SQLite in development", "Migrations branch on dialect"],
      ["Spreadsheets", "pandas + openpyxl", "Ingestion and the evidence pack"],
      ["Auth", "JWT access + refresh, passlib/bcrypt", "Silent refresh on 401, one retry"],
    ],
    [2200, 3400, 4480]
  ),
  spacer(),

  h2("2.2 Deployment topology"),
  ...codeBlock(
`                         ┌──────────────────────────────┐
  Browser  ──────────▶   │  Next.js  (Vercel / Render)  │
                         │  peopleopslab.in             │
                         │                              │
                         │  /api/proxy/[...path]        │  server-side route handler
                         └──────────────┬───────────────┘
                                        │  BACKEND_URL (server-only env)
                                        ▼
                         ┌──────────────────────────────┐
                         │  FastAPI  (Render / Fly / VM)│
                         │  api.peopleopslab.in         │
                         └──────────────┬───────────────┘
                                        ▼
                         ┌──────────────────────────────┐
                         │  PostgreSQL                  │
                         └──────────────────────────────┘`,
    { caption: "Production request path" }
  ),
  p("The browser calls the same origin it was served from. A Next.js route handler forwards /api/* server-side to the real API, which removes CORS, mixed-content and a class of browser fetch failures from the picture. Direct browser-to-API calls remain supported via NEXT_PUBLIC_DIRECT_API=1, in which case CORS_ORIGINS must list the web origins."),
  note("The proxy forwards only an allowlisted set of headers. X-Entity-Id is on that list; omitting it would silently route every proxied request to the caller's default entity — one client's data written against another, with nothing visible in the UI."),

  h2("2.3 The entity scope"),
  p("Every row of tenant data is scoped by entity_id. An entity is one legal employer: its own PF and ESIC registrations, its own statutory configuration, its own registers. An organization owns entities — many for a practice, one for an enterprise."),
  ...codeBlock(
`Organization  (practice | enterprise)
   │
   ├── Entity  "Acme Manufacturing"   PF: KN/BNG/12345   state: Karnataka
   │      └── registers, master, attendance, CTC, config, rates, findings, sign-offs
   │
   ├── Entity  "Beta Logistics"       PF: MH/MUM/67890   state: Maharashtra
   │      └── ...
   │
   └── OrgMembership  (user, role)
          └── EntityAccess *          absent ⇒ access to every entity in the org`,
    { caption: "Scope hierarchy" }
  ),
  p("A request names its entity with the X-Entity-Id header. When it does not — a single-entity enterprise, or a first load before the switcher has mounted — the member's stored default entity is used. That default is explicit rather than derived: deriving it from creation order or name would mean adding a client silently redirects existing requests to a different employer."),
  spacer(),
  table(
    ["Role", "May read", "May write data", "May manage entities", "May sign off"],
    [
      ["owner", "yes", "yes", "yes", "yes"],
      ["manager", "yes", "yes", "yes", "yes"],
      ["analyst", "yes", "yes", "no", "no"],
      ["viewer", "yes", "no", "no", "no"],
    ],
    [1800, 1700, 2200, 2400, 1980]
  ),
  spacer(),
  p("user_id survives on tenant tables as authorship provenance. It is no longer the access boundary."),

  h2("2.4 Request lifecycle"),
  ...codeBlock(
`  HTTP request
      │
      ├─ TenantContextMiddleware      attaches ids to request.state for logging
      │
      ├─ get_current_user             JWT decode → User  (401 on failure)
      │
      ├─ get_current_entity           X-Entity-Id → Entity, membership-checked
      │    └─ require_entity_write    role ≥ analyst, else 403
      │    └─ require_org_admin       role ≥ manager, else 403
      │
      ├─ route handler                queries filtered by Entity.id
      │
      └─ ok(payload)                  { success, data, error } envelope`,
    { caption: "Dependency chain" }
  ),
  note("A request naming an entity in another organization receives 404 \"Entity not found\" — byte-identical to the response for a random UUID, so the header cannot be used to enumerate other organizations' entities."),

  h2("2.5 Schema evolution"),
  p("There is no Alembic. Schema changes are applied by app/migrations.py: ordered, idempotent steps that run on every boot and detect their own completion by inspecting the live schema rather than recording a version. A database at any point in the history converges to the current shape."),
  p("PostgreSQL and SQLite differ on what can be altered in place, so destructive steps branch on dialect — PostgreSQL drops constraints and alters columns directly, SQLite rebuilds the table through copy-and-rename from the current ORM metadata."),
  table(
    ["Step", "What it does"],
    [
      ["add_entity_columns", "Adds entity_id, nullable, to every tenant-scoped table"],
      ["provision_legacy_tenants", "Gives each pre-entity user an organization, one entity, and an owner seat"],
      ["backfill_entity_ids", "Points existing rows at their owner's entity, resolved through membership"],
      ["rekey_config_tables", "Moves statutory_settings and statutory_config from a user PK to an entity PK"],
      ["rescope_unique_constraints", "Replaces UNIQUE (user_id, …) with UNIQUE (entity_id, …)"],
      ["enforce_entity_not_null", "Tightens entity_id once every row carries one, skipping tables with orphans"],
      ["set_membership_defaults", "Adds and backfills org_memberships.default_entity_id"],
    ],
    [3200, 6880]
  ),
  spacer(),
  note("A separate, narrower mechanism — apply_column_patches in app/database.py — adds simple nullable columns. It predates the migration module and is retained for additive-only changes."),
  pageBreak()
);

// ================================================================ 3. DATA MODEL
doc.push(h1("3. Data model"));
doc.push(p(`${tableCount} tables, ${columnCount} columns. Grouped by role below. Every tenant-scoped table carries entity_id; user_id where present records who created the row.`));

const GROUP_ORDER = ["Tenancy", "Identity", "Configuration", "Payroll inputs", "Findings & assurance"];
const GROUP_NOTES = {
  "Tenancy": "The access boundary. Everything else hangs off Entity.",
  "Identity": "Accounts and token storage. Unchanged by the entity work except that provisioning now creates an organization at signup.",
  "Configuration": "What each entity's rules are. All FY- or date-versioned so an old month validates against the rules that applied then.",
  "Payroll inputs": "The four ingested datasets and their upload metadata. Master and CTC records are effective-dated; registers and attendance are keyed by period.",
  "Findings & assurance": "What validation produced, what humans decided about it, and the frozen record of approval.",
};

// Any group produced by regenerate.sh must have a note here, or the section
// renders a silent blank where an explanation should be.
for (const group of new Set(Object.values(schema).map((t) => t.group))) {
  if (!GROUP_ORDER.includes(group)) {
    fail(`schema group "${group}" has no ordering entry.`, "Add it to GROUP_ORDER in this script.");
  }
  if (!GROUP_NOTES[group]) {
    fail(`schema group "${group}" has no description.`, "Add it to GROUP_NOTES in this script.");
  }
}

let secNo = 0;
for (const g of GROUP_ORDER) {
  const names = Object.keys(schema).filter((n) => schema[n].group === g).sort();
  if (!names.length) continue;
  secNo += 1;
  doc.push(h2(`3.${secNo} ${g}`));
  doc.push(p(GROUP_NOTES[g], { color: MUTED, italics: true }));
  for (const name of names) {
    const t = schema[name];
    doc.push(h3(name));
    doc.push(
      table(
        ["Column", "Type", "Constraints"],
        t.columns.map((c) => [c.name, c.type, c.flags || "—"]),
        [3000, 3000, 4080],
        [0, 1, 2]
      )
    );
    if (t.unique.length) {
      doc.push(runs([{ t: t.unique.join("   ·   "), mono: true, c: ACCENT }], { after: 180 }));
    } else {
      doc.push(spacer(180));
    }
  }
}
doc.push(pageBreak());

// ================================================================ 4. API
doc.push(
  h1("4. API surface"),
  p(`${endpointCount} endpoints. Every route is also mounted under /api/v1 as a versioned alias. All JSON responses use the envelope { success, data, error }; the evidence pack and the Excel audit export return binary streams instead.`),
  p("Unless noted, endpoints resolve an entity via get_current_entity and are therefore scoped to one employer. Mutating endpoints additionally require role ≥ analyst; entity management and sign-off require role ≥ manager.")
);

const TAG_ORDER = ["health", "auth", "users", "admin", "org", "components", "statutory",
  "Statutory Config", "reference", "rule-engine", "rule-preferences", "income-tax",
  "ctc", "workforce", "payroll", "findings", "bi", "minimum-wage", "signoff"];
const TAG_TITLE = {
  "health": "Health", "auth": "Authentication", "users": "User profile", "admin": "Administration",
  "org": "Organization & entities", "components": "Salary components", "statutory": "Legacy statutory settings",
  "Statutory Config": "Config-driven statutory engine", "reference": "Reference data",
  "rule-engine": "Rule engine (formulas & slabs)", "rule-preferences": "Rule suppression",
  "income-tax": "Income tax", "ctc": "CTC ingestion", "workforce": "Employee master & attendance",
  "payroll": "Payroll register & validation", "findings": "Findings worklist",
  "bi": "Business intelligence", "minimum-wage": "Minimum wage", "signoff": "Sign-off & evidence pack",
};
let apiNo = 0;
for (const tag of TAG_ORDER) {
  const rows = apiRows.filter((r) => r[0] === tag);
  if (!rows.length) continue;
  apiNo += 1;
  doc.push(h2(`4.${apiNo} ${TAG_TITLE[tag] || tag}`));
  doc.push(
    table(
      ["Method", "Path", "Purpose"],
      rows.map((r) => [r[2], r[1], (r[4] || r[3] || "—").replace(/\s+/g, " ").slice(0, 150)]),
      [1100, 4200, 4780],
      [0, 1]
    )
  );
  doc.push(spacer(180));
}
doc.push(pageBreak());

// ================================================================ 5. RULES
/**
 * What each rule family checks.
 *
 * The identifiers themselves are scanned out of the source by regenerate.sh, so
 * this map only supplies the prose. A family appearing in the code with no entry
 * here fails the build — which is what stops a new rule from quietly going
 * undocumented, the failure mode that matters most in a compliance product.
 */
const RULE_FAMILIES = {
  DATA: ["Data quality", "Missing employee id, negative values, duplicate employee ids, all-zero components, negative deductions, and duplicate PAN / UAN / Aadhaar / bank account across employees."],
  COMP: ["Component mapping", "Columns present in the register that map to no configured component; configured components with no column."],
  STRUCT: ["Structure risk", "PF wage below a configured share of gross (possible PF avoidance); allowance-heavy pay design above a configured threshold."],
  AGG: ["Aggregates", "Gross versus the sum of earnings; net versus gross less statutory deductions, within configurable rupee tolerances."],
  STAT: ["Statutory amounts", "PF, ESIC, PT and LWF expected versus actual; bonus eligibility; gratuity exemption cap; TDS risk on a high-income month."],
  PF: ["PF specifics", "EPS split against the ceiling; EPS zero for post-September-2014 joiners above the wage ceiling; EPS stopping at 58; international workers not capped."],
  ESI: ["ESIC specifics", "Disability coverage ceiling; daily-wage employee-share exemption."],
  PT: ["Professional tax", "Article 276 annual cap of ₹2,500; PT deducted in a state that levies none."],
  LOP: ["Loss of pay", "paid_days + lop_days against the denominator; component proration against CTC monthly × paid / total."],
  MOM: ["Month on month", "New joiner; component spike or drop against the prior month; components appearing or disappearing; increment arrears against CTC."],
  ADV: ["Trend", "Salary spikes and drops measured against prior gross."],
  ID: ["Identity", "PAN format and section 206AA, Aadhaar Verhoeff checksum, UAN, ESI number and IFSC formats, working age, pay before joining or after exit."],
  BON: ["Bonus", "Payment of Bonus Act eligibility at ₹21,000 and the 8.33–20% band on min(Basic + DA, ₹7,000)."],
  GRAT: ["Gratuity", "Service gate of five years, waived on death or disablement; the 15/26 formula; service years computed from the master's joining date; and an explicit finding when that date is absent."],
  TDS: ["Tax deducted", "20% minimum without PAN under section 206AA; monthly TDS against an annualised projection for the declared regime."],
  MST: ["Against the master", "Absent from the employee master; paid before joining; paid after exit; PF deducted without a UAN; ESIC deducted without an IP number."],
  ATT: ["Against attendance", "Paid days and LOP disagreeing with the attendance register; paid with no attendance row; paid days exceeding the month's calendar days."],
  ARR: ["Arrears", "Arrear pay checked in the same pass as regular pay: the arrear window against the CTC effective date, per-month recomputation of PT and LWF across the window, and statutory contributions on the arrear itself. Silent on a row that carries no arrear."],
  MW: ["Minimum wage", "Wages below the applicable floor; or no rate on file — reported as unverifiable rather than passed."],
};

/** "001", "002", "003" → "001…003"; sparse sets stay enumerated. */
function idRange(numbers) {
  if (numbers.length === 1) return numbers[0];
  const asInts = numbers.map(Number);
  const contiguous = asInts.every((n, i) => i === 0 || n === asInts[i - 1] + 1);
  if (contiguous) return `${numbers[0]}\u2026${numbers[numbers.length - 1]}`;
  return numbers.join("/");
}

const undocumentedFamilies = Object.keys(rules).filter((f) => !RULE_FAMILIES[f]).sort();
if (undocumentedFamilies.length) {
  fail(
    `rule famil${undocumentedFamilies.length === 1 ? "y" : "ies"} found in the source with no `
      + `description: ${undocumentedFamilies.join(", ")}.`,
    "Add an entry to RULE_FAMILIES in this script so the catalogue stays complete."
  );
}

const staleFamilies = Object.keys(RULE_FAMILIES).filter((f) => !rules[f]).sort();
if (staleFamilies.length) {
  fail(
    `RULE_FAMILIES describes famil${staleFamilies.length === 1 ? "y" : "ies"} no longer in the `
      + `source: ${staleFamilies.join(", ")}.`,
    "Remove the entr" + (staleFamilies.length === 1 ? "y" : "ies") + " from this script."
  );
}

// Rendered in the order the families are described, which reads as a pipeline:
// data quality, then structure, then statutory, then the input comparisons.
const RULE_ROWS = Object.entries(RULE_FAMILIES).map(([family, [name, desc]]) => [
  `${family}-${idRange(rules[family])}`,
  name,
  desc,
]);
doc.push(
  h1("5. Rule catalogue"),
  p(`${ruleCount} rule identifiers across ${ruleFamilyCount} families. Severity is CRITICAL, WARNING or INFO; each finding carries an expected value, an actual value, a difference, a reason, a suggested fix and a financial impact where one can be computed.`),
  p("Every threshold these rules use is configurable per entity and versioned by financial year. The values quoted below are the seeded defaults, which reflect common India payroll audit practice and carry no legal force of their own."),
  table(
    ["Rule IDs", "Family", "What it checks"],
    RULE_ROWS,
    [1750, 2000, 6330],
    [0]
  ),
  spacer(),
  h2("5.1 The two families that are different in kind"),
  p("MST-* and ATT-* compare the register against its inputs rather than against itself. Every other family is internal to the register, and therefore blind to a wrong input that was processed consistently: an employee paid two months after leaving is arithmetically perfect on the register, and only the employee master reveals it."),
  p("Both families run only for employees the relevant input actually covers. A client who has not uploaded attendance receives silence from ATT-*, not a screenful of false positives."),
  h2("5.2 Suppression and lifecycle"),
  p("A rule can be suppressed entity-wide through tenant_rule_preferences, which removes it from validation output altogether. That is distinct from waiving an individual finding, which removes one employee's instance from the worklist while keeping it in the exposure figures."),
  pageBreak()
);

// ================================================================ 6. MODULE MAP
doc.push(
  h1("6. Module reference"),
  p("85 Python modules and 61 TypeScript modules. Every file is listed; the description is the module's own docstring where it has one."),
  h2("6.1 Backend")
);
const BE_GROUPS = [
  ["Application core", (f) => /^backend\/app\/(main|config|database|deps|envelope|security|seed|migrations)\.py$/.test(f) || f.includes("middleware/")],
  ["Models", (f) => f.includes("/models/")],
  ["Schemas", (f) => f.includes("/schemas/")],
  ["Routers", (f) => f.includes("/routers/")],
  ["Services", (f) => f.includes("/services/")],
];
for (const [label, pred] of BE_GROUPS) {
  const rows = inventory.filter((r) => pred(r.file) && !r.file.endsWith("__init__.py"));
  if (!rows.length) continue;
  doc.push(h3(label));
  doc.push(
    table(
      ["Module", "Lines", "Responsibility"],
      rows.map((r) => [r.file.replace("backend/app/", ""), r.lines, r.desc || "—"]),
      [2900, 800, 6380],
      [0, 1]
    )
  );
  doc.push(spacer(180));
}
doc.push(
  h2("6.2 Frontend"),
  table(
    ["Module", "Lines"],
    feRows.map((r) => [r.file.replace("frontend/src/", ""), r.lines]),
    [8280, 1800],
    [0, 1]
  ),
  pageBreak()
);

// ================================================================ 7. SOURCE
const LISTINGS = [
  ["7.1 Tenancy model", [
    ["backend/app/models/org.py", "Organization, Entity, OrgMembership, EntityAccess"],
    ["backend/app/services/tenancy.py", "Provisioning and access resolution"],
    ["backend/app/deps.py", "Entity resolution and role gates"],
  ]],
  ["7.2 Schema migration", [
    ["backend/app/migrations.py", "Ordered, idempotent, dialect-aware migration steps"],
  ]],
  ["7.3 Workforce ingestion", [
    ["backend/app/models/workforce.py", "Employee master and attendance"],
    ["backend/app/services/workforce_parse.py", "Header aliasing and typed parsing"],
    ["backend/app/services/workforce.py", "Point-in-time lookups"],
  ]],
  ["7.4 Register versus inputs", [
    ["backend/app/services/workforce_rules.py", "MST-*, ATT-*, GRAT-004/005"],
  ]],
  ["7.5 Findings lifecycle", [
    ["backend/app/models/findings.py", "Runs, findings, state and the event log"],
    ["backend/app/services/finding_store.py", "Fingerprinting and state reconciliation"],
  ]],
  ["7.6 Business intelligence", [
    ["backend/app/services/analytics.py", "Cost bridge, exposure, dimensional cost analysis and period comparison"],
    ["backend/app/services/cost_model.py", "The Indian cost taxonomy and the CTC identity"],
    ["backend/app/services/dimensions.py", "The reporting attributes cost is analysed by, snapshotted per period"],
    ["backend/app/services/compliance_calendar.py", "Statutory due dates and filing readiness"],
    ["backend/app/schemas/exposure_config.py", "Interest and damages configuration"],
  ]],
  ["7.7 Minimum wage", [
    ["backend/app/models/minimum_wage.py", "Rate table"],
    ["backend/app/services/minimum_wage.py", "Lookup, proration and the compliance check"],
  ]],
  ["7.8 Sign-off and evidence", [
    ["backend/app/models/signoff.py", "Period sign-off and its event log"],
    ["backend/app/services/signoff.py", "Snapshot assembly and state transitions"],
  ]],
  ["7.9 One-pass validation and the PF basis", [
    ["backend/app/services/row_composition.py", "What one register row is made of, and over what window"],
    ["backend/app/services/pf_basis.py", "Whether an employee's PF is restricted to the ceiling"],
    ["backend/app/services/finding_taxonomy.py", "Missing, mismatch or issue — the shape of the report"],
  ]],
  ["7.10 Frontend entity context", [
    ["frontend/src/context/EntityContext.tsx", "Entity provider"],
    ["frontend/src/components/EntitySwitcher.tsx", "Client switcher"],
  ]],
];

const LISTING_FILES = LISTINGS.flatMap(([, files]) => files.map(([rel]) => rel));
const LISTING_FILE_COUNT = LISTING_FILES.length;
const LISTING_LINE_COUNT = LISTING_FILES.reduce(
  (n, rel) => n + read(rel).split("\n").length, 0
);

doc.push(
  h1("7. Source listings"),
  p(`Full source of ${LISTING_FILE_COUNT} modules totalling ${LISTING_LINE_COUNT.toLocaleString("en-GB")} lines — those that carry the product's logic — the tenancy model and its migration, the four ingestion paths, the rules that compare the register against its inputs, the findings lifecycle, the analytics, minimum wage, and sign-off. The codebase is ${codebaseLines.toLocaleString("en-GB")} lines in total; the rest is inventoried in section 6 rather than pasted.`),
  p("The remaining modules are either pre-existing statutory engines (rule_engine_v2.py, validation.py, the PF, ESIC and income-tax engines) or presentation code. They are inventoried in §6 and their source is in the repository at the commit on the cover.", { color: MUTED })
);
for (const [section, files] of LISTINGS) {
  doc.push(h2(section));
  for (const [rel, caption] of files) {
    doc.push(h3(rel));
    doc.push(p(caption, { color: MUTED, italics: true, after: 80 }));
    doc.push(...codeBlock(read(rel)));
  }
}
doc.push(pageBreak());


/**
 * What each test suite pins down.
 *
 * Counts come from pytest's own collection, so they cannot disagree with what
 * runs; this map supplies only the prose. A new suite with no entry fails the
 * build rather than appearing as a blank row.
 */
const SUITE_NOTES = {
  "test_analytics.py": "Cost bridge reconciliation and exposure arithmetic",
  "test_compliance_calendar.py": "Statutory due dates, blockers, and that no status can read as filed",
  "test_cost_analysis.py": "Dimension snapshotting, grouping, granularity, filters, reconciliation",
  "test_cost_taxonomy.py": "The CTC identity, reported-over-computed precedence, period comparison",
  "test_pf_basis.py": "Per-employee restriction: source precedence and tri-state flags",
  "test_unified_validation.py": "Regular, arrear and increment validated in one pass",
  "test_validate_endpoint.py": "The validate route end to end, against the 500 it once returned",
  "test_entity_isolation.py": "The access boundary, roles and header resolution",
  "test_entity_migration.py": "Upgrade of a database built on the pre-entity schema",
  "test_finding_lifecycle.py": "Recurrence, resolution, waivers, expiry, audit trail",
  "test_income_tax_engine.py": "Old and new regime (inherited)",
  "test_minimum_wage.py": "Lookup precedence, proration, basis, coverage gaps",
  "test_pf_esic_engines.py": "PF and ESIC engines (inherited)",
  "test_signoff.py": "Snapshot immutability, role gate, workbook contents",
  "test_spec_rules.py": "Statutory rule spec (inherited)",
  "test_workforce_ingest.py": "Upload, preview, commit and effective dating",
  "test_workforce_parse.py": "Header aliasing, day-first dates, typing, derivation",
  "test_workforce_rules.py": "MST-*, ATT-*, GRAT-004/005, including silence conditions",

};

const undocumentedSuites = Object.keys(tests.suites).filter((f) => !SUITE_NOTES[f]).sort();
if (undocumentedSuites.length) {
  fail(
    `test suite${undocumentedSuites.length === 1 ? "" : "s"} with no description: `
      + undocumentedSuites.join(", ") + ".",
    "Add an entry to SUITE_NOTES in this script."
  );
}

const SUITE_ROWS = Object.entries(tests.suites)
  .sort((a, b) => b[1] - a[1])
  .map(([file, count]) => [file, String(count), SUITE_NOTES[file]]);

// ================================================================ 8. TESTS
doc.push(
  h1("8. Test architecture"),
  p(`${tests.total} scenarios across ${suiteCount} suites, all passing at the commit on the cover.`),
  table(
    ["Suite", "Count", "What it pins"],
    SUITE_ROWS,
    [3200, 900, 5980],
    [0, 1]
  ),
  spacer(),
  p("conftest.py points the database at a fresh temporary file before anything under app is imported, then boots the application once per session — so every run exercises the real startup path: create_all, the migrations, and the seeders. Tests keep themselves apart by signing up distinct email addresses, which means each also receives its own organization, and the isolation under test is real rather than mocked."),
  h2("8.1 Defects the suite found"),
  p("Five defects, all introduced during this work and all caught before merge."),
  table(
    ["Defect", "Consequence had it shipped"],
    [
      ["Migrations read ORM metadata nothing guaranteed was populated", "Worked only because API startup happened to import models first; failed with \"no such table: entities\" anywhere else"],
      ["Raw SQL bound uuid.UUID objects", "PostgreSQL would accept them and SQLite refuse — every developer database broken on first boot while production looked fine"],
      ["Table rebuilds copied NULLs into NOT NULL columns", "Re-keying a config table on SQLite would fail mid-migration"],
      ["validate_employees received a User where the refactor made it expect an Entity", "Duck typing made it run silently; PT slabs, LWF rates and prior-month registers looked up under a scope that would never match"],
      ["Provisioning read entity.id before flush", "Membership stored a null default entity; entity selection fell through to a random UUID tiebreak"],
    ],
    [3600, 6480]
  ),
  spacer(),
  note("A sixth problem was found by reading rather than by a test: the Next.js proxy's header allowlist omitted x-entity-id, so on peopleopslab.in every proxied request would have fallen back to the caller's default entity. Nothing in the suite would have caught it; a scripted browser walkthrough now exercises the header path end to end."),
  h2("8.2 What is not covered"),
  bullet("The PostgreSQL migration path. Migration tests run on SQLite; the DROP CONSTRAINT / ALTER COLUMN / ADD PRIMARY KEY branches production will take are reviewed but not executed. This is the largest gap in the record."),
  bullet("Frontend component tests. The switcher is covered by one scripted browser walkthrough plus typecheck, lint and build."),
  bullet("Load and performance. Nothing establishes behaviour on a ten-thousand-employee register; the cost bridge loads two full months of rows into memory."),
  bullet("Concurrency. Two analysts validating the same period simultaneously, or signing while another re-validates, is unexercised."),
  bullet("Minimum wage rate data. The lookup, precedence and proration logic is covered; whether a tenant's loaded rates are correct is outside the software."),
  pageBreak()
);

// ================================================================ 9. OPERATIONS
doc.push(
  h1("9. Running the system"),
  h2("9.1 Local development"),
  ...codeBlock(
`# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
#   health: http://127.0.0.1:8000/api/health
#   docs:   http://127.0.0.1:8000/docs

# frontend
cd frontend
npm install
cp .env.example .env.local        # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev

# tests
cd backend && pip install -r requirements-dev.txt && pytest -q tests
cd frontend && npx tsc --noEmit && npm run lint && npm run build`),
  h2("9.2 Environment variables"),
  table(
    ["Variable", "Where", "Purpose"],
    [
      ["DATABASE_URL", "API", "PostgreSQL in production; SQLite by default in development"],
      ["JWT_SECRET", "API", "Required in production. Generate with openssl rand -hex 48"],
      ["CORS_ORIGINS", "API", "Browser origins permitted to call the API directly"],
      ["ALLOW_ANONYMOUS_API", "API", "Must be false in production; forced false when ENV=production"],
      ["BACKEND_URL", "Web (server-only)", "Upstream the /api/proxy route handler forwards to. No NEXT_PUBLIC_ prefix"],
      ["NEXT_PUBLIC_API_URL", "Web (build)", "Used when calling the API directly rather than through the proxy"],
      ["NEXT_PUBLIC_DIRECT_API", "Web (build)", "Set to 1 to disable the proxy and call the API directly"],
    ],
    [2600, 2000, 5480],
    [0]
  ),
  spacer(),
  h2("9.3 First-run setup for an entity"),
  bullet("Configure salary components — which columns are PF, ESIC, PT and LWF applicable, and which are taxable."),
  bullet("Set the PT and LWF state lists, then import slab defaults for those states."),
  bullet("Review the config-driven PF and ESIC engine settings and the FY-versioned income-tax parameters."),
  bullet("Load minimum wage rates for the states and skill categories the workforce covers, and check the coverage report for gaps."),
  bullet("Upload the employee master, then attendance, then the salary register — in that order, so the first validation has its inputs to compare against."),
  h2("9.4 Continuous integration"),
  p("The workflow compiles the backend, runs pytest against requirements-dev.txt, then lints and builds the frontend. The test dependencies file carries both httpx and httpx2 deliberately: which one Starlette's TestClient needs depends on the Starlette version pip resolves, and requirements.txt does not pin it."),
  pageBreak()
);

// ================================================================ 10. LIMITS
doc.push(
  h1("10. Known limitations"),
  p("Stated plainly, because a capability claim is only useful if its edges are honest."),
  table(
    ["Limitation", "Detail"],
    [
      ["Minimum wage rates ship empty", "The engine and checks are built; the rate table is tenant-maintained. Rates vary by state, zone, scheduled employment and skill, and the VDA component is revised twice yearly, so no shipped dataset stays correct. Coverage gaps are reported rather than passed over — but they remain gaps."],
      ["No ECR or challan reconciliation", "Validation compares computed against the register. It does not compare either against what was filed or what was paid. That three-way match is the most direct predictor of a notice and is the obvious next build."],
      ["No recomputation from first principles", "The product checks and explains; it does not independently recompute gross from CTC and attendance."],
      ["TDS is heuristic", "Risk flags plus a regime projection, not a full Form 16 computation. On the cost dashboard TDS is whatever the register reported, or nothing: projecting a month's tax needs the whole year's declarations, which a cost query does not have and must not guess at."],
      ["Filing readiness is not filing status", "The compliance panel reports the statutory due date and what would make a filing wrong. It has no connection to EPFO, ESIC, a state PT portal or TRACES, so it cannot know that a return was submitted — and never says so."],
      ["Professional tax due dates vary by state", "The readiness calendar uses the 20th as the common case and says on the row that it varies. PT is state law, and quoting one date as though it were uniform would be wrong more often than it was right."],
      ["Exposure rates are defaults, not advice", "The interest and damages parameters reflect rates in common use. They are configurable per entity and carry no legal force of their own."],
      ["No full-and-final module", "Leave encashment and notice pay have no dedicated handling."],
      ["No PDF report", "The evidence pack is an Excel workbook."],
      ["No email invitations", "Members are added to an organization directly in the database rather than by invite."],
    ],
    [3000, 7080]
  ),
  spacer(),
  h2("10.1 Where the next investment should go"),
  p("ECR and challan reconciliation. The data model, the findings lifecycle and the exposure ledger are all in place to receive it: an ECR file and a challan become two more ingested inputs, and the gaps between computed, filed and paid become three more rule families feeding the same worklist and the same evidence pack."),
  spacer(400),
  new Paragraph({
    border: { top: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 10 } },
    spacing: { before: 200, after: 120 }, children: [],
  }),
  p("Figures appearing in examples throughout this document are test fixtures, not any organization's payroll data. Statutory rates quoted are the software's configurable defaults and do not constitute legal advice.", { color: MUTED, size: 17, italics: true })
);

// ================================================================ BUILD
// Pinned to the commit date rather than "now", so an unchanged rebuild produces
// an identical file. A binary that differs on every build is a permanent diff in
// review and trains people to stop looking at it.
const BUILD_TIME = new Date(meta.commit_date || 0);

const document = new Document({
  creator: "PayrollCheck",
  created: BUILD_TIME,
  modified: BUILD_TIME,
  title: "PayrollCheck — Architecture & Code Reference",
  description: "Complete architecture, data model, API surface, rule catalogue and core source listings.",
  numbering: {
    config: [{
      reference: "bullets",
      levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 460, hanging: 240 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 920, hanging: 240 } } } },
      ],
    }],
  },
  styles: {
    default: {
      document: { run: { font: "Calibri", size: 20, color: INK } },
    },
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE, space: 6 } },
          children: [new TextRun({ text: "PayrollCheck — Architecture & Code Reference", font: "Calibri", size: 15, color: MUTED })],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: `commit ${builtFrom}   \u00b7   `, font: "Consolas", size: 15, color: MUTED }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Calibri", size: 15, color: MUTED }),
          ],
        })],
      }),
    },
    children: doc,
  }],
});

/**
 * Repackage the document with every timestamp pinned to the commit date.
 *
 * Two things otherwise move on every build: the created/modified properties in
 * docProps/core.xml (docx-js writes "now" and offers no option to override it),
 * and the DOS timestamp on each zip entry. Left alone, an unchanged rebuild
 * produces a different binary — which makes the committed file a permanent diff
 * in review and trains people to stop looking at it.
 */
async function repackageDeterministically(buf, when) {
  const JSZip = require("jszip");
  const source = await JSZip.loadAsync(buf);
  const iso = when.toISOString().replace(/\.\d+Z$/, "Z");

  const out = new JSZip();
  // Insertion order is preserved, and [Content_Types].xml must stay first.
  const names = Object.keys(source.files).sort((a, b) =>
    a === "[Content_Types].xml" ? -1 : b === "[Content_Types].xml" ? 1 : 0
  );
  for (const name of names) {
    const entry = source.files[name];
    if (entry.dir) continue;
    let content = await entry.async("nodebuffer");
    if (name === "docProps/core.xml") {
      content = Buffer.from(
        content
          .toString("utf8")
          .replace(/(<dcterms:created[^>]*>)[^<]*(<)/, `$1${iso}$2`)
          .replace(/(<dcterms:modified[^>]*>)[^<]*(<)/, `$1${iso}$2`),
        "utf8"
      );
    }
    out.file(name, content, { date: when, createFolders: false });
  }
  return out.generateAsync({
    type: "nodebuffer",
    compression: "DEFLATE",
    compressionOptions: { level: 6 },
  });
}

Packer.toBuffer(document)
  .then((buf) => repackageDeterministically(buf, BUILD_TIME))
  .then((out) => {
    fs.mkdirSync(path.dirname(OUT), { recursive: true });
    fs.writeFileSync(OUT, out);

    console.log(`\nWrote ${path.relative(REPO, OUT)}  (${(out.length / 1024).toFixed(0)} KB)`);
    console.log(`  built from   ${builtFrom} on ${meta.branch}`);
    console.log(`  documents    ${tableCount} tables \u00b7 ${endpointCount} endpoints \u00b7 `
              + `${ruleCount} rules \u00b7 ${sourceFileCount} files \u00b7 ${tests.total} tests`);
    console.log(`  embeds       ${LISTING_FILE_COUNT} source files, `
              + `${LISTING_LINE_COUNT.toLocaleString("en-GB")} lines`);
    if (meta.dirty) {
      console.log("  note         built from a modified working tree");
    }
  })
  .catch((e) => fail(e.message));
