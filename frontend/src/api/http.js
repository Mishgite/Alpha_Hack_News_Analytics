import { messages, UserError } from "./errors.js";

const details = {
  "Analysis worker unavailable": "Разбор временно недоступен. Попробуйте позже",
  "Analysis generation paused": "Новые разборы и ответы временно недоступны. Сохранённые разборы можно читать",
  "Database unavailable": "Не удалось загрузить данные. Попробуйте позже",
  "Source PDF is not available": "Документ недоступен. Остальные источники можно открыть в разборе",
  "Source PDF could not be read": "Не удалось открыть документ. Попробуйте позже",
  "Source PDF differs from the cited version": "Документ обновлён и отличается от использованного в разборе",
  "Snapshot expired": "Подборка устарела. Обновите ленту",
};
const fields = {
  city: "город проживания",
  company_id: "компания",
  job_role: "роль",
  question: "вопрос",
  personal: "личные интересы",
  disabled: "отключённые темы",
  wrong_tag_ids: "неверные темы",
  suggested_tag_ids: "предложенные темы",
  days: "период новостей",
};

export class ApiError extends UserError {
  constructor(message, status = 0, diagnostic = null) {
    super(message, status);
    this.diagnostic = diagnostic;
  }
}

export function createHttpClient({ baseUrl, storage, fetcher = fetch }) {
  const base = baseUrl.replace(/\/+$/, "");
  const key = `alfa-api-session:${base}`;
  let session = null;
  try {
    session = JSON.parse(storage.getItem(key));
  } catch {}
  function save(value) {
    session = value;
    try {
      if (value) storage.setItem(key, JSON.stringify(value));
      else storage.removeItem(key);
    } catch {}
  }
  function hasSession() {
    if (
      !session?.access_token ||
      !Number.isFinite(Date.parse(session.expires_at)) ||
      Date.parse(session.expires_at) <= Date.now()
    ) {
      save(null);
      return false;
    }
    return true;
  }
  async function request(method, path, body, options = {}) {
    if (!base)
      throw new ApiError(
        "Приложение пока недоступно. Попробуйте позже", 0, "VITE_API_URL is missing",
      );
    if (!path.startsWith("/api/") && path !== "/health")
      throw new ApiError("Не удалось выполнить действие", 0, "Invalid API path");
    const headers = {
      Accept: path.endsWith("/document")
        ? "application/pdf"
        : "application/json",
    };
    const requestToken = hasSession() ? session.access_token : null;
    if (requestToken) headers.Authorization = `Bearer ${requestToken}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(),
      options.timeoutMs || (path.endsWith("/questions") ? 270000 : 20000),
    );
    let response;
    try {
      response = await fetcher(base + path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
        credentials: "omit",
        redirect: "error",
        cache: "no-store",
      });
      if (!response.ok) {
        let payload;
        try {
          payload = await response.json();
        } catch {}
        if (response.status === 401 && session?.access_token === requestToken) save(null);
        let message = typeof payload?.detail === "string" && Object.hasOwn(details, payload.detail)
          ? details[payload.detail]
          : messages[response.status];
        if (response.status === 422 && Array.isArray(payload?.detail)) {
          const names = [...new Set(payload.detail.flatMap((item) =>
            Array.isArray(item?.loc) ? item.loc.filter((key) => Object.hasOwn(fields, key)).map((key) => fields[key]) : [],
          ))];
          message = names.length ? "Проверьте поля: " + names.join(", ") : messages[422];
        }
        throw new ApiError(
          message || "Не удалось выполнить действие. Попробуйте ещё раз",
          response.status,
          payload?.detail ?? null,
        );
      }
      if (response.status === 204) {
        if (path === "/api/auth/logout" && session?.access_token === requestToken) save(null);
        return null;
      }
      if (path.endsWith("/document")) {
        if (!response.headers.get("content-type")?.includes("application/pdf"))
          throw new ApiError("Не удалось открыть документ. Попробуйте позже");
        return await response.blob();
      }
      if (!response.headers.get("content-type")?.includes("application/json"))
        throw new ApiError("Не удалось загрузить данные. Попробуйте ещё раз");
      let data;
      try {
        data = await response.json();
      } catch (error) {
        throw new ApiError("Не удалось загрузить данные. Попробуйте ещё раз", 0, error);
      }
      if (path === "/api/auth/demo") {
        if (!data?.access_token || !Number.isFinite(Date.parse(data.expires_at)))
          throw new ApiError("Не удалось войти. Попробуйте ещё раз");
        save(data);
      }
      return data;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (controller.signal.aborted)
        throw new ApiError(
          path.endsWith("/analysis")
            ? "Разбор занимает больше времени, чем обычно. Проверьте его позже"
            : path.endsWith("/questions")
              ? "Ответ пока не получен. Проверьте историю вопросов позже"
              : messages[504],
          504,
          error,
        );
      throw new ApiError(
        "Не удалось подключиться. Проверьте интернет и попробуйте ещё раз",
        0,
        error,
      );
    } finally {
      clearTimeout(timer);
    }
  }
  return { request, hasSession, clearSession: () => save(null) };
}
