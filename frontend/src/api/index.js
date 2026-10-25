import { createHttpClient } from "./http.js";

export const roles = {
  ceo: "Руководитель",
  cfo: "Финансовый директор",
  accountant: "Бухгалтер",
  treasury: "Казначей",
  employee: "Сотрудник",
  other: "Другая роль",
};
export const isDemo = import.meta.env.DEV && import.meta.env.MODE === "demo";
export const apiUrl =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");
const storage = {
  getItem: (key) => sessionStorage.getItem(key),
  setItem: (key, value) => sessionStorage.setItem(key, value),
  removeItem: (key) => sessionStorage.removeItem(key),
};
export const api = isDemo
  ? (await import("../demo/mock-api.js")).demo
  : createHttpClient({ baseUrl: apiUrl, storage });
