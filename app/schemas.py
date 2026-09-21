"""API 请求模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

RelationKind = Literal["earlier_than", "later_than", "intersects"]


class UnitCreate(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("编号不能为空")
        if any(ch.isspace() for ch in v):
            raise ValueError("编号不能包含空白字符")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("名称不能为空")
        return v

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, v) -> str:
        return (v or "").strip()


class UnitUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("名称不能为空")
        return v

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, v) -> str:
        return (v or "").strip()


class RelationCreate(BaseModel):
    kind: RelationKind
    source_id: str = Field(min_length=1, max_length=40)
    target_id: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=500)

    @field_validator("source_id", "target_id")
    @classmethod
    def _ids(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("单元编号不能为空")
        return v

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, v) -> str:
        return (v or "").strip()
