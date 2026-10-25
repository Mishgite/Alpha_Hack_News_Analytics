export async function analysisRevision(company, news) {
  const payload = JSON.stringify({ company, news }, (_, value) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, value[key]]))
      : value,
  );
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(payload));
  return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function createAnalysisTracker(api, storage) {
  const memory = new Map();
  const pending = new Map();
  function load(key) {
    if (memory.has(key)) return memory.get(key);
    try {
      return JSON.parse(storage.getItem(key));
    } catch {
      return memory.get(key);
    }
  }
  function save(key, value) {
    memory.set(key, value);
    try {
      storage.setItem(key, JSON.stringify(value));
    } catch {}
  }
  return {
    forget(userId, companyId, newsId) {
      save(`alfa-job:${userId}:${companyId}:${newsId}`, null);
    },
    complete(userId, companyId, newsId, expiresAt) {
      const key = `alfa-job:${userId}:${companyId}:${newsId}`;
      const entry = load(key);
      if (entry) save(key, { ...entry, expiresAt });
    },
    start(userId, companyId, newsId, revision = "") {
      const key = `alfa-job:${userId}:${companyId}:${newsId}`;
      const running = pending.get(key);
      if (running?.revision === revision && running.isCurrent()) return running.request;
      let entry = load(key);
      if (
        !entry ||
        entry.revision !== revision ||
        (entry.expiresAt && Date.parse(entry.expiresAt) <= Date.now())
      ) {
        entry = { idempotency_key: crypto.randomUUID(), revision };
      }
      save(key, entry);
      const isCurrent = () => load(key)?.idempotency_key === entry.idempotency_key;
      async function request() {
        let job;
        if (entry.jobId) {
          try {
            job = await api.request("GET", `/api/analysis-jobs/${entry.jobId}`);
          } catch (error) {
            if (error.status !== 404) throw error;
          }
          if (job?.status === "failed" || !job) {
            if (!isCurrent()) throw new Error("Analysis request superseded");
            entry = { idempotency_key: crypto.randomUUID(), revision };
            save(key, entry);
            job = null;
          }
        }
        if (!job) {
          job = await api.request("POST", `/api/news/${newsId}/analysis`, {
            idempotency_key: entry.idempotency_key,
          });
          if (isCurrent()) save(key, { ...entry, jobId: job.id });
        }
        return job;
      }
      const task = { revision, isCurrent };
      task.request = request().finally(() => {
        if (pending.get(key) === task) pending.delete(key);
      });
      pending.set(key, task);
      return task.request;
    },
    conversation(userId, analysisId) {
      const key = `alfa-conversation:${userId}:${analysisId}`;
      let id = load(key);
      if (!id) {
        id = crypto.randomUUID();
        save(key, id);
      }
      return id;
    },
  };
}
