import test from "node:test";
import assert from "node:assert/strict";
import { createHttpClient } from "../src/api/http.js";
import { analysisRevision, createAnalysisTracker } from "../src/api/analysis.js";

function storage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}
const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });

for (const oldRequest of ["/api/profile", "/api/auth/logout"]) {
  test(`запоздавший ответ ${oldRequest} не удаляет новую сессию`, async () => {
    let finishOld;
    let token = "old";
    const client = createHttpClient({
      baseUrl: "https://api.example", storage: storage(),
      fetcher: async (url, options) => {
        if (url.endsWith("/api/auth/demo")) return json({access_token: token, expires_at: new Date(Date.now() + 60000).toISOString()});
        if (options.headers.Authorization === "Bearer old") return new Promise(resolve => { finishOld = resolve; });
        assert.equal(options.headers.Authorization, "Bearer new");
        return json({company_id: "new-company"});
      },
    });
    await client.request("POST", "/api/auth/demo", {});
    const pending = client.request(oldRequest.endsWith("logout") ? "POST" : "GET", oldRequest);
    token = "new";
    await client.request("POST", "/api/auth/demo", {});
    finishOld(oldRequest.endsWith("logout") ? new Response(null, {status: 204}) : json({detail: "expired"}, 401));
    if (oldRequest.endsWith("logout")) await pending;
    else await assert.rejects(pending, {status: 401});
    assert.equal(client.hasSession(), true);
    assert.equal((await client.request("GET", "/api/profile")).company_id, "new-company");
  });
}

test("сессия передаётся в Bearer, 401 удаляет её, logout принимает пустой ответ", async () => {
  const saved = storage();
  const requests = [];
  let response = json({
    access_token: "test-token",
    expires_at: new Date(Date.now() + 60000).toISOString(),
  });
  const client = createHttpClient({
    baseUrl: "https://api.example/",
    storage: saved,
    fetcher: async (url, options) => {
      requests.push({ url, ...options });
      return response;
    },
  });
  await client.request("POST", "/api/auth/demo", { company_id: "demo" });
  response = json({ user: {} });
  await client.request("GET", "/api/profile");
  assert.equal(requests[1].headers.Authorization, "Bearer test-token");
  assert.equal(requests[1].url, "https://api.example/api/profile");
  assert.equal(requests[1].redirect, "error");
  response = json({ detail: "expired" }, 401);
  await assert.rejects(client.request("GET", "/api/profile"), { status: 401 });
  assert.equal(client.hasSession(), false);
  response = new Response(null, { status: 204 });
  assert.equal(await client.request("POST", "/api/auth/logout"), null);
});

test("ошибка FastAPI и HTML вместо JSON не становятся успешными данными", async () => {
  let response = json(
    { detail: [{ loc: ["body", "city"], msg: "invalid" }] },
    422,
  );
  const client = createHttpClient({
    baseUrl: "https://api.example",
    storage: storage(),
    fetcher: async () => response,
  });
  await assert.rejects(client.request("POST", "/api/auth/demo", {}), /город проживания/);
  response = new Response("<html>proxy error</html>", {
    headers: { "Content-Type": "text/html" },
  });
  await assert.rejects(client.request("GET", "/api/profile"), /Не удалось загрузить данные/);
  response = json({ detail: "Analysis worker unavailable" }, 503);
  await assert.rejects(
    client.request("POST", "/api/news/id/analysis", {}),
    /Разбор временно недоступен/,
  );
});

test("PDF возвращается Blob, таймаут не повторяет POST автоматически", async () => {
  const client = createHttpClient({
    baseUrl: "https://api.example",
    storage: storage(),
    fetcher: async () =>
      new Response("%PDF-1.4", {
        headers: { "Content-Type": "application/pdf" },
      }),
  });
  assert.equal(
    (await client.request("GET", "/api/report-chunks/id/document")).type,
    "application/pdf",
  );
  let count = 0;
  const stalled = createHttpClient({
    baseUrl: "https://api.example",
    storage: storage(),
    fetcher: async (_, options) => {
      count++;
      return new Promise((resolve, reject) =>
        options.signal.addEventListener("abort", () =>
          reject(new Error("aborted")),
        ),
      );
    },
  });
  await assert.rejects(
    stalled.request("POST", "/api/news/id/analysis", {}, { timeoutMs: 10 }),
    { status: 504 },
  );
  assert.equal(count, 1);
});

