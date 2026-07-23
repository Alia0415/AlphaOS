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

const SCENARIOS = {
  factor: {
    prompt: "请根据 OHLCV 数据生成 5 个可验证的量价因子想法，并 shortlist 2 个。",
    response: {
      plan: {
        goal: "生成可验证的 OHLCV 量价因子假设",
        intent: "factor_ideation",
        complexity: "low",
        selected_agents: [{ agent: "quant", reason: "需要量化因子研究能力" }],
        steps: [
          {
            id: "quant_1",
            agent: "quant",
            objective: "生成并筛选结构化因子假设",
            inputs: { fields: ["open", "high", "low", "close", "volume"] },
            depends_on: [],
            expected_output: "待验证 FactorIdea 列表",
          },
        ],
        needs_clarification: false,
        clarification_question: null,
      },
      events: [
        event("plan_created", null, null, "Manager Agent 已创建并验证动态任务图。", 0),
        event("step_started", "quant_1", "quant", "Quant Agent 开始执行任务。", 36),
        event("skill_plan_created", "quant_1", "quant", "专家已创建内部 Skill Plan。", 118),
        event("skill_started", "quant_1", "quant", "factor_idea_generation 开始执行。", 164),
        event("skill_completed", "quant_1", "quant", "factor_idea_generation 执行完成。", 682),
        event("step_completed", "quant_1", "quant", "quant 步骤执行完成。", 704),
        event("synthesis_started", null, null, "Result Aggregator 开始整理实际执行结果。", 722),
        event("task_completed", null, null, "AlphaOS 任务处理完成。", 861),
      ],
      results: {
        quant_1: {
          task_id: "quant_1",
          agent: "quant",
          status: "completed",
          summary: "Quant Agent 完成 1/1 个 Skill 步骤，生成 5 个待验证假设并筛选 2 个。",
          evidence: [
            {
              type: "skill_result",
              skill_id: "factor_idea_generation",
              validation_status: "unverified",
              data: {
                shortlist: ["成交量异常后的价格延续", "量价背离反转"],
                validation_status: "unverified",
              },
            },
          ],
          assumptions: ["使用日频 OHLCV 字段。"],
          risks: ["候选尚未完成实证有效性验证。"],
          limitations: ["尚未计算 IC。", "尚未运行回测。"],
          metadata: {
            actual_skills: ["factor_idea_generation"],
            validation_status: "unverified",
          },
        },
      },
      final_answer:
        "### 研究产出\nQuant Agent 动态选择了 Factor Idea Generation，生成 5 个待验证量价假设，并优先保留“成交量异常后的价格延续”和“量价背离反转”。\n\n### 证据边界\n这些内容只是研究假设，尚未计算 IC，也没有运行回测或形成交易信号。下一步应使用独立样本验证稳定性，并检查不同市场状态下的失效风险。",
      duration_ms: 861,
      disclaimer: DISCLAIMER,
    },
  },
  "r020-risk": {
    prompt:
      "计算 000001.SZ、000002.SZ 和 600519.SH 在 2024 年的 R020 成交量放大因子，并审查主要失效风险。",
    response: {
      plan: {
        goal: "计算三只股票的 R020 因子并审查失效风险",
        intent: "factor_computation_and_risk_review",
        complexity: "medium",
        selected_agents: [
          { agent: "quant", reason: "需要执行真实因子公式" },
          { agent: "risk", reason: "用户明确要求失效风险审查" },
        ],
        steps: [
          {
            id: "quant_1",
            agent: "quant",
            objective: "基于 2024 年 OHLCV 计算 R020",
            inputs: {
              symbols: ["000001.SZ", "000002.SZ", "600519.SH"],
              start_date: "20240101",
              end_date: "20241231",
            },
            depends_on: [],
            expected_output: "结构化 R020 计算结果",
          },
          {
            id: "risk_1",
            agent: "risk",
            objective: "审查 R020 的主要失效风险",
            inputs: {},
            depends_on: ["quant_1"],
            expected_output: "基于上游证据的风险审查",
          },
        ],
        needs_clarification: false,
        clarification_question: null,
      },
      events: [
        event("plan_created", null, null, "Manager Agent 已创建并验证动态任务图。", 0),
        event("step_started", "quant_1", "quant", "Quant Agent 开始执行任务。", 42),
        event("skill_plan_created", "quant_1", "quant", "专家已创建内部 Skill Plan。", 131),
        event("skill_started", "quant_1", "quant", "r020_volume_expansion 开始执行。", 186),
        event("tool_called", "quant_1", "quant", "quant 调用了 pandadata_market_data。", 604),
        event("skill_completed", "quant_1", "quant", "r020_volume_expansion 执行完成。", 810),
        event("step_completed", "quant_1", "quant", "quant 步骤执行完成。", 837),
        event("step_started", "risk_1", "risk", "Risk Agent 开始执行任务。", 851),
        event("step_completed", "risk_1", "risk", "risk 步骤执行完成。", 1124),
        event("synthesis_started", null, null, "Result Aggregator 开始整理实际执行结果。", 1140),
        event("task_completed", null, null, "AlphaOS 任务处理完成。", 1284),
      ],
      results: {
        quant_1: {
          task_id: "quant_1",
          agent: "quant",
          status: "completed",
          summary: "R020 已完成 726 个输入观测的公式计算，非空覆盖率 94.21%。",
          evidence: [
            {
              type: "skill_result",
              skill_id: "r020_volume_expansion",
              validation_status: "computed_not_validated",
              data: {
                factor_id: "R020",
                observation_count: 726,
                non_null_count: 684,
                coverage_ratio: 0.9421,
                latest_values_by_symbol: [
                  { symbol: "000001.SZ", value: 0.38 },
                  { symbol: "000002.SZ", value: -0.17 },
                  { symbol: "600519.SH", value: 0.62 },
                ],
              },
            },
          ],
          assumptions: ["OHLCV 字段口径在区间内一致。"],
          risks: ["因子计算结果尚未完成有效性验证。"],
          limitations: ["未计算 IC、回测收益或交易绩效。"],
          metadata: {
            actual_skills: ["r020_volume_expansion"],
            validation_status: "computed_not_validated",
          },
        },
        risk_1: {
          task_id: "risk_1",
          agent: "risk",
          status: "completed",
          summary: "风险等级为 medium；主要关注滚动窗口、市场状态切换与流动性口径变化。",
          evidence: [
            {
              source_step: "quant_1",
              source_agent: "quant",
              validation_status: "computed_not_validated",
            },
          ],
          assumptions: ["历史量价关系可延续到未来市场状态。"],
          risks: [
            "成交量口径变化可能导致横向不可比。",
            "市场状态切换可能使历史关系失效。",
            "当前仅完成公式计算，不能推导预测能力。",
          ],
          limitations: ["缺少 IC、样本外和回测有效性证据。"],
          metadata: { mode: "dependency", risk_level: "medium" },
        },
      },
      final_answer:
        "### 执行结论\nManager 选择了 Quant → Risk 两步任务图。Quant 实际调用 R020 Skill，对 3 个标的的 726 个示例观测完成计算，非空覆盖率为 94.21%；随后 Risk Agent 基于 Quant 的结构化结果进行审查。\n\n### 主要风险\n- R020 当前状态为 computed_not_validated，仅证明公式已执行，不代表具备预测能力。\n- 滚动窗口预热会产生空值，成交量口径变化会影响跨期与跨标的可比性。\n- 尚缺少 IC、样本外、市场状态分层和交易成本验证。\n\n演示数据中的最新因子值仅用于展示结果结构，不应被解释为买卖信号。",
      duration_ms: 1284,
      disclaimer: DISCLAIMER,
    },
  },
  "research-report": {
    prompt: "分析 000001.SZ 在 2024 年的价格表现，并生成一份简洁研究报告。",
    response: {
      plan: {
        goal: "分析 000001.SZ 的年度表现并生成研究报告",
        intent: "market_research_and_report",
        complexity: "medium",
        selected_agents: [
          { agent: "research", reason: "需要市场数据分析" },
          { agent: "report", reason: "用户明确要求研究报告" },
        ],
        steps: [
          {
            id: "research_1",
            agent: "research",
            objective: "计算 2024 年价格与成交量指标",
            inputs: {
              symbols: ["000001.SZ"],
              start_date: "20240101",
              end_date: "20241231",
            },
            depends_on: [],
            expected_output: "结构化市场指标",
          },
          {
            id: "report_1",
            agent: "report",
            objective: "整合上游结果生成研究报告",
            inputs: { format: "brief" },
            depends_on: ["research_1"],
            expected_output: "可追溯研究报告",
          },
        ],
        needs_clarification: false,
        clarification_question: null,
      },
      events: [
        event("plan_created", null, null, "Manager Agent 已创建并验证动态任务图。", 0),
        event("step_started", "research_1", "research", "Research Agent 开始执行任务。", 31),
        event("tool_called", "research_1", "research", "research 调用了 pandadata_market_data。", 412),
        event("step_completed", "research_1", "research", "research 步骤执行完成。", 608),
        event("step_started", "report_1", "report", "Report Agent 开始执行任务。", 621),
        event("step_completed", "report_1", "report", "report 步骤执行完成。", 879),
        event("synthesis_started", null, null, "Result Aggregator 开始整理实际执行结果。", 895),
        event("task_completed", null, null, "AlphaOS 任务处理完成。", 1023),
      ],
      results: {
        research_1: {
          task_id: "research_1",
          agent: "research",
          status: "completed",
          summary: "完成 000001.SZ 年度价格与成交量指标计算。",
          evidence: [
            {
              type: "market_metrics",
              symbol: "000001.SZ",
              observation_count: 242,
              period_return: -0.087,
              maximum_drawdown: -0.223,
              daily_volatility: 0.018,
            },
          ],
          assumptions: ["收盘价和成交量口径在区间内一致。"],
          risks: ["历史表现不能推导未来收益。"],
          limitations: ["不包含公司基本面与估值信息。"],
          metadata: { calculation_engine: "python" },
        },
        report_1: {
          task_id: "report_1",
          agent: "report",
          status: "completed",
          summary: "已整合 Research Agent 的结构化证据生成简洁报告。",
          evidence: [{ source_step: "research_1", source_agent: "research" }],
          assumptions: [],
          risks: ["历史样本的外推存在不确定性。"],
          limitations: ["报告只整合已声明的上游结果。"],
          metadata: {
            execution_path: ["research_1:research", "report_1:report"],
          },
        },
      },
      final_answer:
        "### 核心发现\n示例数据中，000001.SZ 在 2024 年共有 242 个日频观测，区间收益率为 -8.70%，最大回撤为 -22.30%，日波动率约 1.80%。\n\n### 解读边界\n报告由 Research → Report 的实际路径生成，只整合结构化上游证据。当前未包含基本面、估值或未来事件信息，历史表现不能推导未来收益。",
      duration_ms: 1023,
      disclaimer: DISCLAIMER,
    },
  },
};

