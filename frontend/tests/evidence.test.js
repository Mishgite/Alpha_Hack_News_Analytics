import test from "node:test";
import assert from "node:assert/strict";
import { statementEvidence, featureValue } from "../src/api/evidence.js";

test("один источник может подтверждать разные выводы разными цитатами", () => {
  const result = {
    facts: [
      { source_refs: ["news:1"], evidence_quotes: { "news:1": "Первый факт" } },
    ],
    why_important: [
      { source_refs: ["news:1"], evidence_quotes: { "news:1": "Второй факт" } },
    ],
    risks: [],
    opportunities: [],
    recommendations: [],
    bank_position: null,
  };
  assert.equal(statementEvidence(result, "0", "news:1"), "Первый факт");
  assert.equal(statementEvidence(result, "1", "news:1"), "Второй факт");
  assert.equal(statementEvidence(result, "0", "report:1"), null);
  assert.equal(statementEvidence(result, undefined, "news:1"), null);
});

test("снимок сохраняет нулевые и отрицательные признаки, отсутствующие не выдумываются", () => {
  const context = {
    payload_json: { revenue: 0, profile_json: { FTS_FLAG: false } },
  };
  assert.equal(featureValue(context, "revenue"), 0);
  assert.equal(featureValue(context, "FTS_FLAG"), false);
  assert.equal(featureValue(context, "region"), null);
});
