from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError as PydanticValidationError

from meeting_assistant.db import (
    ConflictError,
    Database,
    NotFoundError,
    ValidationError,
)
from meeting_assistant.domain import (
    ActionCreate,
    AnalysisProposal,
    MeetingCreate,
    ReviewRequest,
)


@pytest.fixture
def database(tmp_path) -> Database:
    repository = Database(tmp_path / "meeting-assistant.sqlite3")
    repository.initialize(seed_demo=False)
    return repository


def create_meeting(database: Database, title: str = "项目周会") -> dict:
    return database.create_meeting(
        {
            "title": title,
            "meeting_type": "项目例会",
            "meeting_date": "2026-08-14",
            "content": "王芳负责接口联调，8 月 15 日前完成。",
        }
    )


def proposal(task: str = "完成接口联调", owner: str = "王芳") -> dict:
    return {
        "summary": "团队明确了接口联调安排。",
        "decisions": [
            {"decision": "按当前方案推进", "source_quote": "王芳负责接口联调"}
        ],
        "action_items": [
            {
                "task": task,
                "owner": owner,
                "due_date_text": "8 月 15 日前",
                "due_date": "2026-08-15",
                "source_quotes": ["王芳负责接口联调，8 月 15 日前完成。"],
                "confidence": 0.96,
            }
        ],
    }


def complete_run(database: Database, meeting_id: int, payload: dict | None = None) -> dict:
    run = database.create_analysis_run(meeting_id, "deepseek-chat", "optimized-v1")
    return database.complete_analysis_run(
        run["id"],
        raw_response='{"summary":"团队明确了接口联调安排。"}',
        proposed=payload or proposal(),
        warnings=["负责人和日期已从原文确认"],
        security_flags=[],
    )


def test_domain_models_validate_request_and_proposal_contracts() -> None:
    meeting = MeetingCreate.model_validate(
        {"title": "评审会", "content": "确认方案 B。", "meeting_date": "2026-08-14"}
    )
    assert meeting.model_dump(mode="json")["meeting_date"] == "2026-08-14"

    action = ActionCreate.model_validate({"task": "补充测试"})
    assert action.owner == "待确认"
    assert action.due_date == "待确认"

    parsed = AnalysisProposal.model_validate(proposal())
    assert parsed.action_items[0].confidence == pytest.approx(0.96)

    with pytest.raises(PydanticValidationError):
        MeetingCreate.model_validate({"title": "   ", "content": "有效记录"})
    with pytest.raises(PydanticValidationError):
        AnalysisProposal.model_validate(
            {**proposal(), "action_items": [{**proposal()["action_items"][0], "due_date": "明天"}]}
        )
    with pytest.raises(PydanticValidationError):
        ReviewRequest.model_validate({"decision": "edit", "note": "缺少最终提案"})


def test_initialize_enables_pragmas_and_seeds_exactly_once(tmp_path) -> None:
    path = tmp_path / "seeded.sqlite3"
    database = Database(path)
    database.initialize(seed_demo=True)
    database.initialize(seed_demo=True)

    stats = database.dashboard_stats()
    assert stats["meetings"] == 3
    assert stats["actions"] == 8
    assert len(database.list_meetings()) == 3
    assert len(database.list_meetings({"owner": "王芳"})) == 1
    assert len(database.list_meetings({"q": "产品发布"})) == 1
    assert database.list_meetings({"owner": "王芳"})[0]["pending_actions"] == 2

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    with database._connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_meeting_crud_filters_and_persistence(tmp_path) -> None:
    path = tmp_path / "persistent.sqlite3"
    first = Database(path)
    first.initialize(seed_demo=False)
    meeting = create_meeting(first, "接口评审会")
    action, created = first.create_action(
        meeting["id"],
        {
            "task": "完成接口联调",
            "owner": "王芳",
            "due_date": "2026-08-15",
            "status": "pending",
        },
    )
    assert created is True
    assert action["version"] == 1

    second = Database(path)
    second.initialize(seed_demo=False)
    detail = second.get_meeting(meeting["id"])
    assert detail is not None
    assert detail["title"] == "接口评审会"
    assert detail["actions"][0]["owner"] == "王芳"
    assert [item["id"] for item in second.list_meetings({"status": "pending"})] == [
        meeting["id"]
    ]
    assert len(second.list_meetings({"meeting_type": "项目例会"})) == 1
    assert len(second.list_meetings({"due_before": "2026-08-15"})) == 1
    with pytest.raises(ValidationError):
        second.list_meetings({"due_before": "下周五"})


