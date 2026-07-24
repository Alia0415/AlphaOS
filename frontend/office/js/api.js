// AlphaOS backend API client. Demo mode reads mock.js instead of this file.

// Same-origin by default (FastAPI serves the office at /office). A different
// backend origin can be pinned via localStorage for standalone hosting.
function apiBase() {
  try {
    return (localStorage.getItem("alphaos.apiBase") || "").replace(/\/$/, "");
  } catch {
    return "";
  }
}

async function requestJSON(
  path,
  { method = "GET", body, timeoutMs = 8000 } = {},
) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(apiBase() + path, {
      method,
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) {
      let message = "请求失败，请稍后重试。";
      try {
        const payload = await res.json();
        if (typeof payload.detail === "string") message = payload.detail;
        else if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
          message = payload.detail[0].msg.replace(/^Value error, /, "");
        }
      } catch {
        // Keep the plain-language fallback.
      }
      throw new Error(`${method} ${path} → ${message}`);
    }
    if (res.status === 204) return null;
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

const getJSON = (path, options = {}) => requestJSON(path, options);
const postJSON = (path, body, options = {}) =>
  requestJSON(path, { ...options, method: "POST", body });

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

  // task and read-only-surface actions
  plan: (prompt) =>
    requestJSON("/api/plan", { method: "POST", body: { prompt } }),
  runTask: (prompt) =>
    requestJSON("/api/tasks", { method: "POST", body: { prompt } }),
  setExpertEnabled: (id, enabled) =>
    postJSON(`/api/experts/${encodeURIComponent(id)}/enabled`, { enabled }),
  reportFollowup: (id, question) =>
    postJSON(`/api/reports/${encodeURIComponent(id)}/followup`, { question }),

  // persistent local user profile
  userProfile: () => getJSON("/api/user-profile"),
  userProfileStatus: () => getJSON("/api/user-profile/status"),
  putUserProfile: (profile) =>
    requestJSON("/api/user-profile", { method: "PUT", body: profile }),
  patchUserProfile: (patch) =>
    requestJSON("/api/user-profile", { method: "PATCH", body: patch }),
  deleteUserProfile: () =>
    requestJSON("/api/user-profile", { method: "DELETE" }),
};
