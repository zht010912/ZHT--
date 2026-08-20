from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from pydantic import ValidationError as PydanticValidationError

from .domain import (
    ActionCreate,
    ActionUpdate,
    AnalysisProposal,
    MeetingCreate,
    ReviewRequest,
)


class NotFoundError(Exception):
    """The requested repository object does not exist."""


class ConflictError(Exception):
    """The requested change conflicts with current persisted state."""


class ValidationError(Exception):
    """Repository input does not satisfy the domain contract."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    meeting_type TEXT NOT NULL,
    meeting_date TEXT NOT NULL,
    content TEXT NOT NULL,
    seed_key TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (length(trim(title)) > 0),
    CHECK (length(trim(content)) > 0)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    raw_response TEXT,
    proposed_json TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    security_flags_json TEXT NOT NULL DEFAULT '[]',
    error_code TEXT,
    error_message TEXT,
    review_decision TEXT,
    final_payload_json TEXT,
    review_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT,
    reviewed_at TEXT,
    CHECK (status IN ('running', 'succeeded', 'failed', 'confirmed', 'edited', 'rejected')),
    CHECK (review_decision IS NULL OR review_decision IN ('confirm', 'edit', 'reject'))
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    task TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '待确认',
    due_date TEXT NOT NULL DEFAULT '待确认',
    status TEXT NOT NULL DEFAULT 'pending',
    source_quotes_json TEXT NOT NULL DEFAULT '[]',
    analysis_run_id INTEGER REFERENCES analysis_runs(id) ON DELETE SET NULL,
    fingerprint TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT,
    UNIQUE (meeting_id, fingerprint),
    CHECK (length(trim(task)) > 0),
    CHECK (status IN ('pending', 'completed')),
    CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_actions_meeting ON actions(meeting_id);
CREATE INDEX IF NOT EXISTS idx_actions_owner_status ON actions(owner, status);
CREATE INDEX IF NOT EXISTS idx_actions_due_date ON actions(due_date);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_meeting ON analysis_runs(meeting_id);
"""


