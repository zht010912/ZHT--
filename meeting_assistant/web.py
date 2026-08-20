from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request
from pydantic import ValidationError as PydanticValidationError

from .ai import AIServiceError, DeepSeekAnalyzer
from .config import Settings
from .db import ConflictError, Database, NotFoundError, ValidationError
from .domain import ActionCreate, ActionUpdate, MeetingCreate, ReviewRequest


def _json_error(code: str, message: str, status: int, *, details: Any = None):
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return jsonify(payload), status


def _validation_details(exc: PydanticValidationError) -> list[dict[str, Any]]:
    details = []
    for item in exc.errors(include_url=False, include_context=False, include_input=False):
        details.append({
            "field": ".".join(str(part) for part in item.get("loc", [])),
            "message": item.get("msg", "输入不合法"),
            "type": item.get("type", "validation_error"),
        })
    return details


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    ai_client: Any | None = None,
) -> Flask:
    root = Path(__file__).resolve().parent.parent
    settings = settings or Settings.from_env(project_root=root)
    database = database or Database(settings.database_path)
    database.initialize(seed_demo=settings.seed_demo)
    ai_client = ai_client or DeepSeekAnalyzer(settings)

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(TESTING=settings.testing, JSON_AS_ASCII=False)
    app.extensions["settings"] = settings
    app.extensions["database"] = database
    app.extensions["ai_client"] = ai_client

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            max_meeting_chars=settings.max_meeting_chars,
        )

    @app.get("/api/health")
    def health():
        return jsonify({
            "status": "ok",
            "database": "ok",
            "model": settings.deepseek_model,
            "api_key_configured": bool(settings.deepseek_api_key),
        })

    @app.get("/api/dashboard")
    def dashboard():
        return jsonify(database.dashboard_stats())

    @app.route("/api/meetings", methods=["GET", "POST"])
    def meetings():
        if request.method == "GET":
            filters = {
                key: value
                for key in ("owner", "status", "due_before", "meeting_type", "q")
                if (value := request.args.get(key, "").strip())
            }
            return jsonify({"items": database.list_meetings(filters), "filters": filters})

        model = MeetingCreate.model_validate(request.get_json(silent=True) or {})
        meeting = database.create_meeting(model.model_dump(mode="json"))
        return jsonify(meeting), 201

    @app.get("/api/meetings/<int:meeting_id>")
    def meeting_detail(meeting_id: int):
        meeting = database.get_meeting(meeting_id)
        if meeting is None:
            raise NotFoundError("会议不存在")
        return jsonify(meeting)

    @app.delete("/api/meetings/<int:meeting_id>")
    def delete_meeting(meeting_id: int):
        return jsonify(database.delete_meeting(meeting_id))

    @app.post("/api/meetings/<int:meeting_id>/actions")
    def create_action(meeting_id: int):
        model = ActionCreate.model_validate(request.get_json(silent=True) or {})
        action, created = database.create_action(meeting_id, model.model_dump(mode="json"))
        return jsonify({"item": action, "created": created}), 201 if created else 200

    @app.patch("/api/actions/<int:action_id>")
    def update_action(action_id: int):
        payload = request.get_json(silent=True) or {}
        if "expected_version" not in payload:
            return _json_error("missing_version", "更新行动项必须携带 expected_version", 422)
        expected_version = int(payload.pop("expected_version"))
        model = ActionUpdate.model_validate(payload)
        action = database.update_action(
            action_id,
            model.model_dump(mode="json", exclude_unset=True),
            expected_version,
        )
        return jsonify(action)

    @app.post("/api/meetings/<int:meeting_id>/analyze")
    def analyze_meeting(meeting_id: int):
        meeting = database.get_meeting(meeting_id)
        if meeting is None:
            raise NotFoundError("会议不存在")
        payload = request.get_json(silent=True) or {}
        prompt_version = payload.get("prompt_version", "optimized")
        if prompt_version not in {"baseline", "optimized"}:
            return _json_error("invalid_prompt_version", "prompt_version 仅支持 baseline 或 optimized", 422)

        run = database.create_analysis_run(meeting_id, settings.deepseek_model, prompt_version)
        try:
            result = ai_client.analyze(meeting, variant=prompt_version)
            proposed_value = result.proposed if hasattr(result, "proposed") else result["proposed"]
            proposed = proposed_value.model_dump(mode="json") if hasattr(proposed_value, "model_dump") else proposed_value
            completed = database.complete_analysis_run(
                run["id"],
                result.raw_response,
                proposed,
                result.warnings,
                result.security_flags,
            )
            return jsonify(completed), 201
        except AIServiceError as exc:
            failed = database.fail_analysis_run(run["id"], exc.code, exc.message)
            return _json_error(exc.code, exc.message, exc.status_code, details={"run": failed})

    @app.post("/api/analysis-runs/<int:run_id>/review")
    def review_analysis(run_id: int):
        model = ReviewRequest.model_validate(request.get_json(silent=True) or {})
        reviewed = database.review_analysis_run(
            run_id,
            model.decision,
            model.final_payload.model_dump(mode="json") if getattr(model, "final_payload", None) is not None and hasattr(model.final_payload, "model_dump") else model.final_payload,
            model.note,
        )
        return jsonify(reviewed)

    @app.errorhandler(PydanticValidationError)
    def handle_pydantic(exc: PydanticValidationError):
        return _json_error("validation_error", "输入校验失败", 422, details=_validation_details(exc))

    @app.errorhandler(NotFoundError)
    def handle_not_found(exc: NotFoundError):
        return _json_error("not_found", str(exc), 404)

    @app.errorhandler(ConflictError)
    def handle_conflict(exc: ConflictError):
        return _json_error("conflict", str(exc), 409)

    @app.errorhandler(ValidationError)
    def handle_domain_validation(exc: ValidationError):
        return _json_error("validation_error", str(exc), 422)

    @app.errorhandler(404)
    def handle_route_not_found(_exc):
        return _json_error("route_not_found", "接口不存在", 404)

    @app.errorhandler(500)
    def handle_unexpected(_exc):
        return _json_error("internal_error", "系统内部错误，请查看服务端日志", 500)

    return app
