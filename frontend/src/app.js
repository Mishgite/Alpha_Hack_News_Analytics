import { UserError, userMessage } from "./api/errors.js";
import { paths, icon } from "./icons.js";
import { api, isDemo, roles } from "./api/index.js";
import { analysisRevision, createAnalysisTracker } from "./api/analysis.js";
import { createInteractionTracker } from "./api/interactions.js";
import {
  analysisStatements,
  statementEvidence,
  featureValue,
} from "./api/evidence.js";
import { marketLayout } from "./market-layout.js";
import "./styles.css";

const tracker = createAnalysisTracker(api, {
  getItem: (key) => sessionStorage.getItem(key),
  setItem: (key, value) => sessionStorage.setItem(key, value),
});
const interactions = createInteractionTracker(api);
Object.assign(paths, {
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  moon: '<path d="M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  minus: '<path d="M5 12h14"/>',
  external: '<path d="M14 3h7v7m0-7L10 14M10 3H3v18h18v-7"/>',
});
const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)];
const main = $("#main"),
  dialog = $("#panel");
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const date = (v) =>
  v
    ? new Intl.DateTimeFormat("ru-RU", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Europe/Moscow",
      }).format(new Date(v)) + " МСК"
    : "Не указано";
const money = (v) =>
  v === null || v === undefined
    ? "Нет данных"
    : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(v);
const tagLabel = (value) => {
  const parts = String(value || "").split(" / ");
  return parts.find((part) => /[А-Яа-яЁё]/.test(part)) || String(value || "");
};
const tagName = (id) =>
  tagLabel(state.tags.find((t) => t.id === id)?.display_name || id);
const tag = (id) => `<span class="tag">${esc(tagName(id))}</span>`;
const state = {
  profile: null,
  feed: null,
  feedDays: null,
  days: null,
  analysis: null,
  article: null,
  market: null,
  conversation: crypto.randomUUID(),
  messages: [],
  tags: [],
  conversations: new Map(),
};
let generation = 0,
  toastTimer,
  opener,
  closeTimer;
