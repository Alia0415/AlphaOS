// AlphaOS Pixel Office — application shell + router.
// Renders the sidebar / topbar / statusbar chrome and the page outlet.
// Demo data comes from mock.js; every demo value stays labelled DEMO in UI.
import { store } from "./store.js";
import {
  maybeStartProfileOnboarding,
  mountProfilePage,
  openProfileOnboarding,
} from "./profile.js?v=20260724-p03";
import {
  AGENTS,
  REPORTS,
  SOON_PAGES,
  OFFICE_FEED,
  TEAM_RADAR,
  RECOMMENDED_GROUPS,
  CLARIFY_GROUPS,
  ANALYSIS_SCOPE,
  DEMO_TASK,
  WAR_SCRIPT,
  SKILL_FINAL_COUNTS,
  HISTORY_TASKS,
} from "./mock.js";
import {
  isLive,
  connectivity,
  fetchExperts,
  fetchSkills,
  fetchOverview,
  fetchTasks,
  fetchReports,
  fetchReport,
  setExpertEnabled as liveSetExpertEnabled,
  submitReportFollowup,
} from "./live.js";

// ---------------------------------------------------------------------------
// mode (demo | live) — demo is the default showcase; live binds read-only
// pages to the real backend. Task execution / planning stay demo until ARK
// credentials are configured (later phase).
// ---------------------------------------------------------------------------
let liveStatus = { online: false, healthy: false, pandadata: null };

function setMode(mode) {
  if (store.state.mode === mode) return;
  store.set({ mode });
  toast(mode === "live" ? "已切换到实时数据模式" : "已切换到演示模式");
  refreshServiceStatus().finally(() => {
    renderTopbar();
    renderStatusbar();
    // land somewhere with guaranteed content for the active mode
    navigate(mode === "live" ? "experts" : "reports", mode === "live" ? null : REPORTS[0].id);
  });
}

async function refreshServiceStatus() {
  if (!isLive()) {
    liveStatus = { online: false, healthy: false, pandadata: null };
    return liveStatus;
  }
  liveStatus = await connectivity();
  return liveStatus;
}

// Standard empty / error / loading states for live read-only pages.
function stateBox(kind, title, sub) {
  const box = el("div", "soon-wrap");
  const ico = kind === "error" ? "⚠" : kind === "empty" ? "🗂" : "⏳";
  box.appendChild(el("div", "sw-ico", ico));
  box.appendChild(el("h2", "", esc(title)));
  if (sub) box.appendChild(el("p", "", esc(sub)));
  return box;
}

// Render an async live page: show a loader, then swap in real content, or an
// error state (with the reason) if the backend is unreachable.
function renderLive(host, loader, builder) {
  host.innerHTML = "";
  host.appendChild(stateBox("loading", "正在从后端加载实时数据…"));
  loader()
    .then((data) => {
      host.innerHTML = "";
      host.appendChild(builder(data));
    })
    .catch((err) => {
      host.innerHTML = "";
      const box = stateBox(
        "error",
        "无法连接后端 API",
        "请确认后端已启动（uvicorn backend.main:app）。" + (err && err.message ? ` [${err.message}]` : ""),
      );
      const retry = el("button", "btn btn-primary", "重试");
      retry.addEventListener("click", () => renderLive(host, loader, builder));
      const back = el("button", "btn-ghost", "切回演示模式");
      back.addEventListener("click", () => setMode("demo"));
      const row = el("div", "");
      row.style.cssText = "display:flex;gap:8px;justify-content:center;margin-top:10px";
      row.append(retry, back);
      box.appendChild(row);
      host.appendChild(box);
    });
  return host;
}

// ---------------------------------------------------------------------------
// tiny DOM helpers
// ---------------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const agentById = (id) => AGENTS.find((a) => a.id === id) || null;

function el(tag, cls, html) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html != null) node.innerHTML = html;
  return node;
}

function esc(str) {
  return String(str ?? "").replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

function nowClock() {
  return new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

// Neon bracketed screen heading, e.g. 「界面 04 │ 专家中心」 with optional subtitle.
function screenTitle(num, name, sub) {
  const box = el("div", "screen-title");
  box.innerHTML = `<h1><span class="st-brk">✦ 界面 ${esc(num)}</span> <span class="st-bar">│</span> ${esc(name)}</h1>` +
    (sub ? `<p>${esc(sub)}</p>` : "");
  return box;
}

// ---------------------------------------------------------------------------
// pixel sprite avatars — drawn from /pixel/<sheet>/atlas.png (frame 0)
// ---------------------------------------------------------------------------
const SPRITE_BASE = "/pixel";
const SPRITE_MAP = {
  manager: "white-beard-businessman",
  macro: "gray-mustache-businessman",
  research: "white-hair-glasses",
  quant: "bald-round-glasses",
  risk: "balding-square-glasses",
  report: "bald-glasses",
  user: "black-hair-businessman",
};
const FRAME = 256; // native frame is 256x256, atlas is a horizontal strip
const spriteCache = new Map(); // sheet -> { img, ready }

function loadSprite(sheet) {
  if (spriteCache.has(sheet)) return spriteCache.get(sheet);
  const img = new Image();
  const entry = { img, ready: false, waiters: [] };
  img.onload = () => {
    entry.ready = true;
    entry.waiters.splice(0).forEach((cb) => cb());
  };
  img.onerror = () => {
    entry.error = true;
    entry.waiters.splice(0).forEach((cb) => cb());
  };
  img.src = `${SPRITE_BASE}/${sheet}/atlas.png`;
  spriteCache.set(sheet, entry);
  return entry;
}

// Returns a wrapper element containing a crisp pixel-art avatar canvas.
function avatar(agentOrSheet, sizePx = 40, wrapCls = "pix-ava") {
  const sheet = SPRITE_MAP[agentOrSheet] || agentOrSheet;
  const wrap = el("span", wrapCls);
  wrap.style.width = `${sizePx}px`;
  wrap.style.height = `${sizePx}px`;
  wrap.style.display = "inline-block";
  const canvas = el("canvas");
  canvas.width = FRAME;
  canvas.height = FRAME;
  // Size the canvas to fill the wrapper regardless of wrapper class, so small
  // avatars (team row / contrib cards) don't show only the sprite's top-left.
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  canvas.style.display = "block";
  canvas.style.imageRendering = "pixelated";
  wrap.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  const paint = () => {
    const entry = spriteCache.get(sheet);
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, FRAME, FRAME);
    if (entry && entry.ready) {
      ctx.drawImage(entry.img, 0, 0, FRAME, FRAME, 0, 0, FRAME, FRAME);
    } else {
      // graceful fallback: solid pixel block while the atlas loads / on error
      ctx.fillStyle = "#13263f";
      ctx.fillRect(0, 0, FRAME, FRAME);
    }
  };
  const entry = loadSprite(sheet);
  paint();
  if (!entry.ready) entry.waiters.push(paint);
  return wrap;
}

// ---------------------------------------------------------------------------
// nav definition
// ---------------------------------------------------------------------------
const NAV = [
  { route: "hall", ico: "🏛", label: "投研大厅" },
  { route: "war", ico: "🛰", label: "多 Agent 作战室" },
  { route: "tasks", ico: "🗂", label: "任务中心" },
  { route: "experts", ico: "👥", label: "专家中心" },
  { route: "reports", ico: "📑", label: "研究报告" },
  { route: "profile", ico: "🪪", label: "用户画像" },
  { sep: true },
  { route: "skills", ico: "🧩", label: "Skills" },
  { route: "data-market", ico: "🗄", label: "数据市场" },
  { route: "strategies", ico: "📦", label: "策略库" },
  { route: "monitor", ico: "📊", label: "监控看板" },
  { route: "knowledge", ico: "📚", label: "知识库" },
  { sep: true },
  { route: "help", ico: "❓", label: "帮助中心" },
];

let currentRoute = "reports";
let routeParam = null;
// teardown hook for pages that own timers / animation frames (war room, live scenes)
let activeTeardown = null;
function registerTeardown(fn) { activeTeardown = fn; }

// ---------------------------------------------------------------------------
// shell — sidebar / topbar / statusbar
// ---------------------------------------------------------------------------
function renderSidebar() {
  const side = $("#sidebar");
  side.innerHTML = "";

  const brand = el("button", "brand");
  brand.appendChild(el("span", "brand-mark", "◆"));
  brand.appendChild(el("span", "", "<strong>AlphaOS</strong><small>AI 投资研究操作系统</small>"));
  brand.addEventListener("click", () => navigate("hall"));
  side.appendChild(brand);

  const nav = el("nav", "nav");
  NAV.forEach((item) => {
    if (item.sep) {
      nav.appendChild(el("div", "nav-sep"));
      return;
    }
    const active = item.route === currentRoute;
    const btn = el("button", `nav-item${active ? " active" : ""}`);
    btn.appendChild(el("span", "nav-ico", item.ico));
    btn.appendChild(el("span", "", esc(item.label)));
    btn.addEventListener("click", () => navigate(item.route));
    nav.appendChild(btn);
  });
  side.appendChild(nav);

  side.appendChild(el("div", "sidebar-foot", `AlphaOS v0.4 · ${isLive() ? "实时数据" : "演示模式"}`));
}

function renderTopbar() {
  const bar = $("#topbar");
  bar.innerHTML = "";

  if (isLive()) {
    const ok = liveStatus.healthy;
    const status = el(
      "span",
      "pill",
      `<span class="dot ${ok ? "ok" : "warn"}"></span>后端 API：<strong style="color:var(--${ok ? "green" : "yellow"})">${ok ? "已连接" : "连接中/离线"}</strong>`,
    );
    const pd = liveStatus.pandadata || {};
    const pdReady = pd.configured || pd.ready || pd.status === "ok";
    const data = el(
      "span",
      "pill",
      `📡 PandaData：${pdReady ? '已配置 <span class="dot ok"></span>' : '未配置 <span class="dot warn"></span>'}`,
    );
    bar.append(status, data);
  } else {
    const status = el("span", "pill", '<span class="dot ok"></span>系统状态：<strong style="color:var(--green)">正常运行</strong>');
    const engine = el("span", "pill", "🧠 模型引擎：GPT-4o（DEMO）");
    const data = el("span", "pill", '📡 数据源：演示数据 <span class="dot ok"></span>');
    bar.append(status, engine, data);
  }

  bar.appendChild(el("div", "topbar-spacer"));

  // demo / live mode toggle
  const live = isLive();
  const modeBtn = el("button", "pill", `${live ? "🟢 实时数据" : "🧪 演示模式"} · 点击切换`);
  modeBtn.title = live ? "当前使用后端真实只读数据" : "当前使用本地演示数据";
  modeBtn.addEventListener("click", () => setMode(live ? "demo" : "live"));
  bar.append(modeBtn);

  const history = el("button", "pill", "🕘 历史任务");
  history.addEventListener("click", () => navigate("tasks"));
  const settings = el("button", "pill", "⚙ 设置");
  settings.addEventListener("click", () => toast("设置面板规划中（DEMO）"));
  bar.append(history, settings);

  const avaBtn = el("button", "avatar-btn");
  avaBtn.appendChild(avatar("user", 34, "pix-ava"));
  avaBtn.addEventListener("click", () => navigate("profile"));
  bar.appendChild(avaBtn);
}

function renderStatusbar() {
  const sb = $("#statusbar");
  sb.innerHTML = "";
  sb.appendChild(el("span", "sb-item", "🙂 用最强的 AI 团队，做最专业的投资研究。"));
  sb.appendChild(el("span", "spacer"));
  sb.appendChild(el("span", "sb-item sb-slogan", `${AGENTS.filter((a) => a.status !== "off").length} 位专家在线`));
  sb.appendChild(el("span", "sb-item sb-slogan", nowClock()));
}

// ---------------------------------------------------------------------------
// toast
// ---------------------------------------------------------------------------
function toast(message) {
  const root = $("#toastRoot");
  const node = el("div", "toast", esc(message));
  root.appendChild(node);
  setTimeout(() => {
    node.style.opacity = "0";
    node.style.transition = "opacity 0.3s";
    setTimeout(() => node.remove(), 320);
  }, 2200);
}

// ---------------------------------------------------------------------------
// canvas line chart (report trend)
// ---------------------------------------------------------------------------
function drawLineChart(canvas, trend) {
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 360;
  const cssH = 210;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  canvas.style.height = `${cssH}px`;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, cssW, cssH);

  const padL = 40, padR = 12, padT = 14, padB = 26;
  const plotW = cssW - padL - padR;
  const plotH = cssH - padT - padB;
  const all = trend.series.flatMap((s) => s.data);
  const maxV = Math.max(...all, 10);
  const minV = Math.min(...all, 0);
  const range = maxV - minV || 1;
  const n = trend.labels.length;
  const xAt = (i) => padL + (n <= 1 ? 0 : (plotW * i) / (n - 1));
  const yAt = (v) => padT + plotH - ((v - minV) / range) * plotH;

  // gridlines + y labels
  ctx.strokeStyle = "#16304f";
  ctx.fillStyle = "#4a6a8f";
  ctx.font = "10px system-ui, sans-serif";
  ctx.textAlign = "right";
  const steps = 4;
  for (let i = 0; i <= steps; i++) {
    const v = minV + (range * i) / steps;
    const y = yAt(v);
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(cssW - padR, y);
    ctx.stroke();
    ctx.fillText(`${Math.round(v)}%`, padL - 6, y + 3);
  }

  // x labels
  ctx.textAlign = "center";
  trend.labels.forEach((lb, i) => ctx.fillText(lb, xAt(i), cssH - 8));

  // series
  trend.series.forEach((s) => {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    s.data.forEach((v, i) => {
      const x = xAt(i), y = yAt(v);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = s.color;
    s.data.forEach((v, i) => {
      ctx.beginPath();
      ctx.arc(xAt(i), yAt(v), 3, 0, Math.PI * 2);
      ctx.fill();
    });
  });
}

// ---------------------------------------------------------------------------
// canvas radar chart (capability radar)
// ---------------------------------------------------------------------------
function drawRadar(canvas, radar, size = 220) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  canvas.style.width = `${size}px`;
  canvas.style.height = `${size}px`;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, size, size);

  const labels = radar.labels || [];
  const vals = radar.values || [];
  const n = labels.length;
  if (!n) return;
  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 - 30;
  const ang = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const maxV = 100;

  // concentric rings
  ctx.strokeStyle = "#16304f";
  ctx.lineWidth = 1;
  for (let r = 1; r <= 4; r++) {
    const rr = (R * r) / 4;
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const a = ang(i);
      const x = cx + rr * Math.cos(a);
      const y = cy + rr * Math.sin(a);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.closePath();
    ctx.stroke();
  }

  // spokes + axis labels
  ctx.fillStyle = "#7fa3c7";
  ctx.font = "10px system-ui, sans-serif";
  ctx.textAlign = "center";
  for (let i = 0; i < n; i++) {
    const a = ang(i);
    ctx.strokeStyle = "#16304f";
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + R * Math.cos(a), cy + R * Math.sin(a));
    ctx.stroke();
    const lx = cx + (R + 15) * Math.cos(a);
    const ly = cy + (R + 15) * Math.sin(a);
    ctx.fillText(labels[i], lx, ly + 3);
  }

  // value polygon
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const a = ang(i);
    const rr = (R * Math.min(vals[i] ?? 0, maxV)) / maxV;
    const x = cx + rr * Math.cos(a);
    const y = cy + rr * Math.sin(a);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.closePath();
  ctx.fillStyle = "rgba(34, 211, 238, 0.18)";
  ctx.fill();
  ctx.strokeStyle = "#22d3ee";
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = "#22d3ee";
  for (let i = 0; i < n; i++) {
    const a = ang(i);
    const rr = (R * Math.min(vals[i] ?? 0, maxV)) / maxV;
    ctx.beginPath();
    ctx.arc(cx + rr * Math.cos(a), cy + rr * Math.sin(a), 2.6, 0, Math.PI * 2);
    ctx.fill();
  }
}

