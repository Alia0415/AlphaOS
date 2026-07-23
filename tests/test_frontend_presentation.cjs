"use strict";

const assert = require("node:assert/strict");
require("../frontend/presentation/status-labels.js");
const { translateEvent } = require("../frontend/presentation/event-labels.js");
const {
  buildPlainLanguageResult,
  safeForDisplay,
} = require("../frontend/presentation/build-plain-language-result.js");

function responseWith(result, selectedAgents = [{ agent: result.agent, reason: "任务需要" }]) {
  return {
    plan: {
      goal: "测试研究任务",
      selected_agents: selectedAgents,
      steps: [{ id: result.task_id, agent: result.agent }],
      needs_clarification: false,
    },
    events: [],
    results: { [result.task_id]: result },
    final_answer: "测试结果",
    duration_ms: 12,
    disclaimer: "仅用于研究，不构成投资建议。",
  };
}

function completedQuant(overrides = {}) {
  return {
    task_id: "quant_1",
    agent: "quant",
    status: "completed",
    summary: "R020 已完成计算。",
    evidence: [
      {
        validation_status: "computed_not_validated",
        data: {
          factor_id: "R020",
          observation_count: 726,
          coverage_ratio: 0.9421,
        },
      },
    ],
    assumptions: [],
    risks: ["市场状态切换可能使结果失效。"],
    limitations: ["尚未计算 IC。"],
    recommendations: [],
    tool_calls: [],
    data_sources: [],
    metadata: {
      validation_status: "computed_not_validated",
      actual_skills: ["r020_volume_expansion"],
    },
    ...overrides,
  };
}

{
  const plain = buildPlainLanguageResult(responseWith(completedQuant()));
  assert.equal(plain.evidenceLevel.label, "已完成计算，尚未验证有效性");
  assert.ok(plain.keyPoints.includes("94.2% 的数据可以正常参与计算。"));
  assert.match(plain.headline, /只能作为研究线索/);
  assert.equal(plain.progress[1].completed, true);
  assert.equal(plain.progress[2].completed, false);
  assert.deepEqual(plain.selectedAgents.map((item) => item.agent), ["quant"]);
  assert.ok(!JSON.stringify(plain).includes("风险审查员开始"));
  assert.ok(plain.nextSteps.some((item) => item.includes("未来 1 日和 5 日")));
  assert.ok(!plain.nextSteps.some((item) => /买入|卖出|建仓/.test(item)));
}

{
  const failed = completedQuant({
    status: "failed",
    summary: "专家步骤未成功执行。",
    evidence: [],
    limitations: ["数据获取失败。"],
    metadata: {},
    error: "Data unavailable.",
  });
  const plain = buildPlainLanguageResult(responseWith(failed));
  assert.equal(plain.hasFailures, true);
  assert.equal(plain.evidenceLevel.status, "insufficient_data");
  assert.match(plain.headline, /没有成功获得足够数据/);
  assert.ok(plain.missingEvidence.some((item) => item.includes("未能成功完成")));
}

{
  const blocked = completedQuant({
    task_id: "risk_1",
    agent: "risk",
    status: "blocked",
    summary: "依赖失败。",
    evidence: [],
    limitations: [],
    metadata: {},
    error: "Required dependency failed.",
  });
  const plain = buildPlainLanguageResult(responseWith(blocked));
  assert.equal(plain.hasFailures, true);
  assert.ok(plain.missingEvidence.some((item) => item.includes("被阻断")));
  assert.equal(plain.progress[1].completed, false);
}

{
  const event = {
    type: "tool_called",
    agent: "quant",
    step_id: "quant_1",
    message: "quant 调用了 pandadata_market_data。",
    metadata: { tool: "pandadata_market_data" },
  };
  assert.equal(translateEvent(event), "正在获取指定区间的历史市场数据");
  assert.equal(event.type, "tool_called");
  assert.equal(event.message, "quant 调用了 pandadata_market_data。");
}

{
  const safe = safeForDisplay({
    validation_status: "computed_not_validated",
    api_key: "secret",
    runtime_path: "C:\\private\\runtime",
  });
  assert.equal(safe.validation_status, "computed_not_validated");
  assert.equal(safe.api_key, "[敏感或内部信息已隐藏]");
  assert.equal(safe.runtime_path, "[敏感或内部信息已隐藏]");
}

console.log("frontend presentation tests passed");
