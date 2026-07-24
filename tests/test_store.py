"""Direct SQLite persistence-layer tests using isolated temp databases."""

from __future__ import annotations

from backend.core.store import Store


def _store(tmp_path) -> Store:
    return Store(tmp_path / "alphaos.db")


def test_create_task_and_get_task_roundtrip(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_task(
        task_id="t1",
        prompt="分析 000001.SZ",
        status="planned",
        plan={"goal": "分析"},
    )

    task = store.get_task("t1")
    assert task is not None
    assert task["prompt"] == "分析 000001.SZ"
    assert task["status"] == "planned"
    assert task["plan"] == {"goal": "分析"}
    assert task["events"] == []
    assert store.get_task("missing") is None


def test_append_event_assigns_incrementing_sequence(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_task(task_id="t1", prompt="p", status="planned")

    seq1 = store.append_event("t1", type="plan_created", message="a")
    seq2 = store.append_event(
        "t1", type="step_started", message="b", agent="research", step_id="s1"
    )

    assert (seq1, seq2) == (1, 2)
    events = store.get_task("t1")["events"]
    assert [e["type"] for e in events] == ["plan_created", "step_started"]
    assert events[1]["agent"] == "research"
    assert events[1]["step_id"] == "s1"


def test_finish_task_updates_status_and_aggregation(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_task(task_id="t1", prompt="p", status="running")

    store.finish_task(
        "t1",
        status="completed",
        aggregation={"user_goal": "g"},
        final_answer="done",
        duration_ms=42,
    )

    task = store.get_task("t1")
    assert task["status"] == "completed"
    assert task["aggregation"] == {"user_goal": "g"}
    assert task["final_answer"] == "done"
    assert task["duration_ms"] == 42


def test_list_tasks_returns_compact_rows(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_task(task_id="a", prompt="pa", status="planned")
    store.create_task(task_id="b", prompt="pb", status="completed")

    rows = store.list_tasks()
    ids = {row["id"] for row in rows}
    assert ids == {"a", "b"}
    assert all(set(row) == {"id", "prompt", "status", "created_at", "duration_ms"} for row in rows)


def test_report_and_followup_roundtrip(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_task(task_id="t1", prompt="p", status="completed")
    store.create_report(
        report_id="r1",
        task_id="t1",
        title="研究报告",
        completeness={"completion_ratio": 1.0},
        aggregation={"user_goal": "g"},
    )
    store.add_followup(
        followup_id="f1",
        report_id="r1",
        role="user",
        text="收益如何？",
    )
    store.add_followup(
        followup_id="f2",
        report_id="r1",
        role="assistant",
        text="见证据",
        evidence=[{"source": "block", "text": "片段"}],
    )

    report = store.get_report("r1")
    assert report["title"] == "研究报告"
    assert report["completeness"] == {"completion_ratio": 1.0}
    assert [f["id"] for f in report["followups"]] == ["f1", "f2"]
    assert report["followups"][1]["evidence"] == [{"source": "block", "text": "片段"}]
    assert [f["role"] for f in store.list_followups("r1")] == ["user", "assistant"]


def test_overrides_get_and_set(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.get_overrides() == {}

    store.set_override("quant", False)
    assert store.get_overrides() == {"quant": False}

    store.set_override("quant", True)
    assert store.get_overrides() == {"quant": True}


def test_overview_counts_average_completion(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_task(task_id="a", prompt="p", status="completed")
    store.create_task(task_id="b", prompt="p", status="planned")
    store.create_report(
        report_id="r1", task_id="a", title="t", completeness={"completion_ratio": 1.0}
    )
    store.create_report(
        report_id="r2", task_id="a", title="t", completeness={"completion_ratio": 0.5}
    )

    counts = store.overview_counts()
    assert counts["total_tasks"] == 2
    assert counts["completed_tasks"] == 1
    assert counts["report_count"] == 2
    assert counts["average_completion"] == 0.75


def test_separate_db_files_are_isolated(tmp_path) -> None:
    store_a = Store(tmp_path / "a.db")
    store_b = Store(tmp_path / "b.db")
    store_a.create_task(task_id="only-a", prompt="p", status="planned")

    assert store_a.get_task("only-a") is not None
    assert store_b.get_task("only-a") is None
