"use strict";

const DISCLAIMER = "本结果仅用于研究与演示，不构成投资建议、荐股或收益承诺。";
const AGENT_COLORS = {
  research: "#8fc7ff",
  quant: "#a8ffcf",
  risk: "#f7cb74",
  report: "#c7a8ff",
};
const {
  buildPlainLanguageResult,
  safeForDisplay,
} = globalThis.AlphaPlainLanguage;
const { translateEvent } = globalThis.AlphaEventLabels;
const { agentLabel } = globalThis.AlphaPresentationStatus;

const EXAMPLE_PROMPTS = {
  factor: "请根据 OHLCV 数据生成 5 个可验证的量价因子想法，并 shortlist 2 个。",
  "r020-risk":
    "计算 000001.SZ、000002.SZ 和 600519.SH 在 2024 年的 R020 成交量放大因子，并审查主要失效风险。",
  "research-report": "分析 000001.SZ 在 2024 年的价格表现，并生成一份简洁研究报告。",
};

const state = {
  conversations: [],
  activeConversationId: null,
  turns: [],
  running: false,
  originalPrompt: "",
  clarificationHistory: [],
  pendingClarification: null,
  activeTurn: null,
};

const elements = {};
const templates = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  checkServices();
  loadConversations();
});

function cacheElements() {
  [
    "serviceStatus",
    "pandaStatus",
    "taskPrompt",
    "runButton",
    "composer",
    "chatScroll",
    "chatEmpty",
    "clarificationBanner",
    "clarificationRound",
    "clarificationQuestions",
    "clarificationReset",
    "conversationList",
    "newConversationBtn",
  ].forEach((id) => {
    elements[id] = document.getElementById(id);
  });
  templates.turn = document.getElementById("turnTemplate");
  templates.result = document.getElementById("turnResultTemplate");
}

function bindEvents() {
  document.querySelectorAll("[data-scenario]").forEach((button) => {
    button.addEventListener("click", () => selectScenario(button.dataset.scenario));
  });
  elements.composer.addEventListener("submit", (submitEvent) => {
    submitEvent.preventDefault();
    runTask();
  });
  elements.runButton.addEventListener("click", runTask);
  elements.taskPrompt.addEventListener("keydown", (eventValue) => {
    if ((eventValue.ctrlKey || eventValue.metaKey) && eventValue.key === "Enter") {
      eventValue.preventDefault();
      runTask();
    }
  });
  elements.clarificationReset.addEventListener("click", resetClarification);
  elements.newConversationBtn.addEventListener("click", newConversation);
}

async function checkServices() {
  try {
    const [healthResponse, pandaResponse] = await Promise.all([
      fetch("/api/health", { headers: { Accept: "application/json" } }),
      fetch("/api/pandadata/status", { headers: { Accept: "application/json" } }),
    ]);
    if (!healthResponse.ok) throw new Error("health check failed");
    const health = await healthResponse.json();
    const panda = pandaResponse.ok ? await pandaResponse.json() : null;
    elements.serviceStatus.className = "service-status ok";
    elements.serviceStatus.lastElementChild.textContent =
      health.status === "ok" ? "服务在线" : "状态未知";
    if (panda?.configured) {
      elements.pandaStatus.textContent = panda.authenticated ? "已认证" : "已配置";
      elements.pandaStatus.classList.add("configured");
    } else {
      elements.pandaStatus.textContent = "未配置";
    }
  } catch (_error) {
    elements.serviceStatus.className = "service-status error";
    elements.serviceStatus.lastElementChild.textContent = "服务离线";
    elements.pandaStatus.textContent = "不可用";
  }
}

function selectScenario(scenario) {
  const prompt = EXAMPLE_PROMPTS[scenario];
  if (!prompt) return;
  resetClarification();
  elements.taskPrompt.value = prompt;
  elements.taskPrompt.focus();
}

