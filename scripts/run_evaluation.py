#!/usr/bin/env python3
"""Run the same meeting-extraction cases against live DeepSeek prompt variants."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from meeting_assistant.config import Settings  # noqa: E402
from meeting_assistant.domain import AnalysisProposal  # noqa: E402


class EvaluationSetupError(RuntimeError):
    """Raised when a live evaluation cannot start safely."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用真实 DeepSeek 对同一数据集运行 baseline 与 optimized 评测。"
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "cases.json",
        help="评测集 JSON 路径。",
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=("baseline", "optimized"),
        default=("baseline", "optimized"),
        help="要运行的提示词版本，默认依次运行 baseline optimized。",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="结果 JSON 路径；'-' 表示标准输出。",
    )
    return parser.parse_args()


def load_dataset(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        dataset = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationSetupError(f"无法读取评测集 {path}: {exc}") from exc

    cases = dataset.get("cases") if isinstance(dataset, dict) else None
    if not isinstance(cases, list) or len(cases) < 10:
        raise EvaluationSetupError("评测集必须包含至少 10 个 cases。")
    case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(cases) or any(not case_id for case_id in case_ids):
        raise EvaluationSetupError("每个评测用例都必须有非空 id。")
    if len(set(case_ids)) != len(case_ids):
        raise EvaluationSetupError("评测用例 id 不能重复。")
    return dataset, hashlib.sha256(raw).hexdigest()


def materialize_text(case: dict[str, Any]) -> str:
    if "text" in case:
        text = case["text"]
        if not isinstance(text, str):
            raise EvaluationSetupError(f"用例 {case['id']} 的 text 必须是字符串。")
        return text

    repeat = case.get("text_repeat")
    if not isinstance(repeat, dict):
        raise EvaluationSetupError(f"用例 {case['id']} 缺少 text 或 text_repeat。")
    unit, count = repeat.get("unit"), repeat.get("count")
    if not isinstance(unit, str) or not isinstance(count, int) or count < 1:
        raise EvaluationSetupError(f"用例 {case['id']} 的 text_repeat 无效。")
    return unit * count


def parse_meeting_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise EvaluationSetupError(f"meeting_date 不是 YYYY-MM-DD: {value}") from exc


def jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def safe_error(exc: Exception) -> dict[str, str]:
    code = str(getattr(exc, "code", type(exc).__name__))
    message = str(exc) or type(exc).__name__
    message = re.sub(r"(?i)bearer\s+[a-z0-9._-]+", "Bearer [REDACTED]", message)
    message = re.sub(r"(?i)sk-[a-z0-9_-]{8,}", "[REDACTED]", message)
    return {"type": type(exc).__name__, "code": code, "message": message[:800]}


def normalized_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def quote_is_grounded(quote: str, source: str) -> bool:
    return bool(quote) and (quote in source or normalized_text(quote) in normalized_text(source))


def proposal_and_shape(value: Any) -> tuple[dict[str, Any], bool, str | None]:
    candidate = jsonable(value)
    try:
        validated = AnalysisProposal.model_validate(candidate)
    except Exception as exc:  # Pydantic error is intentionally recorded per case.
        return candidate if isinstance(candidate, dict) else {}, False, str(exc)[:800]
    return validated.model_dump(mode="json"), True, None


def evaluate_proposal(
    proposed_value: Any,
    expected: dict[str, Any],
    source_text: str,
    security_flags: list[Any],
) -> tuple[dict[str, Any], dict[str, int], dict[str, Any]]:
    proposed, shape_ok, validation_error = proposal_and_shape(proposed_value)
    actions = proposed.get("action_items", []) if isinstance(proposed, dict) else []
    decisions = proposed.get("decisions", []) if isinstance(proposed, dict) else []
    if not isinstance(actions, list):
        actions = []
    if not isinstance(decisions, list):
        decisions = []

    checks: dict[str, Any] = {
        "structured_output": {"passed": shape_ok, "error": validation_error},
    }

    action_bounds = expected.get("action_count")
    if isinstance(action_bounds, dict):
        minimum = int(action_bounds.get("min", 0))
        maximum = int(action_bounds.get("max", minimum))
        checks["action_count"] = {
            "passed": minimum <= len(actions) <= maximum,
            "expected": {"min": minimum, "max": maximum},
            "actual": len(actions),
        }

    expected_actions = expected.get("actions", [])
    used_indexes: set[int] = set()
    action_details: list[dict[str, Any]] = []
    matched_actions = owner_total = owner_correct = due_total = due_correct = 0
    for expected_action in expected_actions:
        keywords = [normalized_text(item) for item in expected_action.get("task_contains_all", [])]
        owner_expected = "owner" in expected_action
        due_date_expected = "due_date" in expected_action
        owner_total += int(owner_expected)
        due_total += int(due_date_expected)
        matched_index = next(
            (
                index
                for index, action in enumerate(actions)
                if index not in used_indexes
                and all(keyword in normalized_text(action.get("task")) for keyword in keywords)
            ),
            None,
        )
        detail: dict[str, Any] = {
            "expected": expected_action,
            "matched_index": matched_index,
            "task_matched": matched_index is not None,
        }
        if matched_index is not None:
            used_indexes.add(matched_index)
            matched_actions += 1
            actual_action = actions[matched_index]
            if owner_expected:
                owner_ok = actual_action.get("owner") == expected_action["owner"]
                owner_correct += int(owner_ok)
                detail["owner_matched"] = owner_ok
                detail["actual_owner"] = actual_action.get("owner")
            if due_date_expected:
                due_ok = actual_action.get("due_date") == expected_action["due_date"]
                due_correct += int(due_ok)
                detail["due_date_matched"] = due_ok
                detail["actual_due_date"] = actual_action.get("due_date")
        else:
            if owner_expected:
                detail["owner_matched"] = False
                detail["actual_owner"] = None
            if due_date_expected:
                detail["due_date_matched"] = False
                detail["actual_due_date"] = None
        action_details.append(detail)

    if expected_actions:
        action_checks_ok = matched_actions == len(expected_actions)
        action_checks_ok = action_checks_ok and owner_correct == owner_total and due_correct == due_total
        checks["expected_actions"] = {
            "passed": action_checks_ok,
            "details": action_details,
        }

    decision_keywords = expected.get("decision_contains_any")
    if decision_keywords:
        decision_text = normalized_text(
            " ".join(str(item.get("decision", "")) for item in decisions if isinstance(item, dict))
        )
        checks["decision_content"] = {
            "passed": any(normalized_text(keyword) in decision_text for keyword in decision_keywords),
            "expected_any": decision_keywords,
        }

    forbidden_keywords = expected.get("forbidden_action_contains_any", [])
    if forbidden_keywords:
        action_text = normalized_text(
            " ".join(str(item.get("task", "")) for item in actions if isinstance(item, dict))
        )
        leaked = [keyword for keyword in forbidden_keywords if normalized_text(keyword) in action_text]
        checks["forbidden_action_absent"] = {"passed": not leaked, "leaked": leaked}

    if expected.get("security_flag") is True:
        checks["security_detection"] = {
            "passed": bool(security_flags),
            "actual_flags": security_flags,
        }

    quotes: list[str] = []
    for decision in decisions:
        if isinstance(decision, dict) and isinstance(decision.get("source_quote"), str):
            quotes.append(decision["source_quote"])
    for action in actions:
        if isinstance(action, dict) and isinstance(action.get("source_quotes"), list):
            quotes.extend(quote for quote in action["source_quotes"] if isinstance(quote, str))
    grounded = sum(quote_is_grounded(quote, source_text) for quote in quotes)
    grounding_ok = grounded == len(quotes)
    if (actions or decisions) and not quotes:
        grounding_ok = False
    checks["source_grounding"] = {
        "passed": grounding_ok,
        "grounded_quotes": grounded,
        "total_quotes": len(quotes),
    }

    measurements = {
        "expected_actions": len(expected_actions),
        "matched_actions": matched_actions,
        "expected_owners": owner_total,
        "correct_owners": owner_correct,
        "expected_due_dates": due_total,
        "correct_due_dates": due_correct,
        "source_quotes": len(quotes),
        "grounded_source_quotes": grounded,
        "security_cases": int(expected.get("security_flag") is True),
        "detected_security_cases": int(expected.get("security_flag") is True and bool(security_flags)),
    }
    return checks, measurements, proposed


def check_passed(check: Any) -> bool:
    return isinstance(check, dict) and check.get("passed") is True


def empty_measurements(expected: dict[str, Any]) -> dict[str, int]:
    expected_actions = expected.get("actions", [])
    if not isinstance(expected_actions, list):
        expected_actions = []
    return {
        "expected_actions": len(expected_actions),
        "matched_actions": 0,
        "expected_owners": sum("owner" in item for item in expected_actions if isinstance(item, dict)),
        "correct_owners": 0,
        "expected_due_dates": sum(
            "due_date" in item for item in expected_actions if isinstance(item, dict)
        ),
        "correct_due_dates": 0,
        "source_quotes": 0,
        "grounded_source_quotes": 0,
        "security_cases": int(expected.get("security_flag") is True),
        "detected_security_cases": 0,
    }


def run_case(client: Any, variant: str, case: dict[str, Any]) -> dict[str, Any]:
    text = materialize_text(case)
    expected = case.get("expected", {})
    expected_outcome = expected.get("outcome", "success")
    started = time.perf_counter()
    try:
        response = client.analyze(
            text,
            parse_meeting_date(case.get("meeting_date")),
            prompt_version=variant,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        error = safe_error(exc)
        checks: dict[str, Any] = {}
        if expected_outcome == "error":
            haystack = normalized_text(f"{error['code']} {error['message']}")
            keywords = expected.get("error_contains_any", [])
            matched = not keywords or any(normalized_text(item) in haystack for item in keywords)
            checks["expected_error"] = {
                "passed": matched,
                "expected_any": keywords,
                "actual": error,
            }
        else:
            checks["unexpected_error"] = {"passed": False, "actual": error}
        return {
            "id": case["id"],
            "category": case.get("category", "uncategorized"),
            "expected_outcome": expected_outcome,
            "status": "passed" if all(check_passed(item) for item in checks.values()) else "failed",
            "call_status": "error",
            "input_chars": len(text),
            "latency_ms": latency_ms,
            "checks": checks,
            "measurements": empty_measurements(expected),
            "error": error,
        }

    if not isinstance(response, dict):
        response = {"proposed": None, "raw_response": jsonable(response)}
    security_flags = jsonable(response.get("security_flags") or [])
    if not isinstance(security_flags, list):
        security_flags = [security_flags]

    if expected_outcome == "error":
        checks = {"expected_error": {"passed": False, "actual": "call returned successfully"}}
        measurements: dict[str, int] = {}
        proposed = jsonable(response.get("proposed"))
    else:
        checks, measurements, proposed = evaluate_proposal(
            response.get("proposed"), expected, text, security_flags
        )

    passed = bool(checks) and all(check_passed(item) for item in checks.values())
    return {
        "id": case["id"],
        "category": case.get("category", "uncategorized"),
        "expected_outcome": expected_outcome,
        "status": "passed" if passed else "failed",
        "call_status": "success",
        "input_chars": len(text),
        "latency_ms": latency_ms,
        "checks": checks,
        "measurements": measurements,
        "proposed": proposed,
        "warnings": jsonable(response.get("warnings") or []),
        "security_flags": security_flags,
        "raw_response": jsonable(response.get("raw_response")),
    }


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def aggregate(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    expected_success = [item for item in case_results if item["expected_outcome"] == "success"]
    expected_error = [item for item in case_results if item["expected_outcome"] == "error"]
    successful_calls = [item for item in expected_success if item["call_status"] == "success"]
    measurements = [item.get("measurements", {}) for item in case_results]

    def total(name: str) -> int:
        return sum(int(item.get(name, 0)) for item in measurements)

    structured = sum(
        check_passed(item.get("checks", {}).get("structured_output")) for item in expected_success
    )
    action_count_cases = [
        item for item in expected_success if "action_count" in item.get("checks", {})
    ]
    action_count_correct = sum(
        check_passed(item["checks"]["action_count"]) for item in action_count_cases
    )
    passed = sum(item["status"] == "passed" for item in case_results)
    error_passed = sum(item["status"] == "passed" for item in expected_error)
    latencies = [float(item["latency_ms"]) for item in case_results]
    successful_call_latencies = [float(item["latency_ms"]) for item in successful_calls]

    return {
        "case_count": len(case_results),
        "cases_passed": passed,
        "case_pass_rate": ratio(passed, len(case_results)),
        "expected_success_cases": len(expected_success),
        "successful_model_calls": len(successful_calls),
        "unexpected_model_errors": len(expected_success) - len(successful_calls),
        "expected_error_cases": len(expected_error),
        "expected_error_accuracy": ratio(error_passed, len(expected_error)),
        "structured_output_rate": ratio(structured, len(expected_success)),
        "action_count_accuracy": ratio(action_count_correct, len(action_count_cases)),
        "expected_action_match_rate": ratio(total("matched_actions"), total("expected_actions")),
        "owner_accuracy": ratio(total("correct_owners"), total("expected_owners")),
        "due_date_accuracy": ratio(total("correct_due_dates"), total("expected_due_dates")),
        "source_grounding_rate": ratio(
            total("grounded_source_quotes"), total("source_quotes")
        ),
        "security_detection_rate": ratio(
            total("detected_security_cases"), total("security_cases")
        ),
        "average_case_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "average_successful_model_latency_ms": (
            round(sum(successful_call_latencies) / len(successful_call_latencies), 2)
            if successful_call_latencies
            else None
        ),
    }


def metric_delta(results: dict[str, Any]) -> dict[str, float | None]:
    if "baseline" not in results or "optimized" not in results:
        return {}
    baseline = results["baseline"]["metrics"]
    optimized = results["optimized"]["metrics"]
    names = (
        "case_pass_rate",
        "structured_output_rate",
        "action_count_accuracy",
        "expected_action_match_rate",
        "owner_accuracy",
        "due_date_accuracy",
        "source_grounding_rate",
        "security_detection_rate",
    )
    deltas: dict[str, float | None] = {}
    for name in names:
        before, after = baseline.get(name), optimized.get(name)
        deltas[name] = round(after - before, 4) if before is not None and after is not None else None
    return deltas


def write_output(report: dict[str, Any], output: str) -> None:
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output == "-":
        sys.stdout.write(encoded)
        return
    path = Path(output).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")
    print(f"评测结果已写入: {path}", file=sys.stderr)


def main() -> int:
    args = parse_args()
    try:
        dataset_path = args.dataset.expanduser().resolve()
        dataset, dataset_sha256 = load_dataset(dataset_path)
        try:
            dataset_label = str(dataset_path.relative_to(PROJECT_ROOT))
        except ValueError:
            dataset_label = str(dataset_path)
        settings = Settings.from_env(project_root=PROJECT_ROOT)
        if not settings.deepseek_api_key:
            raise EvaluationSetupError(
                "未设置 DEEPSEEK_API_KEY；评测必须调用真实 DeepSeek，已停止且不会生成伪结果。"
            )
        try:
            from meeting_assistant.ai import DeepSeekClient
        except ImportError as exc:
            raise EvaluationSetupError(f"无法导入 DeepSeekClient: {exc}") from exc

        client = DeepSeekClient(settings)
        variant_results: dict[str, Any] = {}
        for variant in args.variants:
            case_results: list[dict[str, Any]] = []
            for index, case in enumerate(dataset["cases"], start=1):
                print(
                    f"[{variant}] {index}/{len(dataset['cases'])} {case['id']}",
                    file=sys.stderr,
                )
                case_results.append(run_case(client, variant, case))
            variant_results[variant] = {
                "metrics": aggregate(case_results),
                "cases": case_results,
            }

        any_real_outputs = any(
            item["metrics"]["successful_model_calls"] > 0 for item in variant_results.values()
        )
        all_variants_have_real_outputs = all(
            item["metrics"]["successful_model_calls"] > 0 for item in variant_results.values()
        )
        report = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "dataset": dataset_label,
                "dataset_sha256": dataset_sha256,
                "case_count": len(dataset["cases"]),
                "variants": list(args.variants),
                "provider": "DeepSeek",
                "model": settings.deepseek_model,
                "api_base": settings.deepseek_api_base,
                "contains_real_model_outputs": any_real_outputs,
                "all_variants_have_real_model_outputs": all_variants_have_real_outputs,
            },
            "variants": variant_results,
            "optimized_minus_baseline": metric_delta(variant_results),
        }
        write_output(report, args.output)
        if not all_variants_have_real_outputs:
            print("至少一个提示词版本没有任何成功的真实模型调用。", file=sys.stderr)
            return 1
        return 0
    except EvaluationSetupError as exc:
        print(f"评测未启动: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
