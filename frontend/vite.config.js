import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode, command }) => {
  const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };
  if (command === "build" && env.VITE_API_URL) {
    const url = new URL(env.VITE_API_URL);
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (
      (url.protocol !== "https:" &&
        !(url.protocol === "http:" && local && !env.GITHUB_ACTIONS)) ||
      (local && env.GITHUB_ACTIONS) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      throw new Error(
        "Для Pages нужен публичный HTTPS API без пароля, параметров и якоря; локальная сборка допускает HTTP localhost",
      );
    }
  }
  return {
    base: env.PAGES_BASE_PATH || "./",
    build: { target: "es2022", sourcemap: false },
  };
});
