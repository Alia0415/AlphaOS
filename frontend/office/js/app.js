// AlphaOS Pixel Office — application shell + router.
// Renders the sidebar / topbar / statusbar chrome and the page outlet.
// Demo data comes from mock.js; every demo value stays labelled DEMO in UI.
import { store } from "./store.js";
import { AGENTS, REPORTS, SOON_PAGES, OFFICE_FEED } from "./mock.js";

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
// page: hall (lightweight)
// ---------------------------------------------------------------------------
function pageHall() {
  const wrap = el("div");
  const panel = el("div", "panel");
  panel.appendChild(el("div", "panel-title", "投研大厅 <span class='title-extra'>用最强的 AI 团队，做最专业的投资研究</span>"));
  panel.appendChild(el("p", "", "<span style='color:var(--text-2)'>点击左侧「研究报告」查看《新能源行业投资机会研究报告》与报告后追问界面。</span>"));
  const strip = el("div", "expert-strip");
  strip.style.marginTop = "14px";
  AGENTS.forEach((a) => {
    const card = el("button", "expert-mini");
    card.appendChild(avatar(a.id, 56, "em-ava"));
    card.appendChild(el("strong", "", esc(a.name)));
    card.appendChild(el("div", "em-role", esc(a.role)));
    card.appendChild(el("span", `badge ${a.status}`, `<span class="dot"></span>${statusText(a.status)}`));
    card.addEventListener("click", () => navigate("experts"));
    strip.appendChild(card);
  });
  panel.appendChild(strip);
  wrap.appendChild(panel);

  const feedPanel = el("div", "panel");
  feedPanel.style.marginTop = "14px";
  feedPanel.appendChild(el("div", "panel-title", "实时动态"));
  const feed = el("div", "log-list");
  OFFICE_FEED.forEach((line) => {
    feed.appendChild(el("div", "log-line", `<span class="lt">${nowClock()}</span><span>${esc(line)}</span>`));
  });
  feedPanel.appendChild(feed);
  wrap.appendChild(feedPanel);
  return wrap;
}

function statusText(s) {
  return { online: "在线", working: "工作中", busy: "忙碌", running: "运行中", off: "离线" }[s] || s;
}

// ---------------------------------------------------------------------------
// page: experts (grid)
// ---------------------------------------------------------------------------
function pageExperts() {
  const wrap = el("div", "panel");
  wrap.appendChild(el("div", "panel-title", "专家中心 <span class='title-extra'>AlphaOS 专家池</span>"));
  const grid = el("div", "experts-grid");
  AGENTS.forEach((a) => {
    const enabled = store.state.agentEnabled[a.id] !== false;
    const card = el("button", `expert-card${enabled ? "" : " off"}`);
    card.appendChild(avatar(a.id, 64, "ec-ava"));
    card.appendChild(el("strong", "", esc(a.name)));
    card.appendChild(el("div", "ec-spec", esc(a.duty)));
    card.appendChild(el("div", "ec-desc", esc(a.desc)));
    card.addEventListener("click", () => toast(`${a.name} · ${a.specialty}`));
    grid.appendChild(card);
  });
  wrap.appendChild(grid);
  return wrap;
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
  // land directly on the report follow-up view (matches the design)
  navigate("reports", REPORTS[0].id);
  setInterval(renderStatusbar, 30_000);
}

boot();
