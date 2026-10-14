/**
 * Thin FastAPI client for the apply agent.
 */

export function createApiClient(apiBase) {
  const base = apiBase.replace(/\/$/, "");

  async function request(method, path, body) {
    const url = `${base}${path}`;
    const init = {
      method,
      headers: { Accept: "application/json" },
    };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const res = await fetch(url, init);
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { raw: text };
    }
    if (!res.ok) {
      const detail = data?.detail || text || res.statusText;
      const err = new Error(
        typeof detail === "string" ? detail : JSON.stringify(detail)
      );
      err.status = res.status;
      err.detail = detail;
      throw err;
    }
    return data;
  }

  return {
    health: () => request("GET", "/health"),
    getCandidate: () => request("GET", "/candidate"),
    ingestGlassdoorJob: (payload) =>
      request("POST", "/agent/jobs/ingest", payload),
    analyzeJob: (jobId) => request("POST", `/jobs/${jobId}/analyze`),
    generatePackage: async (jobId) => {
      const started = await request("POST", `/jobs/${jobId}/generate`);
      const runId = started?.runId;
      const deadline = Date.now() + 20 * 60 * 1000;
      while (Date.now() < deadline) {
        const status = await request(
          "GET",
          runId
            ? `/jobs/${jobId}/generate?runId=${encodeURIComponent(runId)}`
            : `/jobs/${jobId}/generate`
        );
        if (status?.status === "completed") {
          return request("GET", `/jobs/${jobId}/package`);
        }
        if (status?.status === "failed") {
          throw new Error(status.error || status.message || "Package generation failed");
        }
        await new Promise((r) => setTimeout(r, 2500));
      }
      throw new Error("Package generation timed out waiting for API");
    },
    getPackage: (jobId) => request("GET", `/jobs/${jobId}/package`),
    getGenerateStatus: (jobId, runId) =>
      request(
        "GET",
        runId
          ? `/jobs/${jobId}/generate?runId=${encodeURIComponent(runId)}`
          : `/jobs/${jobId}/generate`
      ),
    setApplicationStatus: (jobId, applicationStatus, note) =>
      request("PATCH", `/jobs/${jobId}/application-status`, {
        applicationStatus,
        note,
      }),
    createRun: (payload) => request("POST", "/agent/runs", payload),
    patchRun: (runId, payload) =>
      request("PATCH", `/agent/runs/${runId}`, payload),
    getRun: (runId) => request("GET", `/agent/runs/${runId}`),
    listRuns: () => request("GET", "/agent/runs"),
    appendEvent: (runId, event) =>
      request("POST", `/agent/runs/${runId}/events`, event),
    listEvents: (runId) => request("GET", `/agent/runs/${runId}/events`),
    listAnswers: () => request("GET", "/agent/answers"),
    saveAnswer: (payload) => request("POST", "/agent/answers", payload),
    getAgentProfile: () => request("GET", "/agent/profile"),
  };
}
