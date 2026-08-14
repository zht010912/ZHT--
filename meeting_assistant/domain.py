from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PENDING_VALUE = "待确认"


class _DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _required_text(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name}不能为空")
    return value


def _optional_due_date(value: str | date | None) -> str:
    if value is None:
        return PENDING_VALUE
    if isinstance(value, date):
        return value.isoformat()
    value = value.strip()
    if not value or value == PENDING_VALUE:
        return PENDING_VALUE
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("due_date 必须是 YYYY-MM-DD 或待确认") from exc


class MeetingCreate(_DomainModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20_000)
    meeting_type: str = Field(default="项目会议", min_length=1, max_length=50)
    meeting_date: date | None = None

    @field_validator("title", "content", "meeting_type")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        return _required_text(value, info.field_name)


class ActionCreate(_DomainModel):
    task: str = Field(min_length=1, max_length=500)
    owner: str = Field(default=PENDING_VALUE, min_length=1, max_length=100)
    due_date: str | date | None = PENDING_VALUE
    status: Literal["pending", "completed"] = "pending"
    source_quotes: list[str] = Field(default_factory=list)

    @field_validator("task", "owner")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        return _required_text(value, info.field_name)

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value: str | date | None) -> str:
        return _optional_due_date(value)

    @field_validator("source_quotes")
    @classmethod
    def clean_source_quotes(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        return list(dict.fromkeys(cleaned))


class ActionUpdate(_DomainModel):
    task: str | None = Field(default=None, min_length=1, max_length=500)
    owner: str | None = Field(default=None, min_length=1, max_length=100)
    due_date: str | date | None = None
    status: Literal["pending", "completed"] | None = None
    source_quotes: list[str] | None = None

    @field_validator("task", "owner")
    @classmethod
    def validate_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _required_text(value, info.field_name)

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value: str | date | None) -> str | None:
        if value is None:
            return None
        return _optional_due_date(value)

    @field_validator("source_quotes")
    @classmethod
    def clean_source_quotes(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        cleaned = [value.strip() for value in values if value.strip()]
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def require_change(self) -> "ActionUpdate":
        if not self.model_fields_set:
            raise ValueError("至少提供一个待更新字段")
        return self


class DecisionProposal(_DomainModel):
    decision: str = Field(min_length=1, max_length=1000)
    source_quote: str = Field(min_length=1, max_length=2000)

    @field_validator("decision", "source_quote")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        return _required_text(value, info.field_name)


class ActionProposal(_DomainModel):
    task: str = Field(min_length=1, max_length=500)
    owner: str = Field(min_length=1, max_length=100)
    due_date_text: str = Field(min_length=1, max_length=100)
    due_date: str
    source_quotes: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("task", "owner", "due_date_text")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        return _required_text(value, info.field_name)

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value: str) -> str:
        return _optional_due_date(value)

    @field_validator("source_quotes")
    @classmethod
    def clean_source_quotes(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned:
            raise ValueError("source_quotes 至少包含一条非空原文")
        return list(dict.fromkeys(cleaned))


class AnalysisProposal(_DomainModel):
    summary: str = Field(min_length=1, max_length=4000)
    decisions: list[DecisionProposal] = Field(default_factory=list)
    action_items: list[ActionProposal] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _required_text(value, "summary")


class ReviewRequest(_DomainModel):
    decision: Literal["confirm", "edit", "reject"]
    final_payload: AnalysisProposal | None = None
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_review_payload(self) -> "ReviewRequest":
        if self.decision == "edit" and self.final_payload is None:
            raise ValueError("edit 决策必须提供 final_payload")
        if self.decision == "reject" and self.final_payload is not None:
            raise ValueError("reject 决策不能提供 final_payload")
        return self
