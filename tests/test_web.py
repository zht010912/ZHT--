from __future__ import annotations

from pathlib import Path

import pytest

from meeting_assistant.ai import AIServiceError, AnalysisResult
from meeting_assistant.config import Settings
from meeting_assistant.db import Database
from meeting_assistant.web import create_app


class FakeAnalyzer:
    def analyze(self, meeting, variant="optimized"):
        proposal = {
            "summary": "会议明确了接口联调安排。",
            "decisions": [],
            "action_items": [
                {
                    "task": "完成接口联调",
                    "owner": "王芳",
                    "due_date_text": "下周五",
                    "due_date": "2026-08-21",
                    "source_quotes": ["王芳负责接口联调，下周五前完成"],
                    "confidence": 0.95,
                }
            ],
        }
        return AnalysisResult(
            raw_response='{"summary":"会议明确了接口联调安排。"}',
            proposal=proposal,
            warnings=[],
            security_flags=[],
            prompt_version=variant,
        )


class FailingAnalyzer:
    def analyze(self, meeting, variant="optimized"):
        raise AIServiceError("AI_AUTH_ERROR", "AI 服务认证失败，请检查服务端配置。", 502)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "web-test.db",
        deepseek_api_key="test-only-key",
        deepseek_api_base="https://api.deepseek.com",
        deepseek_model="deepseek-v4-flash",
        deepseek_timeout_seconds=2,
        max_meeting_chars=20_000,
        seed_demo=True,
        testing=True,
    )


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings=settings, database=Database(settings.database_path), ai_client=FakeAnalyzer())
    return app.test_client()


def _create_demo_meeting(client):
    response = client.post(
        "/api/meetings",
        json={
            "title": "接口联调验收",
            "meeting_type": "评审会",
            "meeting_date": "2026-08-14",
            "content": "王芳负责接口联调，下周五前完成。",
        },
    )
    assert response.status_code == 201
    return response.get_json()


def test_index_and_health_never_expose_secret(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "ActionFlow" in index.get_data(as_text=True)
    assert "test-only-key" not in index.get_data(as_text=True)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.get_json()["api_key_configured"] is True
    assert "test-only-key" not in health.get_data(as_text=True)


def test_seed_dashboard_and_meeting_detail(client):
    dashboard = client.get("/api/dashboard").get_json()
    assert dashboard["meetings"] == 3
    assert dashboard["actions"] == 8
    meetings = client.get("/api/meetings").get_json()["items"]
    detail = client.get(f"/api/meetings/{meetings[0]['id']}")
    assert detail.status_code == 200
    assert "actions" in detail.get_json()


def test_create_search_and_filter_meetings(client):
    created = _create_demo_meeting(client)
    by_query = client.get("/api/meetings?q=接口联调验收").get_json()["items"]
    by_type = client.get("/api/meetings?meeting_type=评审会").get_json()["items"]
    assert [item["id"] for item in by_query] == [created["id"]]
    assert created["id"] in {item["id"] for item in by_type}


def test_delete_meeting_removes_its_related_data(client):
    meeting = _create_demo_meeting(client)
    action = client.post(
        f"/api/meetings/{meeting['id']}/actions",
        json={"task": "随会议删除", "owner": "王芳", "due_date": "2026-08-20"},
    )
    assert action.status_code == 201

    deleted = client.delete(f"/api/meetings/{meeting['id']}")

    assert deleted.status_code == 200
    assert deleted.get_json() == {"id": meeting["id"], "title": "接口联调验收"}
    assert client.get(f"/api/meetings/{meeting['id']}").status_code == 404
    dashboard = client.get("/api/dashboard").get_json()
    assert dashboard["meetings"] == 3
    assert dashboard["actions"] == 8
    assert client.delete(f"/api/meetings/{meeting['id']}").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "空记录", "meeting_date": "2026-08-14", "content": "   "},
        {"title": "超长记录", "meeting_date": "2026-08-14", "content": "字" * 20_001},
    ],
)
def test_empty_and_overlong_records_are_rejected(client, payload):
    response = client.post("/api/meetings", json=payload)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"

    valid_meeting = _create_demo_meeting(client)
    manual = client.post(
        f"/api/meetings/{valid_meeting['id']}/actions",
        json={"task": "非法输入后仍可手工创建", "owner": "待确认", "due_date": "待确认"},
    )
    assert manual.status_code == 201


