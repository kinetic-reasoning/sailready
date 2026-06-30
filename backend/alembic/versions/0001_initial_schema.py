"""Initial schema: all Phase 1 tables, RLS policies, app role.

Revision ID: 0001
Revises:
Create Date: 2026-06-09

Statements are executed one at a time (asyncpg cannot run multi-statement
strings through prepared statements).
"""
import os

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE_STATEMENTS = [
    # --- extensions ---------------------------------------------------------
    "CREATE EXTENSION IF NOT EXISTS postgis",
    # --- application role (RLS-constrained; the API connects as this) -------
    """
    DO $do$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sailready_app') THEN
            CREATE ROLE sailready_app LOGIN PASSWORD '__APP_DB_PASSWORD__';
        END IF;
    END
    $do$
    """,
    # --- enums ---------------------------------------------------------------
    "CREATE TYPE trip_status AS ENUM ('planning', 'active', 'completed', 'cancelled')",
    "CREATE TYPE routing_type AS ENUM ('manual', 'auto')",
    "CREATE TYPE waypoint_type AS ENUM ('start', 'intermediate', 'destination')",
    "CREATE TYPE constraint_type AS ENUM ('wind', 'wave', 'current', 'depth', 'bridge', 'time_budget')",
    "CREATE TYPE severity AS ENUM ('ok', 'warning', 'violation')",
    "CREATE TYPE leg AS ENUM ('outbound', 'return')",
    "CREATE TYPE notification_type AS ENUM ('score_drop', 'score_threshold', 'marine_warning', 'departure_reminder')",
    "CREATE TYPE notification_channel AS ENUM ('email', 'in_app')",
    "CREATE TYPE rating AS ENUM ('thumbs_up', 'thumbs_down')",
    # --- users ---------------------------------------------------------------
    """
    CREATE TABLE users (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        cognito_id text UNIQUE,
        email text NOT NULL UNIQUE,
        name text,
        default_boat_id uuid,
        alert_score_threshold integer NOT NULL DEFAULT 60,
        alert_score_drop integer NOT NULL DEFAULT 20,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    # --- boats ---------------------------------------------------------------
    """
    CREATE TABLE boats (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name text NOT NULL,
        make text NOT NULL,
        model text NOT NULL,
        year integer,
        loa_ft numeric(5, 1) NOT NULL,
        draft_ft numeric(4, 1) NOT NULL,
        air_draft_ft numeric(5, 1) NOT NULL,
        beam_ft numeric(4, 1) NOT NULL,
        hull_speed_kts numeric(4, 1),
        hull_speed_is_derived boolean NOT NULL DEFAULT false,
        motor_speed_kts numeric(4, 1),
        sail_speed_upwind_kts numeric(4, 1),
        sail_speed_reach_kts numeric(4, 1),
        sail_speed_downwind_kts numeric(4, 1),
        max_wind_kts numeric(4, 1),
        max_wave_ft numeric(4, 1),
        max_adverse_current_kts numeric(4, 1),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX boats_user_id_idx ON boats (user_id)",
    """
    ALTER TABLE users
        ADD CONSTRAINT users_default_boat_fk
        FOREIGN KEY (default_boat_id) REFERENCES boats(id) ON DELETE SET NULL
    """,
    # --- trips ---------------------------------------------------------------
    """
    CREATE TABLE trips (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        boat_id uuid NOT NULL REFERENCES boats(id),
        name text,
        status trip_status NOT NULL DEFAULT 'planning',
        departure_location geometry(Point, 4326) NOT NULL,
        destination_location geometry(Point, 4326) NOT NULL,
        departure_location_name text,
        destination_location_name text,
        departure_time timestamptz NOT NULL,
        return_by_time timestamptz NOT NULL,
        time_at_destination_hrs numeric(4, 1) NOT NULL DEFAULT 0,
        routing_type routing_type NOT NULL DEFAULT 'manual',
        current_score integer CHECK (current_score BETWEEN 0 AND 100),
        current_score_updated_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX trips_user_status_idx ON trips (user_id, status)",
    # --- route_waypoints -----------------------------------------------------
    """
    CREATE TABLE route_waypoints (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
        sequence_order integer NOT NULL,
        location geometry(Point, 4326) NOT NULL,
        name text,
        waypoint_type waypoint_type NOT NULL DEFAULT 'intermediate',
        is_auto_routed boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (trip_id, sequence_order)
    )
    """,
    # --- trip_scores ---------------------------------------------------------
    """
    CREATE TABLE trip_scores (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
        scored_at timestamptz NOT NULL DEFAULT now(),
        forecast_date date NOT NULL,
        score integer NOT NULL CHECK (score BETWEEN 0 AND 100),
        is_current boolean NOT NULL DEFAULT true,
        turn_around_deadline timestamptz,
        max_reachable_distance_nm numeric(6, 1),
        suggestions jsonb NOT NULL DEFAULT '[]'::jsonb
    )
    """,
    # Idempotent daily rescore: one score row per trip per forecast day
    "CREATE UNIQUE INDEX trip_scores_trip_day_uq ON trip_scores (trip_id, forecast_date)",
    "CREATE INDEX trip_scores_current_idx ON trip_scores (trip_id) WHERE is_current",
    # --- score_drivers -------------------------------------------------------
    """
    CREATE TABLE score_drivers (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        trip_score_id uuid NOT NULL REFERENCES trip_scores(id) ON DELETE CASCADE,
        constraint_type constraint_type NOT NULL,
        waypoint_order integer,
        leg leg,
        severity severity NOT NULL,
        actual_value numeric(8, 2),
        threshold_value numeric(8, 2),
        is_interpolated boolean NOT NULL DEFAULT false,
        description text NOT NULL
    )
    """,
    "CREATE INDEX score_drivers_score_idx ON score_drivers (trip_score_id)",
    # --- conditions_cache (global, no RLS) -----------------------------------
    """
    CREATE TABLE conditions_cache (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        source text NOT NULL,
        lat numeric(6, 2) NOT NULL,
        lon numeric(6, 2) NOT NULL,
        valid_time timestamptz NOT NULL,
        fetched_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        data jsonb NOT NULL,
        UNIQUE (source, lat, lon, valid_time)
    )
    """,
    "CREATE INDEX conditions_cache_time_idx ON conditions_cache (source, valid_time)",
    # --- notifications -------------------------------------------------------
    """
    CREATE TABLE notifications (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        trip_id uuid REFERENCES trips(id) ON DELETE CASCADE,
        type notification_type NOT NULL,
        channel notification_channel NOT NULL,
        subject text NOT NULL,
        body text NOT NULL,
        sent_at timestamptz NOT NULL DEFAULT now(),
        read_at timestamptz
    )
    """,
    "CREATE INDEX notifications_user_idx ON notifications (user_id, read_at)",
    # --- trip_feedback -------------------------------------------------------
    """
    CREATE TABLE trip_feedback (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        routing_rating rating,
        routing_notes text,
        score_rating rating,
        score_notes text,
        actual_departure_time timestamptz,
        actual_return_time timestamptz,
        actual_leg_times jsonb NOT NULL DEFAULT '[]'::jsonb,
        overall_notes text,
        submitted_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    # --- saved_routes --------------------------------------------------------
    """
    CREATE TABLE saved_routes (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name text NOT NULL,
        departure_location geometry(Point, 4326) NOT NULL,
        destination_location geometry(Point, 4326) NOT NULL,
        waypoints jsonb NOT NULL DEFAULT '[]'::jsonb,
        notes text,
        created_at timestamptz NOT NULL DEFAULT now(),
        last_used_at timestamptz
    )
    """,
    "CREATE INDEX saved_routes_user_idx ON saved_routes (user_id)",
    # --- auth helpers ---------------------------------------------------------
    # Resolves the authenticated user id set by the API per request.
    """
    CREATE FUNCTION current_app_user() RETURNS uuid
    LANGUAGE sql STABLE
    AS $fn$
        SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid
    $fn$
    """,
    # SECURITY DEFINER: lets the app role find-or-create a user row before the
    # RLS user context exists (first login / dev auth). Owner bypasses RLS.
    """
    CREATE FUNCTION ensure_user(p_email text, p_name text DEFAULT NULL) RETURNS users
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
    AS $fn$
    DECLARE
        u users;
    BEGIN
        SELECT * INTO u FROM users WHERE email = p_email;
        IF NOT FOUND THEN
            INSERT INTO users (email, name) VALUES (p_email, p_name) RETURNING * INTO u;
        END IF;
        RETURN u;
    END
    $fn$
    """,
    # --- row-level security ---------------------------------------------------
    "ALTER TABLE users ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY users_self ON users FOR ALL
        USING (id = current_app_user())
        WITH CHECK (id = current_app_user())
    """,
    "ALTER TABLE boats ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY boats_owner ON boats FOR ALL
        USING (user_id = current_app_user())
        WITH CHECK (user_id = current_app_user())
    """,
    "ALTER TABLE trips ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY trips_owner ON trips FOR ALL
        USING (user_id = current_app_user())
        WITH CHECK (user_id = current_app_user())
    """,
    "ALTER TABLE notifications ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY notifications_owner ON notifications FOR ALL
        USING (user_id = current_app_user())
        WITH CHECK (user_id = current_app_user())
    """,
    "ALTER TABLE trip_feedback ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY trip_feedback_owner ON trip_feedback FOR ALL
        USING (user_id = current_app_user())
        WITH CHECK (user_id = current_app_user())
    """,
    "ALTER TABLE saved_routes ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY saved_routes_owner ON saved_routes FOR ALL
        USING (user_id = current_app_user())
        WITH CHECK (user_id = current_app_user())
    """,
    # Child tables: ownership flows through the parent trip
    "ALTER TABLE route_waypoints ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY route_waypoints_owner ON route_waypoints FOR ALL
        USING (EXISTS (
            SELECT 1 FROM trips t
            WHERE t.id = route_waypoints.trip_id AND t.user_id = current_app_user()
        ))
        WITH CHECK (EXISTS (
            SELECT 1 FROM trips t
            WHERE t.id = route_waypoints.trip_id AND t.user_id = current_app_user()
        ))
    """,
    "ALTER TABLE trip_scores ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY trip_scores_owner ON trip_scores FOR ALL
        USING (EXISTS (
            SELECT 1 FROM trips t
            WHERE t.id = trip_scores.trip_id AND t.user_id = current_app_user()
        ))
        WITH CHECK (EXISTS (
            SELECT 1 FROM trips t
            WHERE t.id = trip_scores.trip_id AND t.user_id = current_app_user()
        ))
    """,
    "ALTER TABLE score_drivers ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY score_drivers_owner ON score_drivers FOR ALL
        USING (EXISTS (
            SELECT 1 FROM trip_scores ts
            JOIN trips t ON t.id = ts.trip_id
            WHERE ts.id = score_drivers.trip_score_id AND t.user_id = current_app_user()
        ))
        WITH CHECK (EXISTS (
            SELECT 1 FROM trip_scores ts
            JOIN trips t ON t.id = ts.trip_id
            WHERE ts.id = score_drivers.trip_score_id AND t.user_id = current_app_user()
        ))
    """,
    # conditions_cache: shared forecast data, intentionally NOT user-scoped
    # --- grants ----------------------------------------------------------------
    "GRANT USAGE ON SCHEMA public TO sailready_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sailready_app",
    "ALTER DEFAULT PRIVILEGES FOR ROLE sailready IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sailready_app",
    "GRANT EXECUTE ON FUNCTION current_app_user() TO sailready_app",
    "GRANT EXECUTE ON FUNCTION ensure_user(text, text) TO sailready_app",
]

DOWNGRADE_STATEMENTS = [
    "DROP FUNCTION IF EXISTS ensure_user(text, text)",
    "DROP FUNCTION IF EXISTS current_app_user() CASCADE",
    "DROP TABLE IF EXISTS saved_routes",
    "DROP TABLE IF EXISTS trip_feedback",
    "DROP TABLE IF EXISTS notifications",
    "DROP TABLE IF EXISTS conditions_cache",
    "DROP TABLE IF EXISTS score_drivers",
    "DROP TABLE IF EXISTS trip_scores",
    "DROP TABLE IF EXISTS route_waypoints",
    "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_default_boat_fk",
    "DROP TABLE IF EXISTS trips",
    "DROP TABLE IF EXISTS boats",
    "DROP TABLE IF EXISTS users",
    "DROP TYPE IF EXISTS rating",
    "DROP TYPE IF EXISTS notification_channel",
    "DROP TYPE IF EXISTS notification_type",
    "DROP TYPE IF EXISTS leg",
    "DROP TYPE IF EXISTS severity",
    "DROP TYPE IF EXISTS constraint_type",
    "DROP TYPE IF EXISTS waypoint_type",
    "DROP TYPE IF EXISTS routing_type",
    "DROP TYPE IF EXISTS trip_status",
]


def upgrade() -> None:
    # The app role's password is injected from the environment (never committed).
    # Set APP_DB_PASSWORD in your .env (see .env.example); compose passes it through.
    app_pw = os.environ.get("APP_DB_PASSWORD")
    if not app_pw:
        raise RuntimeError(
            "APP_DB_PASSWORD must be set so the sailready_app DB role can be created"
        )
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement.replace("__APP_DB_PASSWORD__", app_pw))


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
