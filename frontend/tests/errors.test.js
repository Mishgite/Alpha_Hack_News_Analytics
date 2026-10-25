import test from "node:test";
import assert from "node:assert/strict";
import { createHttpClient, ApiError } from "../src/api/http.js";
import { UserError, userMessage } from "../src/api/errors.js";

const storage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
const response = (detail, status) => new Response(JSON.stringify({ detail }), {
  status, headers: { "Content-Type": "application/json" },
});
const forbidden = /worker|CORS|SQL|VITE_|internal_key|snapshot_id|TypeError|обработчик|сервер|модель/i;

for (const status of [400, 403, 404, 409, 418, 422, 429, 500, 502, 503, 504]) {
  test(`HTTP ${status}: внутреннее описание не попадает в текст интерфейса`, async () => {
    const detail = "SQL worker internal_key CORS snapshot_id";
    const api = createHttpClient({ baseUrl: "https://example.test", storage,
      fetcher: async () => response(detail, status) });
    await assert.rejects(api.request("GET", "/api/feed"), (error) => {
      assert.equal(error.status, status);
      assert.equal(error.diagnostic, detail);
      assert.doesNotMatch(userMessage(error), forbidden);
      return true;
    });
  });
}

test("валидация показывает названия полей без путей и исходных значений", async () => {
  const api = createHttpClient({ baseUrl: "https://example.test", storage,
    fetcher: async () => response([
      { loc: ["body", "city"], msg: "SQL internal_key", input: "secret" },
      { loc: ["body", "snapshot_id"], msg: "Invalid UUID" },
      { loc: ["body", "city"] }, null,
    ], 422) });
  await assert.rejects(api.request("POST", "/api/auth/demo", {}), (error) => {
    assert.equal(userMessage(error), "Проверьте поля: город проживания");
    return true;
  });
});

test("неожиданная ошибка не выводится напрямую, подсказка формы сохраняется", () => {
  assert.doesNotMatch(userMessage(new TypeError("internal_key is undefined")), forbidden);
  assert.equal(userMessage(new UserError("Укажите город проживания")), "Укажите город проживания");
  assert.equal(userMessage(new ApiError("Разбор временно недоступен", 503)), "Разбор временно недоступен");
});

test("ошибки настройки, сети и формата ответа имеют понятные сообщения", async () => {
  const cases = [
    { baseUrl: "", fetcher: async () => { throw new Error("unused"); } },
    { baseUrl: "https://example.test", fetcher: async () => { throw new TypeError("CORS worker"); } },
    { baseUrl: "https://example.test", fetcher: async () => new Response("{broken", { headers: { "Content-Type": "application/json" } }) },
  ];
  for (const config of cases) {
    const api = createHttpClient({ ...config, storage });
    await assert.rejects(api.request("GET", "/api/feed"), (error) => {
      assert.ok(error instanceof ApiError);
      assert.doesNotMatch(userMessage(error), forbidden);
      return true;
    });
  }
});