const state = {
  mode: "demo",
  scenario: "r020-risk",
  running: false,
  view: "plain",
};

const elements = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  checkServices();
  renderResponse(SCENARIOS[state.scenario].response, "demo");
});

function cacheElements() {
  [
    "serviceStatus",
    "pandaStatus",
    "taskPrompt",
    "runButton",
    "modeNote",
    "resultsSection",
    "resultMode",
    "durationLabel",
    "complexityBadge",
    "planGoal",
    "dag",
    "timeline",
    "eventCount",
    "plainTechnicalLog",
    "technicalEventLog",
    "expertResults",
    "resultCount",
    "finalAnswer",
    "disclaimer",
    "rawJson",
    "plainView",
    "professionalView",
    "plainHeadline",
    "plainExplanation",
    "plainSummary",
    "completionStatus",
    "confidenceBadge",
    "failureFlag",
    "contentBlocks",
    "selectedAgents",
    "technicalSummary",
  ].forEach((id) => {
    elements[id] = document.getElementById(id);
  });
}

function bindEvents() {
  document.querySelectorAll(".mode-button").forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  });
  document.querySelectorAll("[data-scenario]").forEach((button) => {
    button.addEventListener("click", () => selectScenario(button.dataset.scenario));
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  elements.runButton.addEventListener("click", runTask);
  elements.taskPrompt.addEventListener("keydown", (eventValue) => {
    if ((eventValue.ctrlKey || eventValue.metaKey) && eventValue.key === "Enter") {
      runTask();
    }
  });
}

function setView(view) {
  state.view = view === "professional" ? "professional" : "plain";
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === state.view;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  elements.plainView.hidden = state.view !== "plain";
  elements.professionalView.hidden = state.view !== "professional";
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
      elements.pandaStatus.textContent = "未配置 · Demo 可用";
    }
  } catch (_error) {
    elements.serviceStatus.className = "service-status error";
    elements.serviceStatus.lastElementChild.textContent = "服务离线";
    elements.pandaStatus.textContent = "不可用";
  }
}

