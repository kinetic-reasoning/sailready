import uuid
from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

T = TypeVar("T")


class ErrorInfo(BaseModel):
    code: str
    message: str


class Envelope(BaseModel, Generic[T]):
    data: T | None = None
    error: ErrorInfo | None = None


# --- users -------------------------------------------------------------------


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str | None
    default_boat_id: uuid.UUID | None
    alert_score_threshold: int
    alert_score_drop: int
    created_at: datetime


class UserUpdate(BaseModel):
    name: str | None = None
    default_boat_id: uuid.UUID | None = None
    alert_score_threshold: int | None = Field(default=None, ge=0, le=100)
    alert_score_drop: int | None = Field(default=None, ge=1, le=100)


# --- boats -------------------------------------------------------------------


class BoatIn(BaseModel):
    name: str = Field(min_length=1)
    make: str = Field(min_length=1)
    model: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=1900, le=2100)
    loa_ft: float = Field(gt=0)
    draft_ft: float = Field(gt=0)
    air_draft_ft: float = Field(gt=0)
    beam_ft: float = Field(gt=0)
    hull_speed_kts: float | None = Field(default=None, gt=0)
    motor_speed_kts: float | None = Field(default=None, gt=0)
    sail_speed_upwind_kts: float | None = Field(default=None, gt=0)
    sail_speed_reach_kts: float | None = Field(default=None, gt=0)
    sail_speed_downwind_kts: float | None = Field(default=None, gt=0)
    max_wind_kts: float | None = Field(default=None, gt=0)
    max_wave_ft: float | None = Field(default=None, gt=0)
    max_adverse_current_kts: float | None = Field(default=None, gt=0)


# --- trips -------------------------------------------------------------------


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = None


class LocationOut(BaseModel):
    lat: float
    lon: float
    name: str | None


def _require_tz(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("datetime must include a timezone offset")
    return v


class TripIn(BaseModel):
    boat_id: uuid.UUID
    name: str | None = None
    departure_location: LocationIn
    destination_location: LocationIn
    departure_time: datetime
    return_by_time: datetime
    time_at_destination_hrs: float = Field(default=0, ge=0)

    _tz_dep = field_validator("departure_time")(_require_tz)
    _tz_ret = field_validator("return_by_time")(_require_tz)

    @model_validator(mode="after")
    def window_is_positive(self) -> "TripIn":
        if self.return_by_time <= self.departure_time:
            raise ValueError("return_by_time must be after departure_time")
        return self


class TripStatusIn(BaseModel):
    status: Literal["active", "completed", "cancelled"]


class WaypointIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = None


class WaypointsReplaceIn(BaseModel):
    waypoints: list[WaypointIn] = Field(min_length=2)


class WaypointOut(BaseModel):
    sequence_order: int
    lat: float
    lon: float
    name: str | None
    waypoint_type: str
    is_auto_routed: bool


class TripOut(BaseModel):
    id: uuid.UUID
    boat_id: uuid.UUID
    name: str | None
    status: str
    departure_location: LocationOut
    destination_location: LocationOut
    departure_time: datetime
    return_by_time: datetime
    time_at_destination_hrs: float
    routing_type: str
    current_score: int | None
    current_score_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TripDetailOut(TripOut):
    waypoints: list[WaypointOut]


# --- saved routes --------------------------------------------------------------


class SavedRouteWaypoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = None


class SavedRouteIn(BaseModel):
    name: str = Field(min_length=1)
    departure_location: LocationIn
    destination_location: LocationIn
    waypoints: list[SavedRouteWaypoint] = Field(min_length=2)
    notes: str | None = None


class SavedRouteOut(BaseModel):
    id: uuid.UUID
    name: str
    departure_location: LocationOut
    destination_location: LocationOut
    waypoints: list[SavedRouteWaypoint]
    notes: str | None
    created_at: datetime
    last_used_at: datetime | None


class TripFromRouteIn(BaseModel):
    boat_id: uuid.UUID | None = None  # falls back to the user's default boat
    name: str | None = None
    departure_time: datetime
    return_by_time: datetime
    time_at_destination_hrs: float = Field(default=0, ge=0)

    _tz_dep = field_validator("departure_time")(_require_tz)
    _tz_ret = field_validator("return_by_time")(_require_tz)

    @model_validator(mode="after")
    def window_is_positive(self) -> "TripFromRouteIn":
        if self.return_by_time <= self.departure_time:
            raise ValueError("return_by_time must be after departure_time")
        return self


# --- feedback -------------------------------------------------------------------


class LegTimeActual(BaseModel):
    waypoint_order: int
    predicted_at: datetime | None = None
    actual_at: datetime | None = None


class TripFeedbackIn(BaseModel):
    routing_rating: Literal["thumbs_up", "thumbs_down"] | None = None
    routing_notes: str | None = None
    score_rating: Literal["thumbs_up", "thumbs_down"] | None = None
    score_notes: str | None = None
    actual_departure_time: datetime | None = None
    actual_return_time: datetime | None = None
    actual_leg_times: list[LegTimeActual] = Field(default_factory=list)
    overall_notes: str | None = None


class TripFeedbackOut(TripFeedbackIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trip_id: uuid.UUID
    submitted_at: datetime


# --- notifications ----------------------------------------------------------------


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trip_id: uuid.UUID | None
    type: str
    channel: str
    subject: str
    body: str
    sent_at: datetime
    read_at: datetime | None


class BoatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    make: str
    model: str
    year: int | None
    loa_ft: float
    draft_ft: float
    air_draft_ft: float
    beam_ft: float
    hull_speed_kts: float | None
    hull_speed_is_derived: bool
    motor_speed_kts: float | None
    sail_speed_upwind_kts: float | None
    sail_speed_reach_kts: float | None
    sail_speed_downwind_kts: float | None
    max_wind_kts: float | None
    max_wave_ft: float | None
    max_adverse_current_kts: float | None
    created_at: datetime
    updated_at: datetime
