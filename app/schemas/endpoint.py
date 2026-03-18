from pydantic import BaseModel, Field, HttpUrl
from uuid import UUID
from datetime import datetime


class EndpointCreate(BaseModel):
    name: str = Field(max_length=100)
    url: str
    method: str = "GET"
    monitor_type: str = "http"
    check_interval: int = Field(default=5, ge=1, le=60)
    monitor_region: str = "auto"


class EndpointUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    is_active: bool | None = None
    check_interval: int | None = Field(None, ge=1, le=60)
    monitor_region: str | None = None


class EndpointResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    url: str
    method: str
    monitor_type: str
    check_interval: int
    monitor_region: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CheckResponse(BaseModel):
    id: UUID
    endpoint_id: UUID
    status_code: int | None
    response_time_ms: int | None
    is_up: bool
    error_message: str | None
    status_indicator: str | None
    checked_at: datetime

    model_config = {"from_attributes": True}


class IncidentResponse(BaseModel):
    id: UUID
    endpoint_id: UUID
    user_id: UUID
    started_at: datetime
    resolved_at: datetime | None
    is_resolved: bool
    cause: str | None
    duration_seconds: int | None
    consecutive_failures: int
    created_at: datetime

    model_config = {"from_attributes": True}
