"""Pydantic 请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from .engine import REL_TYPES

UNIT_KINDS = ("layer", "pit", "wall", "ditch", "tomb", "ash", "other")


class UnitIn(BaseModel):
    code: str
    name: str = ""
    kind: str = "other"
    note: str = ""

    @field_validator("code")
    @classmethod
    def code_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("单元编号不能为空")
        if len(v) > 40:
            raise ValueError("单元编号最长 40 字符")
        return v

    @field_validator("kind")
    @classmethod
    def kind_valid(cls, v: str) -> str:
        if v not in UNIT_KINDS:
            raise ValueError(f"类型必须是 {UNIT_KINDS} 之一")
        return v

    @field_validator("name", "note")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()


class RelationIn(BaseModel):
    source_id: int
    target_id: int
    rel_type: str
    note: str = ""

    @field_validator("rel_type")
    @classmethod
    def rel_valid(cls, v: str) -> str:
        if v not in REL_TYPES:
            raise ValueError(f"关系类型必须是 {REL_TYPES} 之一")
        return v

    @field_validator("note")
    @classmethod
    def strip_note(cls, v: str) -> str:
        return v.strip()
