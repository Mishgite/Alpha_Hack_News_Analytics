export function createInteractionTracker(api) {
  const events = new Map();
  function record(type, snapshotId, newsId) {
    const key = `${type}:${snapshotId}:${newsId}`;
    let entry = events.get(key);
    if (!entry) {
      entry = {
        body: {
          event_id: crypto.randomUUID(),
          snapshot_id: snapshotId,
          occurred_at: new Date().toISOString(),
          ...(type === "impression" ? { news_id: newsId } : {}),
        },
      };
      events.set(key, entry);
    }
    if (!entry.request) {
      const path =
        type === "impression" ? "/api/impressions" : `/api/news/${newsId}/open`;
      entry.request = Promise.resolve()
        .then(() => api.request("POST", path, entry.body))
        .catch((error) => {
          entry.request = null;
          throw error;
        });
    }
    return entry.request;
  }
  return {
    impression: (snapshotId, newsId) => record("impression", snapshotId, newsId),
    open: (snapshotId, newsId) => record("open", snapshotId, newsId),
  };
}
