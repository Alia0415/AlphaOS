"use strict";

const assert = require("node:assert/strict");
require("../frontend/presentation/status-labels.js");
const { translateEvent } = require("../frontend/presentation/event-labels.js");
const {
  buildPlainLanguageResult,
  safeForDisplay,
} = require("../frontend/presentation/build-plain-language-result.js");

function responseWithAggregation(overrides = {}) {
  return {
    plan: {
      goal: "测试研究任务",
      selected_agents: [{ agent: "quant", reason: "任务需要" }],
      steps: [{ id: "quant_1", agent: "quant" }],
      needs_clarification: false,
    },
    results: {},
    aggregation: {
      user_goal: "测试研究任务",
      completion_status: "completed",
      output_mode: "data_analysis",
      direct_answer: {
        headline: "已完成所需的数据计算",
        explanation: "计算完成，但尚未证明方法能够稳定有效。",
        confidence: "low",
        stance: "insufficient_evidence",
      },
      content_blocks: [
        {
          id: "metrics",
          type: "metric_cards",
          title: "实际计算结果",
          importance: "primary",
          source_steps: ["quant_1"],
          data: {
            metrics: [
              {
                metric: "coverage_ratio",
                label: "可正常计算的数据占比",
                value: 0.9421,
                display_value: "94.21%",
                explanation: "表示有多少数据能够正常参与计算。",
              },
            ],
          },
        },
      ],
      execution_summary: {
        selected_agents: ["quant"],
        completed_steps: ["quant_1"],
        failed_steps: [],
        blocked_steps: [],
        analysis_path: [],
      },
      technical_evidence: { source_results: {} },
      disclaimer: "仅用于研究，不构成投资建议。",
      ...overrides,
    },
  };
}

{
  const plain = buildPlainLanguageResult(responseWithAggregation());
  assert.equal(plain.directAnswer.headline, "已完成所需的数据计算");
  assert.equal(plain.completionStatus, "completed");
  assert.equal(plain.outputMode, "data_analysis");
  assert.equal(plain.contentBlocks.length, 1);
  assert.equal(plain.contentBlocks[0].type, "metric_cards");
  assert.deepEqual(plain.selectedAgents, ["quant"]);
  assert.equal(plain.hasFailures, false);
}

{
  const response = responseWithAggregation({
    completion_status: "partially_completed",
    content_blocks: [
      {
        id: "findings",
        type: "narrative",
        title: "已完成的分析",
        importance: "primary",
        source_steps: ["macro_1"],
        data: { items: [{ text: "宏观分析完成。" }] },
      },
      {
        id: "empty-risk",
        type: "risk_list",
        title: "风险",
        importance: "secondary",
        source_steps: [],
        data: { items: [] },
      },
    ],
  });
  const plain = buildPlainLanguageResult(response);
  assert.equal(plain.hasFailures, true);
  assert.deepEqual(plain.contentBlocks.map((block) => block.type), ["narrative"]);
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
