export function createAnalysisTracker(api, storage) {
  const memory = new Map();
  function load(key) {
    try {
      return JSON.parse(storage.getItem(key)) || memory.get(key);
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
    async start(userId, companyId, newsId, revision = "") {
      const key = `alfa-job:${userId}:${companyId}:${newsId}`;
      let entry = load(key);
      if (
        !entry ||
        entry.revision !== revision ||
        (entry.expiresAt && Date.parse(entry.expiresAt) <= Date.now())
      ) {
        entry = { idempotency_key: crypto.randomUUID(), revision };
      }
      save(key, entry);
      let job;
      if (entry.jobId) {
        try {
          job = await api.request("GET", `/api/analysis-jobs/${entry.jobId}`);
        } catch (error) {
          if (error.status !== 404) throw error;
        }
        if (job?.status === "failed" || !job) {
          entry = { idempotency_key: crypto.randomUUID(), revision };
          save(key, entry);
          job = null;
        }
      }
      if (!job) {
        job = await api.request("POST", `/api/news/${newsId}/analysis`, {
          idempotency_key: entry.idempotency_key,
        });
        save(key, { ...entry, jobId: job.id });
      }
      return job;
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