async function runTask() {
  if (state.running) return;
  const inputValue = elements.taskPrompt.value.trim();
  if (!inputValue) {
    elements.taskPrompt.focus();
    return;
  }

  let turn;
  let promptToSend;

  if (state.pendingClarification && state.activeTurn) {
    turn = state.activeTurn;
    appendTurnFollowUp(turn, inputValue);
    state.clarificationHistory = [
      ...state.clarificationHistory,
      {
        questions: state.pendingClarification.questions,
        answer: inputValue,
      },
    ];
    promptToSend = state.originalPrompt;
  } else {
    resetClarification();
    state.originalPrompt = inputValue;
    turn = createTurn(inputValue);
    state.activeTurn = turn;
    promptToSend = inputValue;
  }

  elements.taskPrompt.value = "";
  setRunning(true);
  scrollToLatest();

  try {
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        prompt: promptToSend,
        clarification_history: state.clarificationHistory,
        conversation_id: state.activeConversationId,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `请求失败（HTTP ${response.status}）`);
    }

    if (payload.conversation_id) {
      state.activeConversationId = payload.conversation_id;
    }

    renderTurnResult(turn, payload);
    updateClarificationState(payload);

    if (state.activeConversationId) {
      loadConversations();
    }
  } catch (error) {
    renderTurnError(turn, error instanceof Error ? error.message : "任务执行失败");
  } finally {
    setRunning(false);
    scrollToLatest();
    elements.taskPrompt.focus();
  }
}

function setRunning(running) {
  state.running = running;
  elements.runButton.disabled = running;
  elements.runButton.querySelector(".run-label").textContent =
    running ? "执行中…" : "发送";
}

function scrollToLatest() {
  elements.chatScroll.scrollTop = elements.chatScroll.scrollHeight;
}

function resetClarification() {
  state.pendingClarification = null;
  state.clarificationHistory = [];
  elements.clarificationBanner.hidden = true;
}

function updateClarificationState(payload) {
  if (payload.aggregation?.completion_status === "needs_clarification") {
    const questions = payload.plan?.clarification_questions || [];
    state.pendingClarification = { questions };
    elements.clarificationBanner.hidden = false;
    elements.clarificationRound.textContent = `${state.clarificationHistory.length + 1}`;
    elements.clarificationQuestions.innerHTML = questions
      .map((q) => `<p>${escapeHtml(q)}</p>`)
      .join("");
  } else {
    resetClarification();
    elements.clarificationBanner.hidden = true;
  }
}

function appendTurnFollowUp(turn, text) {
  const followUp = document.createElement("div");
  followUp.className = "turn-user turn-follow-up";
  const role = document.createElement("span");
  role.className = "turn-role";
  role.textContent = "补充";
  const content = document.createElement("p");
  content.className = "turn-prompt";
  content.textContent = text;
  followUp.append(role, content);
  turn.root.querySelector(".turn-assistant").before(followUp);
}

function createTurn(prompt) {
  const node = document.importNode(templates.turn.content, true);
  const turn = {
    id: state.turns.length + 1,
    prompt,
    status: "running",
    root: node.querySelector(".turn"),
    promptEl: node.querySelector(".turn-prompt"),
    completion: node.querySelector(".turn-completion"),
    confidence: node.querySelector(".turn-confidence"),
    duration: node.querySelector(".turn-duration"),
    failure: node.querySelector(".turn-failure"),
    headline: node.querySelector(".turn-headline"),
    explanation: node.querySelector(".turn-explanation"),
    body: node.querySelector(".turn-body"),
  };
  turn.promptEl.textContent = prompt;
  turn.root.classList.add("turn-loading");
  elements.chatEmpty.hidden = true;
  elements.chatScroll.append(node);
  state.turns.push(turn);
  return turn;
}

function buildTurnDetailDom() {
  const fragment = document.importNode(templates.result.content, true);
  return {
    fragment,
    blocks: fragment.querySelector(".turn-blocks"),
    complexity: fragment.querySelector(".turn-complexity"),
    planGoal: fragment.querySelector(".turn-plan-goal"),
    selectedAgents: fragment.querySelector(".turn-selected-agents"),
    dag: fragment.querySelector(".turn-dag"),
    resultCount: fragment.querySelector(".turn-result-count"),
    technicalSummary: fragment.querySelector(".turn-technical-summary"),
    expertResults: fragment.querySelector(".turn-expert-results"),
    eventCount: fragment.querySelector(".turn-event-count"),
    timeline: fragment.querySelector(".turn-timeline"),
    technicalLog: fragment.querySelector(".turn-technical-log"),
    rawJson: fragment.querySelector(".turn-raw-json"),
    disclaimer: fragment.querySelector(".turn-disclaimer"),
  };
}