function setMode(mode) {
  state.mode = mode === "live" ? "live" : "demo";
  elements.taskPrompt.value =
    state.mode === "live" ? "" : SCENARIOS[state.scenario].prompt;
  document.querySelectorAll(".mode-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === state.mode);
  });
  elements.modeNote.textContent =
    state.mode === "demo"
      ? "演示示例使用明确标注的本地数据，不会发起真实研究。"
      : "真实研究由 AlphaOS 服务端统一调用模型和数据源，用户无需填写任何 API Key。";
}

function selectScenario(scenario) {
  const selected = SCENARIOS[scenario];
  if (!selected) return;
  state.scenario = scenario;
  elements.taskPrompt.value = selected.prompt;
  if (state.mode === "demo") renderResponse(selected.response, "demo");
}

async function runTask() {
  if (state.running) return;
  const prompt = elements.taskPrompt.value.trim();
  if (!prompt) {
    elements.taskPrompt.focus();
    return;
  }

  setRunning(true);
  try {
    if (state.mode === "demo") {
      await wait(520);
      const selected = findScenario(prompt);
      renderResponse(selected.response, "demo");
    } else {
      const response = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || `请求失败（HTTP ${response.status}）`);
      }
      renderResponse(payload, "live");
    }
    elements.resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    renderError(error instanceof Error ? error.message : "任务执行失败");
  } finally {
    setRunning(false);
  }
}

