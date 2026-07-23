(function initEventLabels(root) {
  "use strict";

  const statusApi = root.AlphaPresentationStatus || {};
  const agentLabel = statusApi.agentLabel || ((agent) => agent || "研究专家");

  const EVENT_LABELS = {
    plan_created: "研究经理已拆解问题并组建研究团队",
    clarification_required: "研究开始前还需要补充关键信息",
    skill_plan_created: "专家已经选定本次研究需要的专业工具",
    skill_started: "正在运行专业量化工具",
    skill_completed: "专业计算已完成",
    skill_failed: "专业计算未能完成",
    step_completed: "该研究步骤已完成",
    step_failed: "该研究步骤未能完成",
    synthesis_started: "结果整理器正在根据实际证据生成回答",
    task_completed: "本次研究已完成",
  };

  const TOOL_LABELS = {
    pandadata_market_data: "正在获取指定区间的历史市场数据",
  };

  const START_LABELS = {
    research: "市场研究员开始整理数据和市场证据",
    quant: "量化研究员开始计算和分析指标",
    risk: "风险审查员开始检查假设和失效情况",
    report: "报告整理员开始组织研究结论",
    portfolio: "组合研究员开始检查组合层面的影响",
    macro: "宏观研究员开始整理宏观环境证据",
  };

  function translateEvent(event) {
    const item = event || {};
    if (item.type === "step_started") {
      return START_LABELS[item.agent] || `${agentLabel(item.agent)}开始处理研究任务`;
    }
    if (item.type === "tool_called") {
      const tool = item.metadata && item.metadata.tool;
      return TOOL_LABELS[tool] || "正在调用研究所需的数据或计算工具";
    }
    return EVENT_LABELS[item.type] || "研究团队正在更新任务进度";
  }

  const api = { EVENT_LABELS, START_LABELS, TOOL_LABELS, translateEvent };
  root.AlphaEventLabels = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