function renderTurnResult(turn, response) {
  turn.status = "done";
  turn.root.classList.remove("turn-loading");

  const plan = response.plan || {};
  const events = Array.isArray(response.events) ? response.events : [];
  const results = response.results && typeof response.results === "object"
    ? response.results
    : {};
  const plainResult = buildPlainLanguageResult(response);

  turn.completion.textContent = completionLabel(plainResult.completionStatus);
  turn.confidence.textContent = confidenceLabel(plainResult.directAnswer.confidence);
  turn.duration.textContent = `${formatNumber(response.duration_ms || 0)} ms`;
  turn.failure.hidden = !plainResult.hasFailures;
  turn.root.classList.toggle("has-failures", plainResult.hasFailures);
  turn.headline.textContent = plainResult.directAnswer.headline;
  turn.explanation.textContent = plainResult.directAnswer.explanation;

  const dom = buildTurnDetailDom();
  dom.complexity.textContent = String(plan.complexity || "—").toUpperCase();
  dom.planGoal.textContent = plan.goal || "未返回任务目标";
  dom.resultCount.textContent = `${Object.keys(results).length} RESULTS`;
  dom.eventCount.textContent = `${events.length} 项进度`;
  renderDag(dom.dag, plan.steps || []);
  renderSelectedAgents(dom.selectedAgents, plan.selected_agents || []);
  renderTimeline(dom.timeline, events);
  renderTechnicalLog(dom.technicalLog, events);
  renderExpertResults(dom.expertResults, results);
  renderContentBlocks(dom.blocks, plainResult.contentBlocks);
  renderTechnicalSummary(dom.technicalSummary, response, plainResult);
  dom.disclaimer.textContent = response.disclaimer || DISCLAIMER;
  dom.rawJson.textContent = JSON.stringify(safeForDisplay(response), null, 2);

  turn.body.replaceChildren(dom.fragment);
}

function renderTurnError(turn, message) {
  turn.status = "error";
  turn.root.classList.remove("turn-loading");
  turn.root.classList.add("has-failures");

  const modelUnavailable =
    /ARK_API_KEY|Volcano Ark|模型服务|研究分析服务/i.test(String(message));
  const userMessage = modelUnavailable
    ? "行情数据源已连接，但研究分析服务尚未配置。"
    : "本次真实研究未能完成，因此暂时无法形成结论。";

  turn.completion.textContent = "未完成";
  turn.confidence.textContent = "暂不适用";
  turn.duration.textContent = "— ms";
  turn.failure.hidden = false;
  turn.headline.textContent = userMessage;
  turn.explanation.textContent = "当前请求没有生成可以支持结论的结构化证据。";

  const dom = buildTurnDetailDom();
  dom.complexity.textContent = "—";
  dom.planGoal.textContent = "任务未能完成";
  dom.resultCount.textContent = "0 RESULTS";
  dom.eventCount.textContent = "0 项进度";
  renderContentBlocks(dom.blocks, [
    {
      id: "failures",
      type: "failure_notice",
      title: "未完成的部分",
      importance: "primary",
      data: {
        items: [
          {
            stage: "研究服务",
            message: userMessage,
            reason: modelUnavailable
              ? "缺少服务端研究模型配置。"
              : "真实研究任务未能完成。",
          },
        ],
        guidance: "系统没有切换到演示数据；服务恢复后可重新运行。",
      },
    },
  ]);
  dom.disclaimer.textContent = DISCLAIMER;
  dom.rawJson.textContent = JSON.stringify(safeForDisplay({ error: message }), null, 2);

  turn.body.replaceChildren(dom.fragment);
}

