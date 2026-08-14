# Implementation Contract

This file coordinates the parallel implementation. Keep the solution small and traceable to the task.

## Runtime

- Python 3.11+
- Flask + built-in sqlite3 + Pydantic v2 + httpx + pytest
- No frontend build step
- No API key in files; read `DEEPSEEK_API_KEY` only

## Project modules

- `meeting_assistant/config.py`: environment-backed settings
- `meeting_assistant/domain.py`: Pydantic request/proposal models
- `meeting_assistant/db.py`: schema, repository, seed, transactions
- `meeting_assistant/guardrails.py`: grounding, injection detection, date resolution, dedup
- `meeting_assistant/ai.py`: DeepSeek client, prompts, error mapping
- `meeting_assistant/web.py`: Flask app factory and JSON routes
- `meeting_assistant/templates/index.html`, `static/*`: one-page demo UI

## Core database contract

The repository exposes a `Database(path)` object with these public methods:

- `initialize(seed_demo: bool = True) -> None`
- `create_meeting(data: dict) -> dict`
- `list_meetings(filters: dict | None = None) -> list[dict]`
- `get_meeting(meeting_id: int) -> dict | None`
- `create_action(meeting_id: int, data: dict) -> tuple[dict, bool]`
- `update_action(action_id: int, data: dict, expected_version: int) -> dict`
- `create_analysis_run(meeting_id: int, model: str, prompt_version: str) -> dict`
- `complete_analysis_run(run_id: int, raw_response: str, proposed: dict, warnings: list[str], security_flags: list[str]) -> dict`
- `fail_analysis_run(run_id: int, code: str, message: str) -> dict`
- `review_analysis_run(run_id: int, decision: str, final_payload: dict | None, note: str = "") -> dict`
- `dashboard_stats() -> dict`

Repository exceptions: `NotFoundError`, `ConflictError`, `ValidationError`.

## Proposal JSON contract

```json
{
  "summary": "string",
  "decisions": [
    {"decision": "string", "source_quote": "literal excerpt"}
  ],
  "action_items": [
    {
      "task": "string",
      "owner": "name or 待确认",
      "due_date_text": "literal expression or 待确认",
      "due_date": "YYYY-MM-DD or 待确认",
      "source_quotes": ["literal excerpt"],
      "confidence": 0.0
    }
  ]
}
```

Only a confirmed `final_payload` creates official action rows. Raw and final JSON remain separate.

## API contract

- `GET /api/health`
- `GET /api/dashboard`
- `POST /api/meetings`
- `GET /api/meetings`
- `GET /api/meetings/<id>`
- `POST /api/meetings/<id>/actions`
- `PATCH /api/actions/<id>` with `expected_version`
- `POST /api/meetings/<id>/analyze`
- `POST /api/analysis-runs/<id>/review`

All errors use `{"error":{"code":"...","message":"..."}}` and never expose credentials or raw upstream bodies.

## Acceptance priorities

1. Persistence, manual CRUD, filter, 3 meetings + 8 actions.
2. Real DeepSeek JSON extraction with source grounding.
3. Pending markers for uncertain owner/date; deterministic date resolution.
4. AI proposal review: confirm/edit/reject, raw/final audit.
5. Empty/long input, duplicate action, prompt injection, API failure, one-click tests.
6. Ten-case baseline/optimized live evaluation harness.

