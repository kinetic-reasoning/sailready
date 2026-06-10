# SailReady (sailready.ai) — App Specification

**Owner:** Ken Holden
**Status:** Architecture complete (second pass) / pre-build
**Last updated:** 2026-06-09
**Domain:** sailready.ai
**Test vessel:** Com-Pac 27/2, Westerbeke 12B Two diesel
**Home waters:** Ruskin / Tampa Bay, FL

---

## 1. The Problem

Planning a sail today is a manual mashup of disconnected apps:

1. Check a weather app for the forecast (rain?).
2. Open a wind app (10–12 kt — looks OK).
3. Check tides and currents separately.
4. Eyeball a destination, guess outbound and return time.
5. Go on the day if it still looks OK.

**What goes wrong:** no wind, too much wind, weather turns, or current is against you. The biggest failure is the **return leg** — you budget it at outbound speed, but headwind + foul current drops you from 6 kt to 2 kt, and an "8-hour window" blows out.

---

## 2. What the App Is

A **trip-planning and decision engine** — not a chartplotter. You create a Trip (destination + departure/return window + which boat). The engine:

- Routes a safe-water corridor to get distance and the waypoints to sample conditions at.
- Pulls all relevant conditions (wind, wave, tide, current, weather, marine warnings) resolved against **where you'll be and when you'll be there**.
- Returns a **Go/No-Go confidence percentage** with the specific constraints driving it.
- **Re-scores every day** as forecasts update.
- On departure day: final score + actionable suggestions (go closer, leave earlier, shorten stay).
- **Underway co-pilot:** on-plan vs. behind, live turn-around deadline, turn-back alerts.

### The core insight — round-trip time budget

> **Outbound time + time-at-destination + return time ≤ your window**

...where return time is computed under conditions **at return o'clock**, not departure. Two mechanics fall out:

- **Max reachable distance is dynamic** — building SW wind Saturday afternoon shrinks your southern reach even with "8 hours" on paper. The app draws this shrinking circle automatically.
- **Turn-around deadline (point of no return)** — the latest clock time you can still make it back, recomputed live. Underway this is the single most useful number: *"Turn by 1:47pm or you blow the window."*

### Scoring principle

Score = **worst constraint violation across all sampled points**, not an average. One stretch of 25 kt on the nose = No-Go even if the rest is perfect.

---

## 3. The Boat Profile

A setup form (editable any time) builds the boat's constraint envelope. **All fields are user-entered; nothing is hardcoded to a specific vessel.** Make/model are free-text labels — there is no curated boat-model database to maintain (no reliable external API exists, and hand-maintaining one is a full-time job). Optional pre-fill of sail speeds from the open ORC polar database (jieter/orc-data) when a match exists.

| Profile field | Required | Engine use |
|---|---|---|
| **Name, make, model, year** | name/make/model | Labeling, trip log |
| **LOA** | Yes | Hull speed derivation if not provided |
| **Draft** | Yes | Grounding check — min charted depth at each waypoint adjusted for tide at arrival time |
| **Air draft (mast height)** | Yes | Fixed-bridge clearance — route must clear every bridge |
| **Beam** | Yes | Trip log, future marina/slip features |
| **Hull speed** | No — derived from LOA if blank | Hard ceiling on time-budget math |
| **Sail speeds** (upwind / reach / downwind) | No — conservative defaults | Leg-time calculation by wind angle |
| **Motor speed** | No — conservative default | Leg-time when motoring or no wind |
| **Max wind / wave / adverse current** | No — sensible defaults | Skipper's comfort envelope — drives Go/No-Go thresholds |

The leg-time calculation is a **feedback loop**: foul current makes a leg longer → you hit the next waypoint later → conditions there have shifted. This is why naive guesses fail and why the engine simulates position over time.

---

## 4. Feature Set and Phases

### Phase 1 — Core engine, Tampa Bay to Anna Maria Island