function renderDag(container, steps) {
  container.replaceChildren();
  if (!steps.length) {
    container.append(emptyState("任务需要澄清，尚未创建执行节点。"));
    return;
  }
  steps.forEach((step, index) => {
    if (index > 0) {
      const arrow = document.createElement("span");
      arrow.className = "dag-arrow";
      arrow.textContent = step.depends_on?.length ? "→" : "∥";
      container.append(arrow);
    }
    const node = document.createElement("div");
    node.className = "dag-node";
    node.style.setProperty("--agent-color", colorFor(step.agent));
    const label = document.createElement("span");
    label.textContent = `${agentLabel(step.agent)} · ${step.agent || "expert"}`;
    const detail = document.createElement("small");
    detail.textContent = step.objective || step.id;
    node.append(label, detail);
    container.append(node);
  });
}

function renderTimeline(container, events) {
  container.replaceChildren();
  if (!events.length) {
    container.append(emptyState("暂无执行事件"));
    return;
  }
  events.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = `event ${String(item.type).includes("failed") ? "failed" : ""}`;
    const dot = document.createElement("span");
    dot.className = "event-dot";
    const message = document.createElement("div");
    message.className = "event-message";
    message.textContent = translateEvent(item);
    const type = document.createElement("small");
    type.textContent = item.agent
      ? agentLabel(item.agent)
      : item.metadata?.component === "result_aggregator"
        ? "结果整理器"
        : item.type === "task_completed"
          ? "AlphaOS"
          : "研究经理";
    message.append(type);
    const time = document.createElement("time");
    time.textContent = eventTime(item, index);
    row.append(dot, message, time);
    container.append(row);
  });
}

function renderTechnicalLog(container, events) {
  container.replaceChildren();
  if (!events.length) {
    container.append(emptyState("暂无运行日志"));
    return;
  }
  events.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = `technical-event ${String(item.type).includes("failed") ? "failed" : ""}`;
    const heading = document.createElement("div");
    heading.className = "technical-event-heading";
    const type = document.createElement("code");
    type.textContent = item.type || "unknown_event";
    const time = document.createElement("time");
    time.textContent = eventTime(item, index);
    heading.append(type, time);
    const fields = document.createElement("p");
    fields.textContent = [
      item.agent ? `agent: ${item.agent}` : null,
      item.step_id ? `step: ${item.step_id}` : null,
      item.metadata?.skill_id ? `skill: ${item.metadata.skill_id}` : null,
      item.metadata?.tool ? `tool: ${item.metadata.tool}` : null,
      item.metadata?.component ? `component: ${item.metadata.component}` : null,
    ].filter(Boolean).join(" · ") || "system event";
    const original = document.createElement("small");
    original.textContent = item.message || "无原始事件消息";
    row.append(heading, fields, original);
    container.append(row);
  });
}

function renderSelectedAgents(container, selections) {
  container.replaceChildren();
  if (!selections.length) {
    container.append(emptyState("尚未选择执行专家"));
    return;
  }
  selections.forEach((selection) => {
    const row = document.createElement("div");
    row.className = "selected-agent";
    const name = document.createElement("strong");
    name.textContent = `${agentLabel(selection.agent)} · ${selection.agent}`;
    const reason = document.createElement("span");
    reason.textContent = selection.reason || "未提供选择原因";
    row.append(name, reason);
    container.append(row);
  });
}