function findScenario(prompt) {
  const exact = Object.values(SCENARIOS).find((item) => item.prompt === prompt);
  return exact || SCENARIOS[state.scenario] || SCENARIOS["r020-risk"];
}

function setRunning(running) {
  state.running = running;
  elements.runButton.disabled = running;
  elements.runButton.querySelector(".run-label").textContent =
    running ? "执行中…" : "运行任务";
  elements.resultsSection.classList.toggle("loading", running);
}

function renderResponse(response, mode) {
  const plan = response.plan || {};
  const events = Array.isArray(response.events) ? response.events : [];
  const results = response.results && typeof response.results === "object"
    ? response.results
    : {};
  const plainResult = buildPlainLanguageResult(response);

  elements.resultMode.textContent =
    mode === "live" ? "真实研究 · LIVE" : "演示数据 · DEMO";
  elements.durationLabel.textContent = `${formatNumber(response.duration_ms || 0)} ms`;
  elements.complexityBadge.textContent = String(plan.complexity || "—").toUpperCase();
  elements.planGoal.textContent = plan.goal || "未返回任务目标";
  elements.eventCount.textContent = `${events.length} 项进度`;
  elements.resultCount.textContent = `${Object.keys(results).length} RESULTS`;
  renderDag(plan.steps || []);
  renderSelectedAgents(plan.selected_agents || []);
  renderTimeline(events);
  renderTechnicalLog(events, elements.plainTechnicalLog);
  renderTechnicalLog(events, elements.technicalEventLog);
  renderExpertResults(results);
  renderPlainResult(plainResult);
  renderTechnicalSummary(response, plainResult);
  elements.finalAnswer.innerHTML = renderSafeMarkdown(
    `${plainResult.directAnswer.headline}\n\n${plainResult.directAnswer.explanation}`
  );
  elements.disclaimer.textContent = response.disclaimer || DISCLAIMER;
  elements.rawJson.textContent = JSON.stringify(safeForDisplay(response), null, 2);
  setView(state.view);
}

function renderDag(steps) {
  elements.dag.replaceChildren();
  if (!steps.length) {
    elements.dag.append(emptyState("任务需要澄清，尚未创建执行节点。"));
    return;
  }
  steps.forEach((step, index) => {
    if (index > 0) {
      const arrow = document.createElement("span");
      arrow.className = "dag-arrow";
      arrow.textContent = step.depends_on?.length ? "→" : "∥";
      elements.dag.append(arrow);
    }
    const node = document.createElement("div");
    node.className = "dag-node";
    node.style.setProperty("--agent-color", colorFor(step.agent));
    const label = document.createElement("span");
    label.textContent = `${agentLabel(step.agent)} · ${step.agent || "expert"}`;
    const detail = document.createElement("small");
    detail.textContent = step.objective || step.id;
    node.append(label, detail);
    elements.dag.append(node);
  });
}

function renderTimeline(events) {
  elements.timeline.replaceChildren();
  if (!events.length) {
    elements.timeline.append(emptyState("暂无执行事件"));
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
    elements.timeline.append(row);
  });
}