// ---------------------------------------------------------------------------
// router
// ---------------------------------------------------------------------------
function navigate(route, param = null) {
  currentRoute = route;
  routeParam = param;
  renderSidebar();
  renderPage();
  $("#page").scrollTop = 0;
}

function renderPage() {
  if (activeTeardown) { try { activeTeardown(); } catch (_) {} activeTeardown = null; }
  const page = $("#page");
  page.innerHTML = "";
  const live = isLive();
  switch (currentRoute) {
    case "reports":
      if (live) page.appendChild(routeParam ? pageReportDetailLive(routeParam) : pageReportListLive());
      else if (routeParam) page.appendChild(pageReportDetail(routeParam));
      else page.appendChild(pageReportList());
      break;
    case "hall":
      page.appendChild(pageHall());
      break;
    case "clarify":
      page.appendChild(pageClarify());
      break;
    case "war":
      page.appendChild(pageWarRoom());
      break;
    case "experts":
      page.appendChild(live ? pageExpertsLive() : pageExperts());
      break;
    case "tasks":
      page.appendChild(live ? pageTasksLive() : pageTasks());
      break;
    case "skills":
      if (live) page.appendChild(pageSkillsLive());
      else page.appendChild(pageSoon(currentRoute));
      break;
    case "profile":
      mountProfilePage(page, toast);
      break;
    default:
      page.appendChild(pageSoon(currentRoute));
  }
}

// ---------------------------------------------------------------------------
// page: report list
// ---------------------------------------------------------------------------
function pageReportList() {
  const wrap = el("div");
  const panel = el("div", "panel");
  panel.appendChild(el("div", "panel-title", "研究报告 <span class='title-extra'>已完成报告一览</span>"));
  const list = el("div", "report-list");
  REPORTS.forEach((r) => {
    const item = el("button", "report-item");
    item.appendChild(el("span", "ri-ico", "📄"));
    item.appendChild(el("div", "", `
      <div style="font-weight:600">${esc(r.title)}</div>
      <div style="color:var(--text-2);font-size:12px;margin-top:3px">${esc(r.taskNo)} · ${esc(r.doneAt)} · ${esc(r.horizon)}</div>
    `));
    item.appendChild(el("div", "ri-score", `<strong>${r.score}</strong><span style="color:var(--text-2);font-size:11px">评分</span>`));
    item.addEventListener("click", () => navigate("reports", r.id));
    list.appendChild(item);
  });
  panel.appendChild(list);
  wrap.appendChild(panel);
  return wrap;
}

// ---------------------------------------------------------------------------
// page: report detail + follow-up (界面 06)
// ---------------------------------------------------------------------------
function pageReportDetail(reportId) {
  const report = REPORTS.find((r) => r.id === reportId) || REPORTS[0];
  const layout = el("div", "report-layout");
  layout.appendChild(buildReportMain(report));
  layout.appendChild(buildFollowPanel(report));
  return layout;
}

function buildReportMain(report) {
  const col = el("div");

  // toolbar: back + export/share
  const toolbar = el("div", "rpt-toolbar");
  const back = el("button", "btn-ghost", "‹ 返回报告列表");
  back.addEventListener("click", () => navigate("reports"));
  toolbar.appendChild(back);
  const actions = el("div", "rt-actions");
  ["📄 导出 PDF", "📊 导出 PPT", "🔗 分享报告"].forEach((label) => {
    const b = el("button", "btn", esc(label));
    b.addEventListener("click", () => toast(`${label.replace(/^[^ ]+ /, "")}（DEMO）`));
    actions.appendChild(b);
  });
  toolbar.appendChild(actions);
  col.appendChild(toolbar);

  // hero: title + meta + team | score
  const heroPanel = el("div", "panel");
  const hero = el("div", "rpt-hero");
  const main = el("div", "rh-main");
  main.appendChild(el("span", "rh-ico", "📑"));
  const info = el("div");
  info.appendChild(el("h1", "", esc(report.title)));
  info.appendChild(el("div", "rpt-id", `
    <span>任务 ID：${esc(report.taskNo)}</span>
    <span>完成时间：${esc(report.doneAt)}</span>
    <span>目标周期：${esc(report.horizon)}</span>
    <span class="badge done"><span class="dot"></span>已完成</span>
  `));
  const team = el("div", "rpt-team");
  team.appendChild(el("span", "", "研究团队："));
  report.team.forEach((id) => {
    const a = agentById(id);
    if (!a) return;
    const tm = el("span", "tm");
    const ava = avatar(id, 30, "tm-ava");
    tm.appendChild(ava);
    tm.appendChild(el("span", "", esc(a.name)));
    team.appendChild(tm);
  });
  info.appendChild(team);
  main.appendChild(info);
  hero.appendChild(main);

  const dims = report.scoreDims || {};
  const score = el("div", "rpt-score", `
    <div class="rs-label">报告评分 <span>⌄</span></div>
    <div class="rs-big">${report.score}<small> / 100</small></div>
    <div class="rs-dims">
      ${Object.entries(dims).map(([k, v]) => `<span>${esc(k)} <b>${v}</b></span>`).join("")}
    </div>
  `);
  hero.appendChild(score);
  heroPanel.appendChild(hero);
  col.appendChild(heroPanel);

  // summary + charts row
  const row = el("div", "report-charts");
  row.style.marginTop = "14px";

  const summaryPanel = el("div", "panel rpt-summary");
  summaryPanel.appendChild(el("div", "panel-title", "报告摘要"));
  summaryPanel.appendChild(el("p", "", esc(report.summary)));
  const tags = el("div", "rpt-summary-tags");
  (report.tags || []).forEach((t) => tags.appendChild(el("span", "chip", esc(t))));
  summaryPanel.appendChild(tags);
  row.appendChild(summaryPanel);

  const chartPanel = el("div", "panel");
  chartPanel.appendChild(el("div", "panel-title", `核心观点与关键图表 <span class='title-extra'>查看完整报告 ›</span>`));
  // trend line chart
  chartPanel.appendChild(el("div", "", `<div style="color:var(--text-2);font-size:12px;margin-bottom:4px">${esc(report.trend.title)}</div>`));
  const chartBox = el("div", "chart-box");
  const canvas = el("canvas");
  chartBox.appendChild(canvas);
  const legend = el("div", "chart-legend");
  report.trend.series.forEach((s) => {
    legend.appendChild(el("span", "", `<i style="background:${s.color}"></i>${esc(s.name)}`));
  });
  chartBox.appendChild(legend);
  chartPanel.appendChild(chartBox);
  // track bars
  chartPanel.appendChild(el("div", "", `<div style="color:var(--text-2);font-size:12px;margin:14px 0 8px">细分赛道投资机会评分</div>`));
  const bars = el("div", "track-bars");
  const maxTrack = Math.max(...report.tracks.map((t) => t.v), 100);
  report.tracks.forEach((t) => {
    const color = t.v >= 80 ? "var(--green)" : t.v >= 70 ? "var(--cyan)" : "var(--blue)";
    const bar = el("div", "track-bar", `
      <span>${esc(t.name)}</span>
      <span class="tb-track"><i style="width:${(t.v / maxTrack) * 100}%;background:${color}"></i></span>
      <span class="tb-val" style="color:${color}">${t.v}</span>
    `);
    bars.appendChild(bar);
  });
  chartPanel.appendChild(bars);
  row.appendChild(chartPanel);
  col.appendChild(row);
  // draw chart after in DOM
  requestAnimationFrame(() => drawLineChart(canvas, report.trend));

  // key conclusions (kv cards)
  const kvPanel = el("div", "panel");
  kvPanel.style.marginTop = "14px";
  kvPanel.appendChild(el("div", "panel-title", "关键结论速览"));
  const kvCards = el("div", "kv-cards");
  (report.kv || []).forEach((k) => {
    const card = el("div", "kv-card", `
      <div class="kvc-label">${esc(k.label)}</div>
      <div class="kvc-val ${k.color === "green" ? "" : esc(k.color)}">${esc(k.value)}</div>
      <div style="color:var(--text-3);font-size:11px">${esc(k.sub)}</div>
    `);
    kvCards.appendChild(card);
  });
  kvPanel.appendChild(kvCards);
  col.appendChild(kvPanel);

  // team contribution review (contrib grid)
  const contribPanel = el("div", "panel");
  contribPanel.style.marginTop = "14px";
  contribPanel.appendChild(el("div", "panel-title", "团队贡献回顾"));
  const grid = el("div", "contrib-grid");
  report.team.forEach((id) => {
    const a = agentById(id);
    if (!a) return;
    const items = (report.contributions && report.contributions[id]) || a.contributions || [];
    const card = el("div", "contrib-card");
    card.appendChild(avatar(id, 40, "cc-ava"));
    card.appendChild(el("strong", "", esc(a.name)));
    card.appendChild(el("div", "", `<span style="color:var(--text-2)">${esc(a.duty)}</span>`));
    card.appendChild(el("ul", "", items.map((c) => `<li>· ${esc(c)}</li>`).join("")));
    grid.appendChild(card);
  });
  contribPanel.appendChild(grid);
  col.appendChild(contribPanel);

  // footer note + action bar
  col.appendChild(el("div", "rpt-note", "报告已完成，您可以继续追问或发起新的研究探索。"));
  const bar = el("div", "rpt-actions-bar");
  const acts = [
    { label: "📈 补充宏观分析", primary: true },
    { label: "🔄 切换研究周期", primary: false },
    { label: "🆚 对比分析", primary: false },
    { label: "⋯ 更多操作", primary: false },
  ];
  acts.forEach((a) => {
    const chip = el("button", `chip${a.primary ? " primary" : ""}`, esc(a.label));
    chip.addEventListener("click", () => toast(`${a.label.replace(/^[^ ]+ /, "")}（DEMO）`));
    bar.appendChild(chip);
  });
  col.appendChild(bar);

  return col;
}

