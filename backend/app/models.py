import uuid
from datetime import datetime
from decimal import Decimal

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import ENUM, UUID
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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
