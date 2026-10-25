import { paths, icon } from "./icons.js";
import { api, isDemo, roles, apiUrl } from "./api/index.js";
import { createAnalysisTracker } from "./api/analysis.js";
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
  days: 7,
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
const route = () => location.hash.slice(1) || "home";
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
function hydrate() {
  $$("[data-icon]").forEach((x) => (x.innerHTML = icon(x.dataset.icon)));
}
function theme() {
  const dark = document.documentElement.dataset.theme === "dark";
  $(".theme-button").innerHTML = icon(dark ? "sun" : "moon");
  $(".theme-button").setAttribute(
    "aria-label",
    dark ? "Включить светлую тему" : "Включить тёмную тему",
  );
}
function configureShell() {
  if (isDemo) return;
  $(".demo-pill").textContent = apiUrl ? "Данные API" : "API не настроен";
  $(".sidebar-note").innerHTML =
    '<span class="tiny-dot"></span>Хакатон · данные API<p>Демовход без банковской авторизации</p>';
  $$('[data-action="scenarios"]').forEach((button) => {
    button.dataset.action = "connection";
    button.textContent = "Состояние сервисов";
  });
}
async function connection() {
  panel(
    "Состояние сервисов",
    '<p role="status">Проверяем API и обработчик…</p>',
    "Подключение",
  );
  const target = $("#panel-body");
  try {
    const health = await api.request("GET", "/health");
    const status = api.hasSession()
      ? await api.request("GET", "/api/status")
      : null;
    if (!dialog.open || $("#panel-title").textContent !== "Состояние сервисов")
      return;
    target.innerHTML = `<div class="notice success">API доступен</div><p class="field-hint">${esc(apiUrl)}</p>${status ? `<dl class="facts-list"><div><dt>База данных</dt><dd>${status.database === "ready" ? "Доступна" : "Недоступна"}</dd></div><div><dt>Фоновый обработчик</dt><dd>${status.worker_alive ? "Работает" : "Не запущен"}</dd></div><div><dt>AI-разбор</dt><dd>${status.analysis_available ? "Доступен" : "Временно недоступен"}</dd></div></dl><details><summary>Технические данные</summary><pre>${esc(JSON.stringify(status, null, 2))}</pre></details>` : "<p>Для просмотра состояния воркера нужен вход</p>"}`;
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
function panel(title, body, caption = "Бизнес-инсайты") {
  clearTimeout(closeTimer);
  dialog.classList.remove("closing");
  dialog.classList.remove("demo-dialog");
  $("#panel-title").textContent = title;
  $("#panel-caption").textContent = caption;
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
function failure(e, retry = "retry") {
  const expired = e.status === 401;
  return `<div class="error-state" role="alert">${icon("info")}<h2>${expired ? "Нужно войти снова" : "Не получилось загрузить данные"}</h2><p>${esc(e.message)}</p><button class="button primary" data-action="${expired ? "login" : retry}">${expired ? "Войти в демо" : "Попробовать снова"}</button></div>`;
}
function inlineError(form, e) {
  let el = form.querySelector(".form-error");
  if (!el) {
    el = document.createElement("p");
    el.className = "form-error";
    el.setAttribute("role", "alert");
    form.append(el);
  }
  el.textContent = e.message;
}
function skeleton() {
  return `<div class="loading-block" aria-busy="true"><div class="loading-label" role="status"><span class="spinner"></span>Подготавливаем подборку</div>${[0, 1, 2].map(() => '<div class="skeleton-card"><span class="skeleton short"></span><span class="skeleton long"></span><span class="skeleton"></span><span class="skeleton medium"></span></div>').join("")}</div>`;
}
function context() {
  const p = state.profile,
    c = p.company;
  return `<section class="company-context" aria-label="Выбранная компания"><div class="context-company"><span class="company-monogram">${icon("people")}</span><div><span class="context-label">Компания для анализа</span><button class="company-switch" data-action="companies" aria-haspopup="dialog">${esc(c.id)} <span>Сменить компанию</span>${icon("chevron")}</button><p>${esc(c.industry)} <span>·</span> ${esc(c.city || "Город неизвестен")} <span>·</span> ОКВЭД ${esc(c.okved_code || "нет данных")}</p></div></div><div class="context-actions"><span>Ваша роль: <strong>${roles[p.user.job_role]}</strong></span><div><button data-action="company-info">Данные компании ${icon("arrow")}</button><button data-action="interests">${icon("sliders")}Темы подборки</button></div></div></section>`;
}
function heading(title, subtitle) {
  return `<div class="page-heading"><div><h1>${title}</h1><p>${subtitle}</p></div></div>`;
}
function tabs(active) {
  return `<nav class="tabs" aria-label="Раздел сервиса"><a href="#news" ${active === "news" ? 'aria-current="page"' : ""}>Новости для бизнеса</a><a href="#market" ${active === "market" ? 'aria-current="page"' : ""}>Биржевой обзор</a></nav>`;
}
function home() {
  main.innerHTML = `<div class="home-intro"><span class="eyebrow">Бизнес-кабинет</span><h1>Картина дня.<br><span>С учётом вашего бизнеса.</span></h1><p>Новости, их влияние на компанию и данные, на которые можно опереться.</p></div><section class="hero"><div class="hero-copy"><span class="hero-label">СЕРВИС ДЛЯ РУКОВОДИТЕЛЕЙ</span><h2>От события<br>к решению</h2><p>Выберите компанию, откройте подборку<br>и разберите влияние значимой новости.</p><a class="button primary large" href="#news">Открыть бизнес-инсайты ${icon("arrow")}</a></div><div class="hero-art" aria-hidden="true"><div class="art-orbit"></div><div class="art-sheet back"></div><div class="art-sheet front"><span class="art-brand">А</span><span class="art-line"></span><span class="art-line half"></span><div class="art-chart"><i></i><i></i><i></i><i></i><i></i></div><span class="art-label">Бизнес в контексте</span></div><span class="art-badge">${icon("spark")}AI-разбор</span></div></section><div class="journey"><div><span>01</span><h3>Выберите компанию</h3><p>Отрасль, продукты и ваши интересы определят порядок новостей.</p></div><div><span>02</span><h3>Разберите событие</h3><p>Факты, возможное влияние и материалы банка в одном разборе.</p></div><div><span>03</span><h3>Проверьте вывод</h3><p>Откройте источник, уточните вопрос и решите, что проверить дальше.</p></div></div><div class="home-bottom"><a class="market-entry" href="#market"><span class="market-entry-icon">${icon("chart")}</span><div><h3>Биржевой обзор</h3><p>Карта рынка и лидеры изменения</p></div>${icon("arrow")}</a><p class="demo-note">${isDemo ? "Демо без сервера: компании, публикации и котировки синтетические" : "Данные загружаются из API. Авторизация банка пока заменена демовходом"}</p></div>`;
}
function roleOptions(selected) {
  return Object.entries(roles)
    .map(
      ([id, name]) =>
        `<option value="${esc(id)}" ${selected === id ? "selected" : ""}>${name}</option>`,
    )
    .join("");
}
function demoRoleField(selected) {
  return `<fieldset class="demo-role-field"><legend>Настройка демонстрации</legend><p>Выбор роли не входит в интерфейс приложения. Здесь он позволяет проверить подборку для разных пользователей.</p><label>Роль в демосценарии<select name="job_role" aria-label="Роль в демосценарии">${roleOptions(selected)}</select></label></fieldset>`;
}
async function demoRole() {
  if (!state.profile && api.hasSession()) {
    state.profile = await api.request("GET", "/api/profile");
  }
  if (!state.profile) {
    location.hash = "login";
    return;
  }
  panel(
    "Роль для демонстрации",
    `<p class="demo-boundary">Панель прототипа, не экран банковского приложения</p><form id="demo-role-form">${demoRoleField(state.profile.user.job_role)}<p class="field-hint">В приложении используется роль из профиля пользователя. В демо её можно менять, чтобы сравнить подборки. Сохранённый AI-разбор компании и новости остаётся общим.</p><button class="button demo-apply" type="submit">Применить роль и открыть подборку</button></form>`,
    "Управление демонстрацией",
  );
  dialog.classList.add("demo-dialog");
}
async function login() {
  const token = generation;
  const companies = await api.request(
    "GET",
    "/api/companies?limit=50&offset=0",
  );
  if (token !== generation) return;
  main.innerHTML = `<a class="back-link" href="#home">← К обзору</a><div class="onboarding"><div class="onboarding-intro"><span class="eyebrow">Начало работы</span><h1>Для какого бизнеса<br>подобрать новости?</h1><p>Компания задаёт деловой контекст.<br>Роль и интересы помогают расставить приоритеты.</p><div class="onboarding-mark" aria-hidden="true">А<span>Бизнес-инсайты</span></div></div><form id="login-form" class="form-card"><h2>Настройка профиля</h2><p class="muted">Демонстрационный вход без пароля</p><label>Найти компанию<input id="company-search" type="search" aria-label="Поиск компании" placeholder="ID, отрасль или город"></label><label>Компания<select id="login-company" name="company_id" aria-label="Компания" required></select></label><div id="catalog-status" aria-live="polite"></div><div id="catalog-pages" class="catalog-pages"></div><label>Город проживания<input name="city" required maxlength="200" placeholder="Например, Москва" autocomplete="address-level2"></label>${demoRoleField("ceo")}<p class="field-hint">Город проживания не ограничивает новости вашим регионом</p><button class="button primary large" type="submit">Открыть подборку ${icon("arrow")}</button><p class="fine">${isDemo ? "Данные компаний вымышлены. Настройки сохраняются только в этом браузере" : "Демовход создаёт профиль на сервере. Доступ к данным банка здесь не предоставляется"}</p></form></div>`;
  catalog = { query: "", offset: 0, items: companies };
  companyResults(companies);
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
  return `<article class="news-card" data-news="${esc(id)}" style="--order:${Math.min(index, 3)}"><div class="news-meta"><span class="source-dot">${icon("document")}</span>${esc(sourceName(item.source_url))}<span class="meta-divider">·</span><time datetime="${esc(item.published_at)}">${date(item.published_at)}</time></div><h2><button data-action="article" data-id="${esc(id)}">${esc(item.title)}</button></h2><p class="summary">${esc(item.summary)}</p><div class="topic-line">${item.tags.map(tag).join("")}<button class="why-button" data-action="reason" data-id="${esc(id)}">Почему в подборке ${icon("info")}</button></div><div class="news-actions"><button class="button ${index === 0 ? "primary" : "outline"}" data-action="analyse" data-id="${esc(id)}">${icon("spark")}Разобрать влияние ${icon("arrow")}</button><button class="text-button" data-action="article" data-id="${esc(id)}">Читать новость</button></div><div class="feedback"><span>Настроить подборку</span><div><button class="feedback-button ${item.my_reaction === "like" ? "selected" : ""}" data-reaction="like" data-id="${esc(id)}" aria-pressed="${item.my_reaction === "like"}">${icon("plus")}Больше таких тем</button><button class="feedback-button ${item.my_reaction === "dislike" ? "selected" : ""}" data-reaction="dislike" data-id="${esc(id)}" aria-pressed="${item.my_reaction === "dislike"}">${icon("minus")}Меньше таких тем</button></div><button class="tag-error" data-action="tag-feedback" data-id="${esc(id)}">Ошибка в темах</button></div></article>`;
}
function feedBody() {
  const f = state.feed;
  if (!f) return;
  $("#feed-results").innerHTML = f.items.length
    ? `<div class="feed-list">${f.items.map(feedCard).join("")}</div><div class="pagination">${f.has_more ? '<button class="button secondary" data-action="more">Показать ещё 20 ' + icon("plus") + "</button>" : "<span>Все новости этой подборки просмотрены</span>"}<span>Показано ${f.items.length} · Обновлено ${date(f.generated_at)}</span></div>`
    : `<div class="empty-state">${icon("document")}<h2>За этот период новостей нет</h2><p>Выберите более длинный период или обновите подборку позже</p><button class="button secondary" data-action="reset-period">Показать за 7 дней</button></div>`;
  observeImpressions();
}
async function feed(reuse = false) {
  main.innerHTML =
    heading(
      "Бизнес-инсайты",
      "Новости, которые стоит проверить в контексте вашей компании",
    ) +
    context() +
    tabs("news") +
    `<div class="feed-toolbar"><div><h2>Персональная подборка</h2><p>По темам компании, роли и интересам · ${state.days} дн.</p></div><div class="toolbar-actions"><label class="period-label">Период<select id="period" aria-label="Период новостей">${[
      [1, "За сутки"],
      [7, "За 7 дней"],
      [30, "За 30 дней"],
    ]
      .map(
        ([v, n]) =>
          `<option value="${v}" ${state.days === v ? "selected" : ""}>${n}</option>`,
      )
      .join(
        "",
      )}</select></label><button class="button secondary" data-action="refresh">${icon("refresh")}Обновить</button></div></div><div class="feedback-help">${icon("info")}«Больше / меньше таких тем» меняет приоритеты следующей подборки. Это личная настройка, без публичных оценок.</div><div id="feed-results">${skeleton()}</div>`;
  const token = generation;
  try {
    if (
      !reuse ||
      !state.feed ||
      Date.parse(state.feed.expires_at) <= Date.now()
    ) {
      const result = await api.request("POST", "/api/feed", {
        days: state.days,
        page_size: 20,
      });
      if (token !== generation) return;
      state.feed = result;
    }
    if (token !== generation) return;
    feedBody();
  } catch (e) {
    if (token === generation)
      $("#feed-results").innerHTML = failure(e, "refresh");
  }
}
const observer = new IntersectionObserver(
  (entries) => {
    for (const e of entries)
      if (
        e.isIntersecting &&
        e.intersectionRatio >= 0.5 &&
        document.visibilityState === "visible" &&
        !dialog.open &&
        state.feed
      ) {
        interactions
          .impression(state.feed.snapshot_id, e.target.dataset.news)
          .then(() => observer.unobserve(e.target))
          .catch(() => {});
      }
  },
  { threshold: 0.5 },
);
function observeImpressions() {
  observer.disconnect();
  $$("[data-news]").forEach((x) => observer.observe(x));
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") observeImpressions();
});
dialog.addEventListener("close", observeImpressions);
let catalog = { query: "", offset: 0, items: [] };
let searchVersion = 0;
let searchTimer;
async function companies() {
  panel(
    "Сменить компанию",
    `<p class="muted">Личные интересы сохранятся. Для новой компании будет создана новая подборка.</p><label class="search-field">${icon("search")}<input id="company-search" type="search" aria-label="Поиск компании" placeholder="ID, отрасль или город"></label><div id="company-results"></div><div id="catalog-status" aria-live="polite"></div><div id="catalog-pages" class="catalog-pages"></div>`,
    "Контекст анализа",
  );
  await loadCompanies("", 0);
}
async function loadCompanies(query, offset) {
  const version = ++searchVersion;
  const target = $("#catalog-status");
  if (!target) return;
  target.textContent = "Загружаем компании…";
  const select = $("#login-company");
  if (select) {
    select.disabled = true;
    $('#login-form [type="submit"]').disabled = true;
  }
  $("#catalog-pages").innerHTML = "";
  if ($("#company-results")) $("#company-results").innerHTML = "";
  try {
    const items = await api.request(
      "GET",
      `/api/companies?limit=50&offset=${offset}&query=${encodeURIComponent(query)}`,
    );
    if (version !== searchVersion || !target.isConnected) return;
    catalog = { query, offset, items };
    companyResults(items);
  } catch (error) {
    if (version === searchVersion && target.isConnected)
      target.innerHTML = `<p class="form-error">${esc(error.message)}</p><button type="button" class="text-button" data-action="catalog-retry">Повторить поиск</button>`;
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
    ? `Показаны компании ${catalog.offset + 1}–${catalog.offset + items.length}`
    : "Компании не найдены. Измените запрос или проверьте импорт данных";
  $("#catalog-pages").innerHTML =
    `<button type="button" class="text-button" data-action="catalog-prev" ${catalog.offset ? "" : "disabled"}>Назад</button><button type="button" class="text-button" data-action="catalog-next" ${items.length === 50 ? "" : "disabled"}>Далее</button>`;
}
function interests() {
  const p = state.profile;
  panel(
    "Темы подборки",
    `<form id="interests-form"><p>Темы компании определяются по её данным. Личные интересы сохраняются при смене компании.</p><h3>Темы компании <span class="count">${p.company_tags.length}</span></h3><p class="field-hint">Снимите отметку, чтобы тема не повышала приоритет новостей лично для вас</p><div class="topic-options">${p.company_tags.map((t) => `<label><input type="checkbox" name="company-topic" value="${esc(t.tag_id)}" ${p.disabled_tag_ids.includes(t.tag_id) ? "" : "checked"}><span><strong>${esc(tagName(t.tag_id))}</strong><small>${t.origin === "rule" ? "Автоматически по правилам профиля" : "Ручная настройка"}</small></span></label>`).join("")}</div><h3>Личные интересы</h3><label>Поиск темы<input type="search" id="topic-search" placeholder="Например, кредитование"></label><div class="personal-options searchable-topics">${state.tags.map((t) => `<label><input type="checkbox" name="personal" value="${esc(t.id)}" ${p.personal_tag_ids.includes(t.id) ? "checked" : ""}>${esc(tagLabel(t.display_name))}</label>`).join("")}</div><p class="field-hint">Отключённая тема компании не повышает приоритет, даже если она выбрана в личных интересах. Новости по ней могут остаться в ленте.</p><div class="sticky-form-actions"><button class="button primary" type="submit">Сохранить и обновить ленту</button><button class="button ghost" type="button" data-close>Отмена</button></div></form>`,
    "Персонализация",
  );
}
function companyInfo() {
  const c = state.profile.company;
  panel(
    "Данные компании",
    `<span class="label-badge">${isDemo ? "Синтетический профиль" : "Профиль компании"}</span><h3>${esc(c.id)} · ${esc(c.industry)}</h3><dl class="facts-list"><div><dt>Основная деятельность</dt><dd>${esc(c.okved_name || "Нет данных")}<small>ОКВЭД ${esc(c.okved_code)}</small></dd></div><div><dt>Выручка</dt><dd>${c.revenue === null || c.revenue === undefined ? "Нет данных" : money(Number(c.revenue) / 1e9) + " млрд ₽"}</dd></div><div><dt>Регистрация</dt><dd>${esc(c.city || "Город неизвестен")}, ${esc(c.region || "регион неизвестен")}</dd></div><div><dt>Группа компаний</dt><dd>${esc(c.group_id || "Неизвестно")}</dd></div><div><dt>Кредитные продукты</dt><dd>${["1", "1.0", 1, true].includes(c.profile_json?.CL_PRODUCT_LOA_MARK) || (c.known_factor_interests || []).includes("credit") ? "Есть признак наличия" : ["0", "0.0", 0, false].includes(c.profile_json?.CL_PRODUCT_LOA_MARK) ? "В датасете указан признак отсутствия" : "Нет подтверждённых данных"}</dd></div><div><dt>Регионы деятельности</dt><dd>${c.operating_region_codes?.length ? esc(c.operating_region_codes.join(", ")) : "Неизвестны"}</dd></div><div><dt>Доля рынка</dt><dd>Нет данных для оценки</dd></div></dl><div class="notice">Регион регистрации не определяет географию деятельности. Объём платежей не равен выручке или доле рынка.</div><details><summary>Откуда эти признаки</summary><p>Поля получены из профиля компании: ОКВЭД, выручка, город, регион, группа и признаки продуктов. Отсутствующие сведения обозначены явно.</p></details>`,
    "Контекст, используемый в анализе",
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
    "Мой профиль",
    `<form id="settings-form"><label>Город проживания<input name="city" required maxlength="200" value="${esc(state.profile.user.city)}"></label><div class="profile-role"><span class="muted">Роль из профиля</span><strong>${esc(roles[state.profile.user.job_role])}</strong></div><button class="button primary" type="submit">Сохранить настройки</button></form><hr><button class="text-button danger" data-action="logout">Выйти из демопрофиля</button>`,
    "Личные настройки",
  );
}
function reason(id) {
  const item = state.feed.items.find((i) => i.ranking.news_id === id),
    r = item.ranking;
  panel(
    "Почему новость в подборке",
    `<p>${esc(item.title)}</p><h3>${r.matched_signals.length ? "Совпали темы профиля" : "Учтена свежесть публикации"}</h3><div class="tags">${r.matched_signals.map(tag).join("")}</div><p>Подборка учитывает темы компании, личные интересы, роль и ваши реакции.</p><div class="notice">Это объяснение порядка в ленте. Влияние на бизнес оценивается только после нажатия «Разобрать влияние».</div><details><summary>Как считается приоритет</summary><p>80% совпадения тем + 20% свежести. Итоговый балл ${r.final_score.toFixed(3)} не является вероятностью или оценкой ущерба.</p><dl class="facts-list"><div><dt>Совпадение тем</dt><dd>${r.match_score.toFixed(3)}</dd></div><div><dt>Свежесть</dt><dd>${r.freshness_score.toFixed(3)}</dd></div></dl></details>`,
    "Объяснение подбора",
  );
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
    "Текст новости",
  );
  if (snapshot) interactions.open(snapshot, id).catch(() => {});
}
function tagFeedback(id) {
  const a = state.feed.items.find((a) => a.ranking.news_id === id);
  panel(
    "Исправить темы новости",
    `<form id="tag-form" data-id="${esc(id)}"><p>${esc(a.title)}</p><h3>Какие темы назначены неверно?</h3><div class="personal-options">${a.tags.map((t) => `<label><input type="checkbox" name="wrong" value="${esc(t)}">${esc(tagName(t))}</label>`).join("")}</div><h3>Какие темы стоит добавить?</h3><label>Поиск темы<input type="search" id="topic-search" placeholder="Название темы"></label><div class="personal-options searchable-topics">${state.tags
      .filter((t) => !a.tags.includes(t.id))
      .map(
        (t) =>
          `<label><input type="checkbox" name="suggested" value="${esc(t.id)}">${esc(tagLabel(t.display_name))}</label>`,
      )
      .join(
        "",
      )}</div><p class="field-hint">Эта форма сообщает об ошибке разметки. Для изменения личной подборки используются кнопки «Больше / меньше таких тем».</p><button class="button primary" type="submit">Отправить замечание</button></form>`,
    "Качество разметки",
  );
}
function analysisFrame(a, body) {
  main.innerHTML = `<a class="back-link" href="#news">← К подборке</a><div class="analysis-heading"><span class="eyebrow">AI-разбор события</span><h1>${esc(a.title)}</h1><div class="news-meta">${date(a.published_at)} <span>·</span> Компания ${esc(state.profile.company.id)} <span>·</span> ${esc(state.profile.company.industry)}</div></div>${body}`;
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
      `<section class="analysis-loading"><div class="analysis-orb">${icon("spark")}</div><h2 id="job-label">Проверяем сохранённый разбор</h2><p>Сопоставляем событие с контекстом ${esc(state.profile.company.id)}</p><div class="job-progress"><i></i></div><p class="fine">${isDemo ? "Учебный сценарий · модель не вызывается" : "Готовый результат будет загружен из кеша. Новый разбор выполняется на сервере"}</p><a class="text-button" href="#news">Вернуться к ленте</a></section>`,
    );
    let job = await tracker.start(
      state.profile.user.id,
      state.profile.company.id,
      id,
      state.profile.company.profile_version + ":" + a.content_hash,
    );
    const pollingStarted = Date.now();
    while (job.status !== "ready" && job.status !== "failed") {
      if (version !== generation) return;
      $("#job-label").textContent =
        job.status === "queued"
          ? "Разбор в очереди"
          : "Анализируем событие и проверяем источники";
      if (Date.now() - pollingStarted > 180000) {
        throw new Error(
          "Разбор ещё выполняется. Вернитесь позже или повторите проверку: второе задание не создаётся",
        );
      }
      await new Promise((r) => setTimeout(r, isDemo ? 650 : 2500));
      if (version !== generation) return;
      job = await api.request("GET", "/api/analysis-jobs/" + job.id);
    }
    if (version !== generation) return;
    if (job.status === "failed")
      throw Object.assign(
        new Error(
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
          "Разбор готов, но история вопросов не загрузилась: " + error.message,
        );
    }
  } catch (e) {
    if (version === generation)
      analysisFrame(
        state.article || { title: "AI-разбор", published_at: null },
        failure(e),
      );
  }
}
function statements(items) {
  return items.length
    ? items
        .map(
          (s) =>
            `<div class="statement"><p>${esc(s.text)} ${s.source_refs.map((ref) => `<button class="citation" data-source="${esc(ref)}" data-statement="${analysisStatements(state.analysis.result).indexOf(s)}" aria-label="Открыть источник ${state.analysis.result.source_refs.findIndex((r) => r.id === ref) + 1}">${state.analysis.result.source_refs.findIndex((r) => r.id === ref) + 1}</button>`).join("")}</p>${s.condition ? `<span class="condition">Условие: ${esc(s.condition)}</span>` : ""}${s.company_feature_refs.length ? `<button class="feature-link" data-action="statement-features" data-statement="${analysisStatements(state.analysis.result).indexOf(s)}">Использованы признаки компании ${icon("arrow")}</button>` : ""}</div>`,
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
        value === null
          ? "Не сохранено в снимке"
          : Array.isArray(value)
            ? value.join(", ")
            : typeof value === "object"
              ? JSON.stringify(value)
              : String(value);
      const origins = (context.payload_json.features || []).filter(
        (item) => item.key === key,
      );
      return `<div><dt>${esc(labels[key] || key)}</dt><dd>${esc(display)}${origins.map((item) => `<small>${esc([item.origin_file, item.origin_field, item.calc_method].filter(Boolean).join(" · "))}</small>`).join("")}</dd></div>`;
    })
    .join("");
  panel(
    "Признаки этого вывода",
    `<p>${esc(statement.text)}</p><dl class="facts-list">${rows}</dl><p class="field-hint">Снимок компании ${esc(context.company_id)} на момент анализа. Текущий профиль мог измениться.</p>${origin ? `<p class="field-hint">Источник: ${esc(origin.file)} · строка ${esc(origin.record)}</p>` : ""}`,
    "Основание персонализации",
  );
}
function renderAnalysis() {
  const a = state.analysis,
    r = a.result;
  analysisFrame(
    state.article,
    `<div class="analysis-layout"><div class="analysis-main"><div class="saved-analysis"><span>Сохранённый разбор</span><button class="text-button" data-action="update-analysis">Проверить актуальность</button></div>${a.status === "partial" ? `<div class="notice warning"><strong>Разбор готов с ограничениями</strong>${r.limitations.map((value) => `<p>${esc(value)}</p>`).join("")}</div>` : '<div class="notice success">Разбор подготовлен · выводы сопровождаются источниками</div>'}<section class="analysis-section"><div class="section-heading"><span class="section-index">01</span><h2>Что произошло</h2><span class="section-kind">Факты из новости</span></div>${statements(r.facts)}</section><section class="analysis-section"><div class="section-heading"><span class="section-index">02</span><h2>Влияние на компанию</h2><span class="ai-label">Вывод AI</span></div>${statements(r.why_important)}<div class="impact-grid"><div class="impact risk"><h3>${icon("info")}Возможные риски</h3>${statements(r.risks)}</div><div class="impact opportunity"><h3>${icon("plus")}Возможности</h3>${statements(r.opportunities)}</div></div></section><section class="bank-section"><div class="section-heading"><span class="bank-symbol">А</span><h2>Что говорят материалы банка</h2></div>${r.bank_position ? `<span class="label-badge">${isDemo ? "Синтетический пример, не позиция Альфа-Банка" : "Вывод по материалу банка"}</span>${statements([r.bank_position])}` : "<p>Подходящий материал не найден. Выводы AI выше не являются позицией Альфа-Банка.</p>"}</section><section class="analysis-section"><div class="section-heading"><span class="section-index">03</span><h2>Что проверить дальше</h2></div><ol class="recommendations">${r.recommendations.map((s) => `<li>${statements([s])}</li>`).join("")}</ol></section><section class="question-section"><div><span class="ai-label">Уточнение</span><h2>Остались вопросы по событию?</h2><p>Ответ опирается на этот разбор и его источники</p></div><div class="suggested-questions"><button data-question="Каких данных не хватает для оценки влияния?">Каких данных не хватает?</button><button data-question="Что проверить в первую очередь?">Что проверить сначала?</button></div><div id="conversation" aria-live="polite"></div><form id="question-form"><label class="sr-only" for="question">Вопрос по разбору</label><textarea id="question" name="question" required maxlength="1000" placeholder="Например, как это связано с расходами компании?" rows="2"></textarea><div><span class="fine">До 1000 символов</span><button class="button primary" type="submit">Задать вопрос ${icon("arrow")}</button></div></form></section></div><aside class="analysis-aside"><section class="sources-card"><h3>Источники разбора <span>${r.source_refs.length}</span></h3>${r.source_refs.map((s, i) => `<button class="source-row" data-source="${esc(s.id)}"><span class="source-number">${i + 1}</span><span><strong>${esc(s.title)}</strong><small>${s.kind === "company" ? "Данные компании" : s.kind === "bank_report" ? "Материал банка · стр. " + s.page : "Новостной материал"}${s.published_on ? " · " + s.published_on : ""}</small></span>${icon("arrow")}</button>`).join("")}<p class="fine">Номера рядом с выводами открывают соответствующий источник</p></section><button class="trace-button" data-action="trace">${icon("sliders")}Как получен разбор ${icon("arrow")}</button><p class="fine">AI-выводы требуют проверки человеком. Проверяйте источники и условия применимости.</p></aside></div>`,
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
      sourceError = error.message;
    }
  }
  if (token !== generation) return;
  const external = safeUrl(s.url);
  const quote = statementEvidence(state.analysis.result, statementIndex, ref);
  panel(
    s.title,
    `<div class="source-details"><span class="label-badge">${s.kind === "company" ? "Профиль компании" : s.kind === "bank_report" ? "Материал банка" : "Публикация"}</span>${s.published_on ? `<p>Дата: ${esc(s.published_on)}</p>` : ""}${s.page ? `<p>Страница ${s.page}</p>` : ""}<h3>${quote ? "Цитата, подтверждающая этот вывод" : "Фрагмент, использованный в разборе"}</h3><blockquote>${esc(quote || s.excerpt || "Фрагмент не сохранён")}</blockquote><div class="notice">${isDemo ? "Синтетический источник для проверки интерфейса" : "Цитата сохранена вместе с разбором. Сверьте её с оригиналом и датой публикации"}</div>${sourceError ? `<p class="form-error">${esc(sourceError)}</p>` : ""}${documentLink || (external ? `<a class="button secondary" href="${esc(external)}" target="_blank" rel="noopener noreferrer">Открыть первоисточник ${icon("external")}</a>` : '<button class="button secondary" disabled>Внешний источник недоступен</button>')}</div>`,
    "Источник вывода",
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
  if (step.step === "cache_hit") return "Повторный вызов модели не требуется";
  return "Подробности доступны в технических данных";
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
    `<p class="muted">${isDemo ? "Учебная трасса" : "Выполненные шаги агента и использованные источники"}</p><ol class="trace-list">${steps.map((s) => `<li><strong>${names[s.step] || esc(s.step)}</strong><p>${esc(traceDescription(s))}</p></li>`).join("")}</ol><details><summary>Технические данные</summary><code>analysis_id: ${esc(state.analysis.id)}</code><pre>${esc(JSON.stringify(steps, null, 2))}</pre></details>`,
    "Трассировка",
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
    `Показано ${rectangles.length} из ${items.length} · по убыванию оборота${rectangles.length < shown.length ? ". Нулевой оборот не занимает площадь" : ""}`;
  $("#market-more").hidden = shown.length >= items.length;
  $("#market-size").textContent =
    state.market.size_basis === "equal" ||
    !shown.some((item) => item.size_metric > 0)
      ? "Размер: равные доли, оборот не определяет площадь"
      : "Размер: денежный оборот";
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
      "Движение рынка отдельно от персональной новостной подборки",
    ) +
    context() +
    tabs("market") +
    '<div id="market-content">' +
    skeleton() +
    "</div>";
  const token = generation;
  try {
    const m = await api.request("GET", "/api/market?limit=20");
    if (token !== generation) return;
    state.market = m;
    $("#market-content").innerHTML =
      `<div class="market-heading"><div><h2>Карта рынка</h2><p>${isDemo ? "Учебные котировки" : "MOEX · изменение к предыдущему закрытию"}</p></div><button class="button secondary" data-action="refresh">${icon("refresh")}Обновить</button></div>${m.status === "stale" ? '<div class="notice warning">Котировки устарели или источник недоступен. Показан последний сохранённый срез.</div>' : ""}<div class="market-meta"><span>Срез: ${date(m.captured_at)}</span><span>Задержка указана в карточке инструмента</span><label title="Бэкенд пока не связывает эмитентов с профилем"><input type="checkbox" disabled>Связано с моей компанией <small>Позже</small></label></div>${m.status === "empty" ? '<div class="empty-state"><h2>Котировки пока недоступны</h2><p>Источник не передал данные о торгах. Новостная лента продолжает работать.</p><a class="button primary" href="#news">К новостям</a></div>' : `<div class="market-layout"><div><label class="market-search">Найти инструмент<input type="search" id="market-search" placeholder="Тикер или название"></label><div id="market-count" class="field-hint" aria-live="polite"></div><div class="heatmap"></div><details class="market-instruments"><summary>Инструменты списком</summary><div id="market-instruments"></div></details><button class="button secondary" id="market-more" data-action="market-more">Показать ещё 30</button><div class="heatmap-legend"><span id="market-size">Размер: ${m.size_basis === "equal" ? "равные доли, оборот неизвестен" : "денежный оборот"}</span><span>− Снижение <i></i> Рост +</span></div></div><section class="movers"><h3>Лидеры изменения</h3><p>По абсолютному изменению цены</p>${m.top_movers.map((t) => `<button data-ticker="${esc(t.ticker)}"><span><strong>${esc(t.ticker)}</strong><small>${esc(t.name)}</small></span><strong class="${t.change_percent > 0 ? "positive" : t.change_percent < 0 ? "negative" : ""}">${change(t.change_percent)}</strong></button>`).join("")}</section></div>`}`;
    marketLimit = 30;
    if (m.status !== "empty") renderMarketTiles();
  } catch (e) {
    if (token === generation) $("#market-content").innerHTML = failure(e);
  }
}
function scenarios() {
  panel(
    "Сценарии демо",
    `<p>Только локальные состояния. Бэкенд, модель и биржа не вызываются.</p><label>Состояние<select id="scenario" aria-label="Состояние">${[
      ["normal", "Обычная работа / неполный разбор"],
      ["complete", "Разбор с учебным отчётом"],
      ["conflict", "Отчёт старше события"],
      ["network", "Ошибка загрузки / сервис недоступен"],
      ["empty", "Нет новостей / котировок"],
      ["expired", "Истёк срок подборки"],
      ["session", "Сессия завершена"],
      ["limit", "Достигнут лимит AI"],
      ["failed", "Ошибка AI / таймаут уточнения"],
      ["stale", "Устаревшие котировки"],
    ]
      .map(
        ([id, label]) =>
          `<option value="${esc(id)}" ${id === api.getScenario() ? "selected" : ""}>${label}</option>`,
      )
      .join(
        "",
      )}</select></label><p class="field-hint">Состояние применяется к следующему действию. Для нового примера разбора выберите другую новость: готовые результаты кешируются.</p><button class="button primary" data-action="apply-scenario">Применить</button><hr><button class="text-button" data-action="login">Показать экран первого входа</button>`,
    "Проверка интерфейса",
  );
}
async function render() {
  const version = ++generation;
  observer.disconnect();
  clearTimeout(closeTimer);
  if (dialog.open) dialog.close();
  dialog.classList.remove("closing");
  const path = route();
  $$("[data-nav]").forEach((el) => {
    const active =
      el.dataset.nav ===
      (path === "home" ? "home" : path === "market" ? "market" : "news");
    el.toggleAttribute("aria-current", active);
    if (active) el.setAttribute("aria-current", "page");
  });
  main.classList.remove("arrive");
  void main.offsetWidth;
  main.classList.add("arrive");
  window.scrollTo({ top: 0, behavior: "instant" });
  document.title =
    (path === "home"
      ? "Обзор"
      : path === "market"
        ? "Биржевой обзор"
        : path === "login"
          ? "Первый вход"
          : "Бизнес-инсайты") +
    " · Альфа" +
    (isDemo ? " · Демо" : "");
  if (path === "home") {
    home();
    if (api.hasSession()) {
      try {
        const profile = await api.request("GET", "/api/profile");
        if (version === generation) state.profile = profile;
      } catch {
        state.profile = null;
      }
    }
    return;
  }
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
    const [profile, tags] = await Promise.all([
      api.request("GET", "/api/profile"),
      api.request("GET", "/api/tags"),
    ]);
    if (version !== generation) return;
    state.profile = profile;
    state.tags = tags.sort((a, b) =>
      tagLabel(a.display_name).localeCompare(tagLabel(b.display_name), "ru"),
    );
    if (path === "news") await feed(true);
    else if (path === "market") await market();
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
    if (action === "demo-role") await demoRole();
    if (action === "companies") await companies();
    if (
      action === "catalog-prev" ||
      action === "catalog-next" ||
      action === "catalog-retry"
    ) {
      await loadCompanies(
        $("#company-search").value.trim(),
        action === "catalog-retry"
          ? 0
          : Math.max(
              0,
              catalog.offset + (action === "catalog-next" ? 50 : -50),
            ),
      );
    }
    if (action === "company-info") companyInfo();
    if (action === "statement-features")
      await statementFeatures(b.dataset.statement);
    if (action === "interests") interests();
    if (action === "reason") reason(id);
    if (action === "article") await article(id);
    if (action === "tag-feedback") tagFeedback(id);
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
    if (action === "reset-period") {
      state.days = 7;
      await refresh();
    }
    if (action === "logout") {
      if (isDemo) api.setScenario("normal");
      await api.request("POST", "/api/auth/logout");
      state.profile = null;
      state.feed = null;
      state.analysis = null;
      state.messages = [];
      documentUrls.forEach((url) => URL.revokeObjectURL(url));
      documentUrls.clear();
      closePanel();
      location.hash = "home";
    }
    if (b.dataset.company) {
      b.disabled = true;
      state.profile = await api.request("PUT", "/api/profile/company", {
        company_id: b.dataset.company,
      });
      state.feed = null;
      closePanel();
      if (route() === "news") await render();
      else location.hash = "news";
      toast("Компания изменена. Подборка обновлена");
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
          esc(err.message) +
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
        `<span class="eyebrow">${esc(t.ticker)} · ${esc(t.board)}</span><div class="quote-price">${money(t.price)} ₽</div><p class="${t.change_percent > 0 ? "positive" : t.change_percent < 0 ? "negative" : ""}">${change(t.change_percent)} к предыдущему закрытию</p><dl class="facts-list"><div><dt>Предыдущее закрытие</dt><dd>${money(t.previous_close)} ₽</dd></div><div><dt>Денежный оборот</dt><dd>${money(t.turnover_rub === null ? null : t.turnover_rub / 1e6)} млн ₽</dd></div><div><dt>Время котировки</dt><dd>${date(t.as_of)}</dd></div><div><dt>Время получения</dt><dd>${date(t.captured_at)}</dd></div><div><dt>Задержка</dt><dd>${t.data_delay_minutes === null ? "Неизвестна" : esc(t.data_delay_minutes) + " мин"}</dd></div></dl><div class="notice">${isDemo ? "Синтетические котировки" : "Сохранённые данные MOEX"}. Торговые операции недоступны.</div>`,
        "Карточка инструмента",
      );
    }
  } catch (error) {
    toast(error.message);
    if (b.isConnected) b.disabled = false;
  }
});
document.addEventListener("change", async (e) => {
  if (e.target.id === "period") {
    state.days = Number(e.target.value);
    await refresh();
  }
});
document.addEventListener("input", (e) => {
  if (e.target.id === "market-search") {
    marketLimit = 30;
    renderMarketTiles();
    return;
  }
  if (e.target.id === "topic-search") {
    const query = e.target.value.trim().toLocaleLowerCase("ru");
    $$(".searchable-topics label").forEach((label) => {
      label.hidden = !label.textContent.toLocaleLowerCase("ru").includes(query);
    });
    return;
  }
  if (e.target.id !== "company-search") return;
  clearTimeout(searchTimer);
  ++searchVersion;
  const query = e.target.value.trim();
  const input = e.target;
  searchTimer = setTimeout(() => {
    if (input.isConnected) loadCompanies(query, 0);
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
    if (form.id === "login-form") {
      state.profile = null;
      const city = String(body.get("city")).trim();
      if (!city) throw new Error("Укажите город проживания");
      await api.request("POST", "/api/auth/demo", {
        company_id: body.get("company_id"),
        city,
        job_role: body.get("job_role"),
      });
      state.feed = null;
      if (route() === "news") await render();
      else location.hash = "news";
    }
    if (form.id === "settings-form") {
      const city = String(body.get("city")).trim();
      if (!city) throw new Error("Укажите город проживания");
      await api.request("PUT", "/api/profile/settings", {
        city,
        job_role: state.profile.user.job_role,
      });
      state.profile = await api.request("GET", "/api/profile");
      state.feed = null;
      closePanel();
      if (route() === "home") home();
      else if (route().startsWith("analysis/") && state.analysis) {
        renderAnalysis();
        renderConversation();
      } else await render();
      toast("Профиль сохранён");
    }
    if (form.id === "demo-role-form") {
      await api.request("PUT", "/api/profile/settings", {
        city: state.profile.user.city,
        job_role: body.get("job_role"),
      });
      state.profile = await api.request("GET", "/api/profile");
      state.feed = null;
      closePanel();
      if (route() === "news") await render();
      else location.hash = "news";
      toast("Роль демосценария изменена. Подборка обновлена");
    }
    if (form.id === "interests-form") {
      const included = body.getAll("company-topic"),
        companyIds = state.profile.company_tags.map((t) => t.tag_id);
      state.profile = await api.request("PUT", "/api/profile/interests", {
        personal: body.getAll("personal"),
        disabled: [
          ...state.profile.disabled_tag_ids.filter(
            (t) => !companyIds.includes(t),
          ),
          ...companyIds.filter((t) => !included.includes(t)),
        ],
      });
      state.feed = null;
      closePanel();
      if (route() === "news") await render();
      else location.hash = "news";
      toast("Темы сохранены. Подборка обновлена");
    }
    if (form.id === "tag-form") {
      await api.request("POST", `/api/news/${form.dataset.id}/tag-feedback`, {
        snapshot_id: state.feed.snapshot_id,
        wrong_tag_ids: body.getAll("wrong"),
        suggested_tag_ids: body.getAll("suggested"),
      });
      closePanel();
      toast(
        isDemo ? "Замечание принято в учебном режиме" : "Замечание сохранено",
      );
    }
    if (form.id === "question-form") {
      const question = String(body.get("question")).trim();
      if (!question) throw new Error("Введите вопрос");
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
configureShell();
hydrate();
theme();
render();