// ---------------------------------------------------------------------------
// follow-up conversation panel (right column)
// ---------------------------------------------------------------------------
function buildFollowPanel(report) {
  const panel = el("div", "panel follow-panel");

  // header
  const head = el("div", "follow-head");
  head.appendChild(avatar("manager", 46, "fh-ava"));
  const who = el("div", "fh-who");
  who.appendChild(el("strong", "", "与 Manager 继续对话"));
  who.appendChild(el("p", "", "我是您的研究管理员，报告已完成，您可以继续深入追问，或补充研究维度。"));
  who.appendChild(el("span", "badge online", '<span class="dot"></span>在线'));
  head.appendChild(who);
  panel.appendChild(head);

  // quick asks
  panel.appendChild(el("div", "follow-sec-title", "快速追问建议"));
  const chips = el("div", "quick-chips");
  (report.quickAsks || []).forEach((q) => {
    const chip = el("button", "qchip", esc(q));
    chip.addEventListener("click", () => submitFollowup(report, q));
    chips.appendChild(chip);
  });
  panel.appendChild(chips);

  // conversation log
  panel.appendChild(el("div", "follow-sec-title", "对话记录"));
  const scroll = el("div", "follow-scroll");
  scroll.id = "followScroll";
  panel.appendChild(scroll);

  // seed with system message + persisted followups
  const saved = store.state.followups[report.id] || [];
  const seed = [{ role: "sys", text: `报告《${report.title}》已生成`, time: nowClock() }, ...saved];
  seed.forEach((m) => scroll.appendChild(renderMessage(m)));

  panel.appendChild(el("div", "follow-viewall", '<button class="btn-ghost">查看完整对话记录 ›</button>'));

  // input bar
  const inputBar = el("div", "chat-inputbar");
  const input = el("input");
  input.type = "text";
  input.placeholder = "请输入您的问题，继续深入研究…";
  const send = el("button", "btn btn-primary", "➤");
  const fire = () => {
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    submitFollowup(report, q);
  };
  send.addEventListener("click", fire);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") fire();
  });
  inputBar.append(input, send);
  panel.appendChild(inputBar);

  requestAnimationFrame(() => { scroll.scrollTop = scroll.scrollHeight; });
  return panel;
}

function renderMessage(m) {
  if (m.role === "sys") {
    return el("div", "msg", `
      <div class="m-avatar" style="display:grid;place-items:center;color:var(--green)">✓</div>
      <div class="m-body">
        <div class="m-meta"><span>系统</span><span>${esc(m.time || "")}</span></div>
        <div class="m-bubble" style="color:var(--text-2)">${esc(m.text)}</div>
      </div>
    `);
  }
  const me = m.role === "me";
  const node = el("div", `msg${me ? " me" : ""}`);
  const ava = el("div", "m-avatar");
  ava.appendChild(avatar(me ? "user" : "manager", 38));
  const body = el("div", "m-body");
  body.appendChild(el("div", "m-meta", `<span>${me ? "你" : "Manager"}</span><span>${esc(m.time || "")}</span>`));
  body.appendChild(el("div", "m-bubble", esc(m.text)));
  node.append(ava, body);
  return node;
}

function submitFollowup(report, question) {
  const scroll = $("#followScroll");
  if (!scroll) return;
  const userMsg = { role: "me", text: question, time: nowClock() };
  scroll.appendChild(renderMessage(userMsg));
  store.addFollowup(report.id, userMsg);
  scroll.scrollTop = scroll.scrollHeight;

  // typing indicator
  const typing = el("div", "msg");
  const ava = el("div", "m-avatar");
  ava.appendChild(avatar("manager", 38));
  typing.appendChild(ava);
  typing.appendChild(el("div", "m-body", '<div class="m-bubble"><span class="typing-dots"><i></i><i></i><i></i></span></div>'));
  scroll.appendChild(typing);
  scroll.scrollTop = scroll.scrollHeight;

  setTimeout(() => {
    typing.remove();
    const reply = matchReply(report, question);
    const botMsg = { role: "bot", text: reply, time: nowClock() };
    scroll.appendChild(renderMessage(botMsg));
    store.addFollowup(report.id, botMsg);
    scroll.scrollTop = scroll.scrollHeight;
  }, 900);
}

function matchReply(report, question) {
  const rules = report.followReplies || [];
  for (const rule of rules) {
    if (!rule.match || rule.match.length === 0) continue;
    if (rule.match.some((kw) => question.includes(kw))) return rule.reply;
  }
  const fallback = rules.find((r) => !r.match || r.match.length === 0);
  return fallback ? fallback.reply : "收到，我会基于报告的证据链继续分析。（DEMO 应答）";
}

// ---------------------------------------------------------------------------
// canvas office scene — top-down pixel office with agents at their desks
// (static LIVE preview for the hall; the war room animates its own stage)
// ---------------------------------------------------------------------------
function drawOfficeScene(canvas, agents) {
  const dpr = window.devicePixelRatio || 1;
  const W = 720, H = 300;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = "100%";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const seats = agents.slice(0, 6);

  const paint = () => {
    ctx.imageSmoothingEnabled = false;
    // floor
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, "#0c1830");
    g.addColorStop(1, "#0a1322");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
    // floor grid
    ctx.strokeStyle = "#12233c";
    ctx.lineWidth = 1;
    for (let x = 0; x <= W; x += 48) { ctx.beginPath(); ctx.moveTo(x, 58); ctx.lineTo(x, H); ctx.stroke(); }
    for (let y = 58; y <= H; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
    // back wall
    ctx.fillStyle = "#0e1e34";
    ctx.fillRect(0, 0, W, 58);
    ctx.strokeStyle = "#16304f";
    ctx.beginPath(); ctx.moveTo(0, 58); ctx.lineTo(W, 58); ctx.stroke();
    ctx.fillStyle = "#22d3ee";
    ctx.font = "bold 12px system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("◆ AlphaOS 投研办公室", 14, 36);

    const cols = 3;
    const gapX = W / cols;
    seats.forEach((a, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const cx = gapX * col + gapX / 2;
      const cy = 116 + row * 104;
      // desk
      ctx.fillStyle = "#14304f";
      ctx.beginPath(); ctx.roundRect(cx - 54, cy + 26, 108, 24, 6); ctx.fill();
      ctx.fillStyle = "#0b1526";
      ctx.beginPath(); ctx.roundRect(cx - 20, cy + 20, 40, 13, 3); ctx.fill();
      ctx.fillStyle = a.status === "off" ? "#3a4a5f" : "#1e6b52";
      ctx.fillRect(cx - 17, cy + 23, 34, 7);
      // sprite (frame 0)
      const sheet = SPRITE_MAP[a.id] || a.id;
      const entry = spriteCache.get(sheet);
      const size = 60;
      if (entry && entry.ready) {
        ctx.drawImage(entry.img, 0, 0, FRAME, FRAME, cx - size / 2, cy - size + 22, size, size);
      } else {
        ctx.fillStyle = "#13263f";
        ctx.fillRect(cx - size / 2, cy - size + 22, size, size);
      }
      // status dot
      const dot = { online: "#34d399", working: "#60a5fa", busy: "#f59e0b", running: "#60a5fa", off: "#5a6b80" }[a.status] || "#5a6b80";
      ctx.fillStyle = dot;
      ctx.beginPath(); ctx.arc(cx + 22, cy - 34, 4, 0, Math.PI * 2); ctx.fill();
      // name tag
      ctx.fillStyle = "rgba(10,22,40,0.82)";
      ctx.beginPath(); ctx.roundRect(cx - 32, cy + 54, 64, 15, 4); ctx.fill();
      ctx.fillStyle = "#9fc0e0";
      ctx.font = "10px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(a.name, cx, cy + 65);
    });
  };

  seats.forEach((a) => {
    const e = loadSprite(SPRITE_MAP[a.id] || a.id);
    if (!e.ready) e.waiters.push(paint);
  });
  paint();
}

// ---------------------------------------------------------------------------
// page: hall (投研大厅 · 界面 01)
// ---------------------------------------------------------------------------
let hallRecIdx = 0;

function pageHall() {
  const wrap = el("div");
  wrap.appendChild(screenTitle("01", "投研大厅", "用最强的 AI 团队，做最专业的投资研究。"));

  // ---- hero grid: ask box + LIVE office preview ----
  const grid = el("div", "hall-grid");

  const askPanel = el("div", "panel");
  askPanel.appendChild(el("div", "panel-title", "今天想研究什么？ <span class='title-extra'>描述你的研究意向，Manager 会拆解并编排团队</span>"));
  const askBox = el("div", "ask-box");
  const ta = el("textarea");
  ta.placeholder = "例如：分析特斯拉（TSLA）的基本面、自动驾驶与机器人业务，并给出估值与风险判断…";
  askBox.appendChild(ta);
  const foot = el("div", "ask-foot");
  const count = el("span", "ask-count", "0 / 500");
  ta.addEventListener("input", () => { count.textContent = `${ta.value.length} / 500`; });
  const startBtn = el("button", "btn btn-primary", "🚀 开始研究");
  startBtn.addEventListener("click", () => {
    toast("Manager 正在澄清任务需求…（DEMO）");
    navigate("clarify");
  });
  foot.append(count, startBtn);
  askBox.appendChild(foot);
  askPanel.appendChild(askBox);

  // recommended tasks
  const rec = el("div", "rec-row");
  const recLabel = el("span", "rec-label", "💡 推荐任务");
  rec.appendChild(recLabel);
  RECOMMENDED_GROUPS[hallRecIdx % RECOMMENDED_GROUPS.length].forEach((t) => {
    const chip = el("button", "chip", esc(t));
    chip.addEventListener("click", () => { ta.value = t.replace(/^\S+\s/, ""); count.textContent = `${ta.value.length} / 500`; ta.focus(); });
    rec.appendChild(chip);
  });
  const shuffle = el("button", "chip", "🔀 换一批");
  shuffle.addEventListener("click", () => { hallRecIdx++; renderPage(); });
  rec.appendChild(shuffle);
  askPanel.appendChild(rec);
  grid.appendChild(askPanel);

  // LIVE office preview
  const officePanel = el("div", "panel");
  officePanel.appendChild(el("div", "panel-title", "投研办公室 <span class='title-extra'>点击进入作战室</span>"));
  const preview = el("div", "office-preview");
  const canvas = el("canvas");
  preview.appendChild(canvas);
  preview.appendChild(el("div", "live-tag", "<i></i>LIVE"));
  preview.addEventListener("click", () => navigate("war"));
  officePanel.appendChild(preview);
  const ofeed = el("div", "office-feed");
  ofeed.innerHTML = `<span class="dot"></span><span>${esc(OFFICE_FEED[0])}</span>`;
  officePanel.appendChild(ofeed);
  grid.appendChild(officePanel);
  wrap.appendChild(grid);
  requestAnimationFrame(() => drawOfficeScene(canvas, AGENTS));

  // rotate the office feed line
  let feedIdx = 0;
  const feedTimer = setInterval(() => {
    feedIdx = (feedIdx + 1) % OFFICE_FEED.length;
    const span = ofeed.querySelector("span:last-child");
    if (span) span.textContent = OFFICE_FEED[feedIdx];
  }, 2600);
  registerTeardown(() => clearInterval(feedTimer));

  // ---- online experts ----
  const expertPanel = el("div", "panel");
  expertPanel.style.marginTop = "18px";
  expertPanel.appendChild(el("div", "panel-title", `在线专家 <span class='title-extra'>${AGENTS.filter((a) => a.status !== "off").length} 位专家在线协作</span>`));
  const strip = el("div", "expert-strip");
  AGENTS.forEach((a) => {
    const card = el("button", "expert-mini");
    card.appendChild(avatar(a.id, 56, "em-ava"));
    card.appendChild(el("strong", "", esc(a.name)));
    card.appendChild(el("div", "em-role", esc(a.role)));
    card.appendChild(el("span", `badge ${a.status}`, `<span class="dot"></span>${statusText(a.status)}`));
    card.appendChild(el("div", "em-spec", esc(a.specialty)));
    card.addEventListener("click", () => navigate("experts"));
    strip.appendChild(card);
  });
  expertPanel.appendChild(strip);
  wrap.appendChild(expertPanel);

  // ---- overview stats + team radar ----
  const bottom = el("div");
  bottom.style.cssText = "display:grid;grid-template-columns:1.2fr 1fr;gap:18px;margin-top:18px";

  const statPanel = el("div", "panel");
  statPanel.appendChild(el("div", "panel-title", "系统概览"));
  const cards = el("div", "stat-cards");
  const online = AGENTS.filter((a) => a.status !== "off").length;
  const skillTotal = AGENTS.reduce((s, a) => s + (a.skillCount || 0), 0);
  [
    { num: "3", label: "今日研究任务", sub: "含 1 个进行中", green: true },
    { num: `${online}/${AGENTS.length}`, label: "在线专家", sub: "多线协作中" },
    { num: `${skillTotal}`, label: "已装 Skill", sub: "覆盖全研究链路" },
    { num: `${REPORTS.length}`, label: "已完成报告", sub: "可追问 / 导出" },
    { num: "98%", label: "证据校验通过率", sub: "结论均可溯源", green: true },
    { num: "5", label: "本月新增策略", sub: "策略库沉淀" },
  ].forEach((s) => {
    const c = el("button", "stat-card");
    c.innerHTML = `<div class="sc-num${s.green ? " green" : ""}">${esc(s.num)}</div>
      <div class="sc-label">${esc(s.label)}</div><div class="sc-sub">${esc(s.sub)}</div>`;
    c.addEventListener("click", () => navigate("tasks"));
    cards.appendChild(c);
  });
  statPanel.appendChild(cards);
  bottom.appendChild(statPanel);

  const radarPanel = el("div", "panel");
  radarPanel.appendChild(el("div", "panel-title", "团队能力雷达"));
  const rwrap = el("div");
  rwrap.style.cssText = "display:grid;place-items:center;padding:8px 0";
  const rcanvas = el("canvas");
  rwrap.appendChild(rcanvas);
  radarPanel.appendChild(rwrap);
  bottom.appendChild(radarPanel);
  wrap.appendChild(bottom);
  requestAnimationFrame(() => drawRadar(rcanvas, TEAM_RADAR, 260));

  return wrap;
}