| Feature | Description |
|---|---|
| **Trip creation** | Start + destination pin drop on map, departure/return window, boat selection |
| **Manual route waypoints** | User drops pins along route; app samples conditions at each |
| **Conditions engine** | Wind, wave, tide, current, depth check at each waypoint at arrival time |
| **Go/No-Go score** | Deterministic — worst constraint violation across all waypoints |
| **Daily rescore** | Automated job re-fetches forecasts, re-scores all active trips |
| **Email alerts** | Score drops below threshold, marine warnings issued |
| **In-app notifications** | Score changes, suggestions surfaced inside the app |
| **Departure-day suggestions** | Go closer / leave earlier / shorten stay, computed from re-scored alternatives |
| **Underway co-pilot (PWA, foreground)** | On-plan vs. behind; live turn-around deadline from current GPS position. *See iOS limitation in §7.* |
| **Turn-back alerts** | Condition degradation mid-trip triggers alert with updated turn-around deadline |
| **Saved routes / route library** | Save frequently used routes; reload and re-score against new conditions |
| **Multi-window scoring** | Score same destination across multiple time windows, compare side by side |
| **Boat profile** | Manual entry, all constraint fields, optional ORC polar pre-fill |
| **Google Auth** | Single sign-on; initially restricted to owner's account |
| **Float plan generation** | Auto-compose safety brief (route, waypoint ETAs, return time, emergency contacts) to send to a shore contact |
| **Feedback loop** | Thumbs up/down on routing accuracy and score accuracy; free-text notes; captures actual vs. predicted leg times |

### Phase 2 — AI layer + auto-routing + native co-pilot

| Feature | Description |
|---|---|
| **Auto-routing** | Self-built channel-graph router on NOAA ENC data; draft- and bridge-aware; tidal depth offset (see §6a) |
| **iOS native app (React Native + Expo)** | Pulled forward from "someday" specifically for the co-pilot — iOS Safari PWAs cannot run GPS in the background (screen lock kills `watchPosition`). Native app gives background location + reliable underway use |
| **LLM score explanation** | Natural language briefing generated from deterministic scoring output |
| **Forecast uncertainty flagging** | When models disagree significantly, flag lower confidence and explain the disagreement |
| **Weather window finder** | "Find the best window in the next 10 days for this trip" — engine scores all viable windows, LLM presents ranked options |
| **Post-trip debrief** | Compares actual vs. predicted leg times, conditions, turn-around; LLM generates plain-English summary |
| **Trip log** | GPS breadcrumb recording, engine hours, departure/arrival times, GPX export |
| **Apple Sign In** | Second auth provider alongside Google (required for App Store with social login) |

### Phase 3 — Co-pilot chat + calibration

| Feature | Description |
|---|---|
| **Co-pilot chat** | LLM with tool use — ask questions about the trip, re-score with different params, get condition explanations; tools: score_trip, get_conditions, calculate_route, suggest_alternatives, adjust_departure |
| **Calibration from feedback** | AI analyzes accumulated feedback to identify systematic prediction errors (e.g. upwind speeds consistently over-estimated); suggests boat profile adjustments |
| **Smart alert personalization** | Learn which alert types the user acts on; suppress low-signal notifications |

### Phase 4 — Anchor watch + maintenance

| Feature | Description |
|---|---|
| **Anchor watch** | Monitors GPS position against set anchor point; alerts if dragging beyond defined radius |
| **Maintenance log** | Natural language entry parsed by AI; categorized by system (engine, rigging, hull, etc.) |
| **Service interval tracking** | Cross-references engine hours from trip log against manufacturer intervals; generates maintenance alerts |
| **Maintenance prediction** | Pattern-based alerts: "Based on your Westerbeke 12B hours and service history, impeller inspection due in ~15 engine hours" |

### Future / Beta feedback-driven

- Android version
- Push notifications to device (Phase 1 is email + in-app)
- Crowd-sourced depth corrections
- Multi-day voyage planning
- Crew/passenger trip sharing
- Social trip reports

---

## 5. Three Modes (one engine)

1. **Plan** (weekday) → Go/No-Go % + drivers; re-scores daily as forecasts refresh.
2. **Pre-launch** (departure morning) → final score + suggestions (closer destination / leave earlier / shorter stay).
3. **Underway co-pilot** → on-plan vs. behind, live turn-around deadline, turn-back alerts on degrading conditions.

**Connectivity assumption:** internet connection required. US coastal cruising within 3 nm of shore = cell coverage. No offline sync in Phase 1. The last-computed plan (route, score, turn-around deadline) is cached locally on the device to survive short connection drops underway.

---

## 6. Data Sources and External APIs