def test_action_fingerprint_deduplicates_and_optimistic_lock_rejects_stale_write(
    database: Database,
) -> None:
    meeting = create_meeting(database)
    action, created = database.create_action(
        meeting["id"],
        {
            "task": "完成接口联调！",
            "owner": "王芳",
            "due_date": "2026-08-15",
        },
    )
    duplicate, duplicate_created = database.create_action(
        meeting["id"],
        {
            "task": " 完成 接口联调 ",
            "owner": "王芳",
            "due_date": "2026-08-15",
        },
    )
    assert duplicate_created is False
    assert duplicate["id"] == action["id"]

    updated = database.update_action(
        action["id"], {"status": "completed"}, expected_version=1
    )
    assert updated["version"] == 2
    assert updated["status"] == "completed"
    assert updated["completed_at"] is not None

    with pytest.raises(ConflictError, match="当前版本"):
        database.update_action(
            action["id"], {"owner": "李敏"}, expected_version=1
        )


def test_successful_analysis_confirmation_keeps_raw_and_final_audit(
    database: Database,
) -> None:
    meeting = create_meeting(database)
    completed = complete_run(database, meeting["id"])
    assert completed["status"] == "succeeded"
    assert completed["proposed"] == proposal()
    assert completed["raw_response"].startswith("{")

    reviewed = database.review_analysis_run(
        completed["id"], "confirm", final_payload=None, note="内容无误"
    )
    assert reviewed["status"] == "confirmed"
    assert reviewed["review_decision"] == "confirm"
    assert reviewed["final_payload"] == completed["proposed"]
    assert reviewed["proposed"] == completed["proposed"]
    assert reviewed["created_action_count"] == 1

    detail = database.get_meeting(meeting["id"])
    assert detail is not None
    assert len(detail["actions"]) == 1
    assert detail["actions"][0]["analysis_run_id"] == completed["id"]
    assert detail["analysis_runs"][0]["raw_response"] == completed["raw_response"]
    with pytest.raises(ConflictError):
        database.review_analysis_run(completed["id"], "reject", None)


def test_edit_reject_and_failure_are_audited_without_unconfirmed_actions(
    database: Database,
) -> None:
    meeting = create_meeting(database)

    edited_run = complete_run(database, meeting["id"])
    edited_payload = proposal(task="完成接口联调并提交报告", owner="李敏")
    edited = database.review_analysis_run(
        edited_run["id"], "edit", edited_payload, "纠正负责人并补充交付物"
    )
    assert edited["status"] == "edited"
    assert edited["final_payload"] == edited_payload
    assert edited["proposed"] != edited["final_payload"]

    rejected_run = complete_run(database, meeting["id"], proposal(task="误提取任务"))
    rejected = database.review_analysis_run(
        rejected_run["id"], "reject", None, "原文不是任务"
    )
    assert rejected["status"] == "rejected"
    assert rejected["final_payload"] is None
    assert rejected["created_action_count"] == 0

    failed_run = database.create_analysis_run(meeting["id"], "deepseek-chat", "v1")
    failed = database.fail_analysis_run(failed_run["id"], "auth_error", "密钥无效")
    assert failed["status"] == "failed"
    assert failed["error_code"] == "auth_error"
    assert failed["proposed"] is None
    with pytest.raises(ConflictError):
        database.complete_analysis_run(
            failed_run["id"], "{}", proposal(), warnings=[], security_flags=[]
        )

    detail = database.get_meeting(meeting["id"])
    assert detail is not None
    assert [item["task"] for item in detail["actions"]] == ["完成接口联调并提交报告"]


def test_review_rolls_back_all_actions_when_transaction_fails(
    database: Database, monkeypatch
) -> None:
    meeting = create_meeting(database)
    payload = proposal()
    payload["action_items"].append(
        {
            "task": "整理联调报告",
            "owner": "陈浩",
            "due_date_text": "8 月 16 日前",
            "due_date": "2026-08-16",
            "source_quotes": ["陈浩整理联调报告。"],
            "confidence": 0.9,
        }
    )
    completed = complete_run(database, meeting["id"], payload)
    original_insert = database._insert_action
    calls = 0

    def fail_on_second(connection, meeting_id, values):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated write failure")
        return original_insert(connection, meeting_id, values)

    monkeypatch.setattr(database, "_insert_action", fail_on_second)
    with pytest.raises(RuntimeError, match="simulated write failure"):
        database.review_analysis_run(completed["id"], "confirm", payload)

    detail = database.get_meeting(meeting["id"])
    assert detail is not None
    assert detail["actions"] == []
    assert detail["analysis_runs"][0]["status"] == "succeeded"
    assert detail["analysis_runs"][0]["review_decision"] is None


def test_not_found_and_invalid_state_errors_are_explicit(database: Database) -> None:
    assert database.get_meeting(9999) is None
    with pytest.raises(NotFoundError):
        database.create_action(9999, {"task": "不存在会议的任务"})
    with pytest.raises(NotFoundError):
        database.create_analysis_run(9999, "deepseek-chat", "v1")
    with pytest.raises(NotFoundError):
        database.fail_analysis_run(9999, "missing", "不存在")