function renderExpertResults(container, results) {
  container.replaceChildren();
  const entries = Object.entries(results);
  if (!entries.length) {
    container.append(emptyState("没有专家执行结果"));
    return;
  }
  entries.forEach(([stepId, result]) => {
    const card = document.createElement("article");
    card.className = "result-card";
    card.style.setProperty("--agent-color", colorFor(result.agent));

    const header = document.createElement("div");
    header.className = "result-card-header";
    const agent = document.createElement("div");
    agent.className = "result-agent";
    const dot = document.createElement("i");
    const name = document.createElement("strong");
    name.textContent = `${result.agent || "expert"} · ${stepId}`;
    agent.append(dot, name);
    const status = document.createElement("span");
    status.className = `result-status ${result.status || ""}`;
    status.textContent = result.status || "unknown";
    header.append(agent, status);

    const summary = document.createElement("p");
    summary.textContent = result.summary || result.error || "未返回摘要";
    const facts = document.createElement("div");
    facts.className = "result-facts";
    resultFacts(result).forEach((fact) => {
      const chip = document.createElement("span");
      chip.textContent = fact;
      facts.append(chip);
    });
    card.append(header, summary, facts);
    appendProfessionalSection(card, "evidence", result.evidence);
    appendProfessionalSection(card, "assumptions", result.assumptions);
    appendProfessionalSection(card, "risks", result.risks);
    appendProfessionalSection(card, "limitations", result.limitations);
    appendProfessionalSection(card, "recommendations", result.recommendations);
    appendProfessionalSection(card, "tool_calls", result.tool_calls);
    appendProfessionalSection(card, "data_sources", result.data_sources);
    appendProfessionalSection(card, "metadata", result.metadata);
    if (result.error) appendProfessionalSection(card, "error", result.error);
    container.append(card);
  });
}

function appendProfessionalSection(card, label, value) {
  const section = document.createElement("details");
  section.className = "professional-field";
  const summary = document.createElement("summary");
  const count = Array.isArray(value) ? ` · ${value.length}` : "";
  summary.textContent = `${label}${count}`;
  const pre = document.createElement("pre");
  const safeValue = safeForDisplay(value);
  pre.textContent =
    typeof safeValue === "string" ? safeValue : JSON.stringify(safeValue, null, 2);
  section.append(summary, pre);
  card.append(section);
}

function resultFacts(result) {
  const facts = [];
  const skills = result.metadata?.actual_skills;
  if (Array.isArray(skills)) skills.forEach((skill) => facts.push(`SKILL ${skill}`));
  const validation = result.metadata?.validation_status;
  if (validation) facts.push(validation);
  const riskLevel = result.metadata?.risk_level;
  if (riskLevel) facts.push(`RISK ${riskLevel}`);
  const firstEvidence = Array.isArray(result.evidence) ? result.evidence[0] : null;
  const data = firstEvidence?.data || firstEvidence || {};
  if (typeof data.coverage_ratio === "number") {
    facts.push(`COVERAGE ${(data.coverage_ratio * 100).toFixed(1)}%`);
  }
  if (typeof data.observation_count === "number") {
    facts.push(`${formatNumber(data.observation_count)} OBS`);
  }
  if (typeof data.period_return === "number") {
    facts.push(`RETURN ${(data.period_return * 100).toFixed(1)}%`);
  }
  return facts.slice(0, 4);
}

const BLOCK_RENDERERS = {
  finding_cards: renderFindingCards,
  metric_cards: renderMetricCards,
  comparison: renderComparison,
  risk_list: renderListBlock,
  factor_list: renderFactorList,
  action_list: renderListBlock,
  limitations: renderListBlock,
  clarification: renderClarification,
  failure_notice: renderFailureNotice,
  narrative: renderFindingCards,
  report: renderReportBlock,
  data_scope: renderDataScope,
};

function renderContentBlocks(container, blocks) {
  container.replaceChildren();
  const visible = Array.isArray(blocks)
    ? blocks.filter((block) => BLOCK_RENDERERS[block?.type])
    : [];
  visible.forEach((block) => {
    const card = document.createElement("article");
    card.className = `aggregation-block importance-${block.importance || "secondary"} type-${block.type}`;
    const heading = document.createElement("div");
    heading.className = "aggregation-block-heading";
    const title = document.createElement("h3");
    title.textContent = block.title || "结果";
    const type = document.createElement("span");
    type.textContent = blockTypeLabel(block.type);
    heading.append(title, type);
    card.append(heading);
    if (block.description) {
      const description = document.createElement("p");
      description.className = "aggregation-description";
      description.textContent = block.description;
      card.append(description);
    }
    BLOCK_RENDERERS[block.type](card, block.data || {});
    container.append(card);
  });
}