### Weather and sea-state

| Service | Purpose | Cost | Role |
|---|---|---|---|
| **Open-Meteo Marine API** | Wind speed/direction, wave height/period/direction, hourly, global | Commercial Standard tier (~$29-99/mo) | Primary forecast source |
| **NOAA NWS** `api.weather.gov` | Official US marine zone forecasts (incl. bay & inland waters wave guidance), Small Craft Advisories, marine warnings | Free | Authoritative US overlay + warnings |
| **NOAA NDBC** | Real-time buoy observations near Tampa Bay | Free | Nowcast ground truth |
| **Stormglass** | Multi-model aggregated marine forecasts | €19/mo optional | Backup/cross-check |

> ⚠️ **Wave data caveat (enclosed bay):** Open-Meteo's wave model is a **global swell model** — inside Tampa Bay, waves are short-period fetch-limited wind chop that swell models don't resolve. The engine is **regime-aware**: for waypoints inside the bay it computes wind-wave estimates itself (SMB shallow-water wave equations from wind speed + fetch + depth) cross-checked against NWS bay guidance; Open-Meteo wave data is trusted only outside the bay (Egmont Channel, Gulf side of Anna Maria) where swell is the real phenomenon.

### Tides and currents

| Service | Purpose | Cost |
|---|---|---|
| **NOAA CO-OPS** `tidesandcurrents.noaa.gov/api` | Hourly tide predictions + tidal current speed/direction at stations | Free |

> ⚠️ **Current station caveat:** CO-OPS current *predictions* exist at a limited set of stations — strong coverage at the chokepoints that matter most (Egmont Channel, Skyway), thin elsewhere. The engine uses the nearest channel-aligned station per leg and **flags in the score drivers whether a current value is station-direct or interpolated.** The strongest currents in the Phase 1 cruising ground are at the well-instrumented chokepoints, so data exists where risk is highest.

### Routing and charts (self-built — see §6a)

| Data source | Purpose | Cost | How consumed |
|---|---|---|---|
| **NOAA ENC S-57 files** | Depth areas (`DEPARE`), soundings (`SOUNDG`), obstructions, bridge clearances | Free — **public domain** | Parsed with GDAL S-57 driver (fiona/pyogrio); ingested into PostGIS |
| **USACE eHydro** | High-resolution Tampa Bay channel surveys | Free download | Same pipeline as ENC |
| **USCG Bridge Clearances** | Vertical clearance database | Free download | Static lookup table |
| **OpenSeaMap tiles** | Reference seamarks/marinas in map UI | Free | Leaflet tile layer |
| **NOAA RNC/ENC MBTiles** | Official chart appearance | Free | Leaflet tile layer |

### Auth, notifications, payments

| Service | Purpose | Cost |
|---|---|---|
| **AWS Cognito** | Google OAuth + Apple Sign In; JWT issuance; integrates with API Gateway | Free tier generous |
| **AWS SES** | Email notifications (rescore alerts, float plans, trip debriefs) | ~$0.10/1000 emails |
| **Stripe** | Subscription billing (when monetization begins) | 2.9% + $0.30/transaction |

### AI inference

| Service | Purpose | Phase |
|---|---|---|
| **AWS Bedrock (Claude)** | Score explanation, forecast uncertainty narration, weather window presentation, post-trip debrief, co-pilot chat with tool use, maintenance log parsing | Phase 2+ |
| **Managed inference provider** (Modal, Fireworks, Together AI) | Migration target when Bedrock per-token cost exceeds threshold at scale | Future |
| **GPU instances** | Self-hosted inference if usage justifies it | Future |

### Maps

| Service | Purpose | Cost |
|---|---|---|
| **Leaflet** | Map rendering, route polyline, pin drop | Free (OSS library) |
| **Mapbox or OpenStreetMap** | Base map tiles (land/water background) | Mapbox free tier; OSM free |

### Boat polars

| Source | Purpose | Cost |
|---|---|---|
| **jieter/orc-data** (GitHub) | Open database of polars scraped from thousands of ORC certificates — optional pre-fill of sail speeds by make/model | Free |

---

## 6a. Routing Engine — Design and Prior Art

