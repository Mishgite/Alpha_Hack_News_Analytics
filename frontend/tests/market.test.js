import test from "node:test";
import assert from "node:assert/strict";
import { marketLayout } from "../src/market-layout.js";

test("площадь каждого прямоугольника пропорциональна обороту без перекрытий", () => {
  const values = [64, 20, 10, 5, 1].map((size_metric) => ({ size_metric }));
  const rectangles = marketLayout(values, 800, 500);
  for (const r of rectangles) {
    assert.ok(
      Math.abs((r.width * r.height) / 400000 - r.size_metric / 100) < 1e-10,
    );
    assert.ok(
      r.x >= 0 &&
        r.y >= 0 &&
        r.x + r.width <= 800.001 &&
        r.y + r.height <= 500.001,
    );
    for (const other of rectangles) {
      if (r === other) continue;
      const overlapW =
        Math.min(r.x + r.width, other.x + other.width) - Math.max(r.x, other.x);
      const overlapH =
        Math.min(r.y + r.height, other.y + other.height) -
        Math.max(r.y, other.y);
      assert.ok(overlapW < 1e-8 || overlapH < 1e-8);
    }
  }
});

test("пустая карта и нулевой оборот не приводят к делению на ноль", () => {
  assert.deepEqual(marketLayout([], 300, 400), []);
  const rectangles = marketLayout(
    [{ size_metric: 0 }, { size_metric: 0 }],
    300,
    400,
  );
  assert.equal(rectangles[0].width * rectangles[0].height, 60000);
});
