# SailReady — Backlog & Roadmap

**Updated:** 2026-06-10 (post-audit)
**Companion to:** [SPEC.md](SPEC.md) — the spec holds the *what and why*; this holds the *when*.

---

## Milestone A — "It guides me safely" (finish the Phase 1 promise)

| # | Item | Notes | Status |
|---|---|---|---|
| A1 | **Grounding check in scoring** | Charted depth + tide-at-arrival vs draft + 1ft margin; land/unsurveyed/unknown-depth-hazard flags; subordinate tide stations (hilo-only, e.g. Shell Point 8726468) cosine-interpolated and flagged. Caught the land waypoint: trip 100% -> 5%. | **DONE** 2026-06-10 |
| A2 | **Boat + user profile UI** | Modal: all boat fields incl. depth padding under keel, sailing preference, pointing angle; multi-boat with default-star; user name + alert thresholds. | **DONE** 2026-06-10 |
| A3 | **Trip watcher + notification bell** | Continuous watcher service (compose): re-checks every 3h within 48h of departure, 6h within a week, daily beyond; cache TTLs keep upstream APIs polite. Bell with unread count, click-through to trip, mark-all-read. "Score" reframed as "Check conditions now" + watching hint. | **DONE** 2026-06-10 |
| A4 | **Go-closer suggestion + max-reach ring** | Draw max_reachable_distance_nm as a circle from departure; suggest nearer saved destinations that fit the window (the spec's "shrinking circle"). | TODO |
| A5 | **SMB in-bay wind-wave estimate** | Regime classification (bay polygon vs open Gulf) + shallow-water SMB from wind/fetch/depth; cross-check NDBC observations; stop trusting the global swell model inside the bay. | TODO |
| A6 | **Saved routes + feedback UI** | Both APIs exist; surface them (save current route, instantiate trip from template, post-trip thumbs + actuals form). | TODO |
| A7 | **API integration tests** | httpx test client against the stack: auth context, RLS isolation, trip lifecycle, score persistence. Engine already covered (18 tests). | TODO |
| A8 | **Long-leg conditions subdivision** | Conditions are sampled per waypoint at arrival time; a leg uses its START point's conditions. Fine at day-sail pin density, wrong for a 60nm leg (Tampa->Key West). Auto-subdivide legs every ~5-10nm for sampling without adding visible waypoints. | TODO |
| A9 | **Local-knowledge waypoint override** | Acknowledge a flagged waypoint via its popup -> depth violations become "acknowledged (local knowledge)" warnings with the chart math still shown; land never acknowledgeable. Beercan trip: 24 violations -> warnings, real drivers (thunderstorms, gusts) surfaced. | **DONE** 2026-06-10 |

## Milestone B — "Take it to sea" (the co-pilot)

| # | Item | Notes |
|---|---|---|
| B1 | **Local HTTPS** | Tailscale serve (preferred — also gives iPhone access anywhere) or mkcert. Required for browser GPS (secure context). |
| B2 | **React PWA migration** | The 526-line static prototype is at its limit. React + TS + Vite, same Leaflet map, same API; service worker for last-known-plan caching. Carry over all current UI features. |
| B3 | **Co-pilot v1** | POST /trips/{id}/position from watchPosition; on-plan vs behind per leg; live turn-around deadline recompute; turn-back alert on condition degradation. Foreground PWA (screen on) — native app later. |
| B4 | **Trip log** | GPS breadcrumb (LineString), engine hours, auto-capture actual leg times into trip_feedback — feeds calibration. |

## Milestone C — "Let friends in" (real multi-user)

| # | Item | Notes |
|---|---|---|
| C1 | **Cognito + Google SSO, invite-only** | No self-signup. JWT validation replaces AUTH_MODE=dev (mode switch + cognito_id column already in place). Apple Sign In follows when App Store matters. |
| C2 | **AWS deploy** | Build sequence step 6: Terraform/Terragrunt, RDS+PostGIS, Lambda container images, S3+CloudFront, SES, EventBridge rescore. |
| C3 | **Security hardening pass** | Secrets Manager, security headers/CSP, per-user rate limiting, CORS lockdown, RDS backups, auth audit log, tile-endpoint rate limit. |
| C4 | **Bridge clearance check** | Ingest BRIDGE (VERCLR) from ENC cells; air-draft violation on route legs crossing under. |
| C5 | **Weather window finder** | POST /trips/windows — score all viable windows over the forecast horizon, ranked. |
| C6 | **USACE eHydro channel surveys** | Channel-grade depth data (the source Aqua Map uses) layered over ENC DRVAL1 minimums — fixes the Shell Point creek conservatism properly (SPEC §6). |

## Milestone D — "Beta & delight"

| # | Item | Notes |
|---|---|---|
| D1 | LLM trip briefings (Bedrock) | Natural-language explanation of the deterministic score. |
| D2 | Forecast uncertainty flagging | Open-Meteo vs NWS disagreement -> "treat this score as less reliable" (user already hit this: their weather app said rain, model said 15%). |
| D3 | **Share my trip** | Public read-only link: signed expiring revocable token; OG meta for rich previews. |
| D4 | **Trip photos** | Presigned S3 uploads, gallery on trip + log. |
| D5 | **Social cards (FB/IG)** | Rendered trip card (route map + score + stats) for sharing. |
| D6 | Float plan email | One-tap safety brief to a shore contact (spec'd Phase 1, deferred). |
| D7 | Co-pilot chat | LLM + tool use over engine functions (Phase 3 of spec). |
| D8 | Calibration from feedback | Predicted-vs-actual analysis -> boat profile suggestions. |
| D9 | Maintenance log | NL entry, AI parsing, service intervals (Phase 4 of spec). |

## Debt register

- Prototype UI replaced by B2 (do not extend the static page past Milestone A)
- Stale-tab mitigations shipped (app-version reload banner + optimistic concurrency on route saves) — full fix remains B2
- Marine-warning drivers ride constraint_type 'wind' (enum lacks a dedicated value)
- 422 validation errors bypass the {data, error} envelope
- Cold-score latency: per-waypoint conditions fetched sequentially
- conditions_cache table never pruned (add TTL sweep to rescore job)
- Egmont seed trip retained intentionally: waypoint on charted land = A1's regression test

## Resolved-by-design (decisions, not gaps)

- No marine routing API exists -> self-built channel-graph router (Phase 2, SPEC §6a)
- No boat-model database -> manual entry + optional ORC polar pre-fill
- LocalStack skipped; real AWS only at C2
- ENC tiles: cache NOAA renders now, self-render from PostGIS vectors when router lands