**Market reality (verified by live research, 2026-06):** no affordable, depth-aware small-craft routing API exists. Commercial shipping APIs (Searoutes €400+/mo, Aquaplot, etc.) route cargo ships on ocean shipping lanes — they cannot navigate inshore waters. Consumer apps with real routing (Navionics/Garmin Auto Guidance+, Wavve Boating, savvy navvy) expose **no developer API**. Routing is self-built — and it is the app's IP moat alongside the time-budget engine.

### Design: channel-graph, not dense grid

Marine navigation follows dredged channels — the router should too:

1. **Sparse navigable graph** built from ENC `DEPARE` polygons + dredged channel centerlines (USACE eHydro), with nodes at channel junctions and bends. A* runs over hundreds of nodes, not millions of grid cells.
2. **Local depth check** — fine-grained ENC soundings used only for the grounding check at each waypoint (charted depth + CO-OPS tide offset at arrival time vs. draft + safety margin), not for global route search.
3. **Bridge clearance check** per edge against air draft.
4. **Validation loop:** the engine emits **GPX 1.1 routes**; OpenCPN imports GPX — every computed route is eyeballed over official NOAA charts in OpenCPN during development.

### Prior art (verified at repo level)

| Project | What it offers | Status |
|---|---|---|
| **VISIR-2** (CMCC, GMD 2024, GPL-3) | The only open project that is genuinely depth-aware: graph routing with per-edge under-keel clearance against bathymetry, sail polars, currents. **The published academic blueprint for our exact problem** — we substitute chart-resolution NOAA ENC depths for their coarse GEBCO bathymetry | Reference only |
| **weather_routing_pi** (OpenCPN plugin, GPL-3, rgleason fork maintained) | Isochrone propagation engine (`RouteMap.cpp`, `Position.cpp`, `IsoRoute.cpp`) — same family of math as our time-budget simulation. Land avoidance is coarse GSHHS only; **no depth awareness** (acknowledged in code comments as never-implemented future work) | Reference only |
| **OpenCPN core** (GPL-2) | **Has no auto-routing at all** — manual waypoint entry only; depth used for display/alarms. Its S-57 parser is a vendored fork of GDAL's — meaning GDAL's S57 driver in Python is the same data path | Validation tool + data-path confirmation |
| **libweatherrouting** (dakk, pip `weatherrouting`, GPL-3) | Pure-Python isochrone router with pluggable `point_validity`/`line_validity` callbacks — architecturally instructive | Reference only (GPL encumbrance) |

### Licensing stance

All relevant prior art is GPL. **Policy: read for algorithmic understanding, reimplement fresh — never port or copy code.** Server-side GPL use wouldn't violate the license today (copyleft triggers on distribution, not network use; none are AGPL), but a Python port is a permanent derivative work that would poison any future distribution, on-prem deal, or acquisition. Algorithms themselves (isochrone method: Hagiwara 1989; A*) are not copyrightable. NOAA ENC data is public domain. GDAL is MIT/X-licensed.

### GDAL S-57 ingestion notes (hard-won specifics)

- Open with `SPLIT_MULTIPOINT=ON,ADD_SOUNDG_DEPTH=ON` or soundings arrive as opaque multipoints with depth hidden in Z
- `DEPARE.DRVAL1` = conservative (minimum) depth of an area below MLLW — that's the grounding-check value
- Obstructions (`OBSTRN`/`WRECKS`/`UWTROC`): `VALSOU` frequently null = depth unknown — **treat null as dangerous**
- NOAA ENCs come in overlapping usage bands — select the largest-scale cell per area or features double-read
- Keep ENC_ROOT cell directories intact so update files (`.001`…) auto-apply

---

## 7. Tech Stack

### Backend
- **Language:** Python 3.12+
- **Framework:** FastAPI (async, typed, auto-generates OpenAPI docs)
- **Geospatial:** GDAL/fiona (ENC S-57 parsing), Shapely, GeoPandas, PyProj
- **Numerical:** NumPy, SciPy
- **LLM:** Anthropic Python SDK (via AWS Bedrock)
- **Packaging:** **Lambda container images** (not zip) — GDAL/geopandas exceed the 250MB zip limit; containers go to 10GB. If geospatial cold starts prove painful, the routing engine moves to a small Fargate task