_DEMO_MEETINGS = (
    {
        "seed_key": "demo-product-review",
        "title": "产品发布评审会",
        "meeting_type": "评审会",
        "meeting_date": "2026-08-11",
        "content": (
            "会议决定采用方案 B。王芳负责接口联调，8 月 15 日前完成；"
            "陈浩负责整理发布检查单，8 月 16 日前完成。"
        ),
        "actions": (
            ("完成接口联调", "王芳", "2026-08-15", "pending", ["王芳负责接口联调，8 月 15 日前完成"]),
            ("整理发布检查单", "陈浩", "2026-08-16", "completed", ["陈浩负责整理发布检查单"]),
            ("复核回滚方案", "李敏", "2026-08-17", "pending", ["李敏复核回滚方案"]),
        ),
    },
    {
        "seed_key": "demo-api-sync",
        "title": "接口联调周会",
        "meeting_type": "项目例会",
        "meeting_date": "2026-08-12",
        "content": (
            "联调环境已经恢复。赵磊周五前补齐超时重试测试，孙悦更新接口文档；"
            "监控阈值负责人尚未明确。"
        ),
        "actions": (
            ("补齐超时重试测试", "赵磊", "2026-08-14", "pending", ["赵磊周五前补齐超时重试测试"]),
            ("更新接口文档", "孙悦", "待确认", "pending", ["孙悦更新接口文档"]),
            ("确认监控阈值负责人", "待确认", "待确认", "pending", ["监控阈值负责人尚未明确"]),
        ),
    },
    {
        "seed_key": "demo-security",
        "title": "数据安全专项会",
        "meeting_type": "专项会议",
        "meeting_date": "2026-08-13",
        "content": "决定日志默认脱敏。周宁负责检查密钥轮换，刘洋完成权限矩阵复核。",
        "actions": (
            ("检查密钥轮换", "周宁", "2026-08-18", "completed", ["周宁负责检查密钥轮换"]),
            ("完成权限矩阵复核", "刘洋", "2026-08-19", "pending", ["刘洋完成权限矩阵复核"]),
        ),
    },
)


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_load(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _fingerprint_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _action_fingerprint(task: str, owner: str, due_date: str) -> str:
    source = "\x1f".join(
        (_fingerprint_part(task), _fingerprint_part(owner), _fingerprint_part(due_date))
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _validated(model_type, data: dict[str, Any]) -> dict[str, Any]:
    try:
        return model_type.model_validate(data).model_dump(mode="json")
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc


class Database:
    def __init__(self, path: str | Path):
        raw_path = str(path)
        self.path = raw_path
        self._uri = False
        self._anchor: sqlite3.Connection | None = None
        if raw_path == ":memory:":
            self.path = f"file:meeting-assistant-{id(self)}?mode=memory&cache=shared"
            self._uri = True
            self._anchor = self._new_connection()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            uri=self._uri,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._new_connection()
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except Exception:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self, seed_demo: bool = True) -> None:
        if not self._uri:
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        with self._connection(write=True) as connection:
            connection.executescript(_SCHEMA)
            if seed_demo:
                self._seed_demo(connection)

    def _seed_demo(self, connection: sqlite3.Connection) -> None:
        for meeting in _DEMO_MEETINGS:
            connection.execute(
                """
                INSERT INTO meetings (title, meeting_type, meeting_date, content, seed_key)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(seed_key) DO NOTHING
                """,
                (
                    meeting["title"],
                    meeting["meeting_type"],
                    meeting["meeting_date"],
                    meeting["content"],
                    meeting["seed_key"],
                ),
            )
            row = connection.execute(
                "SELECT id FROM meetings WHERE seed_key = ?", (meeting["seed_key"],)
            ).fetchone()
            assert row is not None
            for task, owner, due_date, status, source_quotes in meeting["actions"]:
                self._insert_action(
                    connection,
                    row["id"],
                    {
                        "task": task,
                        "owner": owner,
                        "due_date": due_date,
                        "status": status,
                        "source_quotes": source_quotes,
                        "analysis_run_id": None,
                    },
                )

    def create_meeting(self, data: dict) -> dict:
        values = _validated(MeetingCreate, data)
        meeting_date = values["meeting_date"] or date.today().isoformat()
        with self._connection(write=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO meetings (title, meeting_type, meeting_date, content)
                VALUES (?, ?, ?, ?)
                """,
                (values["title"], values["meeting_type"], meeting_date, values["content"]),
            )
            row = connection.execute(
                "SELECT * FROM meetings WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            assert row is not None
            return self._meeting_dict(row)

    def list_meetings(self, filters: dict | None = None) -> list[dict]:
        filters = dict(filters or {})
        where: list[str] = []
        params: list[Any] = []

        if filters.get("meeting_type"):
            where.append("m.meeting_type = ?")
            params.append(str(filters["meeting_type"]).strip())
        if filters.get("status"):
            status = str(filters["status"]).strip()
            if status not in {"pending", "completed"}:
                raise ValidationError("status 必须是 pending 或 completed")
            where.append(
                "EXISTS (SELECT 1 FROM actions af WHERE af.meeting_id = m.id AND af.status = ?)"
            )
            params.append(status)
        if filters.get("owner"):
            where.append(
                "EXISTS (SELECT 1 FROM actions af WHERE af.meeting_id = m.id "
                "AND lower(af.owner) = lower(?))"
            )
            params.append(str(filters["owner"]).strip())
        if filters.get("due_before"):
            due_before = self._iso_date_filter(filters["due_before"], "due_before")
            where.append(
                "EXISTS (SELECT 1 FROM actions af WHERE af.meeting_id = m.id "
                "AND af.due_date != '待确认' AND af.due_date <= ?)"
            )
            params.append(due_before)
        if filters.get("due_after"):
            due_after = self._iso_date_filter(filters["due_after"], "due_after")
            where.append(
                "EXISTS (SELECT 1 FROM actions af WHERE af.meeting_id = m.id "
                "AND af.due_date != '待确认' AND af.due_date >= ?)"
            )
            params.append(due_after)
        query_value = filters.get("query") or filters.get("q")
        if query_value:
            query = f"%{str(query_value).strip()}%"
            where.append("(m.title LIKE ? OR m.content LIKE ?)")
            params.extend((query, query))

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""
            SELECT m.*,
                   COUNT(a.id) AS action_count,
                   COALESCE(SUM(CASE WHEN a.status = 'completed' THEN 1 ELSE 0 END), 0)
                       AS completed_action_count
            FROM meetings m
            LEFT JOIN actions a ON a.meeting_id = m.id
            {where_sql}
            GROUP BY m.id
            ORDER BY m.meeting_date DESC, m.id DESC
        """
        with self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
            return [self._meeting_dict(row) for row in rows]

    def get_meeting(self, meeting_id: int) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
            if row is None:
                return None
            result = self._meeting_dict(row)
            action_rows = connection.execute(
                "SELECT * FROM actions WHERE meeting_id = ? ORDER BY id", (meeting_id,)
            ).fetchall()
            run_rows = connection.execute(
                "SELECT * FROM analysis_runs WHERE meeting_id = ? ORDER BY id DESC",
                (meeting_id,),
            ).fetchall()
            result["actions"] = [self._action_dict(action) for action in action_rows]
            result["analysis_runs"] = [self._analysis_run_dict(run) for run in run_rows]
            return result

    def create_action(self, meeting_id: int, data: dict) -> tuple[dict, bool]:
        values = _validated(ActionCreate, data)
        with self._connection(write=True) as connection:
            self._require_meeting(connection, meeting_id)
            return self._insert_action(connection, meeting_id, values)

    def _insert_action(
        self, connection: sqlite3.Connection, meeting_id: int, values: dict[str, Any]
    ) -> tuple[dict, bool]:
        fingerprint = _action_fingerprint(
            values["task"], values.get("owner") or "待确认", values.get("due_date") or "待确认"
        )
        completed_at = (
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
            if values.get("status", "pending") == "completed"
            else "NULL"
        )
        cursor = connection.execute(
            f"""
            INSERT INTO actions (
                meeting_id, task, owner, due_date, status, source_quotes_json,
                analysis_run_id, fingerprint, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, {completed_at})
            ON CONFLICT(meeting_id, fingerprint) DO NOTHING
            """,
            (
                meeting_id,
                values["task"],
                values.get("owner") or "待确认",
                values.get("due_date") or "待确认",
                values.get("status") or "pending",
                _json_dump(values.get("source_quotes") or []),
                values.get("analysis_run_id"),
                fingerprint,
            ),
        )
        created = cursor.rowcount == 1
        if created:
            row = connection.execute(
                "SELECT * FROM actions WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM actions WHERE meeting_id = ? AND fingerprint = ?",
                (meeting_id, fingerprint),
            ).fetchone()
        assert row is not None
        return self._action_dict(row), created

    def update_action(self, action_id: int, data: dict, expected_version: int) -> dict:
        if type(expected_version) is not int or expected_version < 1:
            raise ValidationError("expected_version 必须是正整数")
        values = _validated(ActionUpdate, data)
        changes = {key: value for key, value in values.items() if value is not None}
        if not changes:
            raise ValidationError("至少提供一个待更新字段")

        with self._connection(write=True) as connection:
            current = connection.execute(
                "SELECT * FROM actions WHERE id = ?", (action_id,)
            ).fetchone()
            if current is None:
                raise NotFoundError(f"行动项 {action_id} 不存在")
            if current["version"] != expected_version:
                raise ConflictError(
                    f"行动项已被修改，当前版本为 {current['version']}"
                )

            merged = dict(current)
            merged.update(changes)
            fingerprint = _action_fingerprint(
                merged["task"], merged["owner"], merged["due_date"]
            )
            completed_at_sql = "completed_at"
            if "status" in changes:
                completed_at_sql = (
                    "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
                    if changes["status"] == "completed"
                    else "NULL"
                )

            assignments: list[str] = []
            params: list[Any] = []
            for field in ("task", "owner", "due_date", "status"):
                if field in changes:
                    assignments.append(f"{field} = ?")
                    params.append(changes[field])
            if "source_quotes" in changes:
                assignments.append("source_quotes_json = ?")
                params.append(_json_dump(changes["source_quotes"]))
            assignments.extend(
                [
                    "fingerprint = ?",
                    "version = version + 1",
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                    f"completed_at = {completed_at_sql}",
                ]
            )
            params.extend((fingerprint, action_id, expected_version))
            try:
                cursor = connection.execute(
                    f"UPDATE actions SET {', '.join(assignments)} "
                    "WHERE id = ? AND version = ?",
                    params,
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("更新后与现有行动项重复") from exc
            if cursor.rowcount != 1:
                raise ConflictError("行动项版本冲突")
            row = connection.execute(
                "SELECT * FROM actions WHERE id = ?", (action_id,)
            ).fetchone()
            assert row is not None
            return self._action_dict(row)

    def create_analysis_run(self, meeting_id: int, model: str, prompt_version: str) -> dict:
        model = str(model).strip()
        prompt_version = str(prompt_version).strip()
        if not model or not prompt_version:
            raise ValidationError("model 和 prompt_version 不能为空")
        with self._connection(write=True) as connection:
            self._require_meeting(connection, meeting_id)
            cursor = connection.execute(
                """
                INSERT INTO analysis_runs (meeting_id, model, prompt_version)
                VALUES (?, ?, ?)
                """,
                (meeting_id, model, prompt_version),
            )
            row = connection.execute(
                "SELECT * FROM analysis_runs WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            assert row is not None
            return self._analysis_run_dict(row)

    def complete_analysis_run(
        self,
        run_id: int,
        raw_response: str,
        proposed: dict,
        warnings: list[str],
        security_flags: list[str],
    ) -> dict:
        proposal = _validated(AnalysisProposal, proposed)
        if not isinstance(raw_response, str):
            raise ValidationError("raw_response 必须是字符串")
        warning_values = self._string_list(warnings, "warnings")
        security_values = self._string_list(security_flags, "security_flags")
        with self._connection(write=True) as connection:
            run = self._require_run(connection, run_id)
            if run["status"] != "running":
                raise ConflictError("只有运行中的分析可以标记成功")
            connection.execute(
                """
                UPDATE analysis_runs
                SET status = 'succeeded', raw_response = ?, proposed_json = ?,
                    warnings_json = ?, security_flags_json = ?,
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (
                    raw_response,
                    _json_dump(proposal),
                    _json_dump(warning_values),
                    _json_dump(security_values),
                    run_id,
                ),
            )
            row = self._require_run(connection, run_id)
            return self._analysis_run_dict(row)

    def fail_analysis_run(self, run_id: int, code: str, message: str) -> dict:
        code = str(code).strip()
        message = str(message).strip()
        if not code or not message:
            raise ValidationError("失败代码和消息不能为空")
        with self._connection(write=True) as connection:
            run = self._require_run(connection, run_id)
            if run["status"] != "running":
                raise ConflictError("只有运行中的分析可以标记失败")
            connection.execute(
                """
                UPDATE analysis_runs
                SET status = 'failed', error_code = ?, error_message = ?,
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (code, message, run_id),
            )
            row = self._require_run(connection, run_id)
            return self._analysis_run_dict(row)

    def review_analysis_run(
        self,
        run_id: int,
        decision: str,
        final_payload: dict | None,
        note: str = "",
    ) -> dict:
        request_data = {
            "decision": decision,
            "final_payload": final_payload,
            "note": note,
        }
        request = _validated(ReviewRequest, request_data)
        with self._connection(write=True) as connection:
            run = self._require_run(connection, run_id)
            if run["status"] != "succeeded":
                raise ConflictError("只有待审核的成功分析可以审核")

            review_decision = request["decision"]
            final: dict[str, Any] | None = request["final_payload"]
            if review_decision == "confirm" and final is None:
                final = _json_load(run["proposed_json"], None)
                if final is None:
                    raise ValidationError("分析结果缺少可确认的提案")
            if final is not None:
                final = _validated(AnalysisProposal, final)

            official_actions: list[dict[str, Any]] = []
            if review_decision in {"confirm", "edit"}:
                assert final is not None
                for item in final["action_items"]:
                    action, created = self._insert_action(
                        connection,
                        run["meeting_id"],
                        {
                            "task": item["task"],
                            "owner": item["owner"],
                            "due_date": item["due_date"],
                            "status": "pending",
                            "source_quotes": item["source_quotes"],
                            "analysis_run_id": run_id,
                        },
                    )
                    action["created"] = created
                    official_actions.append(action)

            status = {
                "confirm": "confirmed",
                "edit": "edited",
                "reject": "rejected",
            }[review_decision]
            connection.execute(
                """
                UPDATE analysis_runs
                SET status = ?, review_decision = ?, final_payload_json = ?,
                    review_note = ?, reviewed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (
                    status,
                    review_decision,
                    _json_dump(final) if final is not None else None,
                    request["note"],
                    run_id,
                ),
            )
            reviewed = self._analysis_run_dict(self._require_run(connection, run_id))
            reviewed["official_actions"] = official_actions
            reviewed["created_action_count"] = sum(
                1 for action in official_actions if action["created"]
            )
            return reviewed

    def dashboard_stats(self) -> dict:
        with self._connection() as connection:
            meeting_count = connection.execute(
                "SELECT COUNT(*) FROM meetings"
            ).fetchone()[0]
            action_counts = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(status = 'pending'), 0) AS pending,
                       COALESCE(SUM(status = 'completed'), 0) AS completed
                FROM actions
                """
            ).fetchone()
            run_counts = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(status = 'succeeded'), 0) AS awaiting_review,
                       COALESCE(SUM(status = 'failed'), 0) AS failed,
                       COALESCE(SUM(status IN ('confirmed', 'edited')), 0) AS accepted
                FROM analysis_runs
                """
            ).fetchone()
            return {
                "meetings": int(meeting_count),
                "actions": int(action_counts["total"]),
                "pending_actions": int(action_counts["pending"]),
                "completed_actions": int(action_counts["completed"]),
                "completion_rate": (
                    int(action_counts["completed"]) / int(action_counts["total"])
                    if action_counts["total"]
                    else 0.0
                ),
                "analysis_runs": int(run_counts["total"]),
                "awaiting_review": int(run_counts["awaiting_review"]),
                "pending_reviews": int(run_counts["awaiting_review"]),
                "failed_analyses": int(run_counts["failed"]),
                "accepted_analyses": int(run_counts["accepted"]),
            }

    @staticmethod
    def _iso_date_filter(value: Any, field_name: str) -> str:
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except ValueError as exc:
            raise ValidationError(f"{field_name} 必须是 YYYY-MM-DD") from exc

    @staticmethod
    def _string_list(value: Any, field_name: str) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValidationError(f"{field_name} 必须是字符串数组")
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @staticmethod
    def _require_meeting(connection: sqlite3.Connection, meeting_id: int) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM meetings WHERE id = ?", (meeting_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"会议 {meeting_id} 不存在")
        return row

    @staticmethod
    def _require_run(connection: sqlite3.Connection, run_id: int) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM analysis_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"分析任务 {run_id} 不存在")
        return row

    @staticmethod
    def _meeting_dict(row: sqlite3.Row) -> dict:
        result = dict(row)
        result.pop("seed_key", None)
        if "action_count" in result:
            result["action_count"] = int(result["action_count"])
            result["completed_action_count"] = int(result["completed_action_count"])
            result["completed_actions"] = result["completed_action_count"]
            result["pending_actions"] = (
                result["action_count"] - result["completed_action_count"]
            )
        return result

    @staticmethod
    def _action_dict(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["source_quotes"] = _json_load(result.pop("source_quotes_json", None), [])
        result["source_kind"] = (
            "ai_confirmed" if result.get("analysis_run_id") is not None else "manual"
        )
        return result

    @staticmethod
    def _analysis_run_dict(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["proposed"] = _json_load(result.pop("proposed_json", None), None)
        result["warnings"] = _json_load(result.pop("warnings_json", None), [])
        result["security_flags"] = _json_load(
            result.pop("security_flags_json", None), []
        )
        result["final_payload"] = _json_load(
            result.pop("final_payload_json", None), None
        )
        return result