let profileChange = null;
async function changeProfile(operation) {
  if (profileChange) throw new UserError("Дождитесь сохранения профиля");
  ++generation;
  state.feed = null;
  state.analysis = null;
  state.messages = [];
  observer.disconnect();
  profileChange = Promise.resolve().then(operation);
  try {
    return await profileChange;
  } finally {
    profileChange = null;
  }
}
const route = () => location.hash.slice(1) || "home";
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
function hydrate() {
  $$("[data-icon]").forEach((x) => (x.innerHTML = icon(x.dataset.icon)));
}
function theme() {
  const dark = document.documentElement.dataset.theme === "dark";
  $$(".theme-button").forEach((button) => {
    button.innerHTML = icon(dark ? "sun" : "moon");
    button.setAttribute(
      "aria-label",
      dark ? "Включить светлую тему" : "Включить тёмную тему",
    );
  });
}
async function connection() {
  panel(
    "Состояние сервисов",
    '<p role="status">Проверяем доступность…</p>',
  );
  const target = $("#panel-body");
  try {
    await api.request("GET", "/health");
    const status = api.hasSession()
      ? await api.request("GET", "/api/status")
      : null;
    if (!dialog.open || $("#panel-title").textContent !== "Состояние сервисов")
      return;
    target.innerHTML = status
      ? `<dl class="facts-list"><div><dt>Данные приложения</dt><dd>${status.database === "ready" ? "Доступны" : "Временно недоступны"}</dd></div><div><dt>Обновление новостей</dt><dd>${status.worker_alive ? "Работает" : "Временно приостановлено"}</dd></div><div><dt>Разбор событий</dt><dd>${status.analysis_available ? "Доступен" : "Временно недоступен"}</dd></div></dl>`
      : "<p>Приложение доступно. Для проверки остальных функций войдите в профиль</p>";
  } catch (error) {
    if (dialog.open && $("#panel-title").textContent === "Состояние сервисов")
      target.innerHTML = failure(error, "connection");
  }
}
function toast(text) {
  $("#toast").textContent = text;
  $("#toast").classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("#toast").classList.remove("visible"), 4500);
}
function panel(title, body) {
  clearTimeout(closeTimer);
  dialog.classList.remove("closing");
  dialog.classList.remove("demo-dialog", "reason-dialog", "settings-dialog");
  $("#panel-title").textContent = title;
  $("#panel-body").innerHTML = body;
  if (!dialog.open) {
    opener = document.activeElement;
    dialog.showModal();
  }
  dialog.scrollTop = 0;
}
function closePanel() {
  if (!dialog.open) return;
  dialog.classList.add("closing");
  clearTimeout(closeTimer);
  closeTimer = setTimeout(
    () => {
      dialog.close();
      dialog.classList.remove("closing");
      if (opener?.isConnected) opener.focus({ preventScroll: true });
      else main.focus({ preventScroll: true });
    },
    reduced() ? 0 : 150,
  );
}
function failure(e, retry = "retry", title = "Не получилось загрузить данные") {
  const expired = e.status === 401;
  return `<div class="error-state" role="alert">${icon("info")}<h2>${expired ? "Нужно войти снова" : esc(title)}</h2><p>${esc(userMessage(e))}</p><button class="button primary" data-action="${expired ? "login" : retry}">${expired ? "Войти в демо" : "Попробовать снова"}</button></div>`;
}
function inlineError(form, e) {
  let el = form.querySelector(".form-error");
  if (!el) {
    el = document.createElement("p");
    el.className = "form-error";
    el.setAttribute("role", "alert");
    form.append(el);
  }
  el.textContent = userMessage(e);
}
function skeleton() {
  return `<div class="loading-block" aria-busy="true"><div class="loading-label" role="status"><span class="spinner"></span>Загружаем…</div>${[0, 1, 2].map(() => '<div class="skeleton-card"><span class="skeleton short"></span><span class="skeleton long"></span><span class="skeleton"></span><span class="skeleton medium"></span></div>').join("")}</div>`;
}
function heading(title, subtitle) {
  return `<div class="page-heading"><div><h1>${title}</h1><p>${subtitle}</p></div></div>`;
}
async function home() {
  const token = generation;
  main.innerHTML = heading("Главная", "Сервисы для вашего бизнеса") + `
    <section class="bank-overview" aria-label="Банковские сервисы">
      <div class="bank-preview"><span class="overview-icon">${icon("wallet")}</span><div><h2>Счета</h2><p>Остатки и реквизиты</p></div></div>
      <div class="bank-preview"><span class="overview-icon">${icon("card")}</span><div><h2>Платежи</h2><p>Переводы и история операций</p></div></div>
      <p class="bank-preview-note">Счета и платежи недоступны в демонстрации</p>
    </section>
    <div class="overview-grid">
      <section class="insights-widget" aria-labelledby="widget-title">
        <header class="widget-heading"><div><span class="widget-label">Для вашего бизнеса</span><h2 id="widget-title">Бизнес-инсайты</h2><p>Новости и их влияние на компанию</p></div><a class="button primary" href="#news">Открыть ${icon("arrow")}</a></header>
        <div id="overview-news" aria-live="polite"><p class="widget-status"><span class="spinner"></span>Подбираем новости…</p></div>
      </section>
      <a class="market-shortcut" href="#market"><span class="overview-icon">${icon("chart")}</span><h2>Биржевой обзор</h2><p>Котировки и изменения на рынке</p><span class="market-shortcut-link">Смотреть обзор ${icon("arrow")}</span></a>
    </div>`;
  try {
    if (!state.feed || state.feedDays !== 7 || Date.parse(state.feed.expires_at) <= Date.now()) {
      const result = await api.request("POST", "/api/feed", { days: 7, page_size: 20 });
      if (token !== generation) return;
      state.feed = result;
      state.feedDays = 7;
    }
    if (token !== generation) return;
    $("#overview-news").innerHTML = state.feed.items.length
      ? state.feed.items.slice(0, 3).map((item) => `<article class="preview-story" data-news="${esc(item.ranking.news_id)}"><div class="preview-meta">${esc(sourceName(item.source_url))} · ${date(item.published_at)}</div><button data-impression="${esc(item.ranking.news_id)}" data-action="article" data-id="${esc(item.ranking.news_id)}">${esc(item.title)}${icon("chevron")}</button></article>`).join("")
      : '<p class="widget-status">Свежих новостей пока нет</p>';
    observeImpressions();
  } catch (error) {
    if (token !== generation) return;
    $("#overview-news").innerHTML = `<div class="widget-status" role="alert"><p>${esc(userMessage(error))}</p><button class="text-button" data-action="refresh">Повторить</button></div>`;
  }
}
function roleOptions(selected) {
  return Object.entries(roles)
    .map(
      ([id, name]) =>
        `<option value="${esc(id)}" ${selected === id ? "selected" : ""}>${name}</option>`,
    )
    .join("");
}
async function demoSetup() {
  main.innerHTML = `<div class="onboarding"><div class="onboarding-tools"><a class="back-link" href="#news">← Вернуться в приложение</a><button class="icon-button theme-button" data-action="theme" aria-label="Сменить тему"></button></div><div class="onboarding-intro"><span class="eyebrow">Демонстрация</span><h1>Компания и должность</h1></div><form id="demo-role-form" class="form-card"><label>Должность<select name="job_role">${roleOptions(state.profile.user.job_role)}</select></label><button class="button primary" type="submit">Применить</button></form><section class="form-card"><h2>Компания</h2><p>${esc(state.profile.company.industry || state.profile.company.id)}</p><p class="field-hint">${[state.profile.company.id, state.profile.company.city].filter(Boolean).map(esc).join(" · ")}</p><button class="text-button" data-action="company-info">О компании ${icon("arrow")}</button><label>Найти компанию<input id="company-search" type="search" aria-label="Поиск компании" placeholder="ID, отрасль, ОКВЭД, город или регион"></label><div id="company-results"></div><div id="catalog-status" aria-live="polite"></div></section><button class="text-button" data-action="${isDemo ? "scenarios" : "connection"}">${isDemo ? "Сценарии проверки" : "Состояние сервисов"}</button></div>`;
  theme();
  await loadCompanies("");
}
async function login() {
  const token = generation;
  const companies = await api.request(
    "GET",
    "/api/companies?limit=50&demo_selection=true",
  );
  if (token !== generation) return;
  main.innerHTML = `<div class="onboarding">
    <div class="onboarding-tools">${api.hasSession() ? '<a class="back-link" href="#news">← К подборке</a>' : ""}<button class="icon-button theme-button" data-action="theme" aria-label="Сменить тему"></button></div>
    <div class="onboarding-intro">
      <span class="eyebrow">Демовход</span>
      <h1>Настройка профиля</h1>
    </div>
    <form id="login-form" class="form-card">
      <label>Найти компанию<input id="company-search" type="search" aria-label="Поиск компании" placeholder="ID, отрасль, ОКВЭД, город или регион"></label>
      <label>Компания<select id="login-company" name="company_id" aria-label="Компания" required></select></label>
      <div id="catalog-status" aria-live="polite"></div>

      <label>Должность<select name="job_role">${roleOptions("ceo")}</select></label>
      <button class="button primary large" type="submit">Открыть кабинет ${icon("arrow")}</button>
    </form>
  </div>`;
  catalog = { query: "", items: companies };
  companyResults(companies);
  theme();
}
function sourceName(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return isDemo ? "Учебная публикация" : "Источник не указан";
  }
}
function feedCard(item, index) {
  const id = item.ranking.news_id;
  return `<article class="news-card" data-news="${esc(id)}" style="--order:${Math.min(index, 3)}"><div class="news-meta"><span class="source-dot">${icon("document")}</span>${esc(sourceName(item.source_url))}<span class="meta-divider">·</span><time datetime="${esc(item.published_at)}">${date(item.published_at)}</time></div><h2 data-impression="${esc(id)}"><button data-action="article" data-id="${esc(id)}">${esc(item.title)}</button></h2><p class="summary">${esc(item.summary)}</p><div class="news-topics"><div class="topic-line">${item.tags.map(tag).join("")}</div><div class="topic-tools"><button class="why-button" data-action="reason" data-id="${esc(id)}">Почему в подборке ${icon("info")}</button><button class="edit-topics" data-action="tag-feedback" data-id="${esc(id)}" aria-expanded="false" aria-controls="tag-editor-${esc(id)}">Исправить темы</button></div><div class="tag-editor" id="tag-editor-${esc(id)}" hidden></div></div><div class="news-actions"><button class="button ${index === 0 ? "primary" : "outline"}" data-action="analyse" data-id="${esc(id)}">${icon("spark")}Разобрать влияние ${icon("arrow")}</button><button class="text-button" data-action="article" data-id="${esc(id)}">Читать новость</button></div><div class="feedback" role="group" aria-label="Приоритет похожих тем"><div><button class="feedback-button ${item.my_reaction === "like" ? "selected" : ""}" data-reaction="like" data-id="${esc(id)}" aria-pressed="${item.my_reaction === "like"}">${icon("plus")}Больше таких тем</button><button class="feedback-button ${item.my_reaction === "dislike" ? "selected" : ""}" data-reaction="dislike" data-id="${esc(id)}" aria-pressed="${item.my_reaction === "dislike"}">${icon("minus")}Меньше таких тем</button></div></div></article>`;
}
function feedBody() {
  const f = state.feed;
  if (!f) return;
  $("#feed-results").innerHTML = f.items.length
    ? `<div class="feed-list">${f.items.map(feedCard).join("")}</div><div class="pagination">${f.has_more ? '<button class="button secondary" data-action="more">Показать ещё 20 ' + icon("plus") + "</button>" : "<span>Конец подборки</span>"}<span>Показано ${f.items.length}</span></div>`
    : `<div class="empty-state">${icon("document")}<h2>${state.days === null ? "Подходящих новостей пока нет" : "За этот период новостей нет"}</h2><p>${state.days !== null ? "Сбросьте фильтр, чтобы вернуться к обычной подборке" : "Можно посмотреть более ранние публикации"}</p>${state.days !== null ? '<button class="button secondary" data-action="reset-feed-filter">Сбросить фильтр</button>' : '<button class="button secondary" data-action="expand-period">Более ранние новости</button>'}</div>`;
  observeImpressions();
}
async function feed(reuse = false) {
  main.innerHTML =
    heading(
      "Бизнес-инсайты",
      "Новости, которые стоит проверить в контексте вашей компании",
    ) +
    `<div class="feed-toolbar"><div><h2>Новости для вас</h2></div><div class="toolbar-actions"><button class="button secondary" data-action="feed-filters" aria-expanded="false" aria-controls="feed-filters">${icon("sliders")}Фильтр${state.days !== null ? '<span class="filter-count">1</span>' : ""}</button><button class="button secondary" data-action="refresh">${icon("refresh")}Обновить</button></div></div>
    <form id="feed-filters" class="feed-filters" hidden><fieldset><legend>Дата публикации</legend><div class="date-options">${[[0, "По умолчанию"], [1, "За сутки"], [7, "За неделю"], [30, "За месяц"]].map(([value, label]) => `<label><input type="radio" name="days" value="${value}" ${(state.days ?? 0) === value ? "checked" : ""}><span>${label}</span></label>`).join("")}</div></fieldset><div class="filter-actions"><button class="button primary" type="submit">Применить</button><button class="text-button" type="button" data-action="reset-feed-filter">Сбросить</button></div></form>
    ${state.days !== null ? `<div class="active-filters"><button class="filter-chip" data-action="reset-feed-filter" aria-label="Убрать фильтр по дате">${{1: "За сутки", 7: "За неделю", 30: "За месяц"}[state.days]} ${icon("close")}</button></div>` : ""}<div id="feed-results">${skeleton()}</div>`;
  const token = generation;
  try {
    if (
      !reuse ||
      !state.feed ||
      state.feedDays !== (state.days ?? 7) ||
      Date.parse(state.feed.expires_at) <= Date.now()
    ) {
      const result = await api.request("POST", "/api/feed", {
        days: state.days ?? 7,
        page_size: 20,
      });
      if (token !== generation) return;
      state.feed = result;
      state.feedDays = state.days ?? 7;
    }
    if (token !== generation) return;
    feedBody();
  } catch (e) {
    if (token === generation)
      $("#feed-results").innerHTML = failure(e, "refresh");
  }
}
function createImpressionObserver() {
  const bottom = $(".mobile-nav")?.getBoundingClientRect().height || 0;
  const watcher = new IntersectionObserver(
    (entries) => {
      for (const e of entries)
        if (
          e.isIntersecting &&
          e.target.isConnected &&
          e.intersectionRatio >= 0.5 &&
          document.visibilityState === "visible" &&
          !dialog.open &&
          state.feed?.items.some((item) => item.ranking.news_id === e.target.dataset.impression)
        ) {
          interactions
            .impression(state.feed.snapshot_id, e.target.dataset.impression)
            .then(() => watcher.unobserve(e.target))
            .catch(() => {});
        }
    },
    { threshold: 0.5, rootMargin: `0px 0px -${bottom}px 0px` },
  );
  return watcher;
}
let observer = createImpressionObserver();
function observeImpressions() {
  observer.disconnect();
  observer = createImpressionObserver();
  $$("[data-impression]").forEach((x) => observer.observe(x));
}

let impressionResizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(impressionResizeTimer);
  impressionResizeTimer = setTimeout(observeImpressions, 100);
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") observeImpressions();
});
dialog.addEventListener("close", observeImpressions);
let catalog = { query: "", items: [] };
let searchVersion = 0;
let searchTimer;
async function loadCompanies(query) {
  const version = ++searchVersion;
  const target = $("#catalog-status");
  if (!target) return;
  catalog.query = query;
  target.textContent = "Загружаем компании…";
  const select = $("#login-company");
  if (select) {
    select.disabled = true;
    $('#login-form [type="submit"]').disabled = true;
  }
  if ($("#company-results")) $("#company-results").innerHTML = "";
  try {
    const items = await api.request(
      "GET",
      `/api/companies?limit=50&demo_selection=true&query=${encodeURIComponent(query)}`,
    );
    if (version !== searchVersion || !target.isConnected) return;
    catalog = { query, items };
    companyResults(items);
  } catch (error) {
    if (version === searchVersion && target.isConnected)
      target.innerHTML = `<p class="form-error">${esc(userMessage(error))}</p><button type="button" class="text-button" data-action="catalog-retry">Повторить поиск</button>`;
  }
}
function companyResults(items) {
  const options = items
    .map(
      (c) =>
        `<option value="${esc(c.id)}">${esc(c.id)} · ${esc(c.industry || "Отрасль неизвестна")} · ${esc(c.city || "Город неизвестен")}</option>`,
    )
    .join("");
  const select = $("#login-company");
  if (select) {
    select.innerHTML =
      options || '<option value="">Компании не найдены</option>';
    select.disabled = !items.length;
    $('#login-form [type="submit"]').disabled = !items.length;
  } else if ($("#company-results")) {
    $("#company-results").innerHTML = items
      .map(
        (c) =>
          `<button class="company-option ${c.id === state.profile.user.company_id ? "selected" : ""}" data-company="${esc(c.id)}"><span class="company-option-icon">${icon("people")}</span><span><strong>${esc(c.id)}</strong><b>${esc(c.industry || "Отрасль неизвестна")}</b><small>${esc(c.city || "Город неизвестен")} · ОКВЭД ${esc(c.okved_code || "неизвестен")}</small></span>${c.id === state.profile.user.company_id ? icon("check") : icon("arrow")}</button>`,
      )
      .join("");
  }
  $("#catalog-status").textContent = items.length
    ? ""
    : "Компании не найдены. Попробуйте другую отрасль, город или ID";
}
function interests() {
  const p = state.profile;
  const selected = new Set(p.personal_tag_ids);
  const option = (t) => `<label><input type="checkbox" name="personal" value="${esc(t.id)}" ${selected.has(t.id) ? "checked" : ""}>${esc(tagLabel(t.display_name))}</label>`;
  main.innerHTML = `<section class="interests-page"><a class="back-link" href="#news">← К подборке</a><header><h1>Темы подборки</h1><p>Какие темы учитывать в ваших новостях</p></header><form id="interests-form">
    <section class="interest-section"><h2>Темы бизнеса</h2><p class="field-hint">Определены по деятельности компании. Ненужные темы можно отключить.</p><div class="topic-options">${p.company_tags.map((t) => `<label><input type="checkbox" name="company-topic" value="${esc(t.tag_id)}" ${p.disabled_tag_ids.includes(t.tag_id) ? "" : "checked"}><span><strong>${esc(tagName(t.tag_id))}</strong></span></label>`).join("") || '<p class="field-hint">Темы ещё не определены. Можно добавить свои ниже.</p>'}</div></section>
    <section class="interest-section"><h2>Личные интересы</h2><div class="personal-options">${state.tags.filter((t) => selected.has(t.id)).map(option).join("") || '<p class="field-hint">Дополнительные темы не выбраны</p>'}</div><details class="interest-catalog"><summary>Добавить темы</summary><label>Поиск темы<input type="search" id="topic-search" placeholder="Например, кредитование"></label><div class="personal-options searchable-topics">${state.tags.filter((t) => !selected.has(t.id)).map(option).join("")}</div><p class="field-hint tag-search-empty" hidden>Темы не найдены</p></details></section>
    <p class="field-hint">Отключённые темы бизнеса не учитываются, даже если выбраны в личных интересах.</p><div class="sticky-form-actions"><button class="button primary" type="submit">Сохранить</button><a class="button ghost" href="#news">Отмена</a></div></form></section>`;
}
function companyInfo() {
  const c = state.profile.company;
  const credit = c.profile_json?.CL_PRODUCT_LOA_MARK;
  const hasCredit = ["1", "1.0", 1, true].includes(credit) || (c.known_factor_interests || []).includes("credit");
  panel(
    "О компании",
    `<p>${esc(c.id)}</p><dl class="facts-list"><div><dt>Деятельность</dt><dd>${esc(c.okved_name || c.industry || "Нет данных")}${c.okved_code ? `<small>ОКВЭД ${esc(c.okved_code)}</small>` : ""}</dd></div><div><dt>Выручка</dt><dd>${c.revenue == null ? "Нет данных" : money(Number(c.revenue) / 1e9) + " млрд ₽"}</dd></div><div><dt>Регистрация</dt><dd>${esc([...new Set([c.city, c.region].filter(Boolean))].join(", ") || "Нет данных")}</dd></div><div><dt>Кредитные продукты</dt><dd>${hasCredit ? "Есть" : ["0", "0.0", 0, false].includes(credit) ? "Нет" : "Нет данных"}</dd></div><div><dt>Регионы деятельности</dt><dd>${c.operating_region_codes?.length ? esc(c.operating_region_codes.join(", ")) : "Не указаны"}</dd></div>${c.group_id ? `<div><dt>Группа компаний</dt><dd>${esc(c.group_id)}</dd></div>` : ""}</dl><p class="field-hint">Регистрация не означает, что компания работает только в этом регионе</p>`,
  );
}
async function settings() {
  if (!state.profile && api.hasSession())
    state.profile = await api.request("GET", "/api/profile");
  if (!state.profile) {
    location.hash = "login";
    return;
  }
  panel(
    "Настройки",
    `<a class="settings-link" href="#interests">${icon("sliders")}Темы подборки ${icon("arrow")}</a><button class="text-button danger" data-action="logout">Выйти</button>`,
  );
  dialog.classList.add("settings-dialog");
}
function reason(id) {
  const item = state.feed?.items.find((item) => item.ranking.news_id === id);
  if (!item) return;
  const r = item.ranking;
  const hasGeography = ["formula-v2-geography", "formula-v3-business-context"].includes(r.ranking_version);
  const topics = r.matched_signals.length
    ? `<p>Эти темы совпали с вашими настройками и повысили позицию новости:</p><div class="tags">${r.matched_signals.map(tag).join("")}</div>`
    : "<p>Совпадений с вашими темами нет. Новость попала в подборку за счёт свежести.</p>";
  const geography = hasGeography
    ? `<section><h3>Регион</h3><p>${(r.geography_factor ?? 1) < 1 ? "Событие относится к другому региону. Поэтому его приоритет ниже." : r.geography_bonus > 0 ? esc(r.geography_reason) + ". Это повысило позицию новости." : r.geography_score == null ? "География не уточнена и не влияет на порядок." : r.geography_score > 0 ? "Регион совпал, но совпадений по темам нет. Поэтому география не повысила позицию новости." : "География новости не совпала с данными компании. Дополнительный приоритет за регион не добавлен."}</p></section>`
    : "";
  panel("Почему эта новость", `<p class="reason-article">${esc(item.title)}</p><section><h3>Совпадение тем</h3>${topics}</section><section><h3>Свежесть</h3><p>Опубликована ${date(item.published_at)}. Более свежие новости получают больший приоритет.</p></section>${geography}`);
  dialog.classList.add("reason-dialog");
}
async function article(id) {
  const token = generation;
  const snapshot = state.feed?.items.some((item) => item.ranking.news_id === id)
    ? state.feed.snapshot_id
    : null;
  const a = await api.request("GET", "/api/news/" + id);
  if (token !== generation) return;
  panel(
    a.title,
    `<div class="news-meta">${esc(sourceName(a.source_url))} · ${date(a.published_at)}</div><div class="tags">${(a.features?.tags || []).map((t) => tag(t.id)).join("")}</div><p class="article-text">${esc(a.text)}</p>${safeUrl(a.source_url) ? `<a class="button secondary" target="_blank" rel="noopener noreferrer" href="${esc(safeUrl(a.source_url))}">Открыть первоисточник ${icon("external")}</a>` : `<div class="notice">Ссылка на первоисточник отсутствует</div>`}<button class="button primary" data-action="analyse" data-id="${esc(id)}">${icon("spark")}Разобрать влияние на компанию</button>`,
  );
  if (snapshot) interactions.open(snapshot, id).catch(() => {});
}
function tagFeedback(button) {
  const id = button.dataset.id;
  const target = button.closest(".news-topics").querySelector(".tag-editor");
  if (target.querySelector('[type="submit"]')?.disabled) return;
  if (!target.hidden) {
    target.hidden = true;
    button.setAttribute("aria-expanded", "false");
    return;
  }
  const a = state.feed?.items.find((a) => a.ranking.news_id === id);
  if (!a) return;
  if (!target.hasChildNodes()) {
    target.innerHTML = `<form class="tag-form" data-id="${esc(id)}" data-snapshot="${esc(state.feed.snapshot_id)}" aria-label="Исправление тем новости"><h3>Убрать неверные темы</h3>${a.tags.length ? `<div class="personal-options">${a.tags.map((t) => `<label><input type="checkbox" name="wrong" value="${esc(t)}">${esc(tagName(t))}</label>`).join("")}</div>` : '<p class="field-hint">У новости пока нет тем</p>'}<h3>Предложить недостающие темы</h3><label>Найти тему<input type="search" data-topic-search placeholder="Название темы"></label><div class="personal-options searchable-topics">${state.tags
      .filter((t) => !a.tags.includes(t.id))
      .map(
        (t) =>
          `<label><input type="checkbox" name="suggested" value="${esc(t.id)}">${esc(tagLabel(t.display_name))}</label>`,
      )
      .join(
        "",
      )}</div><p class="field-hint tag-search-empty" hidden>Темы не найдены</p><p class="field-hint">Исправление отправится на проверку. Личные интересы не изменятся.</p><div class="tag-editor-actions"><button class="button secondary" type="submit">Отправить исправление</button><button class="text-button" type="button" data-action="cancel-tag-feedback">Отмена</button></div></form>`;
  }
  target.hidden = false;
  button.setAttribute("aria-expanded", "true");
}
function analysisFrame(a, body) {
  main.innerHTML = `<a class="back-link" href="#news">← К подборке</a><div class="analysis-heading"><span class="eyebrow">AI-разбор события</span><h1>${esc(a.title)}</h1><div class="news-meta">${date(a.published_at)} <span>·</span> ${esc(sourceName(a.source_url))}</div></div>${body}`;
}
async function analyse(id) {
  const version = generation;
  state.analysis = null;
  state.article = null;
  state.messages = [];
  state.conversation = crypto.randomUUID();
  try {
    const a = await api.request("GET", "/api/news/" + id);
    if (version !== generation) return;
    state.article = a;
    analysisFrame(
      a,
      `<section class="analysis-loading"><div class="analysis-orb">${icon("spark")}</div><h2 id="job-label">Загружаем разбор</h2><p>Оцениваем влияние новости на ваш бизнес</p><div class="job-progress"><i></i></div><a class="text-button" href="#news">Вернуться к ленте</a></section>`,
    );
    const revision = await analysisRevision(state.profile.company, a);
    if (version !== generation) return;
    let job = await tracker.start(
      state.profile.user.id,
      state.profile.company.id,
      id,
      revision,
    );
    const pollingStarted = Date.now();
    while (job.status !== "ready" && job.status !== "failed") {
      if (version !== generation) return;
      $("#job-label").textContent =
        job.status === "queued"
          ? "Разбор в очереди"
          : "Анализируем событие и проверяем источники";
      if (Date.now() - pollingStarted > 180000) {
        throw new UserError(
          "Разбор ещё готовится. Можно вернуться к ленте и открыть его позже",
        );
      }
      await new Promise((r) => setTimeout(r, isDemo ? 650 : 2500));
      if (version !== generation) return;
      job = await api.request("GET", "/api/analysis-jobs/" + job.id);
    }
    if (version !== generation) return;
    if (job.status === "failed")
      throw Object.assign(
        new UserError(
          "Не удалось подготовить проверенный разбор. Можно повторить попытку",
        ),
        { status: 503 },
      );
    const result = await api.request("GET", "/api/analyses/" + job.analysis_id);
    if (version !== generation) return;
    state.analysis = result;
    tracker.complete(
      state.profile.user.id,
      state.profile.company.id,
      id,
      result.expires_at,
    );
    state.conversation = tracker.conversation(state.profile.user.id, result.id);
    renderAnalysis();
    try {
      const messages = await api.request(
        "GET",
        `/api/analyses/${result.id}/conversations/${state.conversation}?limit=50`,
      );
      if (version !== generation) return;
      state.messages = messages;
      renderConversation();
    } catch (error) {
      if (version === generation)
        toast(
          "Разбор готов, но историю вопросов не удалось загрузить. Попробуйте открыть её позже",
        );
    }
  } catch (e) {
    if (version === generation)
      analysisFrame(
        state.article || { title: "AI-разбор", published_at: null },
        failure(e, "retry", "Не удалось открыть разбор"),
      );
  }
}
function statements(items) {
  return items.length
    ? items
        .map(
          (s) =>
            `<div class="statement"><p>${esc(s.text)} ${s.source_refs.map((ref) => `<button class="citation" data-source="${esc(ref)}" data-statement="${analysisStatements(state.analysis.result).indexOf(s)}" aria-label="Открыть источник ${state.analysis.result.source_refs.findIndex((r) => r.id === ref) + 1}">${state.analysis.result.source_refs.findIndex((r) => r.id === ref) + 1}</button>`).join("")}</p>${s.condition ? `<span class="condition">Условие: ${esc(s.condition)}</span>` : ""}${s.company_feature_refs.length ? `<button class="feature-link" data-action="statement-features" data-statement="${analysisStatements(state.analysis.result).indexOf(s)}">Данные для вывода ${icon("arrow")}</button>` : ""}</div>`,
        )
        .join("")
    : '<p class="muted">Недостаточно подтверждённых данных</p>';
}
async function statementFeatures(index) {
  const version = generation;
  const statement = analysisStatements(state.analysis.result)[Number(index)];
  if (!statement) return;
  const context = await api.request(
    "GET",
    `/api/analyses/${state.analysis.id}/context`,
  );
  if (version !== generation) return;
  const labels = {
    okved_code: "Код ОКВЭД",
    okved_name: "Деятельность",
    industry: "Отрасль",
    revenue: "Выручка, ₽",
    city: "Город регистрации",
    region: "Регион регистрации",
    country_code: "Страна",
    registered_region_code: "Код региона регистрации",
    operating_region_codes: "Регионы деятельности",
    known_factor_interests: "Факторы бизнеса",
    CL_PRODUCT_RKO_MARK: "Расчётно-кассовое обслуживание",
    CL_PRODUCT_GAR_MARK: "Гарантии",
    CL_PRODUCT_LOA_MARK: "Кредитные продукты",
    CL_PRODUCT_LEA_MARK: "Лизинг",
    CL_PRODUCT_DEP_MARK: "Депозиты",
    CL_PRODUCT_ZPP_MARK: "Зарплатный проект",
    FACTORING_MARK: "Факторинг",
    FTS_FLAG: "Внешнеэкономическая деятельность",
    FTS_COUNTRY_NAME: "Страны внешнеэкономической деятельности",
    AMOUNT_WORKERS_FNS_GRADATION: "Диапазон численности работников",
    COMPANY_AGE_YEARS_GRADATION: "Возраст компании",
  };
  const origin = context.payload_json.profile_json?._source;
  const rows = statement.company_feature_refs
    .map((key) => {
      const value = featureValue(context, key);
      const display =
        value == null
          ? "Данные отсутствуют"
          : /(?:_MARK|_FLAG)$/.test(key) && [true, false, 0, 1, "0", "1", "0.0", "1.0"].includes(value)
            ? ([true, 1, "1", "1.0"].includes(value) ? "Есть" : "Нет")
          : key === "revenue" && Number.isFinite(Number(value))
            ? money(Number(value))
          : key === "country_code" && value === "RU"
            ? "Россия"
          : Array.isArray(value)
            ? value.join(", ")
            : typeof value === "object"
              ? JSON.stringify(value)
              : String(value);
      const origins = (context.payload_json.features || []).filter(
        (item) => item.key === key,
      );
      return `<div><dt>${esc(labels[key] || "Дополнительные данные")}</dt><dd>${esc(display)}${origins.length ? `<details class="data-origin"><summary>Источник данных</summary>${origins.map((item) => `<small>${esc([item.origin_file, item.origin_field, item.calc_method].filter(Boolean).join(" · "))}</small>`).join("")}</details>` : ""}</dd></div>`;
    })
    .join("");
  panel(
    "Данные для вывода",
    `<p>${esc(statement.text)}</p><dl class="facts-list">${rows}</dl><p class="field-hint">Данные компании на момент разбора</p>${origin ? `<details class="data-origin"><summary>Исходный документ</summary><p>${esc(origin.file)} · строка ${esc(origin.record)}</p></details>` : ""}`,
  );
}
function renderAnalysis() {
  const a = state.analysis,
    r = a.result;
  analysisFrame(
    state.article,
    `<div class="analysis-layout"><div class="analysis-main"><div class="saved-analysis"><button class="text-button" data-action="update-analysis">Проверить актуальность</button></div>${a.status === "partial" ? `<div class="notice warning analysis-limitations"><strong>Разбор готов с ограничениями</strong>${r.limitations.length ? `<p>${esc(r.limitations[0])}</p>` : ""}${r.limitations.length > 1 ? `<details><summary>Остальные ограничения</summary><ul>${r.limitations.slice(1).map((value) => `<li>${esc(value)}</li>`).join("")}</ul></details>` : ""}</div>` : ""}<section class="analysis-section"><div class="section-heading"><h2>Что произошло</h2></div>${statements(r.facts)}</section><section class="analysis-section"><div class="section-heading"><h2>Влияние на компанию</h2><span class="ai-label">Вывод AI</span></div>${statements(r.why_important)}<div class="impact-grid"><div class="impact risk"><h3>${icon("info")}Возможные риски</h3>${statements(r.risks)}</div><div class="impact opportunity"><h3>${icon("plus")}Возможности</h3>${statements(r.opportunities)}</div></div></section><section class="bank-section"><div class="section-heading"><h2>Материалы банка</h2></div>${r.bank_position ? `<span class="label-badge">${isDemo ? "Синтетический пример, не позиция Альфа-Банка" : "Вывод по материалу банка"}</span>${statements([r.bank_position])}` : "<p>Подходящий материал не найден. Выводы AI выше не являются позицией Альфа-Банка.</p>"}</section><section class="analysis-section"><div class="section-heading"><h2>Что проверить дальше</h2></div><ol class="recommendations">${r.recommendations.map((s) => `<li>${statements([s])}</li>`).join("")}</ol></section><section class="question-section"><div><h2>Вопрос по разбору</h2></div><div class="suggested-questions"><button data-question="Каких данных не хватает для оценки влияния?">Каких данных не хватает?</button><button data-question="Что проверить в первую очередь?">Что проверить сначала?</button></div><div id="conversation" aria-live="polite"></div><form id="question-form"><label class="sr-only" for="question">Вопрос по разбору</label><textarea id="question" name="question" required maxlength="1000" placeholder="Например, как это связано с расходами компании?" rows="2"></textarea><div><button class="button primary" type="submit">Задать вопрос ${icon("arrow")}</button></div></form></section></div><aside class="analysis-aside"><section class="sources-card"><h3>Источники разбора <span>${r.source_refs.length}</span></h3>${r.source_refs.map((s, i) => `<button class="source-row" data-source="${esc(s.id)}"><span class="source-number">${i + 1}</span><span><strong>${esc(s.title)}</strong><small>${s.kind === "company" ? "Данные компании" : s.kind === "bank_report" ? "Материал банка · стр. " + s.page : "Новостной материал"}${s.published_on ? " · " + s.published_on : ""}</small></span>${icon("arrow")}</button>`).join("")}</section><button class="trace-button" data-action="trace">${icon("sliders")}Как получен разбор ${icon("arrow")}</button><p class="fine">Выводы AI могут содержать ошибки. Сверяйтесь с источниками.</p></aside></div>`,
  );
}
function renderConversation() {
  if (!$("#conversation")) return;
  $("#conversation").innerHTML = state.messages
    .map(
      (m) =>
        `<div class="chat-question">${esc(m.question)}</div><div class="chat-answer">${icon("spark")}<div><p>${esc(m.answer)}</p>${
          (m.sources_json || [])
            .filter(
              (s) => s && typeof s === "object" && typeof s.id === "string",
            )
            .map(
              (s) =>
                `<button class="text-button" data-source="${esc(s.id)}">Источник ответа ${icon("arrow")}</button>`,
            )
            .join("") ||
          '<small class="muted">Подтверждающие источники не найдены</small>'
        }</div></div>`,
    )
    .join("");
}
const documentUrls = new Map();
function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}
async function source(ref, statementIndex) {
  const token = generation;
  const s =
    state.analysis?.result.source_refs.find((s) => s.id === ref) ||
    state.messages
      .flatMap((message) => message.sources_json || [])
      .find((source) => source && source.id === ref);
  if (!s) return;
  let documentLink = "",
    sourceError = "";
  if (s.kind === "bank_report" && s.id.startsWith("report:")) {
    const chunkId = s.id.slice(7);
    try {
      await api.request("GET", "/api/report-chunks/" + chunkId);
      if (!documentUrls.has(chunkId)) {
        const file = await api.request(
          "GET",
          "/api/report-chunks/" + chunkId + "/document",
        );
        documentUrls.set(chunkId, URL.createObjectURL(file));
      }
      documentLink = `<a class="button primary" href="${documentUrls.get(chunkId)}#page=${s.page || 1}" target="_blank" rel="noopener noreferrer">Открыть PDF · стр. ${s.page || 1} ${icon("external")}</a>`;
    } catch (error) {
      sourceError = userMessage(error);
    }
  }
  if (token !== generation) return;
  const external = safeUrl(s.url);
  const quote = statementEvidence(state.analysis.result, statementIndex, ref);
  panel(
    s.title,
    `<div class="source-details"><span class="label-badge">${s.kind === "company" ? "Профиль компании" : s.kind === "bank_report" ? "Материал банка" : "Публикация"}</span>${s.published_on ? `<p>Дата: ${esc(s.published_on)}</p>` : ""}${s.page ? `<p>Страница ${s.page}</p>` : ""}<h3>${quote ? "Цитата" : "Фрагмент источника"}</h3><blockquote>${esc(quote || s.excerpt || "Фрагмент не сохранён")}</blockquote>${isDemo ? '<p class="field-hint">Синтетический источник</p>' : ""}${sourceError ? `<p class="form-error">${esc(sourceError)}</p>` : ""}${documentLink || (external ? `<a class="button secondary" href="${esc(external)}" target="_blank" rel="noopener noreferrer">Открыть первоисточник ${icon("external")}</a>` : '<p class="field-hint">Оригинал источника недоступен</p>')}</div>`,
  );
}
window.addEventListener("beforeunload", () =>
  documentUrls.forEach((url) => URL.revokeObjectURL(url)),
);
function traceDescription(step) {
  if (step.step === "company_context")
    return "Отрасль и данные выбранной компании";
  if (step.step === "plan") return (step.queries || []).join("; ");
  if (step.step === "search_reports")
    return "Найдено фрагментов: " + (step.chunks || []).length;
  if (step.step === "validation")
    return step.valid === false || step.supported === false
      ? "Проверка не пройдена, результат отправлен на исправление"
      : "Структура и ссылки проверены. Замечаний: " +
          (step.issues || []).length;
  if (step.step === "complete")
    return "Источников: " + (step.sources || []).length;
  if (step.step === "cache_hit") return "Открыт ранее подготовленный разбор";
  return "Этап завершён";
}
async function trace() {
  const version = generation;
  const steps = await api.request(
    "GET",
    `/api/analyses/${esc(state.analysis.id)}/trace`,
  );
  if (version !== generation) return;
  const names = {
    company_context: "Контекст компании",
    plan: "План анализа",
    search_reports: "Поиск материалов банка",
    validation: "Проверка выводов",
    complete: "Результат сохранён",
    cache_hit: "Использован сохранённый разбор",
  };
  panel(
    "Как получен разбор",
    `<p class="muted">${isDemo ? "Учебный пример разбора" : "Этапы подготовки разбора"}</p><ol class="trace-list">${steps.map((s) => `<li><strong>${names[s.step] || "Обработка данных"}</strong><p>${esc(traceDescription(s))}</p></li>`).join("")}</ol>`,
  );
}
const change = (n) =>
  n === null || n === undefined
    ? "Нет данных"
    : `${n > 0 ? "+" : ""}${n.toFixed(2).replace(".", ",")}%`;