function statusText(s) {
  return { online: "在线", working: "工作中", busy: "忙碌", running: "运行中", off: "离线" }[s] || s;
}

// ---------------------------------------------------------------------------
// page: clarify (界面 02 — Manager 任务澄清)
// ---------------------------------------------------------------------------
const clarifySel = {};
CLARIFY_GROUPS.forEach((g) => { clarifySel[g.key] = new Set(g.def || []); });
const CLARIFY_TASK = { object: "特斯拉（TSLA）", type: "公司深度研究", experts: 5 };

function pageClarify() {
  const layout = el("div", "chat-layout");

  // ---- left: Manager conversation ----
  const left = el("div", "panel chat-col");
  left.appendChild(screenTitle("02", "任务澄清", "Manager 正在与你确认关键研究口径，以便精准编排专家团队。"));

  const head = el("div", "chat-head");
  head.appendChild(avatar("manager", 46, "pix-ava"));
  const who = el("div", "who");
  who.innerHTML = "<strong>Manager · 研究管理员</strong><small>正在澄清任务需求…</small>";
  head.appendChild(who);
  left.appendChild(head);

  const scroll = el("div", "chat-scroll");
  scroll.appendChild(clarifyMsg("bot", `收到你的研究意向：<b>${esc(CLARIFY_TASK.object)}</b>。在正式开工前，我想先确认几个关键口径，团队会据此精准编排。`));

  // clarify option grid, rendered inside a wide Manager bubble
  const gridMsg = el("div", "msg");
  const gAva = el("div", "m-avatar");
  gAva.appendChild(avatar("manager", 38));
  const gBody = el("div", "m-body");
  gBody.style.maxWidth = "none";
  gBody.appendChild(el("div", "m-meta", "<span>Manager</span><span>关键澄清项</span>"));
  const gridWrap = el("div", "m-bubble");
  gridWrap.style.width = "100%";
  const grid = el("div", "clarify-grid");
  gridWrap.appendChild(grid);
  gBody.appendChild(gridWrap);
  gridMsg.append(gAva, gBody);
  scroll.appendChild(gridMsg);
  renderClarifyGrid(grid);

  scroll.appendChild(clarifyMsg("bot", "确认无误后点击右侧「确认并启动研究」，我会立刻把任务拆解给团队并进入作战室。"));
  left.appendChild(scroll);

  const inputBar = el("div", "chat-inputbar");
  const input = el("input");
  input.type = "text";
  input.placeholder = "补充说明（可选）：例如特别关注的时间段或指标…";
  const send = el("button", "btn btn-primary", "➤");
  const fire = () => {
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    scroll.appendChild(clarifyMsg("me", q));
    scroll.scrollTop = scroll.scrollHeight;
    setTimeout(() => {
      scroll.appendChild(clarifyMsg("bot", "已记录你的补充说明，会同步到研究口径中。"));
      scroll.scrollTop = scroll.scrollHeight;
    }, 700);
  };
  send.addEventListener("click", fire);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") fire(); });
  inputBar.append(input, send);
  left.appendChild(inputBar);

  // ---- right: live task summary ----
  const right = el("div", "panel chat-col");
  right.id = "clarifySummary";
  layout.append(left, right);
  renderClarifySummary(right);
  return layout;
}

function clarifyMsg(role, html) {
  const me = role === "me";
  const node = el("div", `msg${me ? " me" : ""}`);
  const ava = el("div", "m-avatar");
  ava.appendChild(avatar(me ? "user" : "manager", 38));
  const body = el("div", "m-body");
  body.appendChild(el("div", "m-meta", `<span>${me ? "你" : "Manager"}</span><span>${nowClock()}</span>`));
  body.appendChild(el("div", "m-bubble", html));
  node.append(ava, body);
  return node;
}

function renderClarifyGrid(grid) {
  grid.innerHTML = "";
  CLARIFY_GROUPS.forEach((g) => {
    const card = el("div", "opt-card");
    card.appendChild(el("h5", "", `${esc(g.title)} <small>${g.multi ? "可多选" : "单选"}</small>`));
    const list = el("div", "opt-list");
    g.items.forEach((label, i) => {
      const sel = clarifySel[g.key].has(i);
      const item = el("button", `opt-item${sel ? " sel" : ""}`);
      item.innerHTML = `<span>${esc(label)}</span>${sel ? '<span class="tick">✓</span>' : ""}`;
      item.addEventListener("click", () => {
        toggleClarify(g, i);
        renderClarifyGrid(grid);
        renderClarifySummary($("#clarifySummary"));
      });
      list.appendChild(item);
    });
    card.appendChild(list);
    grid.appendChild(card);
  });
}

function toggleClarify(g, i) {
  const set = clarifySel[g.key];
  if (!g.multi) { set.clear(); set.add(i); return; }
  const allIdx = g.allItem ? g.items.indexOf(g.allItem) : -1;
  if (i === allIdx) { set.clear(); set.add(i); return; }
  if (set.has(i)) set.delete(i); else set.add(i);
  if (allIdx >= 0) set.delete(allIdx);
  if (set.size === 0 && allIdx >= 0) set.add(allIdx);
}

function clarifyValue(key) {
  const g = CLARIFY_GROUPS.find((x) => x.key === key);
  return [...clarifySel[key]].sort((a, b) => a - b).map((i) => g.items[i]).join("、") || "—";
}

function renderClarifySummary(panel) {
  if (!panel) return;
  panel.innerHTML = "";
  panel.appendChild(el("div", "panel-title", "任务摘要"));

  const kv = el("div", "summary-kv");
  [
    ["研究对象", CLARIFY_TASK.object],
    ["任务类型", CLARIFY_TASK.type],
    ["投资周期", clarifyValue("period")],
    ["风险偏好", clarifyValue("risk")],
    ["研究重点", clarifyValue("focus")],
  ].forEach(([k, v]) => {
    kv.appendChild(el("div", "", `<div class="k">${esc(k)}</div><div>${esc(v)}</div>`));
  });
  panel.appendChild(kv);

  panel.appendChild(el("div", "follow-sec-title", "分析范围"));
  const check = el("div", "check-list");
  ANALYSIS_SCOPE.forEach((s) => {
    check.appendChild(el("div", "ck on", `<i>✓</i><span>${esc(s)}</span>`));
  });
  panel.appendChild(check);

  panel.appendChild(el("div", "follow-sec-title", "预计投入"));
  const yc = el("div", "yield-cards");
  yc.innerHTML = `
    <div class="yc"><strong>~4<small>min</small></strong><span>预计耗时</span></div>
    <div class="yc"><strong>${CLARIFY_TASK.experts}</strong><span>参与专家</span></div>
    <div class="yc"><strong>5</strong><span>涉及 Skill</span></div>`;
  panel.appendChild(yc);

  const go = el("button", "btn btn-primary", "🚀 确认并启动研究");
  go.style.cssText = "width:100%;margin-top:16px";
  go.addEventListener("click", () => {
    toast("任务已启动，进入作战室（DEMO）");
    navigate("war");
  });
  panel.appendChild(go);

  const edit = el("button", "btn-ghost", "‹ 返回大厅重新描述");
  edit.style.cssText = "width:100%;margin-top:8px";
  edit.addEventListener("click", () => navigate("hall"));
  panel.appendChild(edit);
}

