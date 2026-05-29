"""Pydantic schemas for /api/v1/programs."""
from __future__ import annotations

from datetime import date as _Date, datetime as _Datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProgramGenerateRequest(BaseModel):
    """Request body for POST /api/v1/programs/generate."""

    composer: str = Field(
        default="heuristic",
        description="Composer key. 'heuristic' or 'hybrid_<provider>' (openai/anthropic/deepseek/groq/minimax).",
    )
    # Default = 8-week competition arc: base → build → deload → peak → test.
    # Matches the landing copy "constrói volume, deload, intensidade alta,
    # testa PRs". Caller can override with any pattern of base|build|peak|deload|test.
    weeks: List[str] = Field(
        default_factory=lambda: [
            "base", "base", "build", "deload",
            "peak", "peak", "deload", "test",
        ],
        description="Phase per week. Values: base|build|peak|deload|test.",
    )
    deload_weeks: List[int] = Field(
        default_factory=lambda: [4, 7],
        description="1-indexed week numbers flagged as deload.",
    )
    primary_focus: List[str] = Field(
        default_factory=lambda: ["squat_volume", "aerobic_threshold"],
    )
    weekly_focus: List[str] = Field(default_factory=list)
    sessions_per_week: int = Field(default=5, ge=1, le=7)
    start_date: Optional[_Date] = Field(
        default=None,
        description="Mesocycle start date. Defaults to next Monday.",
    )
    name: Optional[str] = Field(default=None, max_length=200)
    persist: bool = Field(default=True, description="Store generated program in DB.")


class ProgramSummary(BaseModel):
    """Lightweight metadata view of a stored program."""
    id: UUID
    name: str
    composer_used: str
    phase: str
    start_date: _Date
    duration_weeks: int
    sessions_per_week: int
    primary_focus: List[str]
    created_at: _Datetime


class ProgramActivationResponse(BaseModel):
    """Result of POST /api/v1/programs/{id}/activate."""
    program_id: UUID
    macrocycle_id: UUID
    microcycles: int
    workout_templates: int
    planned_sessions: int


class ProgramResponse(BaseModel):
    """Full program payload — metadata + serialized cfai Mesocycle."""
    id: Optional[UUID] = None
    user_id: int
    name: str
    composer_used: str
    phase: str
    start_date: _Date
    duration_weeks: int
    sessions_per_week: int
    primary_focus: List[str]
    spec: dict
    mesocycle: dict
    generation_metadata: dict
    created_at: Optional[_Datetime] = None
    persisted: bool = False
