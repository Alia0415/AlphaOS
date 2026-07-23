(function initStatusLabels(root) {
  "use strict";

  const STATUS_DETAILS = {
    unverified: {
      label: "只是研究想法",
      description: "已经形成可研究的方向，但还没有用数据证明它是否成立。",
      rank: 0,
    },
    computed_not_validated: {
      label: "已完成计算，尚未验证有效性",
      description: "公式或指标已经运行完成，但还不能据此判断预测能力。",
      rank: 1,
    },
    insufficient_data: {
      label: "数据不足，暂时无法判断",
      description: "现有数据或成功结果不足，无法形成可靠判断。",
      rank: 0,
    },
    mixed_unvalidated: {
      label: "已完成多项计算，但尚未完成有效性验证",
      description: "已有多个计算结果，仍缺少对有效性和稳定性的检验。",
      rank: 1,
    },
    mixed_evidence: {
      label: "不同检验结果不一致",
      description: "现有证据指向不完全一致，需要继续定位差异来源。",
      rank: 2,
    },
    weak_positive_evidence: {
      label: "有初步支持，但证据较弱",
      description: "部分检验提供了初步支持，证据强度还不足以形成稳定结论。",
      rank: 2,
    },
    moderate_positive_evidence: {
      label: "多项结果支持，仍需谨慎",
      description: "多项检验提供支持，但仍需关注样本外表现、成本和失效风险。",
      rank: 3,
    },
  };

  const AGENT_LABELS = {
    research: "市场研究员",
    quant: "量化研究员",
    risk: "风险审查员",
    report: "报告整理员",
    portfolio: "组合研究员",
    macro: "宏观研究员",
  };

  function evidenceDetails(status) {
    const normalized = String(status || "").trim();
    const known = STATUS_DETAILS[normalized];
    if (known) return { status: normalized, ...known };
    return {
      status: normalized || "unknown",
      label: "当前证据状态需要进一步确认",
      description: "系统没有识别到可确定解释的证据状态，需要查看专业证据。",
      rank: 0,
    };
  }

  function agentLabel(agent) {
    return AGENT_LABELS[agent] || "研究专家";
  }

  const api = {
    AGENT_LABELS,
    STATUS_DETAILS,
    agentLabel,
    evidenceDetails,
  };

  root.AlphaPresentationStatus = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