// ---------------------------------------------------------------------------
// page: war room (界面 03) — autonomous sprite office + script-driven execution
// ---------------------------------------------------------------------------
const WAR_W = 760, WAR_H = 340;
const WALK_CYCLE = [4, 5, 6, 5]; // side-view walk frames present in every sheet
const WAR_HOMES = {
  manager: { x: 380, y: 130 },
  macro: { x: 150, y: 190 },
  research: { x: 390, y: 205 },
  quant: { x: 610, y: 190 },
  risk: { x: 240, y: 300 },
  report: { x: 560, y: 300 },
};
const DAG_POS = {
  manager: [50, 12], macro: [20, 40], research: [50, 40],
  quant: [80, 40], risk: [34, 73], report: [67, 73],
};
const DAG_EDGES = [
  ["manager", "macro"], ["manager", "research"], ["manager", "quant"],
  ["macro", "risk"], ["research", "risk"], ["quant", "risk"], ["risk", "report"],
];
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function pageWarRoom() {
  const wrap = el("div");

  // ---- head ----
  const head = el("div", "war-head");
  head.appendChild(el("h1", "", "🛰 多 Agent 作战室"));
  head.appendChild(el("span", "sub", "专家自主协作 · 任务执行实时可视化"));
  const task = el("div", "war-task");
  task.appendChild(el("span", "wt-name", esc(DEMO_TASK.title)));
  const badge = el("span", "badge running", '<span class="dot"></span>执行中');
  task.appendChild(badge);
  head.appendChild(task);
  wrap.appendChild(head);

  const grid = el("div", "war-grid");

  // ================= LEFT: task-graph DAG =================
  const leftCol = el("div", "panel");
  leftCol.appendChild(el("div", "panel-title", "任务执行流"));
  const dag = el("div", "dag-wrap");
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.setAttribute("preserveAspectRatio", "none");
  const edgeEls = {};
  DAG_EDGES.forEach(([a, b]) => {
    const [x1, y1] = DAG_POS[a], [x2, y2] = DAG_POS[b];
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", x1); line.setAttribute("y1", y1);
    line.setAttribute("x2", x2); line.setAttribute("y2", y2);
    line.setAttribute("stroke", "#1d3a5c");
    line.setAttribute("stroke-width", "0.5");
    svg.appendChild(line);
    edgeEls[`${a}-${b}`] = line;
  });
  dag.appendChild(svg);
  const dagNodes = {};
  Object.entries(DAG_POS).forEach(([id, [x, y]]) => {
    const a = agentById(id);
    const node = el("button", "dag-node st-idle");
    node.style.left = `${x}%`;
    node.style.top = `${y}%`;
    node.appendChild(avatar(id, 34, "dn-ava"));
    node.appendChild(el("strong", "", esc(a.name)));
    node.appendChild(el("small", "", esc(a.role)));
    node.appendChild(el("span", "badge off dn-badge", '<span class="dot"></span>待命'));
    node.addEventListener("click", () => navigate("experts"));
    dagNodes[id] = node;
    dag.appendChild(node);
  });
  leftCol.appendChild(dag);
  grid.appendChild(leftCol);

  // ================= CENTER: live stage + progress + timeline =================
  const centerCol = el("div");
  const stagePanel = el("div", "panel");
  stagePanel.appendChild(el("div", "panel-title", "作战室实时画面 <span class='title-extra'>专家在自主走动与协作</span>"));
  const stage = el("div", "office-stage");
  const canvas = el("canvas");
  stage.appendChild(canvas);
  const bubbleLayer = el("div", "bubble-layer");
  stage.appendChild(bubbleLayer);
  stagePanel.appendChild(stage);

  // overall + per-agent progress
  const prog = el("div", "progress-row");
  const pmain = el("div");
  pmain.innerHTML = '<div style="font-size:12px;color:var(--text-2);margin-bottom:6px">整体进度 <b class="p-pct" style="color:var(--cyan)">0%</b></div><div class="pbar"><i style="width:0%"></i></div>';
  prog.appendChild(pmain);
  const pstats = {
    done: el("div", "pstat", '<strong>0</strong><span>已完成</span>'),
    working: el("div", "pstat", '<strong>0</strong><span>进行中</span>'),
    logs: el("div", "pstat", '<strong>0</strong><span>日志</span>'),
    elapsed: el("div", "pstat", '<strong>0s</strong><span>用时</span>'),
  };
  prog.append(pstats.done, pstats.working, pstats.logs, pstats.elapsed);
  stagePanel.appendChild(prog);
  centerCol.appendChild(stagePanel);

  // timeline
  const tlPanel = el("div", "panel");
  tlPanel.style.marginTop = "14px";
  tlPanel.appendChild(el("div", "panel-title", "活动时间轴"));
  const tl = el("div", "timeline");
  const tlEvents = WAR_SCRIPT.filter((e) => e.type === "timeline");
  const tlTrack = el("div", "tl-track");
  const tlFill = el("div", "tl-fill");
  tlFill.style.width = "0%";
  tlTrack.appendChild(tlFill);
  const tlNodeEls = [];
  tlEvents.forEach((e) => {
    const dot = el("button", "tl-node");
    dot.style.left = `${(e.t / 60) * 100}%`;
    tlTrack.appendChild(dot);
    tlNodeEls.push(dot);
  });
  tl.appendChild(tlTrack);
  const tlLabels = el("div", "tl-labels");
  tlEvents.forEach((e) => {
    tlLabels.appendChild(el("span", "tl-label", `${esc(e.label)}<span class="t">${esc(e.clock)}</span>`));
  });
  tl.appendChild(tlLabels);
  const controls = el("div", "tl-controls");
  const playBtn = el("button", "btn", "⏸ 暂停");
  const speedSel = el("select");
  [["1", "1x"], ["2", "2x"], ["4", "4x"]].forEach(([v, t]) => {
    const o = el("option", "", t); o.value = v; speedSel.appendChild(o);
  });
  const replayBtn = el("button", "btn", "↻ 重播");
  controls.append(el("span", "", '<span style="color:var(--text-2);font-size:12px">播放速度</span>'), speedSel, playBtn, replayBtn);
  tl.appendChild(controls);
  tlPanel.appendChild(tl);
  centerCol.appendChild(tlPanel);
  grid.appendChild(centerCol);

  // ================= RIGHT: summary + skills + logs =================
  const rightCol = el("div");
  const sumPanel = el("div", "panel");
  sumPanel.appendChild(el("div", "panel-title", "任务摘要"));
  const kv = el("div", "kv-list");
  [
    ["研究对象", DEMO_TASK.short], ["任务类型", DEMO_TASK.type],
    ["启动时间", DEMO_TASK.started], ["优先级", DEMO_TASK.priority],
    ["预计完成", DEMO_TASK.eta],
  ].forEach(([k, v]) => {
    kv.appendChild(el("div", "kv", `<span class="k">${esc(k)}</span><span>${esc(v)}</span>`));
  });
  sumPanel.appendChild(kv);
  rightCol.appendChild(sumPanel);

  const skillPanel = el("div", "panel");
  skillPanel.style.marginTop = "14px";
  skillPanel.appendChild(el("div", "panel-title", "Skill 调用"));
  const skillCounts = {};
  const skillRows = {};
  Object.keys(SKILL_FINAL_COUNTS).forEach((name) => {
    skillCounts[name] = 0;
    const row = el("div", "skill-row");
    row.innerHTML = `<span>🧩</span><span>${esc(name)}</span><span class="sk-count">0</span>`;
    skillRows[name] = row;
    skillPanel.appendChild(row);
  });
  rightCol.appendChild(skillPanel);

  const logPanel = el("div", "panel");
  logPanel.style.marginTop = "14px";
  logPanel.appendChild(el("div", "panel-title", "实时日志"));
  const logEl = el("div", "log-list");
  logPanel.appendChild(logEl);
  rightCol.appendChild(logPanel);
  grid.appendChild(rightCol);

  wrap.appendChild(grid);

  // ---------------- engine state ----------------
  const agents = Object.keys(WAR_HOMES).map((id) => {
    const home = WAR_HOMES[id];
    const a = agentById(id);
    loadSprite(SPRITE_MAP[id] || id);
    return {
      id, name: a ? a.name : id, sheet: SPRITE_MAP[id] || id,
      x: home.x, y: home.y, tx: home.x, ty: home.y, home,
      facing: 1, walking: false, pauseT: Math.random() * 1.5,
      frameT: 0, frameIdx: 0, status: "idle", say: null, bubbleEl: null,
    };
  });
  const agentById2 = (id) => agents.find((a) => a.id === id);

  const state = { clock: 0, speed: 1, playing: true, ptr: 0, logs: 0, lastPct: -1 };

  function pickWander(ag) {
    ag.tx = clamp(ag.home.x + (Math.random() * 2 - 1) * 95, 55, WAR_W - 55);
    ag.ty = clamp(ag.home.y + (Math.random() * 2 - 1) * 42, 115, WAR_H - 22);
    ag.pauseT = 0.6 + Math.random() * 1.9;
  }
  function gather(ids) {
    const cx = 380, cy = 225, n = ids.length;
    ids.forEach((id, i) => {
      const ag = agentById2(id);
      if (!ag) return;
      const ang = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(n, 1);
      ag.tx = clamp(cx + Math.cos(ang) * 78, 55, WAR_W - 55);
      ag.ty = clamp(cy + Math.sin(ang) * 46, 115, WAR_H - 22);
      ag.pauseT = 3;
    });
  }

  function appendLog(who, text, color, clockStr) {
    const line = el("div", "log-line");
    line.innerHTML = `<span class="lt">${esc(clockStr)}</span><span class="la" style="color:${color || "var(--text-2)"}">${esc(who)}</span><span>${esc(text)}</span>`;
    logEl.appendChild(line);
    while (logEl.children.length > 40) logEl.removeChild(logEl.firstChild);
    logEl.scrollTop = logEl.scrollHeight;
    state.logs++;
  }

  const DAG_LABEL = { idle: "待命", working: "工作中", running: "运行中", done: "完成" };
  function setDag(id, status) {
    const node = dagNodes[id];
    if (!node) return;
    node.className = `dag-node st-${status}`;
    const b = node.querySelector(".dn-badge");
    if (b) {
      const cls = status === "done" ? "done" : status === "idle" ? "off" : status;
      b.className = `badge ${cls} dn-badge`;
      b.innerHTML = `<span class="dot"></span>${DAG_LABEL[status] || status}`;
    }
    Object.entries(edgeEls).forEach(([key, ln]) => {
      if (key.startsWith(`${id}-`) && (status === "working" || status === "running" || status === "done")) {
        ln.setAttribute("stroke", "#22d3ee");
        ln.setAttribute("stroke-width", "0.8");
      }
    });
  }

  function say(id, text, dur) {
    const ag = agentById2(id);
    if (!ag) return;
    ag.say = { text, until: state.clock + (dur || 3) };
  }

  function clockStr() {
    // map 0..60s script to the demo 10:15 → 10:28 window for log timestamps
    const base = 10 * 60 + 15;
    const mins = base + Math.round((state.clock / 60) * 13);
    return `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
  }

  function dispatch(ev) {
    const cs = ev.clock || clockStr();
    switch (ev.type) {
      case "log": appendLog(ev.agent, ev.text, ev.color, cs); break;
      case "work": setDag(ev.agent, "working"); { const a = agentById2(ev.agent); if (a) a.status = "working"; } break;
      case "dag": setDag(ev.agent, ev.status); break;
      case "say": say(ev.agent, ev.text, ev.dur); break;
      case "done": setDag(ev.agent, "done"); { const a = agentById2(ev.agent); if (a) a.status = "done"; } break;
      case "skill":
        skillCounts[ev.name] = ev.n;
        if (skillRows[ev.name]) {
          skillRows[ev.name].querySelector(".sk-count").textContent = ev.n;
          skillRows[ev.name].classList.add("hl");
          setTimeout(() => skillRows[ev.name] && skillRows[ev.name].classList.remove("hl"), 900);
        }
        break;
      case "visit":
        gather([ev.from, ev.to]);
        (ev.lines || []).forEach((l, i) => say(l.agent, l.text, 3 + i));
        break;
      case "roundtable":
        gather(ev.agents || []);
        (ev.lines || []).forEach((l, i) => say(l.agent, l.text, 3 + i));
        break;
      case "timeline": break; // handled by clock-driven node states
      case "finish":
        agents.forEach((a) => { a.status = "done"; setDag(a.id, "done"); });
        badge.className = "badge done";
        badge.innerHTML = '<span class="dot"></span>已完成';
        appendLog("系统", "AlphaOS 任务处理完成", "#7fa3c7", cs);
        break;
    }
  }

  function stepAgent(ag, dt) {
    const dx = ag.tx - ag.x, dy = ag.ty - ag.y;
    const dist = Math.hypot(dx, dy);
    if (dist < 3) {
      ag.walking = false;
      ag.pauseT -= dt;
      if (ag.pauseT <= 0) pickWander(ag);
    } else {
      ag.walking = true;
      const sp = 52 * dt;
      ag.x += (dx / dist) * sp;
      ag.y += (dy / dist) * sp;
      ag.facing = dx < 0 ? -1 : 1;
      ag.frameT += dt;
      if (ag.frameT > 0.13) { ag.frameT = 0; ag.frameIdx++; }
    }
  }

  const dpr = window.devicePixelRatio || 1;
  canvas.width = WAR_W * dpr;
  canvas.height = WAR_H * dpr;
  const ctx = canvas.getContext("2d");

  function drawRoom() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = false;
    const g = ctx.createLinearGradient(0, 0, 0, WAR_H);
    g.addColorStop(0, "#0c1830"); g.addColorStop(1, "#0a1322");
    ctx.fillStyle = g; ctx.fillRect(0, 0, WAR_W, WAR_H);
    ctx.strokeStyle = "#12233c"; ctx.lineWidth = 1;
    for (let x = 0; x <= WAR_W; x += 48) { ctx.beginPath(); ctx.moveTo(x, 60); ctx.lineTo(x, WAR_H); ctx.stroke(); }
    for (let y = 60; y <= WAR_H; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(WAR_W, y); ctx.stroke(); }
    ctx.fillStyle = "#0e1e34"; ctx.fillRect(0, 0, WAR_W, 60);
    ctx.strokeStyle = "#16304f"; ctx.beginPath(); ctx.moveTo(0, 60); ctx.lineTo(WAR_W, 60); ctx.stroke();
    // desks at each home
    Object.values(WAR_HOMES).forEach((h) => {
      ctx.fillStyle = "#14304f";
      ctx.beginPath(); ctx.roundRect(h.x - 30, h.y + 14, 60, 16, 5); ctx.fill();
    });
  }

  function drawAgent(ag) {
    const entry = spriteCache.get(ag.sheet);
    const size = 66;
    const fx = (ag.walking ? WALK_CYCLE[ag.frameIdx % WALK_CYCLE.length] : 0) * FRAME;
    ctx.fillStyle = "rgba(0,0,0,0.28)";
    ctx.beginPath(); ctx.ellipse(ag.x, ag.y + 4, 18, 5, 0, 0, Math.PI * 2); ctx.fill();
    ctx.save();
    ctx.translate(ag.x, ag.y);
    if (ag.facing < 0) ctx.scale(-1, 1);
    if (entry && entry.ready) ctx.drawImage(entry.img, fx, 0, FRAME, FRAME, -size / 2, -size + 8, size, size);
    else { ctx.fillStyle = "#13263f"; ctx.fillRect(-size / 2, -size + 8, size, size); }
    ctx.restore();
    // status dot
    const dot = { working: "#60a5fa", running: "#60a5fa", done: "#34d399", idle: "#5a6b80" }[ag.status] || "#5a6b80";
    ctx.fillStyle = dot;
    ctx.beginPath(); ctx.arc(ag.x + 18, ag.y - size + 20, 3.5, 0, Math.PI * 2); ctx.fill();
    // name tag
    ctx.fillStyle = "rgba(10,22,40,0.82)";
    ctx.beginPath(); ctx.roundRect(ag.x - 28, ag.y + 8, 56, 14, 4); ctx.fill();
    ctx.fillStyle = "#9fc0e0";
    ctx.font = "10px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(ag.name, ag.x, ag.y + 18);
  }

  function render() {
    drawRoom();
    [...agents].sort((a, b) => a.y - b.y).forEach(drawAgent);
  }

  function updateBubbles() {
    agents.forEach((ag) => {
      const active = ag.say && state.clock < ag.say.until;
      if (active) {
        if (!ag.bubbleEl) {
          ag.bubbleEl = el("div", "say-bubble");
          bubbleLayer.appendChild(ag.bubbleEl);
        }
        ag.bubbleEl.innerHTML = `<span class="sb-name">${esc(ag.name)}</span>${esc(ag.say.text)}`;
        ag.bubbleEl.style.left = `${(ag.x / WAR_W) * 100}%`;
        ag.bubbleEl.style.top = `${((ag.y - 62) / WAR_H) * 100}%`;
      } else if (ag.bubbleEl) {
        ag.bubbleEl.remove();
        ag.bubbleEl = null;
      }
    });
  }

  function updateHud() {
    const pct = Math.min(100, Math.round((state.clock / 60) * 100));
    if (pct !== state.lastPct) {
      state.lastPct = pct;
      pmain.querySelector(".p-pct").textContent = `${pct}%`;
      pmain.querySelector(".pbar i").style.width = `${pct}%`;
      pstats.done.querySelector("strong").textContent = agents.filter((a) => a.status === "done").length;
      pstats.working.querySelector("strong").textContent = agents.filter((a) => a.status === "working" || a.status === "running").length;
      pstats.logs.querySelector("strong").textContent = state.logs;
      pstats.elapsed.querySelector("strong").textContent = `${Math.round(state.clock)}s`;
    }
    tlFill.style.width = `${(state.clock / 60) * 100}%`;
    tlEvents.forEach((e, i) => {
      const node = tlNodeEls[i];
      const done = state.clock >= e.t;
      node.className = `tl-node${done ? " done" : ""}${!done && state.clock >= e.t - 2 ? " now" : ""}`;
    });
  }

  function resetRun() {
    state.clock = 0; state.ptr = 0; state.logs = 0; state.lastPct = -1;
    logEl.innerHTML = "";
    Object.keys(skillCounts).forEach((n) => { skillCounts[n] = 0; skillRows[n].querySelector(".sk-count").textContent = "0"; });
    agents.forEach((a) => { a.status = "idle"; a.say = null; if (a.bubbleEl) { a.bubbleEl.remove(); a.bubbleEl = null; } });
    Object.keys(DAG_POS).forEach((id) => setDag(id, "idle"));
    DAG_EDGES.forEach(([a, b]) => { const ln = edgeEls[`${a}-${b}`]; ln.setAttribute("stroke", "#1d3a5c"); ln.setAttribute("stroke-width", "0.5"); });
    badge.className = "badge running";
    badge.innerHTML = '<span class="dot"></span>执行中';
    state.playing = true;
    playBtn.textContent = "⏸ 暂停";
  }

  playBtn.addEventListener("click", () => {
    state.playing = !state.playing;
    playBtn.textContent = state.playing ? "⏸ 暂停" : "▶ 继续";
  });
  speedSel.addEventListener("change", () => { state.speed = Number(speedSel.value) || 1; });
  replayBtn.addEventListener("click", resetRun);

  // ---------------- rAF loop ----------------
  let raf = 0;
  let last = performance.now();
  function tick(ts) {
    const dtReal = Math.min(0.05, (ts - last) / 1000);
    last = ts;
    const dt = dtReal * state.speed;
    if (state.playing && state.clock < 60) {
      state.clock += dt;
      while (state.ptr < WAR_SCRIPT.length && WAR_SCRIPT[state.ptr].t <= state.clock) {
        dispatch(WAR_SCRIPT[state.ptr++]);
      }
      if (state.clock >= 60) { state.clock = 60; state.playing = false; playBtn.textContent = "▶ 继续"; }
      updateHud();
    }
    // agents always wander (autonomous movement), a touch slower when paused
    agents.forEach((a) => stepAgent(a, (state.playing ? dt : dtReal) * (state.playing ? 1 : 0.5)));
    render();
    updateBubbles();
    raf = requestAnimationFrame(tick);
  }
  raf = requestAnimationFrame(tick);
  registerTeardown(() => {
    cancelAnimationFrame(raf);
    agents.forEach((a) => { if (a.bubbleEl) a.bubbleEl.remove(); });
  });

  return wrap;
}

// ---------------------------------------------------------------------------
// page: experts (master-detail, 界面 04)
// ---------------------------------------------------------------------------
let expertSel = "manager";
let expertTab = "cap";
let expertQuery = "";
let expertFilter = "all";

function pageExperts() {
  const layout = el("div", "experts-layout");
  const left = el("div", "panel");
  left.appendChild(screenTitle("04", "专家中心", "AlphaOS 专家团队由领域顶尖 AI Agent 组成，覆盖宏观、行业、量化、风险、研究与报告全链路。"));

  // toolbar
  const toolbar = el("div", "experts-toolbar");
  const search = el("input");
  search.type = "text";
  search.placeholder = "🔍 搜索专家或技能…";
  search.value = expertQuery;
  search.addEventListener("input", () => { expertQuery = search.value; renderExpertGrid(grid); });
  const filter = el("select");
  [["all", "全部状态"], ["online", "在线"], ["working", "工作中"], ["busy", "忙碌"]].forEach(([v, t]) => {
    const o = el("option", "", esc(t)); o.value = v; if (v === expertFilter) o.selected = true; filter.appendChild(o);
  });
  filter.addEventListener("change", () => { expertFilter = filter.value; renderExpertGrid(grid); });
  toolbar.append(search, filter);
  left.appendChild(toolbar);

  const grid = el("div", "experts-grid");
  left.appendChild(grid);
  renderExpertGrid(grid);

  // footer counts
  const foot = el("div", "experts-foot");
  const by = (s) => AGENTS.filter((a) => a.status === s).length;
  foot.innerHTML = `<span>共 ${AGENTS.length} 位专家</span>
    <span><span class="dot ok"></span>在线 ${by("online")}</span>
    <span><span class="dot" style="background:#60a5fa"></span>工作中 ${by("working")}</span>
    <span><span class="dot warn"></span>忙碌 ${by("busy")}</span>
    <span><span class="dot"></span>离线 ${by("off")}</span>`;
  left.appendChild(foot);

  layout.appendChild(left);
  const detail = el("div", "panel");
  detail.id = "expertDetail";
  layout.appendChild(detail);
  renderExpertDetail(detail);
  return layout;
}

function renderExpertGrid(grid) {
  grid.innerHTML = "";
  const q = expertQuery.trim();
  AGENTS.filter((a) => {
    if (expertFilter !== "all" && a.status !== expertFilter) return false;
    if (!q) return true;
    const hay = `${a.name} ${a.role} ${a.specialty} ${(a.skills || []).map((s) => s.name).join(" ")}`;
    return hay.includes(q);
  }).forEach((a) => {
    const enabled = store.state.agentEnabled[a.id] !== false;
    const card = el("button", `expert-card${a.id === expertSel ? " sel" : ""}${enabled ? "" : " off"}`);
    card.appendChild(avatar(a.id, 64, "ec-ava"));
    card.appendChild(el("strong", "", esc(a.name)));
    card.appendChild(el("div", "", `<span style="color:var(--text-2);font-size:11.5px">${esc(a.role)}</span> <span class="badge ${a.status}"><span class="dot"></span>${statusText(a.status)}</span>`));
    card.appendChild(el("div", "ec-spec", esc(a.specialty)));
    card.appendChild(el("div", "ec-desc", `已安装技能 <b style="color:var(--cyan)">${a.skillCount}</b> 个`));
    card.appendChild(el("div", "ec-desc", esc(a.desc)));
    card.addEventListener("click", () => {
      expertSel = a.id; expertTab = "cap";
      renderExpertGrid(grid);
      renderExpertDetail($("#expertDetail"));
    });
    grid.appendChild(card);
  });
}

function renderExpertDetail(panel) {
  if (!panel) return;
  const a = agentById(expertSel) || AGENTS[0];
  panel.innerHTML = "";

  const head = el("div", "detail-head");
  head.appendChild(avatar(a.id, 74, "pix-ava dh-ava"));
  const hinfo = el("div");
  hinfo.style.flex = "1";
  hinfo.innerHTML = `<div style="font-size:20px;font-weight:700">${esc(a.name)}</div>
    <div style="color:var(--text-2);font-size:12.5px">${esc(a.role)} <span class="badge ${a.status}"><span class="dot"></span>${statusText(a.status)}</span></div>`;
  head.appendChild(hinfo);
  const mgBtn = el("button", "btn", "👥 团队管理");
  mgBtn.addEventListener("click", () => toast("团队管理面板规划中（DEMO）"));
  head.appendChild(mgBtn);
  panel.appendChild(head);

  panel.appendChild(el("p", "", `<span style="color:var(--text-2);line-height:1.7">${esc(a.desc)}</span>`));

  const stars = "★★★★★".slice(0, Math.round(a.rating)) + "☆☆☆☆☆".slice(0, 5 - Math.round(a.rating));
  const stats = el("div", "detail-stats");
  stats.innerHTML = `
    <div class="ds"><strong>${esc(a.joined)}</strong><span>加入时间</span></div>
    <div class="ds"><strong>${esc(a.years)}</strong><span>经验年限</span></div>
    <div class="ds"><strong>${esc(a.completion)}</strong><span>任务完成率</span></div>
    <div class="ds"><strong style="color:var(--yellow)">${a.rating}</strong><span>${stars}</span></div>`;
  panel.appendChild(stats);

  const tabs = el("div", "tabs");
  [["cap", "能力概览"], ["tasks", "近期任务"], ["contrib", "贡献表现"], ["skills", "技能列表"], ["config", "配置管理"]].forEach(([k, t]) => {
    const tab = el("button", `tab${expertTab === k ? " active" : ""}`, esc(t));
    tab.addEventListener("click", () => { expertTab = k; renderExpertDetail(panel); });
    tabs.appendChild(tab);
  });
  panel.appendChild(tabs);

  const body = el("div");
  panel.appendChild(body);

  if (expertTab === "cap") {
    body.appendChild(el("div", "follow-sec-title", "核心能力"));
    const bars = el("div", "cap-bars");
    (a.capabilities || []).forEach((c) => {
      bars.appendChild(el("div", "cap-bar", `<span>${esc(c.label)}</span>
        <span class="cb-track"><i style="width:${c.pct}%"></i></span>
        <span style="text-align:right;color:var(--green)">${c.pct}%</span>`));
    });
    body.appendChild(bars);
    body.appendChild(el("div", "follow-sec-title", "能力雷达"));
    const rwrap = el("div");
    rwrap.style.cssText = "display:grid;place-items:center;padding:6px 0";
    const canvas = el("canvas");
    rwrap.appendChild(canvas);
    body.appendChild(rwrap);
    requestAnimationFrame(() => drawRadar(canvas, a.radar, 240));
  } else if (expertTab === "tasks") {
    (a.recentTasks || []).forEach((t) => {
      const row = el("button", "task-row");
      row.innerHTML = `<span style="flex:1">${esc(t.title)}</span>
        <span class="tr-tag">${esc(t.tag)}</span>
        <span class="badge ${t.status === "running" ? "running" : "done"}"><span class="dot"></span>${t.status === "running" ? "进行中" : "完成"}</span>
        <span class="tr-time">${esc(t.time)}</span>`;
      row.addEventListener("click", () => toast(`${t.title}（DEMO）`));
      body.appendChild(row);
    });
  } else if (expertTab === "contrib") {
    const grid = el("div", "detail-stats");
    grid.style.gridTemplateColumns = "repeat(3,1fr)";
    grid.innerHTML = `
      <div class="ds"><strong>${a.recentTasks ? a.recentTasks.length + 24 : 28}</strong><span>近30天任务</span></div>
      <div class="ds"><strong style="color:var(--green)">96%</strong><span>完成率</span></div>
      <div class="ds"><strong>${a.skillCount}</strong><span>影响策略</span></div>`;
    body.appendChild(grid);
    body.appendChild(el("div", "follow-sec-title", "贡献趋势（近 5 周 · DEMO）"));
    const canvas = el("canvas");
    const box = el("div", "chart-box");
    box.appendChild(canvas);
    body.appendChild(box);
    const trend = { title: "", labels: ["W1", "W2", "W3", "W4", "W5"], series: [{ name: "贡献值", color: "#34d399", data: [62, 70, 66, 82, 90] }] };
    requestAnimationFrame(() => drawLineChart(canvas, trend));
  } else if (expertTab === "skills") {
    body.appendChild(el("div", "follow-sec-title", `已安装技能 · ${a.skillCount} 个`));
    (a.skills || []).forEach((s) => {
      const row = el("div", "skill-row");
      row.innerHTML = `<span>🧩</span><span>${esc(s.name)}</span><span class="sk-count" style="color:var(--text-3)">${esc(s.type)}</span>`;
      body.appendChild(row);
    });
  } else if (expertTab === "config") {
    const enabled = store.state.agentEnabled[a.id] !== false;
    const enable = el("div", "op-enable");
    enable.innerHTML = `<div><strong>启用该专家</strong><div class="op-note">禁用后 Manager 将不会把该专家纳入任务编排。</div></div>`;
    const sw = el("button", `switch${enabled ? " on" : ""}`);
    if (a.id === "manager") { sw.classList.add("disabled"); }
    sw.addEventListener("click", () => {
      if (a.id === "manager") { toast("Manager 为总控，不能禁用（DEMO）"); return; }
      store.setAgentEnabled(a.id, !(store.state.agentEnabled[a.id] !== false));
      renderExpertDetail(panel);
      renderExpertGrid($(".experts-grid"));
    });
    enable.appendChild(sw);
    body.appendChild(enable);
    body.appendChild(el("div", "op-note", "更多配置（模型、温度、Skill 授权）规划中。"));
  }
}

// ---------------------------------------------------------------------------
// page: tasks (report + demo history list)
// ---------------------------------------------------------------------------
function pageTasks() {
  const wrap = el("div", "panel");
  wrap.appendChild(el("div", "panel-title", "任务中心 <span class='title-extra'>历史任务</span>"));
  const list = el("div", "task-list");
  REPORTS.forEach((r) => {
    const item = el("button", "task-item");
    item.appendChild(el("span", "ri-ico", "📄"));
    item.appendChild(el("div", "", `<div class="ti-title">${esc(r.title)}</div><div class="ti-sub">${esc(r.kind)} · ${esc(r.doneAt)}</div>`));
    item.appendChild(el("span", "ti-go", "›"));
    item.addEventListener("click", () => navigate("reports", r.id));
    list.appendChild(item);
  });
  wrap.appendChild(list);
  return wrap;
}

// ---------------------------------------------------------------------------
// page: soon (placeholder pages backed by SOON_PAGES)
// ---------------------------------------------------------------------------
function pageSoon(route) {
  const meta = SOON_PAGES[route] || { ico: "🚧", name: "规划中", desc: "该模块正在规划中。" };
  const wrap = el("div", "panel");
  const box = el("div", "soon-wrap");
  box.appendChild(el("div", "sw-ico", meta.ico));
  box.appendChild(el("h2", "", esc(meta.name)));
  box.appendChild(el("p", "", esc(meta.desc)));
  const back = el("button", "btn btn-primary", "返回研究报告");
  back.addEventListener("click", () => navigate("reports"));
  box.appendChild(back);
  wrap.appendChild(box);
  return wrap;
}

// ===========================================================================
// LIVE pages — bound to the real backend read-only API (mode === "live")
// ===========================================================================
let liveExpertSel = null;
let liveExpertTab = "cap";
let liveExpertQuery = "";

// ---- live: experts center -------------------------------------------------
function pageExpertsLive() {
  const host = el("div");
  return renderLive(host, fetchExperts, (experts) => buildExpertsLive(experts));
}

function buildExpertsLive(experts) {
  if (!liveExpertSel || !experts.some((e) => e.id === liveExpertSel)) {
    liveExpertSel = experts.length ? experts[0].id : null;
  }
  const layout = el("div", "experts-layout");
  const left = el("div", "panel");
  left.appendChild(screenTitle("04", "专家中心 · 实时", "以下为后端 Registry 的真实专家能力、工具与技能授权，启停状态实时生效于 Manager 编排。"));

  const toolbar = el("div", "experts-toolbar");
  const search = el("input");
  search.type = "text";
  search.placeholder = "🔍 搜索专家或能力…";
  search.value = liveExpertQuery;
  const grid = el("div", "experts-grid");
  search.addEventListener("input", () => { liveExpertQuery = search.value; drawGrid(); });
  toolbar.append(search);
  left.appendChild(toolbar);
  left.appendChild(grid);

  const foot = el("div", "experts-foot");
  const enabledN = experts.filter((e) => e.enabled).length;
  foot.innerHTML = `<span>共 ${experts.length} 位专家</span>
    <span><span class="dot ok"></span>启用 ${enabledN}</span>
    <span><span class="dot"></span>停用 ${experts.length - enabledN}</span>`;
  left.appendChild(foot);
  layout.appendChild(left);

  const detail = el("div", "panel");
  detail.id = "liveExpertDetail";
  layout.appendChild(detail);

  function drawGrid() {
    grid.innerHTML = "";
    const q = liveExpertQuery.trim();
    experts
      .filter((e) => {
        if (!q) return true;
        const hay = `${e.name} ${e.role} ${e.specialty} ${e.capabilities.join(" ")} ${e.skills.join(" ")}`;
        return hay.includes(q);
      })
      .forEach((e) => {
        const card = el("button", `expert-card${e.id === liveExpertSel ? " sel" : ""}${e.enabled ? "" : " off"}`);
        card.appendChild(avatar(e.id, 64, "ec-ava"));
        card.appendChild(el("strong", "", esc(e.name)));
        card.appendChild(el("div", "", `<span style="color:var(--text-2);font-size:11.5px">${esc(e.role)}</span> <span class="badge ${e.status}"><span class="dot"></span>${statusText(e.status)}</span>`));
        card.appendChild(el("div", "ec-spec", esc(e.specialty)));
        card.appendChild(el("div", "ec-desc", `授权技能 <b style="color:var(--cyan)">${e.skills.length}</b> · 工具 <b style="color:var(--cyan)">${e.tools.length}</b>`));
        card.appendChild(el("div", "ec-desc", esc(e.description)));
        card.addEventListener("click", () => { liveExpertSel = e.id; liveExpertTab = "cap"; drawGrid(); drawDetail(); });
        grid.appendChild(card);
      });
  }

  function drawDetail() {
    const panel = detail;
    const e = experts.find((x) => x.id === liveExpertSel);
    panel.innerHTML = "";
    if (!e) { panel.appendChild(stateBox("empty", "暂无专家数据")); return; }

    const head = el("div", "detail-head");
    head.appendChild(avatar(e.id, 74, "pix-ava dh-ava"));
    const hinfo = el("div");
    hinfo.style.flex = "1";
    hinfo.innerHTML = `<div style="font-size:20px;font-weight:700">${esc(e.name)}</div>
      <div style="color:var(--text-2);font-size:12.5px">${esc(e.role)} <span class="badge ${e.status}"><span class="dot"></span>${statusText(e.status)}</span> <span class="badge">${e.id}</span></div>`;
    head.appendChild(hinfo);
    panel.appendChild(head);
    panel.appendChild(el("p", "", `<span style="color:var(--text-2);line-height:1.7">${esc(e.description)}</span>`));

    const tabs = el("div", "tabs");
    [["cap", "能力"], ["tools", "工具"], ["skills", "授权技能"], ["config", "配置管理"]].forEach(([k, t]) => {
      const tab = el("button", `tab${liveExpertTab === k ? " active" : ""}`, esc(t));
      tab.addEventListener("click", () => { liveExpertTab = k; drawDetail(); });
      tabs.appendChild(tab);
    });
    panel.appendChild(tabs);

    const body = el("div");
    panel.appendChild(body);

    if (liveExpertTab === "cap") {
      body.appendChild(el("div", "follow-sec-title", `能力标签 · ${e.capabilities.length} 项`));
      if (e.capabilities.length) {
        const tagwrap = el("div"); tagwrap.style.cssText = "display:flex;flex-wrap:wrap;gap:8px";
        e.capabilities.forEach((c) => tagwrap.appendChild(el("span", "badge", esc(c))));
        body.appendChild(tagwrap);
      } else body.appendChild(el("div", "op-note", "该专家未声明能力标签。"));
    } else if (liveExpertTab === "tools") {
      body.appendChild(el("div", "follow-sec-title", `可用工具 · ${e.tools.length} 个`));
      if (e.tools.length) e.tools.forEach((t) => {
        const row = el("div", "skill-row");
        row.innerHTML = `<span>🛠</span><span>${esc(t)}</span>`;
        body.appendChild(row);
      });
      else body.appendChild(el("div", "op-note", "该专家未绑定外部工具。"));
    } else if (liveExpertTab === "skills") {
      body.appendChild(el("div", "follow-sec-title", `授权技能 · ${e.skills.length} 个`));
      if (e.skills.length) e.skills.forEach((s) => {
        const row = el("div", "skill-row");
        row.innerHTML = `<span>🧩</span><span>${esc(s)}</span>`;
        body.appendChild(row);
      });
      else body.appendChild(el("div", "op-note", "该专家未被授权任何 Skill。"));
    } else if (liveExpertTab === "config") {
      const isPortfolio = e.id === "portfolio";
      const enable = el("div", "op-enable");
      enable.innerHTML = `<div><strong>启用该专家</strong><div class="op-note">${isPortfolio ? "Portfolio 暂无运行实现，后端不可启用。" : "禁用后 Manager 将不会把该专家纳入任务编排（实时生效）。"}</div></div>`;
      const sw = el("button", `switch${e.enabled ? " on" : ""}${isPortfolio ? " disabled" : ""}`);
      sw.addEventListener("click", () => {
        if (isPortfolio) { toast("Portfolio 专家暂不可启用"); return; }
        const next = !e.enabled;
        sw.classList.toggle("on", next);
        liveSetExpertEnabled(e.id, next)
          .then((info) => {
            e.enabled = info.enabled;
            e.status = info.enabled ? "online" : "off";
            toast(`${e.name} 已${e.enabled ? "启用" : "停用"}`);
            drawGrid();
            drawDetail();
          })
          .catch((err) => {
            sw.classList.toggle("on", e.enabled);
            toast(`操作失败：${err && err.message ? err.message : "后端拒绝"}`);
          });
      });
      enable.appendChild(sw);
      body.appendChild(enable);
    }
  }

  drawGrid();
  drawDetail();
  return layout;
}

// ---- live: skills market --------------------------------------------------
function pageSkillsLive() {
  const host = el("div");
  return renderLive(host, fetchSkills, (skills) => {
    const wrap = el("div", "panel");
    wrap.appendChild(screenTitle("07", "Skills · 实时", "以下为后端 skill_registry 托管的运行时 Skill 真实清单（来源与状态由后端统一管理）。"));
    if (!skills.length) { wrap.appendChild(stateBox("empty", "暂无已注册的运行时 Skill")); return wrap; }
    const list = el("div", "report-list");
    skills.forEach((s) => {
      const item = el("div", "report-item");
      item.style.cursor = "default";
      item.appendChild(el("span", "ri-ico", s.mode === "executable" ? "⚙" : "📘"));
      const modeLabel = s.mode === "executable" ? "可执行" : s.mode === "instruction" ? "指令式" : s.mode;
      item.appendChild(el("div", "", `
        <div style="font-weight:600">${esc(s.name)} <span class="badge ${s.enabled ? "online" : ""}"><span class="dot ${s.enabled ? "ok" : ""}"></span>${s.enabled ? "已启用" : "停用"}</span></div>
        <div style="color:var(--text-2);font-size:12px;margin-top:3px">${esc(s.description)}</div>
        <div style="color:var(--text-3);font-size:11px;margin-top:4px">${esc(s.id)} · ${esc(modeLabel)} · 归属 ${esc(s.owner_agents.join(" / ") || "-")}${s.capabilities.length ? " · 能力 " + esc(s.capabilities.join(", ")) : ""}</div>
      `));
      list.appendChild(item);
    });
    wrap.appendChild(list);
    return wrap;
  });
}

// ---- live: tasks center ---------------------------------------------------
function pageTasksLive() {
  const host = el("div");
  return renderLive(host, fetchTasks, (tasks) => {
    const wrap = el("div", "panel");
    wrap.appendChild(el("div", "panel-title", "任务中心 <span class='title-extra'>实时任务记录</span>"));
    if (!tasks.length) {
      wrap.appendChild(stateBox("empty", "暂无任务记录", "任务执行需要配置 ARK 凭证并从大厅提交研究请求（下一阶段）。当前后端任务库为空。"));
      return wrap;
    }
    const list = el("div", "task-list");
    tasks.forEach((t) => {
      const item = el("button", "task-item");
      item.appendChild(el("span", "ri-ico", "📄"));
      const dur = t.duration_ms != null ? ` · ${(t.duration_ms / 1000).toFixed(1)}s` : "";
      item.appendChild(el("div", "", `<div class="ti-title">${esc(t.prompt.slice(0, 60) || t.id)}</div><div class="ti-sub">${esc(t.status)} · ${esc(t.created_at)}${esc(dur)}</div>`));
      item.appendChild(el("span", "ti-go", "›"));
      item.addEventListener("click", () => toast(`任务 ${t.id}（状态：${t.status}）`));
      list.appendChild(item);
    });
    wrap.appendChild(list);
    return wrap;
  });
}

// ---- live: reports list ---------------------------------------------------
function pageReportListLive() {
  const host = el("div");
  return renderLive(host, fetchReports, (reports) => {
    const wrap = el("div");
    const panel = el("div", "panel");
    panel.appendChild(el("div", "panel-title", "研究报告 <span class='title-extra'>实时报告库</span>"));
    if (!reports.length) {
      panel.appendChild(stateBox("empty", "暂无已生成的研究报告", "报告在任务执行完成后由 Result Aggregator 落库（需 ARK 凭证，下一阶段）。当前后端报告库为空。"));
      wrap.appendChild(panel);
      return wrap;
    }
    const list = el("div", "report-list");
    reports.forEach((r) => {
      const item = el("button", "report-item");
      item.appendChild(el("span", "ri-ico", "📄"));
      const ratio = r.completeness ? Math.round((r.completeness.completion_ratio || 0) * 100) : null;
      item.appendChild(el("div", "", `
        <div style="font-weight:600">${esc(r.title)}</div>
        <div style="color:var(--text-2);font-size:12px;margin-top:3px">${esc(r.id)} · ${esc(r.created_at)}</div>
      `));
      if (ratio != null) item.appendChild(el("div", "ri-score", `<strong>${ratio}%</strong><span style="color:var(--text-2);font-size:11px">完成度</span>`));
      item.addEventListener("click", () => navigate("reports", r.id));
      list.appendChild(item);
    });
    panel.appendChild(list);
    wrap.appendChild(panel);
    return wrap;
  });
}

// ---- live: report detail + real evidence-bounded follow-up ----------------
function pageReportDetailLive(reportId) {
  const host = el("div");
  return renderLive(host, () => fetchReport(reportId), (report) => {
    const layout = el("div", "report-layout");
    layout.appendChild(buildReportMainLive(report));
    layout.appendChild(buildFollowPanelLive(report));
    return layout;
  });
}

function buildReportMainLive(report) {
  const col = el("div");
  const toolbar = el("div", "rpt-toolbar");
  const back = el("button", "btn-ghost", "‹ 返回报告列表");
  back.addEventListener("click", () => navigate("reports"));
  toolbar.appendChild(back);
  col.appendChild(toolbar);

  const agg = report.aggregation || {};
  const direct = agg.direct_answer || {};
  const heroPanel = el("div", "panel");
  heroPanel.appendChild(el("div", "panel-title", esc(report.title)));
  heroPanel.appendChild(el("div", "op-note", `${esc(report.id)} · ${esc(report.created_at)}`));
  if (report.completeness) {
    const c = report.completeness;
    const stats = el("div", "detail-stats");
    stats.innerHTML = `
      <div class="ds"><strong>${c.planned_steps}</strong><span>计划步骤</span></div>
      <div class="ds"><strong style="color:var(--green)">${c.completed_steps}</strong><span>已完成</span></div>
      <div class="ds"><strong style="color:var(--yellow)">${c.failed_steps + c.blocked_steps}</strong><span>失败/受阻</span></div>
      <div class="ds"><strong>${Math.round((c.completion_ratio || 0) * 100)}%</strong><span>完成度</span></div>`;
    heroPanel.appendChild(stats);
  }
  col.appendChild(heroPanel);

  if (direct.headline) {
    const dp = el("div", "panel");
    dp.appendChild(el("div", "follow-sec-title", "核心结论"));
    dp.appendChild(el("h2", "", esc(direct.headline)));
    if (direct.explanation) dp.appendChild(el("p", "", `<span style="color:var(--text-2);line-height:1.7">${esc(direct.explanation)}</span>`));
    col.appendChild(dp);
  }

  const blocks = Array.isArray(agg.content_blocks) ? agg.content_blocks : [];
  blocks.forEach((b) => {
    const bp = el("div", "panel");
    bp.appendChild(el("div", "follow-sec-title", esc(b.title || b.type || "内容块")));
    if (b.description) bp.appendChild(el("p", "", `<span style="color:var(--text-2);line-height:1.7">${esc(b.description)}</span>`));
    bp.appendChild(
      b.type === "personal_constraints"
        ? renderPersonalConstraintData(b.data || {})
        : renderBlockData(b.data),
    );
    col.appendChild(bp);
  });

  if (agg.disclaimer) col.appendChild(el("div", "op-note", esc(agg.disclaimer)));
  return col;
}

// Generic, bounded renderer for a content block's `data` — no fixed schema.
function renderBlockData(data) {
  const wrap = el("div");
  const walk = (value, into, depth) => {
    if (depth > 3) return;
    if (value == null) return;
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      into.appendChild(el("div", "skill-row", `<span>•</span><span>${esc(String(value))}</span>`));
    } else if (Array.isArray(value)) {
      value.slice(0, 20).forEach((item) => walk(item, into, depth + 1));
    } else if (typeof value === "object") {
      Object.entries(value).slice(0, 20).forEach(([k, v]) => {
        if (typeof v === "object" && v !== null) {
          into.appendChild(el("div", "follow-sec-title", esc(k)));
          walk(v, into, depth + 1);
        } else {
          into.appendChild(el("div", "skill-row", `<span style="color:var(--text-3)">${esc(k)}</span><span>${esc(String(v))}</span>`));
        }
      });
    }
  };
  walk(data, wrap, 0);
  return wrap;
}

function buildFollowPanelLive(report) {
  const panel = el("div", "panel follow-panel");
  const head = el("div", "follow-head");
  head.appendChild(avatar("manager", 46, "fh-ava"));
  const who = el("div", "fh-who");
  who.appendChild(el("strong", "", "报告内证据检索"));
  who.appendChild(el("p", "", "追问将在后端对报告证据做确定性检索，不调用模型、不产生新分析。"));
  who.appendChild(el("span", "badge online", '<span class="dot"></span>实时'));
  head.appendChild(who);
  panel.appendChild(head);

  panel.appendChild(el("div", "follow-sec-title", "对话记录"));
  const scroll = el("div", "follow-scroll");
  scroll.id = "liveFollowScroll";
  panel.appendChild(scroll);

  const seed = [{ role: "sys", text: `报告《${report.title}》已生成`, time: "" }];
  (report.followups || []).forEach((f) => {
    seed.push({ role: f.role === "user" ? "me" : "bot", text: f.text, time: (f.created_at || "").slice(11, 19), evidence: f.evidence });
  });
  seed.forEach((m) => scroll.appendChild(renderLiveMessage(m)));

  const inputBar = el("div", "chat-inputbar");
  const input = el("input");
  input.type = "text";
  input.placeholder = "输入问题，检索报告证据…";
  const send = el("button", "btn btn-primary", "➤");
  const fire = () => {
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    submitLiveFollowup(report, q, scroll);
  };
  send.addEventListener("click", fire);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") fire(); });
  inputBar.append(input, send);
  panel.appendChild(inputBar);

  requestAnimationFrame(() => { scroll.scrollTop = scroll.scrollHeight; });
  return panel;
}

function renderLiveMessage(m) {
  if (m.role === "sys") {
    return el("div", "msg", `
      <div class="m-avatar" style="display:grid;place-items:center;color:var(--green)">✓</div>
      <div class="m-body"><div class="m-meta"><span>系统</span><span>${esc(m.time || "")}</span></div>
      <div class="m-bubble" style="color:var(--text-2)">${esc(m.text)}</div></div>`);
  }
  const me = m.role === "me";
  const node = el("div", `msg${me ? " me" : ""}`);
  const ava = el("div", "m-avatar");
  ava.appendChild(avatar(me ? "user" : "manager", 38));
  const body = el("div", "m-body");
  body.appendChild(el("div", "m-meta", `<span>${me ? "你" : "Manager"}</span><span>${esc(m.time || "")}</span>`));
  body.appendChild(el("div", "m-bubble", esc(m.text)));
  if (m.evidence && m.evidence.length) {
    const ev = el("div", "op-note");
    ev.style.marginTop = "6px";
    ev.innerHTML = m.evidence.map((e) => `<div>· <b>${esc(e.source || "证据")}</b>：${esc(String(e.text || "").slice(0, 160))}</div>`).join("");
    body.appendChild(ev);
  }
  node.append(ava, body);
  return node;
}

function submitLiveFollowup(report, question, scroll) {
  scroll.appendChild(renderLiveMessage({ role: "me", text: question, time: nowClock() }));
  scroll.scrollTop = scroll.scrollHeight;
  const typing = el("div", "msg");
  const ava = el("div", "m-avatar");
  ava.appendChild(avatar("manager", 38));
  typing.append(ava, el("div", "m-body", '<div class="m-bubble"><span class="typing-dots"><i></i><i></i><i></i></span></div>'));
  scroll.appendChild(typing);
  scroll.scrollTop = scroll.scrollHeight;
  submitReportFollowup(report.id, question)
    .then((ans) => {
      typing.remove();
      scroll.appendChild(renderLiveMessage({ role: "bot", text: ans.text, time: (ans.created_at || "").slice(11, 19), evidence: ans.evidence }));
      scroll.scrollTop = scroll.scrollHeight;
    })
    .catch((err) => {
      typing.remove();
      scroll.appendChild(renderLiveMessage({ role: "bot", text: `检索失败：${err && err.message ? err.message : "后端不可用"}`, time: nowClock() }));
      scroll.scrollTop = scroll.scrollHeight;
    });
}

// ---------------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------------
function boot() {
  renderTopbar();
  renderStatusbar();
  renderSidebar();
  // expose the router so hall hero / LIVE-office previews can jump into the
  // clarify + war-room sub-flows (which have no top-level nav entry).
  window.__navigate = navigate;
  window.__openProfileOnboarding = () => openProfileOnboarding(toast);
  if (isLive()) {
    // live mode: probe the backend, then land on a page with real data.
    refreshServiceStatus().finally(() => {
      renderTopbar();
      navigate("experts");
    });
  } else {
    // demo mode: land directly on the report follow-up view (matches design).
    navigate("reports", REPORTS[0].id);
  }
  maybeStartProfileOnboarding(toast);
  setInterval(renderStatusbar, 30_000);
}

function renderPersonalConstraintData(data) {
  const wrap = el("div");
  const summary = el("div", "metric-grid");
  [
    ["评估状态", data.status || "—"],
    ["承受能力边界", data.capacity_level || "unable_to_grade"],
    ["使用字段", (data.fields_used || []).join("、") || "无"],
    ["缺失字段", (data.missing_critical_fields || []).join("、") || "无"],
  ].forEach(([label, value]) => {
    summary.appendChild(
      el(
        "div",
        "metric-card",
        `<span>${esc(label)}</span><strong>${esc(value)}</strong>`,
      ),
    );
  });
  wrap.appendChild(summary);
  (data.constraints || []).forEach((item) => {
    wrap.appendChild(
      el(
        "div",
        "skill-row",
        `<span>${esc(item.category || "约束")} · ${esc(item.severity || "")}</span>` +
          `<span>${esc(item.statement || "")} ${esc(item.basis || "")}</span>`,
      ),
    );
  });
  wrap.appendChild(
    el(
      "p",
      "op-note",
      "原始敏感数值不会进入结果，也不会传给 Research、Quant 或 Macro。",
    ),
  );
  return wrap;
}

boot();
