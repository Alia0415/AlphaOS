"""Deterministic policy gate for AlphaOS research requests."""

from __future__ import annotations

import re

from backend.core.policy_contracts import PolicyDecision


_TRADING_EXECUTION = (
    "自动下单",
    "帮我下单",
    "替我下单",
    "代我买",
    "代我卖",
    "直接买入",
    "直接卖出",
    "执行交易",
    "自动交易",
    "place order",
    "execute trade",
)
_GUARANTEED_RETURN = (
    "保证收益",
    "保本保收益",
    "一定上涨",
    "一定会涨",
    "稳赚",
    "必赚",
    "无风险收益",
    "guaranteed return",
    "will definitely rise",
)
_PERSONALIZED_RECOMMENDATION = (
    "建议买入",
    "建议卖出",
    "推荐持有",
    "可以建仓",
    "当前应配置",
    "目标仓位",
    "最值得买",
    "强烈推荐",
    "荐股",
)
_RECOMMEND_STOCK = re.compile(
    r"(推荐|选出|挑选|给我)\s*(?:\d+\s*(?:只|支|个))?.{0,8}(股票|标的)"
)
_RESEARCH_MARKERS = (
    "股票",
    "证券",
    "公司",
    "财务",
    "财报",
    "现金流",
    "行业",
    "市场",
    "因子",
    "r020",
    "风险",
    "历史",
    "收益率",
    "波动",
    "回撤",
    "量化",
    "宏观",
    "利率",
    "流动性",
    "政策",
    "经济周期",
    "投资",
    "估值",
    "成交量",
    "ohlcv",
    "research",
    "factor",
    "market",
)
_OUT_OF_DOMAIN_MARKERS = (
    "天气",
    "气温",
    "下雨",
    "降雨",
    "菜谱",
    "翻译",
    "写诗",
    "旅游",
    "星座",
)
_INVESTMENT_IMPACT_MARKERS = (
    "影响哪些行业",
    "行业影响",
    "市场影响",
    "投资影响",
    "对农业",
    "对能源",
    "对航运",
)

_SAFE_RESEARCH_SUGGESTIONS = [
    "分析指定行业或公司的历史事实与主要风险",
    "计算并验证指定量化因子的历史数据表现",
    "比较多个研究对象在明确时间范围内的证据",
]


class PolicyGate:
    """Apply ordered, finite rules before any model or expert is called."""

    def evaluate(self, prompt: str) -> PolicyDecision:
        text = " ".join(prompt.strip().lower().split())
        if any(marker in text for marker in _TRADING_EXECUTION):
            return _blocked(
                "trading_execution",
                ["trading_execution"],
                "请求要求 AlphaOS 代为执行或自动执行证券交易。",
                "AlphaOS 不执行下单、调仓或任何代客交易。可以改为研究指定标的的历史数据、方法假设和风险。",
            )
        if any(marker in text for marker in _GUARANTEED_RETURN):
            return _blocked(
                "guaranteed_return",
                ["guaranteed_return", "securities_recommendation"],
                "请求包含确定上涨或保证收益要求。",
                "AlphaOS 不提供证券推荐或收益保证。可以改为分析指定行业、公司或量化因子的历史数据、风险和验证状态。",
            )
        if (
            any(marker in text for marker in _PERSONALIZED_RECOMMENDATION)
            or _RECOMMEND_STOCK.search(text)
        ):
            return _blocked(
                "personalized_recommendation",
                ["securities_recommendation"],
                "请求要求形成具体证券买卖或持有建议。",
                "AlphaOS 不提供个性化证券推荐。可以改为公司研究、行业研究、风险审查或因子历史验证。",
            )

        research_related = any(marker in text for marker in _RESEARCH_MARKERS)
        impact_research = any(marker in text for marker in _INVESTMENT_IMPACT_MARKERS)
        if (
            any(marker in text for marker in _OUT_OF_DOMAIN_MARKERS)
            and not research_related
            and not impact_research
        ):
            return PolicyDecision(
                decision="out_of_domain",
                allowed=False,
                domain="outside_quant_research",
                policy_tags=["out_of_domain"],
                reason="请求属于日常信息查询，不是量化投资研究问题。",
                safe_response=(
                    "AlphaOS 专注于量化投资研究，暂不提供日常天气等通用查询。"
                    "你可以让我研究高温、降雨或极端天气对农业、能源、航运等行业的历史影响。"
                ),
                suggested_research_tasks=[
                    "研究高温对农业与能源行业的历史影响",
                    "分析极端天气对航运和供应链的风险",
                ],
            )

        return PolicyDecision(
            decision="allowed_research",
            allowed=True,
            domain="quant_investment_research",
            policy_tags=["research_only"],
            reason="请求可以在量化投资研究与证据边界内处理。",
        )


def _blocked(
    decision: str,
    tags: list[str],
    reason: str,
    safe_response: str,
) -> PolicyDecision:
    return PolicyDecision.model_validate(
        {
            "decision": decision,
            "allowed": False,
            "domain": "quant_investment_research",
            "policy_tags": tags,
            "reason": reason,
            "safe_response": safe_response,
            "suggested_research_tasks": _SAFE_RESEARCH_SUGGESTIONS,
        }
    )
