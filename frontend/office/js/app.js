// AlphaOS Pixel Office — application shell + router.
// Renders the sidebar / topbar / statusbar chrome and the page outlet.
// Demo data comes from mock.js; every demo value stays labelled DEMO in UI.
import { store } from "./store.js";
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

  side.appendChild(el("div", "sidebar-foot", "AlphaOS v0.3 · Demo"));
}

function renderTopbar() {
  const bar = $("#topbar");
  bar.innerHTML = "";

  const status = el("span", "pill", '<span class="dot ok"></span>系统状态：<strong style="color:var(--green)">正常运行</strong>');
  const engine = el("span", "pill", "🧠 模型引擎：GPT-4o");
  const data = el("span", "pill", '📡 数据源：实时已连接 <span class="dot ok"></span>');
  bar.append(status, engine, data);

  bar.appendChild(el("div", "topbar-spacer"));

  const history = el("button", "pill", "🕘 历史任务");
  history.addEventListener("click", () => navigate("tasks"));
  const settings = el("button", "pill", "⚙ 设置");
  settings.addEventListener("click", () => toast("设置面板规划中（DEMO）"));
  bar.append(history, settings);

  const avaBtn = el("button", "avatar-btn");
  avaBtn.appendChild(avatar("user", 34, "pix-ava"));
  avaBtn.addEventListener("click", () => toast("当前用户：演示账户"));
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
  switch (currentRoute) {
    case "reports":
      if (routeParam) page.appendChild(pageReportDetail(routeParam));
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
      page.appendChild(pageExperts());
      break;
    case "tasks":
      page.appendChild(pageTasks());
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
// page: war room (界面 03) — full sprite-driven build lands in the next step
// ---------------------------------------------------------------------------
function pageWarRoom() {
  const wrap = el("div", "panel");
  wrap.appendChild(screenTitle("03", "多 Agent 作战室", "任务执行可视化中心。"));
  const box = el("div", "empty-state");
  box.innerHTML = '<div class="es-ico">🛰</div><p>作战室精灵动画引擎即将上线。</p>';
  wrap.appendChild(box);
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
  // land directly on the report follow-up view (matches the design)
  navigate("reports", REPORTS[0].id);
  setInterval(renderStatusbar, 30_000);
}

boot();
