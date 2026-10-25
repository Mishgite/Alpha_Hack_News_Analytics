import test from "node:test";
import assert from "node:assert/strict";
import { createInteractionTracker } from "../src/api/interactions.js";

test("parallel and repeated events are sent once per feed item and type", async () => {
  const calls = [];
  const tracker = createInteractionTracker({ request: async (...args) => {
    calls.push(args);
    return { ok: true };
  }});
  await Promise.all([tracker.impression("s1", "n1"), tracker.impression("s1", "n1")]);
  await tracker.impression("s1", "n1");
  await tracker.open("s1", "n1");
  await tracker.open("s1", "n1");
  await tracker.impression("s2", "n1");
  assert.equal(calls.length, 3);
  assert.equal(calls[1][1], "/api/news/n1/open");
  assert.deepEqual(Object.keys(calls[1][2]).sort(), ["event_id", "occurred_at", "snapshot_id"]);
  assert.equal(calls[0][2].news_id, "n1");
});

test("retry after a lost response reuses the event id and timestamp", async () => {
  const bodies = [];
  const tracker = createInteractionTracker({ request: async (method, path, body) => {
    bodies.push({ ...body });
    if (bodies.length === 1) throw new Error("network");
    return { ok: true };
  }});
  await assert.rejects(tracker.open("s1", "n1"));
  await tracker.open("s1", "n1");
  assert.deepEqual(bodies[0], bodies[1]);
});
