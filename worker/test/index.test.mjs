// node --test worker/test : the Worker sends one workflow_dispatch request with the token and the night mode.
import assert from "node:assert/strict";
import { test } from "node:test";
import { dispatch } from "../src/index.js";

test("dispatch posts to the workflow with the token and mode", async () => {
  const calls = [];
  const fake = async (url, init) => {
    calls.push({ url, init });
    return { status: 204 };
  };
  const r = await dispatch({ REPO: "o/r", GITHUB_TOKEN: "t0k", WORKFLOW: "live.yml", REF: "main" }, "night", fake);
  assert.equal(r.ok, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.github.com/repos/o/r/actions/workflows/live.yml/dispatches");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers.Authorization, "Bearer t0k");
  assert.deepEqual(JSON.parse(calls[0].init.body), { ref: "main", inputs: { mode: "night" } });
});

test("a refused token is reported, not ok", async () => {
  const r = await dispatch({ REPO: "o/r", GITHUB_TOKEN: "bad" }, "night", async () => ({ status: 401 }));
  assert.equal(r.ok, false);
  assert.equal(r.status, 401);
});
