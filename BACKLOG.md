# SailReady — Backlog & Roadmap

**Updated:** 2026-06-10 (post-audit)
**Companion to:** [SPEC.md](SPEC.md) — the spec holds the *what and why*; this holds the *when*.

---

## Milestone A — "It guides me safely" (finish the Phase 1 promise)

| # | Item | Notes | Status |
|---|---|---|---|
| A1 | **Grounding check in scoring** | Charted depth + tide-at-arrival vs draft + 1ft margin; land/unsurveyed/unknown-depth-hazard flags; subordinate tide stations (hilo-only, e.g. Shell Point 8726468) cosine-interpolated and flagged. Caught the land waypoint: trip 100% -> 5%. | **DONE** 2026-06-10 |
| A2 | **Boat + user profile UI** | Form for all boat fields (draft, air draft, beam, speeds, polars, limits, sailing preference, pointing angle); user alert thresholds. Today only via /docs. | TODO |
| A3 | **Scheduled daily rescore + notification bell** | Cron container (or ofelia) in compose firing the existing rescore job; unread-count bell in UI reading the existing notifications API; Mailpit verifies email path. | TODO |
| A4 | **Go-closer suggestion + max-reach ring** | Draw max_reachable_distance_nm as a circle from departure; suggest nearer saved destinations that fit the window (the spec's "shrinking circle"). | TODO |
| A5 | **SMB in-bay wind-wave estimate** | Regime classification (bay polygon vs open Gulf) + shallow-water SMB from wind/fetch/depth; cross-check NDBC observations; stop trusting the global swell model inside the bay. | TODO |
| A6 | **Saved routes + feedback UI** | Both APIs exist; surface them (save current route, instantiate trip from template, post-trip thumbs + actuals form). | TODO |
| A7 | **API integration tests** | httpx test client against the stack: auth context, RLS isolation, trip lifecycle, score persistence. Engine already covered (18 tests). | TODO |
| A8 | **Long-leg conditions subdivision** | Conditions are sampled per waypoint at arrival time; a leg uses its START point's conditions. Fine at day-sail pin density, wrong for a 60nm leg (Tampa->Key West). Auto-subdivide legs every ~5-10nm for sampling without adding visible waypoints. | TODO |
| A9 | **Local-knowledge waypoint override** | ENC DRVAL1 is the conservative minimum of a whole depth polygon — Shell Point creek charts 3.0ft while soundings beside the pins read 3.9-6.9ft. Let the skipper acknowledge a flagged waypoint ("I know this channel"), downgrading violation->warning with an audit note in drivers. Real fix for channel-grade depth is eHydro (C6). | TODO |

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
