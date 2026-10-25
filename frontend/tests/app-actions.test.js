import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { marketLayout } from "../src/market-layout.js";
import { UserError, userMessage } from "../src/api/errors.js";

function element() {
  const attributes = new Map();
  const classes = new Set();
  return {
    innerHTML: "", textContent: "", value: "", disabled: false, hidden: false,
    isConnected: true, clientWidth: 600, dataset: {},
    classList: {
      add: (name) => classes.add(name), remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name), toggle() {},
    },
    setAttribute: (name, value) => attributes.set(name, value),
    removeAttribute: (name) => attributes.delete(name),
    hasAttribute: (name) => attributes.has(name),
    getAttribute: (name) => attributes.get(name),
    addEventListener() {}, querySelectorAll: () => [], focus() {},
    getBoundingClientRect: () => ({ height: 0 }),
  };
}

function application(request) {
  const nodes = new Map();
  const handlers = new Map();
  const node = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, element());
    return nodes.get(selector);
  };
  const context = vm.createContext({
    document: {
      querySelector: node, querySelectorAll: () => [],
      addEventListener: (name, handler) => handlers.set(name, handler),
      documentElement: { dataset: {} },
    },
    window: { addEventListener() {} }, location: { hash: "#market" },
    crypto, URL, Intl, console, UserError, userMessage, marketLayout,
    setTimeout: () => 1, clearTimeout() {},
    IntersectionObserver: class { disconnect() {} observe() {} },
    api: { request }, isDemo: false, roles: {}, paths: {},
    icon: () => '<svg aria-hidden="true"></svg>',
    createAnalysisTracker: () => ({}), createInteractionTracker: () => ({}),
  });
  const source = readFileSync(new URL("../src/app.js", import.meta.url), "utf8")
    .replace(/^import\s[\s\S]*?;\s*/gm, "")
    .replace(/hydrate\(\);\s*theme\(\);\s*render\(\);\s*$/, "");
  vm.runInContext(source + "\nthis.app = { state, market, feed, reason, feedPreferences, interestSettings, changeProfile, renderConversation, invalidate: () => ++generation };", context);
  return {
    app: context.app, node,
    click: (button) => handlers.get("click")({ target: {
      closest: (selector) => selector === "button" ? button : null,
    } }),
  };
}

const overview = () => ({
  status: "ready", size_basis: "turnover_rub", top_movers: [],
  heatmap: [{ ticker: "SBER", name: "Сбербанк", size_metric: 100, color_metric: 1,
    change_percent: 1, turnover_rub: 100, as_of: "2026-10-23T20:50:00Z" }],
});

test("кнопка обновления биржи делает POST к источнику, чтение экрана делает GET", async () => {
  const requests = [];
  const ui = application(async (...args) => { requests.push(args); return overview(); });
  await ui.app.market();
  const button = ui.node('[data-action="market-refresh"]');
  button.dataset.action = "market-refresh";
  await ui.click(button);
  assert.equal(requests[0][0], "GET");
  assert.equal(requests[0][1], "/api/market?limit=20");
  assert.equal(requests[1][0], "POST");
  assert.equal(requests[1][1], "/api/market/refresh?limit=20");
  assert.match(ui.node("#market-content").innerHTML, /Цены на/);
  assert.equal(button.disabled, false);
});

test("повторное нажатие не дублирует запрос, поиск во время загрузки сохраняется", async () => {
  let finish;
  let calls = 0;
  const ui = application(() => { calls++; return new Promise(resolve => { finish = resolve; }); });
  const first = ui.app.market(true);
  await ui.app.market(true);
  assert.equal(calls, 1);
  ui.node("#market-search").value = "Сбер";
  finish(overview());
  await first;
  assert.equal(ui.node("#market-search").value, "Сбер");
  assert.equal(ui.node("#market-count").textContent, "Найдено: 1");
  assert.equal(ui.node('[data-action="market-refresh"]').disabled, false);
});

test("сбой обновления сохраняет карту и разрешает повторную попытку", async () => {
  const ui = application(async () => { throw new Error("upstream unavailable"); });
  ui.node("#market-content").innerHTML = "saved chart";
  await ui.app.market(true);
  assert.equal(ui.node("#market-content").innerHTML, "saved chart");
  assert.match(ui.node("#toast").textContent, /Не удалось обновить/);
  assert.equal(ui.node('[data-action="market-refresh"]').disabled, false);
});