### Database
- **Phase 1: RDS PostgreSQL on t4g.micro** (~$12–15/mo per environment) with PostGIS — elastic capacity isn't needed for one user + small beta
- **Scale path: Aurora Serverless v2** when beta traffic justifies it (same Postgres wire format, low-drama migration)
- Row-level security enforced at the database layer for multi-tenant isolation
- Every user-scoped table has a `user_id` column; RLS policies prevent cross-user data access
- **Conditions cache is a Postgres table** — no separate cache tier in Phase 1

### Job scheduling
- **EventBridge Scheduler → Lambda directly** — a daily cron over a handful of trips needs no queue broker
- **No Redis/ElastiCache in Phase 1** (ElastiCache Serverless has a ~$90/mo floor per environment — the single worst cost line for a personal app). Reintroduce in Phase 3+ only if measured load demands it

### Frontend
- **Framework:** React 18 + TypeScript
- **Map:** Leaflet with OpenSeaMap + NOAA tile layers
- **Delivery:** Progressive Web App (PWA) — works on iPhone and iPad via Safari
- Browser Geolocation API (`watchPosition`) for underway GPS tracking
- Last-known plan cached in localStorage/IndexedDB for short connection drops

> ⚠️ **iOS PWA limitation (known, accepted):** iOS Safari cannot run GPS in the background — `watchPosition` stops when the screen locks or the app is backgrounded. Planning/scoring/rescore/float plans are fully PWA-viable; the **underway co-pilot** requires screen-on foreground use as a PWA and is the driver for pulling the native app into Phase 2.

### Mobile (Phase 2)
- **React Native + Expo** — wraps same backend API
- Background location for the co-pilot, push notifications via APNs, App Store distribution
- Shares component logic with web via React Native Web

### Infrastructure (AWS Serverless)

| Component | Service |
|---|---|
| API | AWS Lambda (container images) + API Gateway (FastAPI via Mangum) |
| Database | RDS PostgreSQL t4g.micro + PostGIS (Phase 1) → Aurora Serverless v2 (scale) |
| Frontend | S3 + CloudFront |
| Background jobs | EventBridge Scheduler → Lambda |
| ENC data storage | S3 |
| Auth | AWS Cognito |
| Email | AWS SES |
| Secrets | AWS Secrets Manager |
| AI inference | AWS Bedrock (Phase 2+) |

**Realistic Phase 1 cost (dev + prod):** ~$40–60/mo — two RDS micros + storage + trace Lambda/CloudFront/SES usage + Open-Meteo commercial tier. (Earlier "scale to zero ≈ free" framing was over-optimistic; the original Aurora + ElastiCache stack would have floored at $150–250/mo.)

### IaC and CI/CD
- **Terraform** — all infrastructure declared as code
- **Terragrunt** — DRY environment management (dev / prod share module definitions, separate variable files)
- **GitHub Actions** — CI/CD; push to `develop` deploys to dev; release tag deploys to prod
- No Helm (Kubernetes-specific, not applicable to serverless)

### Environments
- **Local** (primary dev loop) + **Dev** + **Prod** (AWS), same application containers everywhere
- Single AWS account to start; can split to separate accounts via AWS Organizations when needed

### Local-first development

The backend ships as a container image anyway (Lambda container images) — the same artifact runs locally. The entire Phase 1 app is buildable and personally usable on the local workstation before any AWS spend:

| Piece | Local answer |
|---|---|
| Database | `postgis/postgis` container — same engine, extensions, and RLS behavior as RDS |
| API | FastAPI container with hot reload (same image base as the Lambda deploy) |
| Frontend | Vite dev server |
| External data APIs | Hit directly — NOAA CO-OPS/NWS/NDBC are free, no auth wall; Open-Meteo non-commercial tier free during development |
| ENC ingestion / routing dev | One-shot GDAL container against local PostGIS — the loop where local iteration matters most |
| Daily rescore | `make rescore` / local cron — EventBridge is only the cloud trigger for the same function |
| Cognito auth | **Not emulated** (LocalStack Cognito is paid + flaky). `AUTH_MODE=dev` config flag accepts a static dev identity; auth middleware is the only code that knows |
| SES email | Mailpit container — catches all outbound mail in a local web UI, same SMTP code path |
| S3 | Local filesystem behind the same storage interface (MinIO only if genuinely needed) |
| LocalStack | **Explicitly skipped** — more friction than fidelity for this stack |