function renderFindingCards(card, data) {
  const list = document.createElement("div");
  list.className = "finding-list";
  (data.items || []).forEach((item) => {
    const entry = document.createElement("p");
    entry.textContent = typeof item === "string" ? item : item.text || item.summary || "";
    if (entry.textContent) list.append(entry);
  });
  card.append(list);
}

function renderMetricCards(card, data) {
  const grid = document.createElement("div");
  grid.className = "metric-card-grid";
  (data.metrics || []).forEach((metric) => {
    const item = document.createElement("div");
    item.className = "metric-card";
    const label = document.createElement("span");
    label.textContent = [metric.subject, metric.label].filter(Boolean).join(" · ");
    const value = document.createElement("strong");
    value.textContent = metric.display_value ?? String(metric.value ?? "—");
    const explanation = document.createElement("p");
    explanation.textContent = metric.explanation || "";
    item.append(label, value, explanation);
    grid.append(item);
  });
  card.append(grid);
}

function renderComparison(card, data) {
  const grid = document.createElement("div");
  grid.className = "comparison-grid";
  (data.entities || []).forEach((entity) => {
    const item = document.createElement("section");
    const title = document.createElement("h4");
    title.textContent = entity.name || "对比项";
    item.append(title);
    (entity.metrics || []).forEach((metric) => {
      const row = document.createElement("p");
      row.textContent = `${metric.label || metric.metric || "指标"}：${
        metric.display_value ?? metric.value ?? "—"
      }`;
      item.append(row);
    });
    grid.append(item);
  });
  card.append(grid);
}

function renderListBlock(card, data) {
  const list = document.createElement("ul");
  list.className = "aggregation-list";
  (data.items || []).forEach((item) => {
    const row = document.createElement("li");
    row.textContent = typeof item === "string" ? item : item.text || item.message || "";
    if (row.textContent) list.append(row);
  });
  card.append(list);
}

function renderFactorList(card, data) {
  const shortlist = new Set(data.shortlist || []);
  const list = document.createElement("div");
  list.className = "factor-list";
  (data.items || []).forEach((factor) => {
    const item = document.createElement("section");
    const title = document.createElement("h4");
    const name = factor.name || factor.title || "研究想法";
    title.textContent = shortlist.has(name) ? `优先验证 · ${name}` : name;
    const text = document.createElement("p");
    text.textContent =
      factor.hypothesis || factor.description || factor.rationale || "";
    item.append(title, text);
    list.append(item);
  });
  if (!(data.items || []).length && shortlist.size) {
    [...shortlist].forEach((name) => {
      const item = document.createElement("section");
      const title = document.createElement("h4");
      title.textContent = `优先验证 · ${name}`;
      item.append(title);
      list.append(item);
    });
  }
  const status = document.createElement("p");
  status.className = "aggregation-note";
  status.textContent = data.plain_status || "";
  card.append(list, status);
}

function renderClarification(card, data) {
  const question = document.createElement("p");
  question.className = "clarification-question";
  question.textContent = data.question || "请补充完成任务所需的信息。";
  const hint = document.createElement("p");
  hint.className = "aggregation-note";
  hint.textContent = "把补充信息直接输入下方对话框继续这次研究。";
  card.append(question, hint);
}

function renderFailureNotice(card, data) {
  const list = document.createElement("div");
  list.className = "failure-list";
  (data.items || []).forEach((failure) => {
    const item = document.createElement("section");
    const title = document.createElement("h4");
    title.textContent = failure.stage || failure.step_id || "未完成阶段";
    const message = document.createElement("p");
    message.textContent = [failure.message, failure.reason].filter(Boolean).join(" ");
    item.append(title, message);
    list.append(item);
  });
  const guidance = document.createElement("p");
  guidance.className = "aggregation-note";
  guidance.textContent = data.guidance || "";
  card.append(list, guidance);
}

function renderReportBlock(card, data) {
  const report = document.createElement("div");
  report.className = "report-content";
  report.innerHTML = renderSafeMarkdown(data.content || "");
  card.append(report);
}

