"""SQLAlchemy ORM 模型 + Pydantic DTO。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.utcnow()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# SQLAlchemy ORM 模型
# ---------------------------------------------------------------------------

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    name: Mapped[str] = mapped_column(String(200))
    batch: Mapped[Optional[str]] = mapped_column(String(100))
    rubric_version: Mapped[Optional[str]] = mapped_column(String(50))
    skill_version: Mapped[Optional[str]] = mapped_column(String(50))
    weight_version: Mapped[Optional[str]] = mapped_column(String(50))
    judge_model: Mapped[Optional[str]] = mapped_column(String(100))
    score_range: Mapped[Optional[str]] = mapped_column(String(50), default="0,1,2")
    note: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    uploaded_files: Mapped[list["UploadedFile"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    check_results: Mapped[list["CheckResult"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    metric_results: Mapped[list["MetricResult"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    exported_reports: Mapped[list["ExportedReport"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    run_logs: Mapped[list["RunLog"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    file_type: Mapped[str] = mapped_column(String(20))  # ground_truth | auto_eval
    original_name: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(500))
    n_rows: Mapped[Optional[int]] = mapped_column(Integer)
    n_sheets: Mapped[Optional[int]] = mapped_column(Integer)
    detected_schema: Mapped[Optional[dict]] = mapped_column(JSON)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    task: Mapped["Task"] = relationship(back_populates="uploaded_files")


class FieldMapping(Base):
    __tablename__ = "field_mappings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    file_type: Mapped[str] = mapped_column(String(20))
    source_column: Mapped[str] = mapped_column(String(200))
    target_field: Mapped[str] = mapped_column(String(100))
    mapping_type: Mapped[str] = mapped_column(String(20), default="auto")  # auto | manual


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    check_type: Mapped[str] = mapped_column(String(50))  # file | dimension | sample | weight
    status: Mapped[str] = mapped_column(String(20))  # pass | warn | fail
    summary: Mapped[Optional[dict]] = mapped_column(JSON)
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    task: Mapped["Task"] = relationship(back_populates="check_results")


class MetricResult(Base):
    __tablename__ = "metric_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    scope: Mapped[str] = mapped_column(String(50))  # overall | category | dimension | model
    scope_key: Mapped[Optional[str]] = mapped_column(String(100))  # 类别名/维度代码/模型名
    metrics: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    task: Mapped["Task"] = relationship(back_populates="metric_results")


class DifferenceRecord(Base):
    __tablename__ = "difference_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    data_id: Mapped[Optional[str]] = mapped_column(String(200))
    query_id: Mapped[Optional[str]] = mapped_column(String(200))
    candidate_model: Mapped[Optional[str]] = mapped_column(String(100))
    dimension_code: Mapped[Optional[str]] = mapped_column(String(20))
    ground_truth_score: Mapped[Optional[float]] = mapped_column(Float)
    auto_score: Mapped[Optional[float]] = mapped_column(Float)
    delta: Mapped[Optional[float]] = mapped_column(Float)
    auto_reason: Mapped[Optional[str]] = mapped_column(Text)
    root_cause_category: Mapped[Optional[str]] = mapped_column(String(100))
    is_severe_error: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[Optional[dict]] = mapped_column(JSON)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    rec_type: Mapped[str] = mapped_column(String(30))  # skill | strategy | weight
    target_dimension: Mapped[Optional[str]] = mapped_column(String(20))
    category: Mapped[Optional[str]] = mapped_column(String(50))
    priority: Mapped[Optional[str]] = mapped_column(String(5))  # P0 | P1 | P2
    status: Mapped[str] = mapped_column(String(30), default="待验证")
    content: Mapped[Optional[dict]] = mapped_column(JSON)
    llm_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    task: Mapped["Task"] = relationship(back_populates="recommendations")


class WeightScenario(Base):
    __tablename__ = "weight_scenarios"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    scenario_name: Mapped[str] = mapped_column(String(50))  # A | B | C | simulation
    description: Mapped[Optional[str]] = mapped_column(Text)
    weights: Mapped[Optional[dict]] = mapped_column(JSON)
    simulation_result: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ExportedReport(Base):
    __tablename__ = "exported_reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    file_name: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    task: Mapped["Task"] = relationship(back_populates="exported_reports")


class RunLog(Base):
    __tablename__ = "run_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    module: Mapped[Optional[str]] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    extra: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    task: Mapped["Task"] = relationship(back_populates="run_logs")


# ---------------------------------------------------------------------------
# Pydantic DTOs
# ---------------------------------------------------------------------------

class TaskCreate(BaseModel):
    name: str
    batch: Optional[str] = None
    rubric_version: Optional[str] = None
    skill_version: Optional[str] = None
    weight_version: Optional[str] = None
    judge_model: Optional[str] = None
    score_range: Optional[str] = "0,1,2"
    note: Optional[str] = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    batch: Optional[str]
    rubric_version: Optional[str]
    skill_version: Optional[str]
    weight_version: Optional[str]
    judge_model: Optional[str]
    score_range: Optional[str]
    note: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime


class DimensionMappingItem(BaseModel):
    source_column: str
    target_field: str
    file_type: str  # ground_truth | auto_eval
    mapping_type: str = "manual"


class ApiResponse(BaseModel):
    success: bool
    data: Any = None
    error: Optional[str] = None
