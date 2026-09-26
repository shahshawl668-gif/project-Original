const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function harness(fetch) {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  let expire;
  const globals = {
    fetch, localStorage: storage, window: { location: { hostname: "localhost" } },
    process: { env: {} }, Headers, FormData, AbortController, atob,
    setTimeout: (callback) => { expire = callback; return 1; },
    clearTimeout: () => {},
  };
  function load(file, imports = {}) {
    const module = { exports: {} };
    const source = fs.readFileSync(path.join(__dirname, "../src/lib", file), "utf8");
    const js = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    }).outputText;
    vm.runInNewContext(js, { ...globals, module, exports: module.exports,
      require: (name) => {
        if (!(name in imports)) throw new Error("Unexpected import: " + name);
        return imports[name];
      },
    }, { filename: file });
    return module.exports;
  }
  const api = load("api.ts");
  const auth = load("auth.ts", { "@/lib/api": api });
  return { ...auth, api, storage, expire: () => expire() };
}

const tokens = { access_token: "new-access", refresh_token: "new-refresh" };
const user = { id: "user-1", email: "test@example.com", company_name: "Test", role: "user" };
const ok = (data) => Response.json({ success: true, data, error: null });
const failure = (status, detail) => Response.json({
  success: false, data: null, error: { detail },
}, { status });

test("sign-in loads the profile with the new token and bypasses cached responses", async () => {
  const calls = [];
  const h = harness(async (url, init) => {
    calls.push({ url, init });
    return url.endsWith("/login") ? ok(tokens) : ok(user);
  });
  const actual = await h.signIn(" test@example.com ", "password");
  assert.equal(actual.id, user.id);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].init.headers.get("Authorization"), "Bearer new-access");
  assert.equal(JSON.parse(calls[0].init.body).email, "test@example.com");
  assert.ok(calls.every(({ init }) => init.cache === "no-store"));
});

test("invalid credentials are reported instead of completing sign-in", async () => {
  const h = harness(async () => failure(401, "Invalid email or password"));
  await assert.rejects(h.signIn("test@example.com", "wrong"), /Invalid email or password/);
  assert.equal(h.api.getAccessToken(), null);
});

test("network failures are propagated to the login form", async () => {
  const h = harness(async () => { throw new TypeError("Network unavailable"); });
  await assert.rejects(h.signIn("test@example.com", "password"), /Network unavailable/);
  assert.equal(h.api.getAccessToken(), null);
});

test("invalid JSON is reported and leaves no session", async () => {
  const h = harness(async () => new Response("<html>Unavailable</html>", { status: 502 }));
  await assert.rejects(h.signIn("test@example.com", "password"), /Invalid JSON/);
  assert.equal(h.api.getAccessToken(), null);
});

test("profile failure clears the tokens issued by login", async () => {
  const h = harness(async (url) => url.endsWith("/login")
    ? ok(tokens) : failure(503, "Profile temporarily unavailable"));
  await assert.rejects(h.signIn("test@example.com", "password"), /Profile temporarily unavailable/);
  assert.equal(h.api.getAccessToken(), null);
  assert.equal(h.api.getRefreshToken(), null);
});

test("a hung login is aborted with a retryable error", async () => {
  const h = harness((_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(new Error("aborted")));
  }));
  const pending = h.signIn("test@example.com", "password");
  h.expire();
  await assert.rejects(pending, /Sign-in took too long/);
});

test("an incomplete token response cannot create an authenticated session", async () => {
  const h = harness(async () => ok({ access_token: "only-access" }));
  await assert.rejects(h.signIn("test@example.com", "password"), /incomplete session/);
  assert.equal(h.api.getAccessToken(), null);
});

for (const status of [200, 401]) {
  test("an old refresh response cannot overwrite a new login (status " + status + ")", async () => {
    let respond;
    const h = harness(() => new Promise((resolve) => { respond = resolve; }));
    h.api.setTokens("old-access", "old-refresh");
    const pending = h.api.refreshSession();
    h.api.setTokens(tokens.access_token, tokens.refresh_token);
    respond(status === 200
      ? ok({ access_token: "stale-access", refresh_token: "stale-refresh" })
      : failure(401, "Expired"));
    assert.equal(await pending, false);
    assert.equal(h.api.getAccessToken(), tokens.access_token);
    assert.equal(h.api.getRefreshToken(), tokens.refresh_token);
  });
}
