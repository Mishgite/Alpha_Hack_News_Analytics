import { UserError } from "../api/errors.js";
import { seedStories, detailText } from "./data.js";
import samplePdf from "../../assets/sample-report.pdf?url";
export const demo = (() => {
  const uid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
  const now = new Date("2026-10-25T12:00:00+03:00");
  const tags = [
    ["biz_credit", "Кредитование"],
    ["biz_rates", "Экономика"],
    ["biz_logistic", "Логистика"],
    ["biz_regulation", "Регулирование"],
    ["biz_tax", "Налоги"],
    ["biz_technology", "Технологии"],
    ["biz_investment", "Инвестиции"],
    ["biz_staff", "Кадры"],
    ["biz_fx", "Валютные расчёты"],
    ["biz_budget", "Бюджет"],
  ].map(([id, display_name]) => ({ id, display_name }));
  const tagId = (name) =>
    tags.find((t) => t.display_name === name)?.id || "biz_rates";
  const companies = [
    {
      id: "DEMO-001",
      industry: "Грузоперевозки",
      city: "Москва",
      region: "Москва",
      okved_code: "49.41",
      okved_name: "Деятельность автомобильного грузового транспорта",
      revenue: "21000000000",
      group_id: "GROUP-DEMO-01",
      profile_version: "demo-v1",
      profile_json: { synthetic: true },
      known_factor_interests: ["credit"],
      operating_region_codes: null,
    },
    {
      id: "DEMO-002",
      industry: "Разработка ПО",
      city: "Казань",
      region: "Татарстан",
      okved_code: "62.01",
      okved_name: "Разработка компьютерного программного обеспечения",
      revenue: "18000000000",
      group_id: null,
      profile_version: "demo-v1",
      profile_json: { synthetic: true },
      known_factor_interests: [],
      operating_region_codes: null,
    },
    {
      id: "DEMO-003",
      industry: "Промышленное производство",
      city: "Екатеринбург",
      region: "Свердловская область",
      okved_code: "25.11",
      okved_name: "Производство строительных металлических конструкций",
      revenue: "32000000000",
      group_id: "GROUP-DEMO-02",
      profile_version: "demo-v1",
      profile_json: { synthetic: true },
      known_factor_interests: ["credit"],
      operating_region_codes: null,
    },
  ];
  const companyTags = {
    "DEMO-001": ["biz_logistic", "biz_credit", "biz_regulation"],
    "DEMO-002": ["biz_technology", "biz_tax", "biz_staff"],
    "DEMO-003": ["biz_investment", "biz_credit", "biz_logistic"],
  };
  const extra = [
    ["Компании пересматривают условия оборотного финансирования", "rate"],
    ["Перевозчики готовят переход на электронные накладные", "logistics"],
    ["Финансовые команды уточняют налоговые бюджеты", "tax"],
    ["Сезонный спрос увеличивает нагрузку на склады", "logistics"],
    ["Автоматизация закупок: бизнес переходит к пилотным проектам", "digital"],
    ["Производители оценивают затраты на доставку сырья", "fuel"],
    ["Рынок труда: растёт спрос на технических специалистов", "staff"],
    ["Кредитные условия становятся предметом пересмотра договоров", "rate"],
    ["ИТ-компании проверяют условия подтверждения льгот", "tax"],
    ["Новые инструменты для контроля расходов на перевозки", "digital"],
    ["Топливные расходы включают в сценарное планирование", "fuel"],
    ["Бизнес планирует обучение сотрудников новым системам", "staff"],
    ["Региональные склады расширяют электронный обмен", "logistics"],
    ["Финансовые службы сравнивают варианты рефинансирования", "rate"],
    ["Производственные компании тестируют учёт запасов", "digital"],
    ["ИТ-отрасль пересматривает планы найма", "staff"],
    ["Поставщики обсуждают индексацию транспортных тарифов", "fuel"],
    ["Компании готовят документы для налоговой проверки", "tax"],
  ];
  const all = [
    ...seedStories.map((s) => ({ ...s, key: s.id })),
    ...extra.map(([title, key]) => ({
      ...seedStories.find((s) => s.id === key),
      title,
      key,
    })),
  ];
  const articles = all.map((s, i) => ({
    news_id: uid(i + 1),
    title: s.title,
    summary: s.summary,
    text: detailText[s.key].fact + " " + s.summary,
    published_at: new Date(now.getTime() - (i * 5 + 1) * 3600000).toISOString(),
    source_url: null,
    tags: s.tags.map(tagId),
    source_name:
      i % 3 === 0
        ? "Учебная деловая лента"
        : i % 3 === 1
          ? "Учебный отраслевой обзор"
          : "Учебный экономический обзор",
    seed: s.key,
  }));
  const roles = {
    ceo: "Руководитель",
    cfo: "Финансовый директор",
    accountant: "Бухгалтер",
    treasury: "Казначей",
    employee: "Сотрудник",
    other: "Другая роль",
  };
  const roleWeights = {
    ceo: { biz_investment: 1.2, biz_logistic: 1.1 },
    cfo: { biz_credit: 1.3, biz_rates: 1.3, biz_budget: 1.2 },
    accountant: { biz_tax: 1.3 },
    treasury: { biz_fx: 1.3, biz_rates: 1.3 },
  };
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem("alfa-prototype-v3"));
  } catch {}
  const validSaved =
    saved?.user &&
    companies.some((c) => c.id === saved.user.company_id) &&
    roles[saved.user.job_role] &&
    typeof saved.user.city === "string";
  let user = validSaved ? saved.user : null;
  let personal =
    validSaved && Array.isArray(saved.personal)
      ? saved.personal.filter((t) => tags.some((x) => x.id === t))
      : [];
  let disabled =
    validSaved && Array.isArray(saved.disabled)
      ? saved.disabled.filter((t) => tags.some((x) => x.id === t))
      : [];
  let reactions =
    validSaved && saved.reactions && typeof saved.reactions === "object"
      ? saved.reactions
      : {};
  let scenario = "normal";
  const snapshots = new Map(),
    analyses = new Map(),
    jobs = new Map(),
    conversations = new Map(),
    impressions = new Set();
  let serial = 200;
  const persist = () => {
    try {
      localStorage.setItem(
        "alfa-prototype-v3",
        JSON.stringify({ user, personal, disabled, reactions }),
      );
    } catch {}
  };
  const error = (status, detail) =>
    new UserError(detail, status);
  const delay = (ms) => new Promise((r) => setTimeout(r, ms));
  const profile = () => ({
    user: { ...user },
    company: companies.find((c) => c.id === user.company_id),
    company_tags: companyTags[user.company_id].map((tag_id) => ({
      tag_id,
      origin: "rule",
      base_weight: 1,
    })),
    personal_tag_ids: [...personal],
    disabled_tag_ids: [...disabled],
    reaction_counts: counts(),
  });
  function counts() {
    const result = {};
    for (const [id, reaction] of Object.entries(reactions))
      for (const tag of articles.find((a) => a.news_id === id)?.tags || []) {
        result[tag] ??= { likes: 0, dislikes: 0 };
        if (reaction === "like") result[tag].likes++;
        if (reaction === "dislike") result[tag].dislikes++;
      }
    return result;
  }
  function weights() {
    const w = { ...roleWeights[user.job_role] };
    for (const t of [...companyTags[user.company_id], ...personal])
      w[t] = Math.max(w[t] || 0, 1);
    for (const [t, c] of Object.entries(counts()))
      if (w[t])
        w[t] = Math.max(
          0,
          Math.min(
            2,
            w[t] * (1 + 0.2 * (Math.log1p(c.likes) - Math.log1p(c.dislikes))),
          ),
        );
    for (const t of disabled) w[t] = 0;
    return w;
  }
  function page(s, position = 0, limit = 20) {
    return {
      snapshot_id: s.id,
      generated_at: s.generated_at,
      expires_at: s.expires_at,
      items: s.items.slice(position, position + limit).map((a) => ({
        ...a,
        my_reaction: reactions[a.ranking.news_id] || "none",
      })),
      next_position:
        position + limit < s.items.length ? position + limit : null,
      has_more: position + limit < s.items.length,
    };
  }
  function analysis(article, companyId, analysisScenario) {
    const c = companies.find((c) => c.id === companyId),
      d = detailText[article.seed],
      nid = article.news_id;
    const newsRef = {
      id: "news:" + nid,
      title: article.title,
      url: null,
      page: null,
      excerpt: d.fact,
      kind: "news",
      published_on: article.published_at.slice(0, 10),
    };
    const companyRef = {
      id: "company:" + c.id,
      title: "Профиль " + c.id,
      url: null,
      page: null,
      excerpt: `${c.industry}. ОКВЭД ${c.okved_code}. Город регистрации: ${c.city}. Выручка ${c.revenue} ₽. Синтетические данные.`,
      kind: "company",
      published_on: null,
    };
    const statement = (text, refs = [newsRef.id], condition = null) => ({
      text,
      source_refs: refs,
      company_feature_refs: refs.includes(companyRef.id)
        ? ["industry", "okved_code"]
        : [],
      condition,
      evidence_quotes: {},
    });
    const direct = companyTags[c.id].some((t) => article.tags.includes(t));
    const result = {
      news_id: nid,
      company_id: c.id,
      facts: [statement(d.fact)],
      why_important: [
        statement(
          direct
            ? `Событие связано с деятельностью компании: ${c.industry.toLowerCase()}. Необходимо проверить влияние на текущие договоры и расходы.`
            : `Прямое влияние на отрасль «${c.industry}» не подтверждено. Возможна косвенная связь через подрядчиков и затраты.`,
          [newsRef.id, companyRef.id],
        ),
      ],
      risks: [
        statement(
          direct
            ? d.risk
            : `Для компании из отрасли «${c.industry}» риск возможен через зависимость от затронутых поставщиков: изменение их затрат может отразиться на стоимости закупаемых услуг`,
          [newsRef.id, companyRef.id],
          "Если условия события распространяются на действующие договоры компании",
        ),
      ],
      opportunities: [
        statement(
          direct
            ? d.opportunity
            : `Компания ${c.id} может заранее запросить у подрядчиков оценку изменений и сравнить условия действующих договоров`,
          [newsRef.id, companyRef.id],
          "После проверки применимости к компании",
        ),
      ],
      recommendations: (direct
        ? d.actions
        : [
            "Проверить, есть ли среди контрагентов участники затронутой отрасли",
            "Уточнить у закупочной команды условия индексации и сроки исполнения",
            "Не менять бюджет до подтверждения связи события с действующими договорами",
          ]
      ).map((a) => statement(a, [newsRef.id, companyRef.id])),
      bank_position: null,
      source_refs: [newsRef, companyRef],
      limitations: [
        "Подходящий аналитический материал банка не найден",
        "Доля рынка, география деятельности и условия договоров неизвестны",
      ],
    };
    if (analysisScenario === "complete" || analysisScenario === "conflict") {
      const bank = {
        id: "report:" + uid(900),
        title: "Учебный макрообзор · синтетический пример",
        url: "/api/report-chunks/" + uid(900),
        page: 3,
        excerpt:
          "Изменение условий финансирования может постепенно отражаться на инвестиционных решениях компаний.",
        kind: "bank_report",
        published_on: "2026-10-20",
      };
      result.source_refs.push(bank);
      result.bank_position = statement(bank.excerpt, [bank.id]);
      result.limitations =
        analysisScenario === "conflict"
          ? [
              "Учебный отчёт от 20 октября относится к более раннему периоду, чем новость. Его оценку нельзя считать актуальным подтверждением события.",
            ]
          : [];
    }
    return {
      id: uid(++serial),
      company_id: c.id,
      news_id: nid,
      result,
      status: result.limitations.length ? "partial" : "ready",
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      cache_key: `${c.id}:${nid}`,
      trace: [
        { step: "company_context", context_id: uid(500) },
        {
          step: "plan",
          queries: [article.title],
          company_feature_refs: ["industry", "okved_code"],
        },
        {
          step: "search_reports",
          query: article.title,
          chunks: result.bank_position ? [uid(900)] : [],
        },
        {
          step: "validation",
          attempt: 1,
          valid: true,
          supported: true,
          issues: result.limitations,
        },
        { step: "complete", sources: result.source_refs.map((s) => s.id) },
      ],
    };
  }
  async function request(method, path, body = {}) {
    await delay(180);
    const url = new URL(path, "http://demo.local"),
      p = url.pathname,
      q = url.searchParams;
    if (p === "/api/companies")
      return companies.filter((c) =>
        [c.id, c.industry, c.okved_code, c.okved_name, c.city, c.region]
          .join(" ")
          .toLowerCase()
          .includes((q.get("query") || "").trim().toLowerCase()),
      );
    if (p === "/api/auth/demo") {
      if (
        !companies.some((c) => c.id === body.company_id) ||
        !roles[body.job_role]
      )
        throw error(422, "Укажите компанию и роль");
      user = {
        id: uid(100),
        company_id: body.company_id,
        city: body.city?.trim() || "",
        job_role: body.job_role,
        access_role: "user",
      };
      persist();
      return {
        user: { ...user },
        access_token: "local-demo-only",
        token_type: "bearer",
        expires_at: new Date(Date.now() + 86400000).toISOString(),
      };
    }
    if (!user || scenario === "session")
      throw error(401, "Сессия завершена. Войдите снова");
    if (p === "/api/auth/logout") {
      user = null;
      personal = [];
      disabled = [];
      reactions = {};
      snapshots.clear();
      persist();
      return null;
    }
    if (p === "/api/profile") return profile();
    if (p === "/api/tags") return tags;
    if (p === "/api/profile/company") {
      if (!companies.some((c) => c.id === body.company_id))
        throw error(404, "Компания не найдена");
      user.company_id = body.company_id;
      snapshots.clear();
      persist();
      return profile();
    }
    if (p === "/api/profile/settings") {
      user = { ...user, ...body };
      persist();
      return { ...user };
    }
    if (p === "/api/profile/interests") {
      personal = [...body.personal];
      disabled = [...body.disabled];
      persist();
      return profile();
    }
    if (p === "/api/profile/priorities")
      return {
        user_id: user.id,
        company_id: user.company_id,
        job_role: user.job_role,
        tag_weights: weights(),
        profile_version: "demo-v1",
      };
    if (p === "/api/profile/context")
      return {
        id: uid(500),
        company_id: user.company_id,
        context_hash: "demo",
        payload_json: {
          company: profile().company,
          unknown: ["market_share", "operating_regions"],
        },
        source_versions_json: { fixture: "demo-v1" },
      };
    if (p === "/api/feed") {
      if (scenario === "network")
        throw error(503, "Не удалось получить новости. Попробуйте ещё раз");
      const w = weights(),
        days = body.days || 7;
      let items = articles
        .filter((a) => (now - new Date(a.published_at)) / 86400000 <= days)
        .map((a) => {
          const matched = a.tags.filter((t) => w[t] > 0),
            match = Math.min(
              1,
              Math.max(0, ...matched.map((t) => (w[t] * 0.9) / 2)),
            ),
            fresh = 1 / (1 + (now - new Date(a.published_at)) / 86400000);
          return {
            position: 0,
            title: a.title,
            summary: a.summary,
            published_at: a.published_at,
            source_url: a.source_url,
            tags: a.tags,
            my_reaction: reactions[a.news_id] || "none",
            ranking: {
              news_id: a.news_id,
              match_score: match,
              freshness_score: fresh,
              final_score: 0.8 * match + 0.2 * fresh,
              matched_signals: matched,
              reason: matched.length
                ? "Совпали темы профиля: " + matched.join(", ")
                : "Совпадений тем нет, учтена свежесть",
            },
          };
        })
        .sort(
          (a, b) =>
            b.ranking.final_score - a.ranking.final_score ||
            a.ranking.news_id.localeCompare(b.ranking.news_id),
        )
        .map((a, i) => ({ ...a, position: i }));
      if (scenario === "empty") items = [];
      const s = {
        id: uid(++serial),
        company_id: user.company_id,
        items,
        generated_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 1800000).toISOString(),
      };
      snapshots.set(s.id, s);
      return page(s, 0, body.page_size || 20);
    }
    if (p.startsWith("/api/feed/")) {
      const s = snapshots.get(p.split("/").pop());
      if (
        !s ||
        s.company_id !== user.company_id ||
        scenario === "expired" ||
        Date.parse(s.expires_at) < Date.now()
      )
        throw error(400, "Подборка устарела. Обновите ленту");
      return page(
        s,
        Number(q.get("position") || 0),
        Number(q.get("limit") || 20),
      );
    }
    if (p === "/api/impressions" || p.endsWith("/open")) {
      impressions.add(body.event_id);
      return {
        event_id: body.event_id,
        user_id: user.id,
        news_id: body.news_id || p.split("/")[3],
        snapshot_id: body.snapshot_id,
        event_type: p === "/api/impressions" ? "impression" : "open",
        occurred_at: body.occurred_at,
      };
    }
    if (p.startsWith("/api/news/")) {
      const id = p.split("/")[3],
        a = articles.find((x) => x.news_id === id);
      if (!a) throw error(404, "Новость не найдена");
      if (p.endsWith("/reaction") || p.endsWith("/tag-feedback")) {
        const s = snapshots.get(body.snapshot_id);
        if (!s || s.company_id !== user.company_id || scenario === "expired")
          throw error(400, "Подборка устарела. Обновите ленту");
        if (p.endsWith("/reaction")) {
          reactions[id] = body.reaction;
          persist();
          return {
            news_id: id,
            likes_cnt: body.reaction === "like" ? 1 : 0,
            dislikes_cnt: body.reaction === "dislike" ? 1 : 0,
            my_reaction: body.reaction,
          };
        }
        if (!body.wrong_tag_ids?.length && !body.suggested_tag_ids?.length)
          throw error(422, "Выберите неверную тему или предложите другую");
        return { accepted: true };
      }
      if (p.endsWith("/analysis")) {
        if (scenario === "limit")
          throw error(
            503,
            "Лимит AI-разборов на сегодня исчерпан. Новости и готовые разборы доступны",
          );
        if (scenario === "network")
          throw error(503, "Разбор временно недоступен. Попробуйте позже");
        const key = user.company_id + ":" + body.idempotency_key;
        if (jobs.has(key)) return jobs.get(key);
        const cached = [...analyses.values()].find(
          (x) => x.news_id === id && x.company_id === user.company_id,
        );
        const j = {
          id: uid(++serial),
          user_id: user.id,
          company_id: user.company_id,
          news_id: id,
          analysis_id: cached?.id || null,
          status: cached ? "ready" : "queued",
          worker_id: null,
          attempts: 0,
          lease_until: null,
          error_code: null,
        };
        jobs.set(key, j);
        jobs.set(j.id, j);
        if (!cached) {
          const companyId = user.company_id,
            analysisScenario = scenario;
          setTimeout(() => {
            j.status = "running";
          }, 450);
          setTimeout(() => {
            if (analysisScenario === "failed") {
              j.status = "failed";
              j.error_code = "analysis_failed";
              return;
            }
            const result = analysis(a, companyId, analysisScenario);
            analyses.set(result.id, result);
            j.status = "ready";
            j.analysis_id = result.id;
          }, 1600);
        }
        return { ...j };
      }
      return {
        news_id: a.news_id,
        title: a.title,
        text: a.text,
        published_at: a.published_at,
        source_url: a.source_url,
        content_hash: "demo-" + a.news_id,
        tagging_status: "ready",
        tagging_version: "demo-v1",
        features: {
          news_id: a.news_id,
          tags: a.tags.map((id) => ({ id, confidence: 0.9 })),
          geography: { country_code: "RU", region_codes: [], nationwide: null },
          summary: a.summary,
        },
      };
    }
    if (p.startsWith("/api/analysis-jobs/")) {
      const j = jobs.get(p.split("/").pop());
      if (!j || j.company_id !== user.company_id)
        throw error(404, "Разбор больше недоступен");
      return { ...j };
    }
    if (p.startsWith("/api/analyses/")) {
      const id = p.split("/")[3],
        a = analyses.get(id);
      if (!a || a.company_id !== user.company_id)
        throw error(404, "Разбор не найден");
      if (p.endsWith("/trace")) return a.trace;
      if (p.endsWith("/context"))
        return {
          id: uid(500),
          company_id: a.company_id,
          context_hash: "demo",
          payload_json: { ...companies.find((c) => c.id === a.company_id) },
          source_versions_json: { fixture: "demo-v1" },
        };
      if (p.includes("/conversations/"))
        return conversations.get(id + ":" + p.split("/").pop()) || [];
      if (p.endsWith("/questions")) {
        if (scenario === "limit") throw error(503, "Лимит уточнений исчерпан");
        if (scenario === "failed")
          throw error(
            504,
            "Ответ не получен вовремя. Вопрос можно отправить повторно",
          );
        await delay(700);
        const answer = {
          id: uid(++serial),
          user_id: user.id,
          analysis_id: id,
          conversation_id: body.conversation_id,
          question: body.question,
          answer: `По компании ${a.company_id} подтверждён только отраслевой контекст. ${a.result.recommendations[0].text}. Точные финансовые последствия требуют условий договоров и внутренних показателей. Это подготовленный пример ответа, а не результат работы модели.`,
          sources_json: [a.result.source_refs[0]],
          created_at: new Date().toISOString(),
        };
        const key = id + ":" + body.conversation_id;
        conversations.set(key, [...(conversations.get(key) || []), answer]);
        return answer;
      }
      return a;
    }
    if (p.startsWith("/api/report-chunks/")) {
      if (p.endsWith("/document")) {
        const response = await fetch(samplePdf);
        if (!response.ok) throw error(404, "Документ недоступен");
        return response.blob();
      }
      return {
        id: uid(900),
        report_id: uid(901),
        page_num: 3,
        chunk_no: 0,
        text: "Изменение условий финансирования может постепенно отражаться на инвестиционных решениях компаний.",
        source_span_json: null,
        filename: "sample-report.pdf",
        title: "Учебный макрообзор",
        report_date: "2026-10-20",
        source_url: null,
      };
    }
    if (p === "/api/market" || p === "/api/market/refresh") {
      const stocks = [
        ["SBER", "Сбербанк", 1.84, 286.4, 8],
        ["GAZP", "Газпром", -2.12, 135.8, 6],
        ["LKOH", "Лукойл", 0.76, 7120, 4],
        ["NVTK", "Новатэк", -0.63, 1090, 3],
        ["YDEX", "Яндекс", 1.21, 4130, 3],
        ["TATN", "Татнефть", 0, 620, 2],
        ["PLZL", "Полюс", null, 2400, 2],
      ];
      const tiles = stocks.map(([ticker, name, change, price, size]) => ({
        ticker,
        name,
        board: "TQBR",
        price,
        previous_close: change === null ? null : price / (1 + change / 100),
        change_abs: change === null ? null : price - price / (1 + change / 100),
        change_percent: change,
        turnover_rub: size * 100000000,
        volume: null,
        as_of: "2026-10-23T18:50:00+03:00",
        captured_at: "2026-10-23T18:55:00+03:00",
        data_delay_minutes: null,
        size_metric: size,
        color_metric: change,
      }));
      return {
        source: "MOEX ISS",
        status:
          scenario === "empty"
            ? "empty"
            : scenario === "stale"
              ? "stale"
              : "ready",
        captured_at: "2026-10-23T18:55:00+03:00",
        size_basis: "turnover_rub",
        change_basis: "previous_close",
        heatmap: scenario === "empty" ? [] : tiles,
        top_movers:
          scenario === "empty"
            ? []
            : tiles
                .filter((t) => t.change_percent !== null)
                .sort(
                  (a, b) =>
                    Math.abs(b.change_percent) - Math.abs(a.change_percent),
                )
                .map(({ size_metric, color_metric, ...quote }) => quote),
      };
    }
    throw error(404, "Не удалось выполнить действие");
  }
  return {
    request,
    tags,
    roles,
    companies,
    articles,
    tagName: (id) => tags.find((t) => t.id === id)?.display_name || id,
    hasSession: () => Boolean(user),
    setScenario: (value) => {
      scenario = value;
    },
    getScenario: () => scenario,
  };
})();
