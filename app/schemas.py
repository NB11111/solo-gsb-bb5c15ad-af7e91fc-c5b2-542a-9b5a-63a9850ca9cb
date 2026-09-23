"""请求 / 响应数据模型。"""
from __future__ import annotations

import math

from pydantic import BaseModel, Field, field_validator

_EPS = 1e-12


class Vec2(BaseModel):
    x: float
    y: float

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


class InterfaceIn(BaseModel):
    """一个界面：线上一点、指向下一介质的法线、下一介质折射率。"""

    point: Vec2
    normal: Vec2
    n_next: float = Field(gt=0, description="下一介质折射率，必须为正")

    @field_validator("normal")
    @classmethod
    def normal_nonzero(cls, v: Vec2) -> Vec2:
        if math.hypot(v.x, v.y) < _EPS:
            raise ValueError("法线不能为零向量")
        return v


class TraceRequest(BaseModel):
    start: Vec2
    direction: Vec2
    n_start: float = Field(gt=0, description="起始介质折射率，必须为正")
    interfaces: list[InterfaceIn] = Field(default_factory=list)

    @field_validator("direction")
    @classmethod
    def direction_nonzero(cls, v: Vec2) -> Vec2:
        if math.hypot(v.x, v.y) < _EPS:
            raise ValueError("方向不能为零向量")
        return v


class SegmentOut(BaseModel):
    seg_index: int
    origin: Vec2
    direction: Vec2
    n_medium: float
    hit_point: Vec2 | None
    event: str | None
    n_after: float | None


class TraceOut(BaseModel):
    id: int
    start: Vec2
    direction: Vec2
    n_start: float
    status: str
    reason: str | None
    created_at: str
    segments: list[SegmentOut]


class TraceSummary(BaseModel):
    id: int
    status: str
    reason: str | None
    n_start: float
    created_at: str


class ObservationLineIn(BaseModel):
    """观察线：线上一点与法线（法线方向不影响直线位置，仅用于求交方程）。"""

    point: Vec2
    normal: Vec2

    @field_validator("normal")
    @classmethod
    def normal_nonzero(cls, v: Vec2) -> Vec2:
        if math.hypot(v.x, v.y) < _EPS:
            raise ValueError("法线不能为零向量")
        return v


class BeamRequest(BaseModel):
    start: Vec2
    center_direction: Vec2
    half_angle_deg: float = Field(gt=0, lt=90, description="对称半角（度），0<a<90")
    sample_count: int = Field(ge=2, le=101, description="采样数，2～101（含端点）")
    n_start: float = Field(gt=0, description="起始介质折射率，必须为正")
    interfaces: list[InterfaceIn] = Field(default_factory=list)
    observation_line: ObservationLineIn

    @field_validator("center_direction")
    @classmethod
    def direction_nonzero(cls, v: Vec2) -> Vec2:
        if math.hypot(v.x, v.y) < _EPS:
            raise ValueError("中心方向不能为零向量")
        return v


class BeamRayOut(BaseModel):
    emission_angle_deg: float
    direction: Vec2
    status: str
    reason: str | None
    observation_point: Vec2 | None


class BeamEvaluationOut(BaseModel):
    half_angle_deg: float
    sample_count: int
    ray_count: int
    hit_count: int
    centroid: Vec2 | None
    rms_radius: float | None
    rays: list[BeamRayOut]