let marketLimit = 30;
window.addEventListener("resize", () => {
  if ($(".heatmap") && state.market) renderMarketTiles();
});
function renderMarketTiles() {
  const query = $("#market-search")?.value.trim().toLocaleLowerCase("ru") || "";
  const items = state.market.heatmap
    .filter((t) =>
      (t.ticker + " " + t.name).toLocaleLowerCase("ru").includes(query),
    )
    .sort(
      (a, b) =>
        b.size_metric - a.size_metric || a.ticker.localeCompare(b.ticker),
    );
  const shown = items.slice(0, marketLimit);
  const width = $(".heatmap").clientWidth;
  const height = 480;
  const rectangles = marketLayout(shown, width, height);
  $(".heatmap").innerHTML = shown.length
    ? rectangles
        .map(
          (t) =>
            `<button class="market-tile ${t.color_metric === null ? "unknown" : t.color_metric === 0 ? "neutral" : t.color_metric > 0 ? "up" : "down"}" data-ticker="${esc(t.ticker)}" title="${esc(t.ticker + ": " + t.name + " · " + change(t.change_percent))}" aria-label="${esc(t.ticker + ": " + t.name + " · " + change(t.change_percent))}" style="left:${t.x}px;top:${t.y}px;width:${t.width}px;height:${t.height}px"><strong>${esc(t.width >= 45 && t.height >= 30 ? t.ticker : "")}</strong>${t.width >= 70 && t.height >= 70 ? `<span>${change(t.change_percent)}</span>` : ""}${t.width >= 120 && t.height >= 120 ? `<small>${esc(t.name)}</small>` : ""}</button>`,
        )
        .join("")
    : '<p class="empty-inline">Инструменты не найдены</p>';
  $("#market-count").textContent =
    query ? `Найдено: ${items.length}` : `На карте: ${rectangles.length} из ${items.length}`;
  $("#market-more").hidden = shown.length >= items.length;
  $("#market-size").textContent =
    state.market.size_basis === "equal" ||
    !shown.some((item) => item.size_metric > 0)
      ? "Размер одинаковый: нет данных об обороте"
      : "Размер блока — объём торгов";
  $("#market-instruments").innerHTML = shown
    .map(
      (item) =>
        `<button class="source-row" data-ticker="${esc(item.ticker)}"><span><strong>${esc(item.ticker)} · ${esc(item.name)}</strong><small>${change(item.change_percent)} · оборот ${money(item.turnover_rub)} ₽</small></span>${icon("arrow")}</button>`,
    )
    .join("");
}
async function market() {
  main.innerHTML =
    heading(
      "Биржевой обзор",
      "Котировки и изменения цен",
    ) +
    '<div id="market-content">' +
    skeleton() +
    "</div>";
  const token = generation;
  try {
    const m = await api.request("GET", "/api/market?limit=20");
    if (token !== generation) return;
    state.market = m;
    $("#market-content").innerHTML =
      `<div class="market-heading"><div><h2>Карта рынка</h2><p>${isDemo ? "Учебные котировки" : "MOEX · изменение к предыдущему закрытию"}</p></div><button class="button secondary" data-action="refresh">${icon("refresh")}Обновить</button></div>${m.status === "stale" ? '<div class="notice warning">Котировки пока не обновились. Показаны последние доступные цены.</div>' : ""}${m.status === "empty" ? '<div class="empty-state"><h2>Котировки пока недоступны</h2><p>Попробуйте обновить страницу позже</p><a class="button primary" href="#news">К новостям</a></div>' : `<div class="market-layout"><div><label class="market-search">Найти инструмент<input type="search" id="market-search" placeholder="Тикер или название"></label><div id="market-count" class="field-hint" aria-live="polite"></div><div class="heatmap"></div><details class="market-instruments"><summary>Инструменты списком</summary><div id="market-instruments"></div></details><button class="button secondary" id="market-more" data-action="market-more">Показать ещё 30</button><div class="heatmap-legend"><span id="market-size">Размер: ${m.size_basis === "equal" ? "равные доли, оборот неизвестен" : "денежный оборот"}</span><span>− Снижение <i></i> Рост +</span></div></div><section class="movers"><h3>Наибольшие изменения</h3>${m.top_movers.map((t) => `<button data-ticker="${esc(t.ticker)}"><span><strong>${esc(t.ticker)}</strong><small>${esc(t.name)}</small></span><strong class="${t.change_percent > 0 ? "positive" : t.change_percent < 0 ? "negative" : ""}">${change(t.change_percent)}</strong></button>`).join("")}</section></div>`}`;
    marketLimit = 30;
    if (m.status !== "empty") renderMarketTiles();
  } catch (e) {
    if (token === generation) $("#market-content").innerHTML = failure(e);
  }
}
function scenarios() {
  panel(
    "Сценарии демо",
    `<p>Учебные примеры работы приложения</p><label>Состояние<select id="scenario" aria-label="Состояние">${[
      ["normal", "Обычная работа / неполный разбор"],
      ["complete", "Разбор с учебным отчётом"],
      ["conflict", "Отчёт старше события"],
      ["network", "Ошибка загрузки / сервис недоступен"],
      ["empty", "Нет новостей / котировок"],
      ["expired", "Истёк срок подборки"],
      ["session", "Сессия завершена"],
      ["limit", "Достигнут лимит AI"],
      ["failed", "Не удалось подготовить разбор или ответ"],
      ["stale", "Устаревшие котировки"],
    ]
      .map(
        ([id, label]) =>
          `<option value="${esc(id)}" ${id === api.getScenario() ? "selected" : ""}>${label}</option>`,
      )
      .join(
        "",
      )}</select></label><p class="field-hint">Выбранный сценарий применяется к следующему действию</p><button class="button primary" data-action="apply-scenario">Применить</button><hr><button class="text-button" data-action="login">Показать экран первого входа</button>`,
  );
}
async function render() {
  const version = ++generation;
  observer.disconnect();
  clearTimeout(closeTimer);
  if (dialog.open) dialog.close();
  dialog.classList.remove("closing");
  if (!location.hash) history.replaceState(history.state, "", "#home");
  const path = route();
  const setup = path === "login" || path === "demo" || !api.hasSession();
  document.body.classList.toggle("profile-setup", setup);
  $$("[data-nav]").forEach((el) => {
    const active =
      el.dataset.nav ===
      (path === "home" ? "home" : path === "market" ? "market" : path === "interests" ? "interests" : "news");
    el.toggleAttribute("aria-current", active);
    if (active) el.setAttribute("aria-current", "page");
  });
  main.classList.remove("arrive");
  void main.offsetWidth;
  main.classList.add("arrive");
  window.scrollTo({ top: 0, behavior: "instant" });
  document.title = setup
    ? (path === "demo" ? "Компания и должность · Демонстрация" : "Настройка профиля")
    : (path === "home" ? "Главная" : path === "interests" ? "Темы подборки" : path === "market"
          ? "Биржевой обзор"
          : "Бизнес-инсайты") +
      " · Альфа" +
      (isDemo ? " · Демо" : "");
  if (path === "login" || !api.hasSession()) {
    main.innerHTML = skeleton();
    try {
      await login();
    } catch (error) {
      if (version === generation) main.innerHTML = failure(error);
    }
    return;
  }
  main.innerHTML = skeleton();
  try {
    if (profileChange) await profileChange;
    if (version !== generation) return;
    const [profile, tags] = await Promise.all([
      api.request("GET", "/api/profile"),
      api.request("GET", "/api/tags"),
    ]);
    if (version !== generation) return;
    if (JSON.stringify(state.profile) !== JSON.stringify(profile)) state.feed = null;
    state.profile = profile;
    state.tags = tags.sort((a, b) =>
      tagLabel(a.display_name).localeCompare(tagLabel(b.display_name), "ru"),
    );
    if (path === "home") await home();
    else if (path === "news") await feed(true);
    else if (path === "market") await market();
    else if (path === "interests") interests();
    else if (path === "demo") await demoSetup();
    else if (path.startsWith("analysis/")) await analyse(path.slice(9));
    else
      main.innerHTML =
        '<div class="empty-state"><h1>Страница не найдена</h1><a class="button primary" href="#news">К подборке</a></div>';
  } catch (e) {
    if (version === generation) main.innerHTML = failure(e);
  }
}
async function refresh() {
  state.feed = null;
  await render();
}
document.addEventListener("click", async (e) => {
  if (e.target.closest(".settings-link")) closePanel();
  if (e.target.closest(".skip-link")) {
    e.preventDefault();
    main.focus();
    return;
  }
  const b = e.target.closest("button");
  if (!b) return;
  if (b.hasAttribute("data-close")) {
    closePanel();
    return;
  }
  const action = b.dataset.action,
    id = b.dataset.id;
  try {
    if (action === "theme") {
      const next =
        document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try {
        localStorage.setItem("alfa-theme", next);
      } catch {}
      theme();
      return;
    }
    if (action === "scenarios" && isDemo) scenarios();
    if (action === "market-more") {
      marketLimit += 30;
      renderMarketTiles();
    }
    if (action === "connection") await connection();
    if (action === "apply-scenario" && isDemo) {
      api.setScenario($("#scenario").value);
      closePanel();
      toast(
        "Сценарий выбран. Выполните действие или обновите страницу сервиса",
      );
    }
    if (action === "login") {
      if (isDemo) api.setScenario("normal");
      closePanel();
      if (route() === "login") await render();
      else location.hash = "login";
    }
    if (action === "settings") await settings();
    if (action === "demo-setup") location.hash = "demo";

    if (action === "catalog-retry") await loadCompanies(catalog.query);
    if (action === "company-info") companyInfo();
    if (action === "statement-features") await statementFeatures(b.dataset.statement);
    if (action === "reason") reason(id);
    if (action === "article") await article(id);
    if (action === "tag-feedback") tagFeedback(b);
    if (action === "cancel-tag-feedback") {
      const container = b.closest(".news-topics");
      const form = b.closest("form");
      if (form.querySelector('[type="submit"]').disabled) return;
      const opener = container.querySelector('[data-action="tag-feedback"]');
      container.querySelector(".tag-editor").replaceChildren();
      container.querySelector(".tag-editor").hidden = true;
      opener.setAttribute("aria-expanded", "false");
      opener.focus();
    }
    if (action === "analyse") {
      closePanel();
      location.hash = "analysis/" + id;
    }
    if (action === "trace") await trace();
    if (action === "update-analysis" && state.article) {
      tracker.forget(
        state.profile.user.id,
        state.profile.company.id,
        state.article.news_id,
      );
      await render();
    }
    if (action === "refresh" || action === "retry") await refresh();
    if (action === "feed-filters") {
      const filters = $("#feed-filters");
      filters.hidden = !filters.hidden;
      b.setAttribute("aria-expanded", String(!filters.hidden));
    }
    if (action === "reset-feed-filter") {
      state.days = null;
      await refresh();
      $('[data-action="feed-filters"]')?.focus();
    }
    if (action === "expand-period") {
      state.days = 30;
      await refresh();
    }
    if (action === "logout") {
      if (isDemo) api.setScenario("normal");
      await changeProfile(() => api.request("POST", "/api/auth/logout"));
      state.profile = null;
      state.feed = null;
      state.analysis = null;
      state.messages = [];
      documentUrls.forEach((url) => URL.revokeObjectURL(url));
      documentUrls.clear();
      closePanel();
      location.hash = "login";
    }
    if (b.dataset.company) {
      b.disabled = true;
      state.profile = await changeProfile(() => api.request("PUT", "/api/profile/company", {
        company_id: b.dataset.company,
      }));
      state.feed = null;
      closePanel();
      if (route() === "news") await render();
      else location.hash = "news";
      toast("Компания изменена");
    }
    if (action === "more") {
      b.disabled = true;
      const version = generation;
      try {
        const next = await api.request(
          "GET",
          `/api/feed/${state.feed.snapshot_id}?position=${state.feed.next_position}&limit=20`,
        );
        if (version !== generation) return;
        const previous = state.feed.items.length;
        state.feed = { ...next, items: [...state.feed.items, ...next.items] };
        feedBody();
        const first = $$(".news-card")[previous];
        first?.setAttribute("tabindex", "-1");
        first?.focus({ preventScroll: true });
        first?.scrollIntoView({
          behavior: reduced() ? "instant" : "smooth",
          block: "start",
        });
      } catch (err) {
        b.disabled = false;
        const warning = document.createElement("div");
        warning.className = "notice warning";
        warning.innerHTML =
          esc(userMessage(err)) +
          ' <button class="text-button" data-action="refresh">Обновить подборку</button>';
        b.closest(".pagination").before(warning);
      }
    }
    if (b.dataset.reaction) {
      const version = generation;
      const feedback = b.closest(".feedback");
      const buttons = [...feedback.querySelectorAll("[data-reaction]")];
      if (buttons.some((button) => button.disabled)) return;
      const item = state.feed.items.find((i) => i.ranking.news_id === id),
        reaction =
          item.my_reaction === b.dataset.reaction ? "none" : b.dataset.reaction;
      buttons.forEach((button) => {
        button.disabled = true;
      });
      try {
        const result = await api.request(
          "PUT",
          `/api/news/${esc(id)}/reaction`,
          {
            snapshot_id: state.feed.snapshot_id,
            reaction,
          },
        );
        if (version !== generation) return;
        item.my_reaction = result.my_reaction;
        feedback.querySelectorAll("[data-reaction]").forEach((x) => {
          x.classList.toggle(
            "selected",
            x.dataset.reaction === result.my_reaction,
          );
          x.setAttribute(
            "aria-pressed",
            String(x.dataset.reaction === result.my_reaction),
          );
        });
        toast(
          reaction === "none"
            ? "Настройка снята. Изменение учтётся при обновлении"
            : "Приоритет тем изменён. Обновите подборку, чтобы применить",
        );
      } finally {
        buttons.forEach((button) => {
          button.disabled = false;
        });
      }
    }
    if (b.dataset.source) await source(b.dataset.source, b.dataset.statement);
    if (b.dataset.question) {
      $("#question").value = b.dataset.question;
      $("#question").focus();
    }
    if (b.dataset.ticker) {
      const t = [...state.market.heatmap, ...state.market.top_movers].find(
        (t) => t.ticker === b.dataset.ticker,
      );
      panel(
        t.name,
        `<span class="eyebrow">${esc(t.ticker)}</span><div class="quote-price">${money(t.price)} ₽</div><p class="${t.change_percent > 0 ? "positive" : t.change_percent < 0 ? "negative" : ""}">${change(t.change_percent)} к предыдущему закрытию</p><dl class="facts-list"><div><dt>Предыдущее закрытие</dt><dd>${money(t.previous_close)} ₽</dd></div><div><dt>Денежный оборот</dt><dd>${money(t.turnover_rub === null ? null : t.turnover_rub / 1e6)} млн ₽</dd></div><div><dt>Время котировки</dt><dd>${date(t.as_of)}</dd></div>${t.data_delay_minutes > 0 ? `<div><dt>Данные с задержкой</dt><dd>${esc(t.data_delay_minutes)} мин</dd></div>` : ""}</dl>${isDemo ? '<p class="field-hint">Учебные котировки</p>' : ""}`,
      );
    }
  } catch (error) {
    toast(userMessage(error));
    if (b.isConnected) b.disabled = false;
  }
});
document.addEventListener("input", (e) => {
  if (e.target.id === "market-search") {
    marketLimit = 30;
    renderMarketTiles();
    return;
  }
  if (e.target.id === "topic-search" || e.target.hasAttribute("data-topic-search")) {
    const query = e.target.value.trim().toLocaleLowerCase("ru");
    const form = e.target.closest("form");
    const labels = [...form.querySelectorAll(".searchable-topics label")];
    labels.forEach((label) => {
      label.hidden = !label.textContent.toLocaleLowerCase("ru").includes(query);
    });
    const empty = form.querySelector(".tag-search-empty");
    if (empty) empty.hidden = labels.some((label) => !label.hidden);
    return;
  }
  if (e.target.id !== "company-search") return;
  const select = $("#login-company");
  if (select) {
    select.disabled = true;
    $('#login-form [type="submit"]').disabled = true;
  }
  clearTimeout(searchTimer);
  ++searchVersion;
  const query = e.target.value.trim();
  const input = e.target;
  searchTimer = setTimeout(() => {
    if (input.isConnected) loadCompanies(query);
  }, 300);
});

