(function initPlainLanguageAdapter(root) {
  "use strict";

  const SENSITIVE_KEY_PATTERN =
    /(api.?key|password|secret|token|prompt|skill.?md|stack|traceback|runtime.?path|local.?path|file.?path|directory)/i;
  const BULK_DATA_KEY_PATTERN =
    /^(raw_?data|market_?data|records|rows|ohlcv|prices|full_?data)$/i;

  function buildPlainLanguageResult(response) {
    const source = response && typeof response === "object" ? response : {};
    if (source.aggregation && typeof source.aggregation === "object") {
      return normalizeAggregation(source.aggregation);
    }
    return legacyAggregation(source);
  }

  function normalizeAggregation(value) {
    const direct = value.direct_answer && typeof value.direct_answer === "object"
      ? value.direct_answer
      : {};
    const contentBlocks = Array.isArray(value.content_blocks)
      ? value.content_blocks.filter(hasBlockContent)
      : [];
    return {
      userGoal: String(value.user_goal || ""),
      completionStatus: String(value.completion_status || "failed"),
      outputMode: String(value.output_mode || "failure"),
      directAnswer: {
        headline: String(direct.headline || "任务没有返回直接答案"),
        explanation: String(direct.explanation || ""),
        confidence: String(direct.confidence || "not_applicable"),
        stance: String(direct.stance || "not_applicable"),
      },
      contentBlocks,
      executionSummary: value.execution_summary || null,
      technicalEvidence: value.technical_evidence || null,
      disclaimer: String(value.disclaimer || ""),
      // Compatibility aliases for older embedding code.
      headline: String(direct.headline || "任务没有返回直接答案"),
      hasFailures: ["partially_completed", "failed"].includes(value.completion_status),
      selectedAgents: Array.isArray(value.execution_summary?.selected_agents)
        ? value.execution_summary.selected_agents
        : [],
    };
  }

  function legacyAggregation(source) {
    const results = Object.entries(
      source.results && typeof source.results === "object" ? source.results : {}
    );
    const completed = results.filter(([, result]) => result?.status === "completed");
    const failed = results.filter(([, result]) =>
      ["failed", "blocked"].includes(result?.status)
    );
    const needsClarification = Boolean(source.plan?.needs_clarification);
    const completionStatus = needsClarification
      ? "needs_clarification"
      : completed.length && failed.length
        ? "partially_completed"
        : completed.length
          ? "completed"
          : "failed";
    const contentBlocks = [];
    const summaries = completed
      .filter(([, result]) => result?.summary)
      .map(([sourceStep, result]) => ({ source_step: sourceStep, text: result.summary }));
    const risks = completed.flatMap(([sourceStep, result]) =>
      (result.risks || []).map((text) => ({ source_step: sourceStep, text }))
    );
    const limitations = results.flatMap(([sourceStep, result]) =>
      (result.limitations || []).map((text) => ({ source_step: sourceStep, text }))
    );
    if (needsClarification) {
      contentBlocks.push({
        id: "clarification",
        type: "clarification",
        title: "需要补充的信息",
        importance: "primary",
        source_steps: [],
        data: { question: source.plan?.clarification_question || source.final_answer },
      });
    } else {
      if (summaries.length) {
        contentBlocks.push({
          id: "findings",
          type: summaries.length > 1 ? "finding_cards" : "narrative",
          title: "已完成的分析",
          importance: "primary",
          source_steps: summaries.map((item) => item.source_step),
          data: { items: summaries },
        });
      }
      if (risks.length) {
        contentBlocks.push({
          id: "risks",
          type: "risk_list",
          title: "实际识别的风险",
          importance: "secondary",
          source_steps: risks.map((item) => item.source_step),
          data: { items: risks },
        });
      }
      if (limitations.length) {
        contentBlocks.push({
          id: "limitations",
          type: "limitations",
          title: "目前不能确定的部分",
          importance: "supporting",
          source_steps: limitations.map((item) => item.source_step),
          data: { items: limitations },
        });
      }
    }
    const explanation =
      source.final_answer ||
      (needsClarification
        ? source.plan?.clarification_question
        : completed[0]?.[1]?.summary) ||
      "当前没有可以可靠展示的结果。";
    return normalizeAggregation({
      user_goal: source.plan?.goal || "",
      completion_status: completionStatus,
      output_mode: needsClarification
        ? "clarification"
        : completionStatus === "failed"
          ? "failure"
          : "direct_answer",
      direct_answer: {
        headline:
          completionStatus === "failed"
            ? "本次任务没有成功完成"
            : needsClarification
              ? "需要先补充信息"
              : "已完成所需分析",
        explanation,
        confidence: completionStatus === "completed" ? "medium" : "not_applicable",
        stance: completionStatus === "completed" ? "neutral" : "insufficient_evidence",
      },
      content_blocks: contentBlocks,
      execution_summary: {
        selected_agents: (source.plan?.selected_agents || []).map((item) => item.agent),
      },
      technical_evidence: { source_results: source.results || {} },
      disclaimer: source.disclaimer || "",
    });
  }

  function hasBlockContent(block) {
    if (!block || typeof block !== "object" || !block.data) return false;
    return Object.values(block.data).some(
      (value) =>
        value !== null &&
        value !== "" &&
        !(Array.isArray(value) && value.length === 0) &&
        !(typeof value === "object" &&
          !Array.isArray(value) &&
          Object.keys(value).length === 0)
    );
  }

  function safeForDisplay(value, key = "", depth = 0) {
    if (depth > 8) return "[内容层级过深，已省略]";
    if (SENSITIVE_KEY_PATTERN.test(key)) return "[敏感或内部信息已隐藏]";
    if (BULK_DATA_KEY_PATTERN.test(key)) return "[完整原始市场数据未在界面展示]";
    if (Array.isArray(value)) {
      const visible = value
        .slice(0, 20)
        .map((item) => safeForDisplay(item, key, depth + 1));
      if (value.length > 20) visible.push(`[其余 ${value.length - 20} 项未展示]`);
      return visible;
    }
    if (value && typeof value === "object") {
      return Object.fromEntries(
        Object.entries(value).map(([childKey, childValue]) => [
          childKey,
          safeForDisplay(childValue, childKey, depth + 1),
        ])
      );
    }
    if (
      typeof value === "string" &&
      /[A-Za-z]:\\[^ \n]+|\/(?:home|Users|var|opt|srv)\/[^ \n]+/.test(value)
    ) {
      return "[内部文件路径已隐藏]";
    }
    return value;
  }

  const api = { buildPlainLanguageResult, safeForDisplay };
  root.AlphaPlainLanguage = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