def test_manual_action_duplicate_edit_and_optimistic_update(client):
    meeting = _create_demo_meeting(client)
    payload = {"task": "补充接口测试", "owner": "李敏", "due_date": "2026-08-18", "source_quotes": []}
    first = client.post(f"/api/meetings/{meeting['id']}/actions", json=payload)
    second = client.post(f"/api/meetings/{meeting['id']}/actions", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["created"] is False

    action = first.get_json()["item"]
    updated = client.patch(
        f"/api/actions/{action['id']}",
        json={
            "task": "补充接口集成测试",
            "owner": "王芳",
            "due_date": "2026-08-20",
            "status": "completed",
            "expected_version": 1,
        },
    )
    stale = client.patch(f"/api/actions/{action['id']}", json={"status": "pending", "expected_version": 1})
    assert updated.status_code == 200
    updated_item = updated.get_json()
    assert updated_item["task"] == "补充接口集成测试"
    assert updated_item["owner"] == "王芳"
    assert updated_item["due_date"] == "2026-08-20"
    assert updated_item["status"] == "completed"
    assert updated_item["version"] == 2
    assert stale.status_code == 409


def test_ai_suggestion_is_not_official_until_human_review(client):
    meeting = _create_demo_meeting(client)
    run_response = client.post(f"/api/meetings/{meeting['id']}/analyze", json={"prompt_version": "optimized"})
    assert run_response.status_code == 201
    run = run_response.get_json()
    before = client.get(f"/api/meetings/{meeting['id']}").get_json()
    assert before["actions"] == []
    assert run["status"] == "succeeded"
    assert run["raw_response"]

    reviewed = client.post(
        f"/api/analysis-runs/{run['id']}/review",
        json={"decision": "confirm", "note": "人工核对原文后确认"},
    )
    assert reviewed.status_code == 200
    reviewed_run = reviewed.get_json()
    assert reviewed_run["created_action_count"] == 1
    assert reviewed_run["status"] == "confirmed"
    assert reviewed_run["review_decision"] == "confirm"
    assert reviewed_run["raw_response"] == run["raw_response"]
    assert reviewed_run["final_payload"] == reviewed_run["proposed"]
    after = client.get(f"/api/meetings/{meeting['id']}").get_json()
    assert len(after["actions"]) == 1
    assert isinstance(after["analysis_runs"][0]["raw_response"], str)
    assert isinstance(after["analysis_runs"][0]["final_payload"], dict)


def test_human_can_edit_or_reject_ai_package(client):
    meeting = _create_demo_meeting(client)
    run = client.post(f"/api/meetings/{meeting['id']}/analyze", json={}).get_json()
    final_payload = run["proposed"]
    final_payload["action_items"][0]["owner"] = "待确认"
    edited = client.post(
        f"/api/analysis-runs/{run['id']}/review",
        json={"decision": "edit", "final_payload": final_payload, "note": "负责人需要再次确认"},
    )
    assert edited.status_code == 200
    edited_run = edited.get_json()
    assert edited_run["status"] == "edited"
    assert edited_run["review_decision"] == "edit"
    assert edited_run["raw_response"] == run["raw_response"]
    assert edited_run["proposed"]["action_items"][0]["owner"] == "王芳"
    assert edited_run["final_payload"]["action_items"][0]["owner"] == "待确认"
    assert edited_run["proposed"] != edited_run["final_payload"]

    another = _create_demo_meeting(client)
    reject_run = client.post(f"/api/meetings/{another['id']}/analyze", json={}).get_json()
    rejected = client.post(
        f"/api/analysis-runs/{reject_run['id']}/review",
        json={"decision": "reject", "note": "提取质量不足"},
    )
    assert rejected.status_code == 200
    rejected_run = rejected.get_json()
    assert rejected_run["status"] == "rejected"
    assert rejected_run["review_decision"] == "reject"
    assert rejected_run["raw_response"] == reject_run["raw_response"]
    assert rejected_run["proposed"] == reject_run["proposed"]
    assert rejected_run["final_payload"] is None


def test_model_failure_is_audited_and_manual_core_still_works(settings):
    app = create_app(settings=settings, database=Database(settings.database_path), ai_client=FailingAnalyzer())
    client = app.test_client()
    meeting = _create_demo_meeting(client)
    failed = client.post(f"/api/meetings/{meeting['id']}/analyze", json={})
    assert failed.status_code == 502
    assert failed.get_json()["error"]["code"] == "AI_AUTH_ERROR"

    manual = client.post(
        f"/api/meetings/{meeting['id']}/actions",
        json={"task": "模型失败后仍可手工创建", "owner": "待确认", "due_date": "待确认"},
    )
    assert manual.status_code == 201
    detail = client.get(f"/api/meetings/{meeting['id']}").get_json()
    assert detail["analysis_runs"][0]["status"] == "failed"
    assert len(detail["actions"]) == 1


def test_unknown_routes_and_invalid_prompt_have_explicit_errors(client):
    assert client.get("/api/does-not-exist").get_json()["error"]["code"] == "route_not_found"
    meeting = _create_demo_meeting(client)
    invalid = client.post(f"/api/meetings/{meeting['id']}/analyze", json={"prompt_version": "magic"})
    assert invalid.status_code == 422
    assert invalid.get_json()["error"]["code"] == "invalid_prompt_version"
