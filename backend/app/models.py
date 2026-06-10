import uuid
from datetime import date, datetime
from decimal import Decimal

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # All datetime columns are timestamptz — make the ORM bind them that way
    type_annotation_map = {datetime: DateTime(timezone=True)}


# Postgres enum types are created by the migration; create_type=False everywhere.
trip_status_enum = ENUM(
    "planning", "active", "completed", "cancelled", name="trip_status", create_type=False
)
routing_type_enum = ENUM("manual", "auto", name="routing_type", create_type=False)
waypoint_type_enum = ENUM(
    "start", "intermediate", "destination", name="waypoint_type", create_type=False
)
constraint_type_enum = ENUM(
    "wind", "wave", "current", "depth", "bridge", "time_budget", "weather",
    name="constraint_type",
    create_type=False,
)
severity_enum = ENUM("ok", "warning", "violation", name="severity", create_type=False)
leg_enum = ENUM("outbound", "return", name="leg", create_type=False)
notification_type_enum = ENUM(
    "score_drop",
    "score_threshold",
    "marine_warning",
    "departure_reminder",
    name="notification_type",
    create_type=False,
)
notification_channel_enum = ENUM("email", "in_app", name="notification_channel", create_type=False)
rating_enum = ENUM("thumbs_up", "thumbs_down", name="rating", create_type=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    cognito_id: Mapped[str | None]
    email: Mapped[str]
    name: Mapped[str | None]
    default_boat_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    alert_score_threshold: Mapped[int] = mapped_column(server_default=text("60"))
    alert_score_drop: Mapped[int] = mapped_column(server_default=text("20"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Boat(Base):
    __tablename__ = "boats"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str]
    make: Mapped[str]
    model: Mapped[str]
    year: Mapped[int | None]
    loa_ft: Mapped[Decimal]
    draft_ft: Mapped[Decimal]
    air_draft_ft: Mapped[Decimal]
    beam_ft: Mapped[Decimal]
    hull_speed_kts: Mapped[Decimal | None]
    hull_speed_is_derived: Mapped[bool] = mapped_column(server_default=text("false"))
    motor_speed_kts: Mapped[Decimal | None]
    sail_speed_upwind_kts: Mapped[Decimal | None]
    sail_speed_reach_kts: Mapped[Decimal | None]
    sail_speed_downwind_kts: Mapped[Decimal | None]
    max_wind_kts: Mapped[Decimal | None]
    max_wave_ft: Mapped[Decimal | None]
    max_adverse_current_kts: Mapped[Decimal | None]
    sailing_preference: Mapped[str] = mapped_column(server_default=text("'sail'"))
    min_upwind_angle_deg: Mapped[Decimal] = mapped_column(server_default=text("45"))
    grounding_margin_ft: Mapped[Decimal] = mapped_column(server_default=text("1.0"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    boat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boats.id"))
    name: Mapped[str | None]
    status: Mapped[str] = mapped_column(trip_status_enum, server_default=text("'planning'"))
    departure_location: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326)
    )
    destination_location: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326)
    )
    departure_location_name: Mapped[str | None]
    destination_location_name: Mapped[str | None]
    departure_time: Mapped[datetime]
    return_by_time: Mapped[datetime]
    time_at_destination_hrs: Mapped[Decimal] = mapped_column(server_default=text("0"))
    routing_type: Mapped[str] = mapped_column(routing_type_enum, server_default=text("'manual'"))
    current_score: Mapped[int | None]
    current_score_updated_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # lazy="raise" forbids accidental implicit IO in async context —
    # always load explicitly with selectinload(Trip.waypoints)
    waypoints: Mapped[list["RouteWaypoint"]] = relationship(
        order_by="RouteWaypoint.sequence_order",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class RouteWaypoint(Base):
    __tablename__ = "route_waypoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE")
    )
    sequence_order: Mapped[int]
    location: Mapped[WKBElement] = mapped_column(Geometry(geometry_type="POINT", srid=4326))
    name: Mapped[str | None]
    waypoint_type: Mapped[str] = mapped_column(
        waypoint_type_enum, server_default=text("'intermediate'")
    )
    is_auto_routed: Mapped[bool] = mapped_column(server_default=text("false"))
    leg_mode: Mapped[str] = mapped_column(server_default=text("'auto'"))
    depth_acknowledged: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TripScore(Base):
    __tablename__ = "trip_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE")
    )
    scored_at: Mapped[datetime] = mapped_column(server_default=func.now())
    forecast_date: Mapped[date]
    score: Mapped[int]
    is_current: Mapped[bool] = mapped_column(server_default=text("true"))
    feasible: Mapped[bool] = mapped_column(server_default=text("true"))
    turn_around_deadline: Mapped[datetime | None]
    max_reachable_distance_nm: Mapped[Decimal | None]
    suggestions: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    legs: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    conditions_summary: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    outbound_arrival: Mapped[datetime | None]
    return_home: Mapped[datetime | None]

    drivers: Mapped[list["ScoreDriver"]] = relationship(
        cascade="all, delete-orphan", lazy="raise"
    )


class ScoreDriver(Base):
    __tablename__ = "score_drivers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trip_score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trip_scores.id", ondelete="CASCADE")
    )
    constraint_type: Mapped[str] = mapped_column(constraint_type_enum)
    waypoint_order: Mapped[int | None]
    leg: Mapped[str | None] = mapped_column(leg_enum)
    severity: Mapped[str] = mapped_column(severity_enum)
    actual_value: Mapped[Decimal | None]
    threshold_value: Mapped[Decimal | None]
    is_interpolated: Mapped[bool] = mapped_column(server_default=text("false"))
    description: Mapped[str]


class SavedRoute(Base):
    __tablename__ = "saved_routes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str]
    departure_location: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326)
    )
    destination_location: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326)
    )
    waypoints: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    notes: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_used_at: Mapped[datetime | None]


class TripFeedback(Base):
    __tablename__ = "trip_feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    routing_rating: Mapped[str | None] = mapped_column(rating_enum)
    routing_notes: Mapped[str | None]
    score_rating: Mapped[str | None] = mapped_column(rating_enum)
    score_notes: Mapped[str | None]
    actual_departure_time: Mapped[datetime | None]
    actual_return_time: Mapped[datetime | None]
    actual_leg_times: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    overall_notes: Mapped[str | None]
    submitted_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ConditionsCache(Base):
    """Shared (not user-scoped) cache of fetched forecast/prediction data,
    keyed by source + snapped coordinate + valid hour."""

    __tablename__ = "conditions_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    source: Mapped[str]
    lat: Mapped[Decimal]
    lon: Mapped[Decimal]
    valid_time: Mapped[datetime]
    fetched_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    data: Mapped[dict] = mapped_column(JSONB)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(notification_type_enum)
    channel: Mapped[str] = mapped_column(notification_channel_enum)
    subject: Mapped[str]
    body: Mapped[str]
    sent_at: Mapped[datetime] = mapped_column(server_default=func.now())
    read_at: Mapped[datetime | None]
