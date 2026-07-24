// AlphaOS backend API client (live mode); demo mode reads mock.js instead.
async function getJSON(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`GET ${url} → ${res.status}`);
  return res.json();
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${url} → ${res.status}`);
  return res.json();
}

export const api = {
  health: () => getJSON("/api/health"),
  pandadataStatus: () => getJSON("/api/pandadata/status"),
  plan: (prompt) => postJSON("/api/plan", { prompt }),
  runTask: (prompt) => postJSON("/api/tasks", { prompt }),
};
