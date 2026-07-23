(function initPlainLanguageAdapter(root) {
  "use strict";

  const statusApi = root.AlphaPresentationStatus || {};
  const evidenceDetails =
    statusApi.evidenceDetails ||
    ((status) => ({
      status: status || "unknown",
      label: "当前证据状态需要进一步确认",
      description: "需要查看专业证据。",
      rank: 0,
    }));
  const agentLabel = statusApi.agentLabel || ((agent) => agent || "研究专家");

  const TRADING_ADVICE_PATTERN =
    /(买入|卖出|建仓|加仓|减仓|清仓|目标价|止盈|止损|稳赚|收益承诺|推荐指数|可以冲|放心买)/i;
  const SENSITIVE_KEY_PATTERN =
    /(api.?key|password|secret|token|prompt|skill.?md|stack|traceback|runtime.?path|local.?path|file.?path|directory)/i;
  const BULK_DATA_KEY_PATTERN =
    /^(raw_?data|market_?data|records|rows|ohlcv|prices|full_?data)$/i;

  const TERM_RULES = [
    [/\bcoverage ratio\b/gi, "可正常计算的数据占比"],
    [/\bcoverage_ratio\b/gi, "可正常计算的数据占比"],
    [/\bobservation count\b/gi, "使用的数据条数"],
    [/\bobservation_count\b/gi, "使用的数据条数"],
    [/\bmaximum drawdown\b/gi, "区间内从高点到低点出现过的最大跌幅"],
    [/\bmaximum_drawdown\b/gi, "区间内从高点到低点出现过的最大跌幅"],
    [/\bdaily volatility\b/gi, "日常价格波动程度"],
    [/\bdaily_volatility\b/gi, "日常价格波动程度"],
    [/\bRank IC\b/gi, "Rank IC（指标排名与未来收益排名之间的关系）"],
    [/\bICIR\b/g, "ICIR（指标与未来收益关系的稳定程度）"],
    [/\bIC\b/g, "IC（指标与未来收益之间的关系）"],
    [/\bout-of-sample\b/gi, "使用未参与设计的数据进行验证"],
    [/\btransaction cost\b/gi, "手续费、滑点和市场冲击等实际成本"],
    [/\brolling window warm-up\b/gi, "指标计算初期需要积累数据而产生的空值"],
  ];

  function buildPlainLanguageResult(response) {
    const source = response && typeof response === "object" ? response : {};
    const results = Object.values(
      source.results && typeof source.results === "object" ? source.results : {}
    );
    const failed = results.filter((result) =>
      ["failed", "blocked"].includes(result && result.status)
    );
    const completed = results.filter((result) => result && result.status === "completed");
    const statuses = collectValidationStatuses(results);
    const primaryStatus = resolveValidationStatus(statuses, failed, completed);
    const evidenceLevel = evidenceDetails(primaryStatus);
    const metrics = collectMetrics(results);
    const limitations = uniqueStrings(results.flatMap((result) => result.limitations || []));
    const risks = uniqueStrings(results.flatMap((result) => result.risks || []));
    const recommendations = safeResearchActions(
      results.flatMap((result) => result.recommendations || [])
    );
    const missingEvidence = buildMissingEvidence({
      failed,
      limitations,
      status: primaryStatus,
    });
    const nextSteps = buildNextSteps(recommendations, limitations, primaryStatus);
    const headline = buildHeadline({
      completed,
      failed,
      status: primaryStatus,
      metrics,
      needsClarification: Boolean(source.plan && source.plan.needs_clarification),
    });
    const keyPoints = buildKeyPoints({
      completed,
      failed,
      metrics,
      missingEvidence,
      nextSteps,
      status: primaryStatus,
    });

    return {
      headline,
      keyPoints,
      meaning: evidenceLevel.description,
      evidenceLevel,
      missingEvidence,
      nextSteps,
      majorRisks: risks.slice(0, 5).map(explainText),
      hasFailures: failed.length > 0,
      progress: buildProgress(source, results, primaryStatus),
      selectedAgents: Array.isArray(source.plan && source.plan.selected_agents)
        ? source.plan.selected_agents
        : [],
    };
  }

  function collectValidationStatuses(results) {
    const statuses = [];
    for (const result of results) {
      if (result && result.metadata && result.metadata.validation_status) {
        statuses.push(result.metadata.validation_status);
      }
      visit(result && result.evidence, (key, value) => {
        if (key === "validation_status" && typeof value === "string") statuses.push(value);
      });
    }
    return uniqueStrings(statuses);
  }

  function resolveValidationStatus(statuses, failed, completed) {
    if (!completed.length && failed.length) return "insufficient_data";
    if (!statuses.length) return failed.length ? "insufficient_data" : "unknown";
    if (statuses.length === 1) return statuses[0];
    const unvalidated = new Set(["unverified", "computed_not_validated", "mixed_unvalidated"]);
    return statuses.every((status) => unvalidated.has(status))
      ? "mixed_unvalidated"
      : "mixed_evidence";
  }

  function collectMetrics(results) {
    const metrics = {};
    for (const result of results) {
      visit(result && result.evidence, (key, value, parent) => {
        if (key === "coverage_ratio" && typeof value === "number") {
          metrics.coverageRatio = Math.max(
            Number.isFinite(metrics.coverageRatio) ? metrics.coverageRatio : 0,
            value
          );
        }
        if (key === "observation_count" && typeof value === "number") {
          metrics.observationCount = Math.max(metrics.observationCount || 0, value);
        }
        if (key === "factor_id" && typeof value === "string") metrics.factorId = value;
        if (parent && parent.factor_id && !metrics.factorId) metrics.factorId = parent.factor_id;
      });
    }
    return metrics;
  }

  function buildHeadline(context) {
    if (context.needsClarification) {
      return "研究所需的关键信息还不完整，补充后才能开始判断。";
    }
    if (!context.completed.length && context.failed.length) {
      return "当前没有成功获得足够数据，因此暂时无法判断。";
    }
    if (context.failed.length) {
      return "部分研究步骤已经完成，但仍有步骤失败或受阻，因此目前只能形成有限结论。";
    }
    const subject = context.metrics.factorId
      ? `${context.metrics.factorId} 指标`
      : "相关研究";
    const headlines = {
      unverified: `${subject}已经形成研究想法，但尚未经过数据验证，目前不能判断它是否有效。`,
      computed_not_validated: `${subject}已经成功计算，但目前只能作为研究线索，还没有足够证据证明它能够稳定预测未来收益。`,
      insufficient_data: "当前数据不足，因此暂时无法形成可靠判断。",
      mixed_unvalidated: "多项研究计算已经完成，但有效性尚未验证，目前只能把结果视为研究线索。",
      mixed_evidence: "现有检验得出了不一致的结果，目前还不能形成稳定结论。",
      weak_positive_evidence: "现有检验提供了初步支持，但证据仍然较弱，需要继续验证稳定性。",
      moderate_positive_evidence: "多项检验提供了支持，但样本外表现、实际成本和失效风险仍需谨慎核对。",
    };
    if (headlines[context.status]) return headlines[context.status];
    const firstSummary = context.completed.find((result) => result.summary);
    return firstSummary
      ? `${explainText(firstSummary.summary)} 当前证据仍需结合专业结果谨慎理解。`
      : "研究步骤已经完成，但当前证据状态仍需进一步确认。";
  }

  function buildKeyPoints(context) {
    const points = [];
    if (typeof context.metrics.coverageRatio === "number") {
      points.push(`${(context.metrics.coverageRatio * 100).toFixed(1)}% 的数据可以正常参与计算。`);
    } else if (context.completed.length) {
      const summary = context.completed.find((result) => result.summary);
      if (summary) points.push(explainText(summary.summary));
    }
    if (context.failed.length) {
      const roles = uniqueStrings(context.failed.map((result) => agentLabel(result.agent)));
      points.push(`${roles.join("、")}的步骤失败或受阻，不能按成功结果解释。`);
    } else {
      const boundary = {
        unverified: "当前只是研究想法，还没有完成有效性检验。",
        computed_not_validated: "当前只完成了计算，尚未检验它与未来收益的关系。",
        mixed_unvalidated: "多项计算已完成，但还没有完成统一的有效性检验。",
        mixed_evidence: "不同检验的结果不一致，结论稳定性仍不明确。",
      }[context.status];
      if (boundary) points.push(boundary);
    }
    if (context.missingEvidence.length) points.push(context.missingEvidence[0]);
    if (points.length < 3 && context.nextSteps.length) points.push(context.nextSteps[0]);
    return uniqueStrings(points).slice(0, 3);
  }

  function buildMissingEvidence(context) {
    const missing = context.failed.map((result) => {
      const role = agentLabel(result.agent);
      return result.status === "blocked"
        ? `${role}因上游步骤未完成而被阻断，当前无法获得这部分证据。`
        : `${role}未能成功完成，当前无法获得这部分证据。`;
    });
    missing.push(...context.limitations.map(explainText));
    if (!missing.length) {
      const defaults = {
        unverified: ["尚缺少基于真实数据的有效性验证。"],
        computed_not_validated: ["尚缺少指标与未来收益关系的有效性验证。"],
        mixed_unvalidated: ["尚缺少对多项计算结果的一致性和有效性验证。"],
        mixed_evidence: ["尚未解释不同检验结果不一致的原因。"],
        insufficient_data: ["当前没有成功获得足够数据，因此暂时无法判断。"],
      };
      missing.push(...(defaults[context.status] || []));
    }
    return uniqueStrings(missing).slice(0, 6);
  }

  function buildNextSteps(recommendations, limitations, status) {
    const actions = [...recommendations];
    const limitationText = limitations.join(" ");
    const deterministicRules = [
      [/IC|Rank IC|未来收益关系/i, "计算未来 1 日和 5 日的指标排名与未来收益排名关系。"],
      [/样本外|out.?of.?sample/i, "使用未参与设计的数据进行样本外测试。"],
      [/交易成本|手续费|滑点|市场冲击/i, "纳入手续费、滑点和市场冲击等实际成本。"],
      [/股票池|标的过少|样本过小/i, "扩大股票池，检查结论是否依赖少数标的。"],
      [/时间区间|时间窗口|区间较短|样本期/i, "延长研究时间区间，覆盖更多市场状态。"],
      [/市场状态|regime/i, "分别检验不同市场状态下的表现和失效情况。"],
      [/基本面|估值/i, "补充基本面和估值证据，避免只依赖量价信息。"],
    ];
    for (const [pattern, action] of deterministicRules) {
      if (pattern.test(limitationText)) actions.push(action);
    }
    if (!actions.length && ["unverified", "computed_not_validated", "mixed_unvalidated"].includes(status)) {
      actions.push("先补充与未来收益关系的有效性检验，再讨论结果是否稳定。");
    }
    return uniqueStrings(safeResearchActions(actions)).slice(0, 6);
  }

  function buildProgress(response, results, status) {
    const hasPlan = Boolean(
      response.plan &&
        (response.plan.goal || (Array.isArray(response.plan.steps) && response.plan.steps.length))
    );
    const hasCompleted = results.some((result) => result && result.status === "completed");
    const calculatedStatuses = new Set([
      "computed_not_validated",
      "mixed_unvalidated",
      "mixed_evidence",
      "weak_positive_evidence",
      "moderate_positive_evidence",
    ]);
    const validatedStatuses = new Set([
      "mixed_evidence",
      "weak_positive_evidence",
      "moderate_positive_evidence",
    ]);
    return [
      { label: "提出研究想法", completed: hasPlan },
      { label: "完成数据计算", completed: hasCompleted && calculatedStatuses.has(status) },
      { label: "初步有效性验证", completed: validatedStatuses.has(status) },
      { label: "样本外验证", completed: hasEvidenceFlag(results, ["out_of_sample_validated", "oos_completed"]) },
      {
        label: "交易成本检验",
        completed: hasEvidenceFlag(results, [
          "transaction_cost_validated",
          "transaction_cost_included",
          "cost_test_completed",
        ]),
      },
    ];
  }

  function hasEvidenceFlag(results, keys) {
    let found = false;
    visit(results, (key, value) => {
      if (keys.includes(key) && (value === true || value === "completed" || value === "validated")) {
        found = true;
      }
    });
    return found;
  }

  function safeResearchActions(values) {
    return uniqueStrings(values)
      .filter((value) => !TRADING_ADVICE_PATTERN.test(value))
      .map(explainText);
  }

  function explainText(value) {
    let text = String(value || "").trim();
    for (const [pattern, replacement] of TERM_RULES) text = text.replace(pattern, replacement);
    return text;
  }

  function safeForDisplay(value, key = "", depth = 0) {
    if (depth > 8) return "[内容层级过深，已省略]";
    if (SENSITIVE_KEY_PATTERN.test(key)) return "[敏感或内部信息已隐藏]";
    if (BULK_DATA_KEY_PATTERN.test(key)) return "[完整原始市场数据未在界面展示]";
    if (Array.isArray(value)) {
      const visible = value.slice(0, 20).map((item) => safeForDisplay(item, key, depth + 1));
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
    if (typeof value === "string") {
      if (/[A-Za-z]:\\[^ \n]+|\/(?:home|Users|var|opt|srv)\/[^ \n]+/.test(value)) {
        return "[内部文件路径已隐藏]";
      }
      return value;
    }
    return value;
  }

  function visit(value, callback, parent = null) {
    if (Array.isArray(value)) {
      value.forEach((item) => visit(item, callback, value));
      return;
    }
    if (!value || typeof value !== "object") return;
    Object.entries(value).forEach(([key, child]) => {
      callback(key, child, value);
      visit(child, callback, value);
    });
  }

  function uniqueStrings(values) {
    const seen = new Set();
    return values
      .map((value) => String(value || "").trim())
      .filter((value) => {
        if (!value || seen.has(value)) return false;
        seen.add(value);
        return true;
      });
  }

  const api = {
    buildPlainLanguageResult,
    explainText,
    safeForDisplay,
  };
  root.AlphaPlainLanguage = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
