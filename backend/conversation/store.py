"""In-memory conversation store for multi-turn AlphaOS sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend.core.contracts import (
    AggregationResult,
    ExecutionPlan,
    ExpertResult,
)


class TurnRecord:
    """One user prompt + the full AlphaOS response in a conversation."""

    def __init__(
        self,
        prompt: str,
        plan: ExecutionPlan,
        results: dict[str, ExpertResult],
        aggregation: AggregationResult,
        events: list[dict[str, Any]],
        final_answer: str,
        duration_ms: int,
    ) -> None:
        self.prompt = prompt
        self.plan = plan
        self.results = results
        self.aggregation = aggregation
        self.events = events
        self.final_answer = final_answer
        self.duration_ms = duration_ms
        self.timestamp = datetime.now(timezone.utc)

    def to_summary(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt[:200],
            "headline": self.aggregation.direct_answer.headline,
            "completion_status": self.aggregation.completion_status,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
        }

    def extract_key_findings(self) -> str:
        """Compact, plain-text summary of this turn's results for cross-turn context.

        Extracts headline, metrics, risks, and key findings without dumping raw data.
        """
        parts: list[str] = []
        parts.append(f"结论：{self.aggregation.direct_answer.headline}")

        if self.aggregation.completion_status != "completed":
            parts.append(f"状态：{self.aggregation.completion_status}")

        for block in self.aggregation.content_blocks:
            data = block.data or {}
            if block.type == "metric_cards":
                metrics = data.get("metrics", [])
                values = [
                    f"{m.get('label', '')}={m.get('display_value', m.get('value', '?'))}"
                    for m in metrics[:5]
                    if isinstance(m, dict)
                ]
                if values:
                    parts.append(f"指标：{'，'.join(values)}")
            elif block.type == "risk_list":
                items = data.get("items", [])
                texts = [
                    str(i.get("text", i))[:80]
                    for i in items[:3]
                ]
                if texts:
                    parts.append(f"风险（{len(items)}项）：{'，'.join(texts)}")
            elif block.type in ("finding_cards", "narrative"):
                items = data.get("items", [])
                texts = [
                    str(i.get("text", i))[:100]
                    for i in items[:3]
                ]
                if texts:
                    parts.append(f"发现：{'，'.join(texts)}")
            elif block.type == "factor_list":
                items = data.get("items", [])
                names = [
                    str(i.get("name", i.get("title", "")))[:60]
                    for i in items[:3]
                ]
                shortlist = data.get("shortlist", [])
                if shortlist:
                    names.extend(f"[优先]{s}" for s in shortlist[:2])
                if names:
                    parts.append(f"研究想法：{'，'.join(names)}")
            elif block.type == "report":
                parts.append("已生成正式研究报告")

        return "；".join(parts)

    def to_detail(self) -> dict[str, Any]:
        """Full turn data for the frontend to re-render."""
        return {
            "prompt": self.prompt,
            "plan": self.plan.model_dump(mode="json"),
            "results": {
                k: v.model_dump(mode="json")
                for k, v in self.results.items()
            },
            "aggregation": self.aggregation.model_dump(mode="json"),
            "events": self.events,
            "final_answer": self.final_answer,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }


class Conversation:
    """A named sequence of AlphaOS turns."""

    def __init__(self, title: str | None = None) -> None:
        self.id = uuid4().hex[:12]
        self.title = title or f"对话 {self.id[:8]}"
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = self.created_at
        self.turns: list[TurnRecord] = []

    def add_turn(self, turn: TurnRecord) -> None:
        self.turns.append(turn)
        self.updated_at = datetime.now(timezone.utc)
        if len(self.turns) == 1:
            self.title = turn.prompt[:60]

    def build_history_context(self, exclude_turns: int = 1) -> str:
        """Build a compact plain-text summary of all past turns (excluding the
        most recent *exclude_turns* turns) for the Manager Agent's cross-turn
        awareness. Returns an empty string when there is no prior history."""
        past = self.turns[:-exclude_turns] if exclude_turns > 0 else self.turns
        if not past:
            return ""
        lines: list[str] = ["之前已完成的分析（按时间顺序）："]
        for idx, turn in enumerate(past, start=1):
            lines.append(f"\n第 {idx} 轮：")
            lines.append(f"  用户请求：{turn.prompt[:200]}")
            lines.append(f"  结论摘要：{turn.extract_key_findings()[:300]}")
        return "\n".join(lines)

    def to_meta(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "turn_count": len(self.turns),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ConversationStore:
    """Thread-safe in-memory store for conversations."""

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}

    def create(self, title: str | None = None) -> Conversation:
        conv = Conversation(title)
        self._conversations[conv.id] = conv
        return conv

    def get(self, conv_id: str) -> Conversation | None:
        return self._conversations.get(conv_id)

    def list_all(self) -> list[Conversation]:
        return sorted(
            self._conversations.values(),
            key=lambda c: c.updated_at,
            reverse=True,
        )

    def delete(self, conv_id: str) -> bool:
        return self._conversations.pop(conv_id, None) is not None


# Singleton shared across the app
_store = ConversationStore()


def get_store() -> ConversationStore:
    return _store
