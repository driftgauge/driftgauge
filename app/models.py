from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EntryCreate(BaseModel):
    user_id: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1, description="Opted-in source label, e.g. journal, drafts, sms")
    text: str = Field(..., min_length=1)
    created_at: datetime | None = None


class Entry(BaseModel):
    id: int
    user_id: str
    source: str
    text: str
    created_at: datetime


class AnalysisRequest(BaseModel):
    user_id: str
    window_size: int = Field(10, ge=3, le=200)


class FeatureSummary(BaseModel):
    posting_volume_ratio: float
    late_night_ratio: float
    average_length_delta: float
    elevated_language_hits: int
    paranoia_language_hits: int
    urgency_language_hits: int
    punctuation_intensity_delta: float
    coherence_signal: float


class Alert(BaseModel):
    id: int | None = None
    user_id: str
    risk_score: int
    level: Literal["none", "low", "moderate", "high"]
    explanation: str
    recommendations: list[str]
    created_at: datetime | None = None
    feature_summary: FeatureSummary


class ImportRequest(BaseModel):
    user_id: str
    directory: str
    source: str = "import"


class PrivacySettings(BaseModel):
    user_id: str
    retention_days: int = Field(30, ge=1, le=3650)
    allow_file_imports: bool = True


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=256)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=256)


class ScheduleSettings(BaseModel):
    user_id: str
    enabled: bool = True
    interval_minutes: int = Field(60, ge=5, le=10080)


class IngestionSourceRequest(BaseModel):
    user_id: str
    source_key: str
    label: str
    url: str
    kind: str = Field("site")
    enabled: bool = True


class AlertSettingsRequest(BaseModel):
    user_id: str
    email_enabled: bool = True
    email_to: str


class HealthResponse(BaseModel):
    status: str