test("повтор потерянного запроса сохраняет ключ, перезагрузка продолжает то же задание", async () => {
  const saved = storage();
  const calls = [];
  let fail = true;
  const api = {
    async request(method, path, body) {
      calls.push({ method, path, body });
      if (fail) {
        fail = false;
        throw new Error("connection lost");
      }
      return { id: "job-id", status: "running" };
    },
  };
  const tracker = createAnalysisTracker(api, saved);
  await assert.rejects(tracker.start("user", "company", "news"));
  await tracker.start("user", "company", "news");
  assert.equal(calls[0].body.idempotency_key, calls[1].body.idempotency_key);
  const reloaded = createAnalysisTracker(api, saved);
  await reloaded.start("user", "company", "news");
  assert.equal(calls[2].method, "GET");
  assert.equal(
    reloaded.conversation("user", "result"),
    tracker.conversation("user", "result"),
  );
  assert.notEqual(
    reloaded.conversation("other-user", "result"),
    tracker.conversation("user", "result"),
  );
});

test("готовый разбор читается без POST, изменение новости требует нового задания", async () => {
  const saved = storage();
  const calls = [];
  const api = {
    async request(method, path) {
      calls.push(method);
      return { id: "job", status: "ready" };
    },
  };
  const tracker = createAnalysisTracker(api, saved);
  await tracker.start("user", "company", "news", "v1");
  tracker.complete(
    "user",
    "company",
    "news",
    new Date(Date.now() + 60000).toISOString(),
  );
  await tracker.start("user", "company", "news", "v1");
  assert.deepEqual(calls, ["POST", "GET"]);
  await tracker.start("user", "company", "news", "v2");
  assert.equal(calls.at(-1), "POST");
  tracker.complete("user", "company", "news", new Date(0).toISOString());
  await tracker.start("user", "company", "news", "v2");
  assert.equal(calls.at(-1), "POST");
});

test("одновременное открытие одного разбора отправляет один запрос", async () => {
  let release;
  const calls = [];
  const tracker = createAnalysisTracker({ request: async (...args) => {
    calls.push(args);
    return new Promise((resolve) => { release = resolve; });
  }}, storage());
  const first = tracker.start("user", "company", "news", "v1");
  const second = tracker.start("user", "company", "news", "v1");
  assert.equal(calls.length, 1);
  release({id: "job", status: "queued"});
  assert.deepEqual(await first, await second);
});

test("поздний ответ старой версии не заменяет новое задание", async () => {
  const requests = [];
  const tracker = createAnalysisTracker({ request: async (method, path) => {
    if (method === "GET") return {id: path.split("/").at(-1), status: "ready"};
    return new Promise((resolve) => requests.push(resolve));
  }}, storage());
  const old = tracker.start("user", "company", "news", "v1");
  const current = tracker.start("user", "company", "news", "v2");
  requests[1]({id: "new-job", status: "ready"});
  await current;
  requests[0]({id: "old-job", status: "ready"});
  await old;
  const restored = tracker.start("user", "company", "news", "v2");
  assert.equal(requests.length, 2);
  assert.equal((await restored).id, "new-job");
});

test("изменение даты, признаков или данных компании обновляет версию разбора", async () => {
  const company = { id: "company", profile_version: "v1", city: "Москва" };
  const news = { content_hash: "same-text", published_at: "2026-10-25T00:00:00Z", features: { summary: "Первый вариант" } };
  const initial = await analysisRevision(company, news);
  assert.equal(initial.length, 64);
  assert.equal(await analysisRevision({city: "Москва", profile_version: "v1", id: "company"}, news), initial);
  for (const changed of [
    { ...news, published_at: "2026-10-24T00:00:00Z" },
    { ...news, features: {summary: "Исправленный вариант"} },
    { ...news, tagging_version: "new-tagger" },
  ]) assert.notEqual(await analysisRevision(company, changed), initial);
  assert.notEqual(await analysisRevision({...company, city: "Казань"}, news), initial);
});

test("запрет записи в хранилище не восстанавливает забытое задание", async () => {
  const saved = storage();
  let writesFail = false;
  const unreliable = {
    getItem: saved.getItem,
    setItem: (key, value) => {
      if (writesFail) throw new Error("Quota exceeded");
      saved.setItem(key, value);
    },
  };
  const calls = [];
  const tracker = createAnalysisTracker({request: async (method) => {
    calls.push(method);
    return {id: "job", status: "ready"};
  }}, unreliable);
  await tracker.start("user", "company", "news", "v1");
  writesFail = true;
  tracker.forget("user", "company", "news");
  await tracker.start("user", "company", "news", "v1");
  assert.deepEqual(calls, ["POST", "POST"]);
});
