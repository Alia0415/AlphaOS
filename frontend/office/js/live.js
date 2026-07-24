// AlphaOS Office — live data layer. Maps backend read-only contracts into the
// view models the office pages render. Factual fields (name, description,
// enabled, capabilities, tools, skills, counts, statuses) come from the API;
// only cosmetic fields (sprite / role label / specialty) are overlaid from the
// static presentation map. It never invents research facts.
import { api } from "./api.js";
import { store } from "./store.js";

export const isLive = () => store.state.mode === "live";

// Cosmetic-only presentation overlay keyed by real backend agent id. These are
// display labels and desk assignments, never analytical claims.
const PRESENTATION = {
  research: { role: "行业研究员", specialty: "行业研究 · 公司分析 · 估值建模", desk: 2 },
  quant: { role: "量化分析师", specialty: "量化建模 · 因子研究 · 统计学习", desk: 3 },
  risk: { role: "风险分析师", specialty: "风险管理 · 压力测试 · 组合风控", desk: 4 },
  portfolio: { role: "组合经理", specialty: "组合构建 · 仓位配置 · 再平衡", desk: 0 },
  macro: { role: "宏观分析师", specialty: "宏观经济 · 政策分析 · 全球大势", desk: 1 },
  report: { role: "研究报告专员", specialty: "报告撰写 · 证据整合 · 结论呈现", desk: 5 },
};

function presentationFor(id) {
  return PRESENTATION[id] || { role: "专家", specialty: "", desk: 0 };
}

// ---- mappers ---------------------------------------------------------------

export function mapExpert(info) {
  const pres = presentationFor(info.id);
  return {
    id: info.id,
    name: info.name,
    description: info.description || "",
    enabled: info.enabled !== false,
    capabilities: Array.isArray(info.capabilities) ? info.capabilities : [],
    tools: Array.isArray(info.tools) ? info.tools : [],
    skills: Array.isArray(info.skills) ? info.skills : [],
    role: pres.role,
    specialty: pres.specialty,
    desk: pres.desk,
    // office status vocabulary derived from the real enabled flag only
    status: info.enabled !== false ? "online" : "off",
    live: true,
  };
}

export function mapSkill(info) {
  return {
    id: info.id,
    name: info.name,
    description: info.description || "",
    mode: info.mode || "",
    enabled: info.enabled !== false,
    owner_agents: Array.isArray(info.owner_agents) ? info.owner_agents : [],
    capabilities: Array.isArray(info.capabilities) ? info.capabilities : [],
  };
}

export function mapTask(row) {
  return {
    id: row.id,
    prompt: row.prompt || "",
    status: row.status || "",
    created_at: row.created_at || "",
    duration_ms: row.duration_ms ?? null,
  };
}

export function mapReportSummary(row) {
  return {
    id: row.id,
    task_id: row.task_id,
    title: row.title || "(未命名报告)",
    created_at: row.created_at || "",
    completeness: row.completeness || null,
  };
}

// ---- connectivity ----------------------------------------------------------

export async function connectivity() {
  const result = { online: false, healthy: false, pandadata: null };
  try {
    const health = await api.health();
    result.online = true;
    result.healthy = health && health.status === "ok";
  } catch {
    return result;
  }
  try {
    result.pandadata = await api.pandadataStatus();
  } catch {
    result.pandadata = null;
  }
  return result;
}

// ---- fetchers (thin, always fresh; pages own their own render lifecycle) ---

export async function fetchExperts() {
  const rows = await api.experts();
  return Array.isArray(rows) ? rows.map(mapExpert) : [];
}

export async function fetchSkills() {
  const rows = await api.skills();
  return Array.isArray(rows) ? rows.map(mapSkill) : [];
}

export async function fetchOverview() {
  return api.overview();
}

export async function fetchTasks() {
  const rows = await api.tasks();
  return Array.isArray(rows) ? rows.map(mapTask) : [];
}

export async function fetchReports() {
  const rows = await api.reports();
  return Array.isArray(rows) ? rows.map(mapReportSummary) : [];
}

export async function fetchReport(id) {
  return api.report(id);
}

export async function setExpertEnabled(id, enabled) {
  return api.setExpertEnabled(id, enabled);
}

export async function submitReportFollowup(id, question) {
  return api.reportFollowup(id, question);
}