function renderDataScope(card, data) {
  const list = document.createElement("ul");
  list.className = "aggregation-list";
  (data.sources || []).forEach((source) => {
    const item = document.createElement("li");
    const symbols = Array.isArray(source.symbols) ? source.symbols.join("、") : "";
    const dates =
      source.start_date || source.end_date
        ? `${source.start_date || "起始日期未知"} 至 ${source.end_date || "结束日期未知"}`
        : "";
    item.textContent = [source.name, symbols, dates].filter(Boolean).join(" · ");
    if (item.textContent) list.append(item);
  });
  card.append(list);
}

function completionLabel(status) {
  return {
    completed: "已完成",
    partially_completed: "部分完成",
    needs_clarification: "需要补充信息",
    failed: "未完成",
  }[status] || status;
}

function confidenceLabel(confidence) {
  return {
    high: "较高可信度",
    medium: "中等可信度",
    low: "较低可信度",
    not_applicable: "暂不适用",
  }[confidence] || confidence;
}

function blockTypeLabel(type) {
  return {
    finding_cards: "发现",
    metric_cards: "指标",
    comparison: "对比",
    risk_list: "风险",
    factor_list: "研究想法",
    action_list: "验证事项",
    limitations: "限制",
    clarification: "澄清",
    failure_notice: "未完成",
    narrative: "说明",
    report: "报告",
    data_scope: "数据范围",
  }[type] || type;
}

