const messages = {
  401: "Сессия завершена. Войдите снова",
  403: "Нет доступа к этим данным или демовход отключён на сервере",
  404: "Данные не найдены",
  409: "Данные изменились. Обновите страницу и повторите действие",
  429: "Слишком много запросов. Повторите позже",
  500: "Внутренняя ошибка сервера",
  502: "Сервер временно недоступен",
  503: "Сервис временно недоступен. Попробуйте позже",
  504: "Сервер не успел ответить. Повторите позже",
};
const details = {
  "Analysis worker unavailable":
    "AI-разбор сейчас недоступен: обработчик не запущен или модель не настроена",
  "Database unavailable": "Нет соединения с базой данных",
  "Source PDF is not available": "Исходный PDF отсутствует на сервере",
  "Snapshot expired": "Срок подборки истёк. Обновите ленту",
};

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
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
        "Адрес API не настроен. Укажите VITE_API_URL при сборке",
      );
    if (!path.startsWith("/api/") && path !== "/health")
      throw new ApiError("Недопустимый путь API");
    const headers = {
      Accept: path.endsWith("/document")
        ? "application/pdf"
        : "application/json",
    };
    if (hasSession()) headers.Authorization = `Bearer ${session.access_token}`;
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
        if (response.status === 401) save(null);
        let message = details[payload?.detail] || messages[response.status];
        if (response.status === 422 && Array.isArray(payload?.detail)) {
          message =
            "Проверьте поля: " +
            payload.detail
              .map((item) => item.loc?.slice(1).join(".") || "запрос")
              .join(", ");
        }
        if (!message && typeof payload?.detail === "string")
          message = payload.detail;
        throw new ApiError(
          message || "Не удалось выполнить запрос",
          response.status,
        );
      }
      if (response.status === 204) {
        if (path === "/api/auth/logout") save(null);
        return null;
      }
      if (path.endsWith("/document")) {
        if (!response.headers.get("content-type")?.includes("application/pdf"))
          throw new ApiError("Сервер вернул файл неизвестного формата");
        return await response.blob();
      }
      if (!response.headers.get("content-type")?.includes("application/json"))
        throw new ApiError("Сервер вернул некорректный ответ");
      const data = await response.json();
      if (path === "/api/auth/demo") {
        if (!data.access_token || !Number.isFinite(Date.parse(data.expires_at)))
          throw new ApiError("Некорректная сессия в ответе сервера");
        save(data);
      }
      return data;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (controller.signal.aborted)
        throw new ApiError(
          "Время ожидания истекло. Сервер мог принять запрос; повторите проверку состояния",
          504,
        );
      throw new ApiError(
        "Нет соединения с API. Проверьте подключение, адрес сервера и настройки CORS",
      );
    } finally {
      clearTimeout(timer);
    }
  }
  return { request, hasSession, clearSession: () => save(null) };
}
