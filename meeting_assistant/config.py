from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    deepseek_api_key: str | None
    deepseek_api_base: str
    deepseek_model: str
    deepseek_timeout_seconds: float
    max_meeting_chars: int
    seed_demo: bool
    testing: bool = False

    @classmethod
    def from_env(cls, *, project_root: Path | None = None, testing: bool = False) -> "Settings":
        root = project_root or Path(__file__).resolve().parent.parent
        default_db = root / "instance" / "meeting_assistant.db"
        database_path = Path(os.getenv("MEETING_DB_PATH", str(default_db))).expanduser().resolve()
        return cls(
            database_path=database_path,
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
            deepseek_api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            deepseek_timeout_seconds=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "45")),
            max_meeting_chars=int(os.getenv("MAX_MEETING_CHARS", "20000")),
            seed_demo=os.getenv("SEED_DEMO", "true").lower() in {"1", "true", "yes", "on"},
            testing=testing,
        )