function renderTechnicalSummary(container, response, plainResult) {
  const rows = [
    ["duration", `${formatNumber(response.duration_ms || 0)} ms`],
    ["completion_status", plainResult.completionStatus],
    ["output_mode", plainResult.outputMode],
    ["confidence", plainResult.directAnswer.confidence],
    ["selected_agents", String(plainResult.selectedAgents.length)],
    ["has_failures", String(plainResult.hasFailures)],
  ];
  container.replaceChildren();
  rows.forEach(([term, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    container.append(dt, dd);
  });
}

function renderSafeMarkdown(value) {
  const lines = escapeHtml(String(value)).split(/\r?\n/);
  const output = [];
  let listOpen = false;
  for (const line of lines) {
    if (line.startsWith("### ")) {
      if (listOpen) output.push("</ul>");
      listOpen = false;
      output.push(`<h3>${line.slice(4)}</h3>`);
    } else if (line.startsWith("- ")) {
      if (!listOpen) output.push("<ul>");
      listOpen = true;
      output.push(`<li>${line.slice(2)}</li>`);
    } else if (!line.trim()) {
      if (listOpen) output.push("</ul>");
      listOpen = false;
    } else {
      if (listOpen) output.push("</ul>");
      listOpen = false;
      output.push(`<p>${line}</p>`);
    }
  }
  if (listOpen) output.push("</ul>");
  return output.join("");
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function eventTime(item, index) {
  if (!item.timestamp) return `+${index}`;
  const date = new Date(item.timestamp);
  if (Number.isNaN(date.getTime())) return `+${index}`;
  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function colorFor(agent) {
  return AGENT_COLORS[agent] || "#a8ffcf";
}

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function emptyState(message) {
  const element = document.createElement("div");
  element.className = "empty-state";
  element.textContent = message;
  return element;
}

/* ---------- Conversation management ---------- */

async function loadConversations() {
  try {
    const resp = await fetch("/api/conversations", {
      headers: { Accept: "application/json" },
    });
    if (!resp.ok) return;
    state.conversations = await resp.json();
    renderConversationList();
  } catch (_) {/* silently fail */}
}

function renderConversationList() {
  elements.conversationList.innerHTML = "";
  if (!state.conversations.length) {
    const empty = document.createElement("div");
    empty.className = "conversation-empty";
    empty.textContent = "新对话会在提交后自动创建";
    elements.conversationList.append(empty);
    return;
  }
  state.conversations.forEach((conv) => {
    const item = document.createElement("div");
    item.className = "conversation-item";
    if (conv.id === state.activeConversationId) item.classList.add("active");
    item.dataset.id = conv.id;

    const info = document.createElement("div");
    info.className = "conversation-item-info";

    const title = document.createElement("div");
    title.className = "conversation-item-title";
    title.textContent = conv.title;

    const meta = document.createElement("div");
    meta.className = "conversation-item-meta";
    meta.textContent = `${conv.turn_count} 轮`;

    const del = document.createElement("button");
    del.className = "conversation-item-delete";
    del.textContent = "✕";
    del.title = "删除对话";
    del.addEventListener("click", async (e) => {
      e.stopPropagation();
      await deleteConversation(conv.id);
    });

    item.addEventListener("click", () => switchConversation(conv.id));

    info.append(title, meta);
    item.append(info, del);
    elements.conversationList.append(item);
  });
}

async function newConversation() {
  if (state.running) return;
  resetClarification();
  elements.chatScroll.querySelectorAll(".turn").forEach((el) => el.remove());
  elements.chatEmpty.hidden = false;
  state.activeConversationId = null;
  state.activeTurn = null;
  state.originalPrompt = "";
  state.clarificationHistory = [];
  elements.taskPrompt.value = "";
  renderConversationList();
}

async function switchConversation(convId) {
  if (state.running) return;
  try {
    const resp = await fetch(`/api/conversations/${convId}`, {
      headers: { Accept: "application/json" },
    });
    if (!resp.ok) return;
    const conv = await resp.json();

    resetClarification();
    state.activeConversationId = conv.id;
    state.activeTurn = null;
    state.originalPrompt = "";

    elements.chatScroll.querySelectorAll(".turn").forEach((el) => el.remove());
    elements.chatEmpty.hidden = true;

    (conv.turns || []).forEach((data) => restoreTurnFromHistory(data));

    renderConversationList();
    scrollToLatest();
  } catch (_) {/* silently fail */}
}

async function deleteConversation(convId) {
  if (state.activeConversationId === convId) {
    await newConversation();
  }
  try {
    await fetch(`/api/conversations/${convId}`, { method: "DELETE" });
  } catch (_) {/* silently fail */}
  state.conversations = state.conversations.filter((c) => c.id !== convId);
  renderConversationList();
}

function restoreTurnFromHistory(data) {
  const turn = createTurn(data.prompt);
  turn.status = "done";
  turn.root.classList.remove("turn-loading");

  const plainResult = buildPlainLanguageResult(data);

  turn.completion.textContent = completionLabel(plainResult.completionStatus);
  turn.confidence.textContent = confidenceLabel(plainResult.directAnswer.confidence);
  turn.duration.textContent = `${formatNumber(data.duration_ms || 0)} ms`;
  turn.failure.hidden = !plainResult.hasFailures;
  turn.root.classList.toggle("has-failures", plainResult.hasFailures);
  turn.headline.textContent = plainResult.directAnswer.headline;
  turn.explanation.textContent = plainResult.directAnswer.explanation;

  const dom = buildTurnDetailDom();
  const plan = data.plan || {};
  const events = Array.isArray(data.events) ? data.events : [];
  const results = data.results && typeof data.results === "object" ? data.results : {};

  dom.complexity.textContent = String(plan.complexity || "—").toUpperCase();
  dom.planGoal.textContent = plan.goal || "未返回任务目标";
  dom.resultCount.textContent = `${Object.keys(results).length} RESULTS`;
  dom.eventCount.textContent = `${events.length} 项进度`;
  renderDag(dom.dag, plan.steps || []);
  renderSelectedAgents(dom.selectedAgents, plan.selected_agents || []);
  renderTimeline(dom.timeline, events);
  renderTechnicalLog(dom.technicalLog, events);
  renderExpertResults(dom.expertResults, results);
  renderContentBlocks(dom.blocks, plainResult.contentBlocks);
  renderTechnicalSummary(dom.technicalSummary, data, plainResult);
  dom.disclaimer.textContent = data.disclaimer || DISCLAIMER;
  dom.rawJson.textContent = JSON.stringify(safeForDisplay(data), null, 2);

  turn.body.replaceChildren(dom.fragment);
}
