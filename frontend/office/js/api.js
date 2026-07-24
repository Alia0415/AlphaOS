// AlphaOS backend API client (live mode). Read-only surfaces only for the
// current phase — task execution / planning endpoints require ARK credentials
// and are wired in a later phase. Demo mode reads mock.js instead of this file.

// Same-origin by default (FastAPI serves the office at /office). A different
// backend origin can be pinned via localStorage for standalone hosting.
function apiBase() {
  try {
    return (localStorage.getItem("alphaos.apiBase") || "").replace(/\/$/, "");
  } catch {
    return "";
  }
}

async function getJSON(path, { timeoutMs = 8000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(apiBase() + path, {
      headers: { Accept: "application/json" },
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function postJSON(path, body, { timeoutMs = 15000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(apiBase() + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) {
      let detail = `${res.status}`;
      try {
        const payload = await res.json();
        if (payload && payload.detail) detail = payload.detail;
      } catch {
        /* non-JSON error body */
      }
      throw new Error(`POST ${path} → ${detail}`);
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  // service status
  health: () => getJSON("/api/health", { timeoutMs: 4000 }),
  pandadataStatus: () => getJSON("/api/pandadata/status", { timeoutMs: 4000 }),

  // read-only surfaces
  overview: () => getJSON("/api/overview"),
  experts: () => getJSON("/api/experts"),
  skills: () => getJSON("/api/skills"),
  tasks: () => getJSON("/api/tasks"),
  task: (id) => getJSON(`/api/tasks/${encodeURIComponent(id)}`),
  reports: () => getJSON("/api/reports"),
  report: (id) => getJSON(`/api/reports/${encodeURIComponent(id)}`),

  // read-only surface mutations (no model quota required)
  setExpertEnabled: (id, enabled) =>
    postJSON(`/api/experts/${encodeURIComponent(id)}/enabled`, { enabled }),
  reportFollowup: (id, question) =>
    postJSON(`/api/reports/${encodeURIComponent(id)}/followup`, { question }),
};
