// AlphaOS backend API client (live mode); demo mode reads mock.js instead.
async function requestJSON(url, method = "GET", body) {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let message = "请求失败，请稍后重试。";
    try {
      const payload = await res.json();
      if (typeof payload.detail === "string") message = payload.detail;
      else if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
        message = payload.detail[0].msg.replace(/^Value error, /, "");
      }
    } catch (_) {
      // Keep the plain-language fallback.
    }
    throw new Error(message);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  health: () => requestJSON("/api/health"),
  pandadataStatus: () => requestJSON("/api/pandadata/status"),
  plan: (prompt) => requestJSON("/api/plan", "POST", { prompt }),
  runTask: (prompt) => requestJSON("/api/tasks", "POST", { prompt }),
  userProfile: () => requestJSON("/api/user-profile"),
  userProfileStatus: () => requestJSON("/api/user-profile/status"),
  putUserProfile: (profile) => requestJSON("/api/user-profile", "PUT", profile),
  patchUserProfile: (patch) => requestJSON("/api/user-profile", "PATCH", patch),
  deleteUserProfile: () => requestJSON("/api/user-profile", "DELETE"),
};