function renderTechnicalLog(events, container) {
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

function renderSelectedAgents(selections) {
  elements.selectedAgents.replaceChildren();
  if (!selections.length) {
    elements.selectedAgents.append(emptyState("尚未选择执行专家"));
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
    elements.selectedAgents.append(row);
  });
}

function renderExpertResults(results) {
  elements.expertResults.replaceChildren();
  const entries = Object.entries(results);
  if (!entries.length) {
    elements.expertResults.append(emptyState("没有专家执行结果"));
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
    elements.expertResults.append(card);
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

function renderPlainResult(result) {
  elements.plainHeadline.textContent = result.directAnswer.headline;
  elements.plainExplanation.textContent = result.directAnswer.explanation;
  elements.completionStatus.textContent = completionLabel(result.completionStatus);
  elements.confidenceBadge.textContent = confidenceLabel(
    result.directAnswer.confidence
  );
  elements.plainSummary.classList.toggle("has-failures", result.hasFailures);
  elements.failureFlag.hidden = !result.hasFailures;
  renderContentBlocks(result.contentBlocks);
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

function renderContentBlocks(blocks) {
  elements.contentBlocks.replaceChildren();
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
    elements.contentBlocks.append(card);
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
  card.append(question);
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

function renderTechnicalSummary(response, plainResult) {
  const rows = [
    ["duration", `${formatNumber(response.duration_ms || 0)} ms`],
    ["completion_status", plainResult.completionStatus],
    ["output_mode", plainResult.outputMode],
    ["confidence", plainResult.directAnswer.confidence],
    ["selected_agents", String(plainResult.selectedAgents.length)],
    ["has_failures", String(plainResult.hasFailures)],
  ];
  elements.technicalSummary.replaceChildren();
  rows.forEach(([term, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    elements.technicalSummary.append(dt, dd);
  });
}

function renderError(message) {
  const modelUnavailable =
    /ARK_API_KEY|Volcano Ark|模型服务|研究分析服务/i.test(String(message));
  const userMessage = modelUnavailable
    ? "行情数据源已连接，但研究分析服务尚未配置。"
    : "本次真实研究未能完成，因此暂时无法形成结论。";
  elements.resultMode.textContent = "ERROR";
  elements.durationLabel.textContent = "— ms";
  elements.planGoal.textContent = "任务未能完成";
  elements.dag.replaceChildren();
  elements.timeline.replaceChildren();
  elements.plainTechnicalLog.replaceChildren();
  elements.technicalEventLog.replaceChildren();
  elements.expertResults.replaceChildren();
  elements.selectedAgents.replaceChildren();
  const banner = document.createElement("div");
  banner.className = "error-banner";
  banner.textContent = `${userMessage} 系统没有切换或回退到演示数据。`;
  elements.expertResults.append(banner);
  elements.plainHeadline.textContent = userMessage;
  elements.plainExplanation.textContent =
    "当前请求没有生成可以支持结论的结构化证据。";
  elements.completionStatus.textContent = "未完成";
  elements.confidenceBadge.textContent = "暂不适用";
  elements.plainSummary.classList.add("has-failures");
  elements.failureFlag.hidden = false;
  renderContentBlocks([
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
  elements.finalAnswer.textContent = modelUnavailable
    ? "真实行情数据已经接通，但研究分析尚未开始。"
    : "真实研究服务暂不可用，未生成研究结论。";
  elements.disclaimer.textContent = DISCLAIMER;
  elements.rawJson.textContent = JSON.stringify(safeForDisplay({ error: message }), null, 2);
  setView("plain");
  elements.resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
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

function event(type, stepId, agent, message, offsetMs) {
  const metadata = {};
  if (type === "synthesis_started") metadata.component = "result_aggregator";
  if (type === "tool_called") {
    const tool = String(message).match(/调用了\s+([A-Za-z0-9_-]+)/)?.[1];
    if (tool) metadata.tool = tool;
  }
  if (String(type).startsWith("skill_")) {
    const skill = String(message).match(/^([A-Za-z0-9_-]+)\s/)?.[1];
    if (skill && skill !== "专家已创建内部") metadata.skill_id = skill;
  }
  return {
    type,
    step_id: stepId,
    agent,
    timestamp: new Date(Date.UTC(2026, 6, 23, 8, 0, 0, offsetMs)).toISOString(),
    message,
    metadata,
  };
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

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