---

## 8. Architecture Principles

**Scoring engine is a pure function**
`score_trip(route_waypoints, boat_profile, conditions_at_each_waypoint) → (score, drivers, turn_around_deadline)`

No database, HTTP, or user knowledge inside the engine. Independently testable. Called identically by the daily rescore Lambda, the API, and the LLM tool use interface.

**Conditions cache decouples scoring from API availability**
Weather and tide data is fetched once and stored in a `conditions_cache` table keyed by `(source, lat, lon, valid_time)`. Every scoring run reads from cache. This controls API costs and makes scoring fast and reliable.

**Regime-aware conditions sourcing**
Every waypoint is classified (enclosed bay vs. open Gulf). Wave data is sourced per regime: computed wind-wave estimate + NWS bay guidance inside; Open-Meteo swell model outside. Current values carry a station-direct vs. interpolated flag into score drivers.

**LLM wraps the engine — never replaces it**
Go/No-Go score is deterministic and auditable. The LLM generates natural language explanations of the score and orchestrates tool calls in the chat interface. It does not compute safety-critical values.

**API-first, clients are consumers**
The backend is a REST API from day one. The web app is client #1. The iOS native app is client #2. No logic lives in the frontend.

**Multi-tenancy at the database layer**
RLS policies enforce user isolation. A bug in the API layer cannot expose another user's trips.

**Idempotent background jobs**
The daily rescore job is identified by `(trip_id, forecast_date)`. Re-running it overwrites the previous result without side effects.

**API versioning from day one**
All endpoints under `/api/v1/`. New capabilities are introduced as `/api/v2/` without breaking existing clients.

---

## 9. Build Sequence (local-first)

The app is built and personally usable locally (Steps 1–5) before any cloud infrastructure exists. AWS becomes a packaging exercise for something that already works, not a debugging environment.

### Step 1 — Local stack + repo scaffold
Dedicated git repo. `docker-compose` with PostGIS, FastAPI (hot reload), Mailpit. Makefile targets (`up`, `migrate`, `psql`, `rescore`). Alembic migrations. Initial schema migration with RLS policies. Dev-mode auth (`AUTH_MODE=dev`). First working endpoints (health, users, boats).

### Step 2 — Data schema + API surface
All database tables migrated. Trips/waypoints/saved-routes/feedback/notifications endpoints — real implementations as features land, never placeholder stubs.

### Step 3 — Conditions data pipeline
Integrate Open-Meteo Marine, NOAA CO-OPS, and NWS APIs (all hit directly from local). Fetch, normalize, cache conditions for Tampa Bay waypoints in the `conditions_cache` table. Regime classification (bay vs. Gulf) + SMB wind-wave estimate for in-bay waypoints. This is the data foundation everything else sits on.

### Step 4 — Scoring engine
Implement `score_trip()` as a pure function. Unit tests with fixed condition inputs and known expected outputs. `make rescore` job calling it on manually defined waypoints — locally cron-able.

### Step 5 — Web frontend + manual routing
React PWA with Leaflet map. Pin drop for start/destination. Manual intermediate waypoints. Trip creation form. Score display with constraint breakdown. **Milestone: the app plans real trips for real weekends — before a dollar of AWS spend.**

### Step 6 — AWS deployment
Terraform + Terragrunt: VPC, RDS PostgreSQL + PostGIS, S3 + CloudFront, Cognito (Google OAuth, replacing dev auth), SES (replacing Mailpit), EventBridge Scheduler (replacing local cron), API Gateway + Lambda from the same container image. GitHub Actions CI/CD to dev, then prod.

### Step 7 — Auto-routing engine
Ingest NOAA ENC S-57 + USACE eHydro for Tampa Bay into PostGIS (developed locally, shipped as the same containers). Build the **channel graph** (nodes at junctions/bends, edges from `DEPARE`/channel centerlines). A* with draft-aware passability, tidal offset, bridge clearance. **Validate every route via GPX export into OpenCPN over official NOAA charts.** Design reference: VISIR-2's under-keel-clearance graph approach at ENC resolution.

### Step 8 — Underway co-pilot
GPS tracking via browser geolocation (foreground PWA). On-plan vs. behind calculation. Live turn-around deadline. Turn-back alerts on condition degradation. Native app (background GPS) follows in Phase 2.

