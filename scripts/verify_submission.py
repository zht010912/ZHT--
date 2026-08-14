#!/usr/bin/env python3
"""Fast, deterministic checks before packaging the submission."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "app.py",
    "README.md",
    ".gitignore",
    "requirements.txt",
    "setup.ps1",
    "run.ps1",
    "test.ps1",
    "meeting_assistant/web.py",
    "meeting_assistant/db.py",
    "meeting_assistant/ai.py",
    "meeting_assistant/guardrails.py",
    "meeting_assistant/templates/index.html",
    "meeting_assistant/static/app.js",
    "meeting_assistant/static/style.css",
    "tests/test_db.py",
    "tests/test_ai.py",
    "tests/test_web.py",
    "evaluation/cases.json",
    "evaluation/results.json",
    "scripts/live_smoke.py",
    "docs/设计与协作说明.md",
    "docs/风险与加固清单.md",
    "docs/API说明.md",
    "docs/测试报告.md",
    "docs/评测报告.md",
    "docs/演示脚本.md",
    "docs/提交清单.md",
    "docs/成果索引.md",
)
FORBIDDEN_DIRS = {".venv", ".pytest_cache", ".test-tmp", "__pycache__"}
SKIP_DIRS = FORBIDDEN_DIRS | {".git"}
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".js", ".css", ".html", ".ps1",
    ".example", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)authorization\s*:\s*bearer\s+(?!\$|\{|\[REDACTED\]|replace)[A-Za-z0-9._-]{12,}"),
)


def forbidden_artifacts():
    """Yield (kind, path) findings that must not enter a submission."""
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if ".git" in relative.parts:
            continue
        if any(part in FORBIDDEN_DIRS for part in relative.parts[:-1]):
            continue
        if path.is_dir() and path.name in FORBIDDEN_DIRS:
            yield "runtime", relative
            continue
        if not path.is_file():
            continue

        name = path.name.lower()
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            yield "credential", relative
        elif name.endswith((".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")):
            yield "runtime", relative


def text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name == ".env.example":
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(description="检查源码完整性、评测证据和提交安全性")
    parser.add_argument(
        "--strict-clean",
        action="store_true",
        help="提交打包模式：数据库、缓存、虚拟环境等本地运行物也会导致失败",
    )
    args = parser.parse_args()
    failures: list[str] = []
    runtime_artifacts: list[Path] = []

    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            failures.append(f"缺少必需文件：{relative}")

    for kind, relative in forbidden_artifacts():
        if kind == "credential":
            failures.append(f"禁止提交环境或凭据文件：{relative}")
        elif args.strict_clean:
            failures.append(f"严格提交模式禁止本地运行物：{relative}")
        else:
            runtime_artifacts.append(relative)

    dataset_path = ROOT / "evaluation" / "cases.json"
    if dataset_path.is_file():
        try:
            dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
            cases = dataset.get("cases", [])
            ids = [item.get("id") for item in cases if isinstance(item, dict)]
            if len(cases) < 10:
                failures.append(f"评测用例不足 10 条：当前 {len(cases)} 条")
            if len(ids) != len(set(ids)):
                failures.append("评测用例 ID 存在重复")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            failures.append(f"评测集无法解析：{exc}")

    results_path = ROOT / "evaluation" / "results.json"
    if results_path.is_file():
        try:
            results = json.loads(results_path.read_text(encoding="utf-8"))
            metadata = results.get("metadata", {})
            variants = results.get("variants", {})
            if metadata.get("case_count", 0) < 10:
                failures.append("评测结果记录的用例不足 10 条")
            if metadata.get("contains_real_model_outputs") is not True:
                failures.append("评测结果未声明包含真实模型输出")
            for variant in ("baseline", "optimized"):
                variant_result = variants.get(variant, {})
                if not variant_result.get("metrics") or len(variant_result.get("cases", [])) < 10:
                    failures.append(f"评测结果缺少可展示的 {variant} 指标或逐例记录")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            failures.append(f"评测结果无法解析：{exc}")

    for path in text_files():
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            failures.append(f"无法读取 {path.relative_to(ROOT)}：{exc}")
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                failures.append(f"发现疑似真实密钥：{path.relative_to(ROOT)}")
                break

    if failures:
        print("提交检查失败：", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    if runtime_artifacts:
        print("提示：开发目录含以下本地运行物，提交包必须排除：")
        for relative in runtime_artifacts:
            print(f"- {relative}")
        print("打包前请在干净副本运行：python scripts\\verify_submission.py --strict-clean")

    print(
        "检查通过：必需文件齐全、真实评测可追溯，"
        "未发现环境文件或疑似真实密钥。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