document.addEventListener("submit", async (e) => {
  const form = e.target;
  e.preventDefault();
  const body = new FormData(form),
    button = form.querySelector('[type="submit"]');
  if (button.disabled) return;
  button.disabled = true;
  form.querySelector(".form-error")?.remove();
  try {
    if (form.id === "feed-filters") {
      state.days = Number(body.get("days")) || null;
      await refresh();
      $('[data-action="feed-filters"]')?.focus();
    }
    if (form.id === "login-form") {
      state.profile = null;
      await changeProfile(() => api.request("POST", "/api/auth/demo", {
        company_id: body.get("company_id"),
        job_role: body.get("job_role"),
      }));
      state.feed = null;
      if (route() === "home") await render();
      else location.hash = "home";
    }
    if (form.id === "demo-role-form") {
      await changeProfile(() => api.request("PUT", "/api/profile/settings", {
        job_role: body.get("job_role"),
      }));
      state.feed = null;
      closePanel();
      if (route() === "news") await render();
      else location.hash = "news";
      toast("Должность сохранена");
    }
    if (form.id === "interests-form") {
      const included = body.getAll("company-topic"),
        companyIds = state.profile.company_tags.map((t) => t.tag_id);
      state.profile = await changeProfile(() => api.request("PUT", "/api/profile/interests", {
        personal: body.getAll("personal"),
        disabled: [
          ...state.profile.disabled_tag_ids.filter(
            (t) => !companyIds.includes(t),
          ),
          ...companyIds.filter((t) => !included.includes(t)),
        ],
      }));
      state.feed = null;
      closePanel();
      if (route() === "news") await render();
      else location.hash = "news";
      toast("Темы сохранены");
    }
    if (form.classList.contains("tag-form")) {
      if (!body.getAll("wrong").length && !body.getAll("suggested").length)
        throw new UserError("Отметьте неверную тему или предложите новую");
      await api.request("POST", `/api/news/${form.dataset.id}/tag-feedback`, {
        snapshot_id: form.dataset.snapshot,
        wrong_tag_ids: body.getAll("wrong"),
        suggested_tag_ids: body.getAll("suggested"),
      });
      if (form.isConnected)
        form.parentElement.innerHTML = `<p class="tag-editor-success" role="status">${icon("check")}${isDemo ? "Исправление принято в деморежиме" : "Исправление отправлено на проверку"}</p>`;
    }
    if (form.id === "question-form") {
      const question = String(body.get("question")).trim();
      if (!question) throw new UserError("Введите вопрос");
      const version = generation;
      $("#conversation").insertAdjacentHTML(
        "beforeend",
        '<div id="question-loading" class="loading-label" role="status"><span class="spinner"></span>Подготавливаем ответ</div>',
      );
      try {
        const answer = await api.request(
          "POST",
          `/api/analyses/${esc(state.analysis.id)}/questions`,
          { conversation_id: state.conversation, question },
        );
        if (version !== generation) return;
        state.messages.push(answer);
        renderConversation();
        form.reset();
      } finally {
        if (version === generation) $("#question-loading")?.remove();
      }
    }
  } catch (error) {
    if (form.isConnected) inlineError(form, error);
  } finally {
    if (button.isConnected) button.disabled = false;
  }
});
dialog.addEventListener("cancel", (e) => {
  e.preventDefault();
  closePanel();
});
dialog.addEventListener("click", (e) => {
  if (e.target !== dialog) return;
  const r = dialog.getBoundingClientRect();
  if (
    e.clientX < r.left ||
    e.clientX > r.right ||
    e.clientY < r.top ||
    e.clientY > r.bottom
  )
    closePanel();
});
window.addEventListener("hashchange", () => render());
hydrate();
theme();
render();