test("ответ биржи после перехода не заменяет содержимое другой страницы", async () => {
  let finish;
  const ui = application(() => new Promise(resolve => { finish = resolve; }));
  const pending = ui.app.market(true);
  ui.app.invalidate();
  ui.node("#market-content").innerHTML = "another page";
  finish(overview());
  await pending;
  assert.equal(ui.node("#market-content").innerHTML, "another page");
});

test("фильтр ленты отправляется серверу, истёкшая подборка создаётся заново", async () => {
  const requests = [];
  const ui = application(async (...args) => {
    requests.push(args);
    return { snapshot_id: "new", items: [], has_more: false, expires_at: new Date(Date.now() + 60000).toISOString() };
  });
  ui.app.state.profile = { personal_tag_ids: [], company_tags: [], disabled_tag_ids: [] };
  ui.app.state.days = 1;
  await ui.app.feed(true);
  assert.equal(requests[0][0], "POST");
  assert.equal(requests[0][1], "/api/feed");
  assert.equal(requests[0][2].days, 1);
  await ui.app.feed(true);
  assert.equal(requests.length, 1);
  ui.app.state.feed.expires_at = "2020-01-01T00:00:00Z";
  await ui.app.feed(true);
  assert.equal(requests.length, 2);
});

test("источники ответа различимы, текст ответа не исполняется как HTML", () => {
  const ui = application(async () => {});
  ui.app.state.messages = [{ question: "Вопрос", answer: "<script>alert(1)</script>", sources_json: [
    {id: "company:test", kind: "company", title: "Снимок профиля"},
    {id: "news:one", kind: "news", title: "Новость об экспорте"},
  ] }];
  ui.app.renderConversation();
  const html = ui.node("#conversation").innerHTML;
  assert.match(html, /Данные компании/);
  assert.match(html, /Новость об экспорте/);
  assert.doesNotMatch(html, /<script>/);
});


test("ручная и автоматическая тема показываются одним переключателем", () => {
  const ui = application(async () => {});
  ui.app.state.profile = { personal_tag_ids: [], disabled_tag_ids: [], company_tags: [
    {tag_id: "biz_it", origin: "rule"}, {tag_id: "biz_it", origin: "manual"},
  ] };
  ui.app.state.tags = [{id: "biz_it", display_name: "IT"}];
  assert.equal((ui.app.feedPreferences().match(/name="company-topic"/g) || []).length, 1);
});

test("отключение личной темы не отправляет противоречащие настройки", () => {
  const ui = application(async () => {});
  ui.app.state.profile = { disabled_tag_ids: ["biz_old"], company_tags: [
    {tag_id: "biz_it", origin: "rule"}, {tag_id: "biz_it", origin: "manual"},
    {tag_id: "biz_tax", origin: "rule"},
  ] };
  const form = new FormData();
  form.append("company-topic", "biz_tax");
  for (const id of ["biz_it", "biz_tax", "biz_tax", "biz_old"]) form.append("personal", id);
  const settings = JSON.parse(JSON.stringify(ui.app.interestSettings(form)));
  assert.deepEqual(settings, {personal: ["biz_tax"], disabled: ["biz_old", "biz_it"]});
});

test("сбой сохранения профиля не оставляет видимую ленту без данных", async () => {
  const ui = application(async () => {});
  const feed = {snapshot_id: "saved", items: []};
  const analysis = {id: "saved-analysis"};
  ui.app.state.feed = feed;
  ui.app.state.analysis = analysis;
  ui.app.state.messages = [{question: "Вопрос", answer: "Ответ"}];
  await assert.rejects(ui.app.changeProfile(async () => {throw new Error("offline");}));
  assert.equal(ui.app.state.feed, feed);
  assert.equal(ui.app.state.analysis, analysis);
  assert.equal(ui.app.state.messages.length, 1);
  await ui.app.changeProfile(async () => ({}));
  assert.equal(ui.app.state.feed, null);
  assert.equal(ui.app.state.analysis, null);
  assert.equal(ui.app.state.messages.length, 0);
});