### Step 9 — LLM layer (Phase 2)
Score explanation generation. Forecast uncertainty flagging. Weather window finder. Post-trip debrief. Bedrock integration.

### Step 10 — Co-pilot chat (Phase 3)
Tool use interface. Register engine functions as LLM tools. Chat UI in the app.

### Step 11 — Trip log + maintenance (Phase 4)
GPS track recording. Engine hours. Maintenance log with AI parsing. Service interval alerts.

---

## 10. Geographic Scope

**Phase 1:** Tampa Bay to Anna Maria Island. Covers home waters, the passes (Egmont, Anna Maria), and common day-sail destinations.

**Phase 2+:** Generalizes to all US coastal waters. Same data pipeline (NOAA ENC + USACE eHydro), more geographic coverage. Architecture supports this from day one — routing and conditions are parameterized by coordinates, not hardcoded to Tampa Bay.

---

## 11. Monetization Plan

**Phase 1:** Personal use only. No billing infrastructure needed. Google Auth restricted to owner's account.

**Beta:** Invite-only free access to a small group of sailors. No paywalls or usage limits. Collect feedback: does the scoring engine match real-world experience? What would they pay? What's missing?

**Launch:** Subscription via Stripe. Pricing model determined from beta feedback. App Store distribution via iOS native app.

---

## 12. Open Questions

1. **Channel-graph design details** — node density at bends, how to weight edges for "stay in the channel" preference vs. shortest distance across known-good open water.
2. **Tidal offset stations** — which CO-OPS stations to use across the Tampa Bay → Anna Maria corridor (St. Petersburg, Old Port Tampa, Manatee River entries).
3. **Score threshold for alerts** — configurable per-trip; default "below 60%" or "drops by 20+ points."
4. **Open-Meteo commercial tier** — Standard vs. Professional sizing once beta opens.
5. **SMB wind-wave model validation** — compare computed in-bay wave estimates against NDBC/observed data before trusting them in the score.

---

## 13. Verified External Links

### Data and services
- Open-Meteo Marine: https://open-meteo.com/en/docs/marine-weather-api — Pricing: https://open-meteo.com/en/pricing
- NWS API: https://www.weather.gov/documentation/services-web-api (`https://api.weather.gov`)
- NOAA CO-OPS: https://api.tidesandcurrents.noaa.gov/api/prod/
- NOAA NDBC: https://www.ndbc.noaa.gov/
- NOAA ENC / GIS: https://nauticalcharts.noaa.gov/data/gis-data-and-services.html
- USACE eHydro: https://www.sam.usace.army.mil/Missions/Spatial-Data-Branch/eHydro/
- USCG Bridge Clearances: https://www.dco.uscg.mil/Our-Organization/Assistant-Commandant-for-Prevention-Policy-CG-5P/Inspections-Compliance-CG-5PC-/Office-of-Bridge-Programs/Bridge-Guide-Clearances/
- Stormglass: https://stormglass.io/pricing/
- OpenSeaMap: https://openseamap.org/

### Routing prior art / references
- GDAL S-57 driver: https://gdal.org/en/stable/drivers/vector/s57.html
- VISIR-2 paper (GMD 2024): https://gmd.copernicus.org/articles/17/4355/2024/ — docs: https://cmcc-foundation.github.io/visir2-docu/
- weather_routing_pi (maintained fork): https://github.com/rgleason/weather_routing_pi
- OpenCPN: https://github.com/OpenCPN/OpenCPN
- libweatherrouting: https://github.com/dakk/libweatherrouting
- ORC polar database: https://github.com/jieter/orc-data — browse: https://jieter.github.io/orc-data/site/

### Infrastructure
- AWS Bedrock: https://aws.amazon.com/bedrock/
- Terragrunt: https://terragrunt.gruntwork.io/

### Rejected options (documented so they're not re-researched)
- Searoutes (€400+/mo, commercial shipping lanes, not inshore-capable): https://searoutes.com/pricing/
- Navionics/Garmin (routing exists in-app only; Web API is chart display only): https://developer.garmin.com/marine-charts/overview/
- Aurora Serverless v2 + ElastiCache Serverless for Phase 1 (cost floor $150–250/mo; revisit at scale)
