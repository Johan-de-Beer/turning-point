# Replay, evidence and provider implementation

Reviewed locally on 2026-10-05. This build describes one fictional synthetic fixture. “Turning point” labels a descriptive observed episode, not causality, prediction or a validated football model.

## Fixture generation and football review

`backend/generator.py` is a seeded state machine. It owns period, live/stopped state, possession, legal actor/recipient membership, event coordinates and shot outcomes. Macro phases are deliberately constructed to exercise pressure, possession with little threat, end-to-end play, transitions and neutral play. Legal micro events are sampled deterministically. The production fixture contains 694 delivery envelopes, including two period start/end pairs; it is under `server_data/fixtures`, outside the frontend build context.

Pressure ownership cycles target 75% in-play possession, two forward entries per cycle and a shot. Possession-with-little-threat cycles use safe completed passes and avoid shots/box entries. End-to-end cycles alternate ownership and include attempts at both ends. Neutral periods contain sparse shots and fewer forward entries. Goals do not automatically trigger a pattern. The private expected-window manifest lives only in backend tests; neither it, the seed, complete event stream nor the future outcome enters ordinary API responses or agent bundles.

The four-minute planted attacking phases are intentionally dense for demonstration. A football expert must review whether the sampled events, shot frequency, possession transitions, involvement distributions and narrative terms are plausible enough for the demo. Review the threshold choices and their false positives; do not present them as learned or scientifically validated. Coordinate progressions are schematic action endpoints, not a continuous physical ball model. No real clubs, players, footage, measured speeds, distances or expected-goals values are used.

`FIXTURE_CORRECTION=1` creates a separate reproducible correction demonstration from the same state machine. A later delivery revises an earlier observed goal attempt. This option is server-side and does not give the browser a future correction manifest.

## Measurements and eligibility

Snapshots are evaluated every five simulated seconds. Current events use `(T−180000, T]`; preceding comparison uses `(T−360000, T−180000]`. Both are restricted to the current period. A baseline is unavailable until a full eligible preceding window exists; unavailable is never encoded as zero.

Exact integer counts are retained. Shots count SHOT events; goal/saved are on target. Goals derive solely from goal-outcome shots. Pass accuracy is completed/attempted × 100, or null for no attempts. Final-third entries count completed PASS or CARRY crossing x < 66.67 to x ≥ 66.67. Box entries count a completed PASS or CARRY crossing from outside to inside x ≥ 83 and 20 ≤ y ≤ 80.

Possession is integrated duration, using the effective state at the left boundary. Possession facts cite state transitions influencing both numerator and denominator, including stopping boundaries. Known owned live time, stoppage time and unknown state are recorded separately. Patterns require a complete 180-second window, at least 120 seconds of known in-play time, no unknown time and valid state transitions. Tackle events do not themselves change ownership. Live turnovers exclude restarts and period boundaries. A legal state-transition tombstone is retained; missing dependent context causes metrics to fail closed.

Pattern conditions are versioned in `backend/patterns.py`. Entry needs two consecutive eligible passes; closure needs two failures. Period changes and replay restart reset debounce. Default priority is end-to-end, sustained pressure, sterile possession, with suppressed candidates exposed in diagnostics if future threshold edits overlap. No prose claims an increase without a computed comparison; current templates describe the current observed window only.

Player involvement counts unique events with a player actor or a completed-pass recipient. Touches mean one modeled controlled touch per POSSESSION/PASS/CARRY/SHOT actor and completed-pass recipient; these are not all real-ball touches. Passes attempted/completed, completed passes received, carries, shots, goals and tackles have explicit event semantics. Favorite filtering changes ordering and supported player context, never global evidence or score.

## Replay, corrections and persistence

FastAPI serves a single local SQLite process. Clock authority is monotonic server time. Background reconciliation runs every 100ms; handlers also reconcile elapsed time, so polling rate does not control progression. Pause freezes the eligibility clock. Speed changes reconcile at the old speed before switching. Only 1×, 12× and 60× are supported. A large tick halts exactly at the first half until Continue releases period-two envelopes, including shared-boundary timestamp events. Full time requires the delivered final marker.

Session creation requires a browser-generated bearer capability and Idempotency-Key. SQLite persists only SHA-256 capability hashes. Missing/wrong capabilities use the same 404 response across data/control routes. Idempotency is capability-scoped; a changed body with the same key is 409. Opaque HMAC cursors bind session, generation and transport version; expired/mismatched cursors yield an explicit cutoff-safe resynchronization. Fixture delivery sequence, transport version and metric snapshot identity are distinct.

Canonical observed revisions, retained historical revisions, snapshots, insights, recaps and minimal role traces are persisted. Valid tombstones retain original identity/time checks. Duplicate identical event versions have no additional effect, conflicting same-version payloads are rejected, and older deliveries cannot replace newer canonical versions. Roster/coordinate/time/live-state errors are rejected and shown in diagnostics. No public fixture ingestion, seek or arbitrary-cutoff endpoint exists.

Higher revisions/tombstones increase data_epoch, remove overlays, retract prior explanations and recompute affected historical evidence from the canonical observed prefix. Recaps are marker-gated and regenerated with a correction notice when revised. Restart increments generation and clears that session’s outputs. Recovery restores unfinished sessions paused and records interrupted role runs as recoverable; playing again is a user action. Local retention is 32 active sessions, with 24-hour idle expiry checked during authorization/create plus startup cleanup. This capability isolation is a local MVP boundary, not production authentication.

## Two independent role stages and hard validation

`backend/agents.py` contains both system prompts and the `ExplanationProvider` interface. Football Analyst receives an immutable cutoff-safe fact bundle and selects fact IDs, importance, supported associations and caveats. Evidence Editor independently checks that proposal against the same bundle and supplies materially different casual/analyst variants plus the overlay. It can request one bounded analyst revision followed by another editor review. Provider exceptions use at most one transient retry per call, then transparent deterministic fallback. The queue is capped at eight jobs, concurrency at two, and each call has a configured timeout.

Hard validation runs outside both roles. It rejects unknown IDs, version mismatches, unsupported player associations, wrong numbers, arbitrary factual prose, markup and unsupported causal/predictive claims. To prevent a number from being incorrectly paired with another metric or club, numeric narrative clauses are rendered by trusted code from fact slots. Providers must select exact approved clauses, rather than author unrestricted numerical prose. This narrow MVP adapter prioritizes traceable factual integrity over flexible prose. The mock executes the same two role contracts and review/fallback path, and output honestly says `mock_template` or `deterministic_fallback`.

Jobs capture generation, data_epoch, preferences_version, snapshot, rules, audience and language. The final commit checks version keys, pending/supersession state and overlay expiry atomically under the same session lock as controls and ingestion. Restart, correction, preference changes and reversed completion cannot resurrect stale variants. A later ordinary tick preserves historical approved insights with their original window. Overlays are valid for 90 simulated seconds, frozen while paused; score notices outrank ordinary insights. Optional pause-on-insight supports accelerated demonstrations.

Role diagnostics retain input fact IDs/fingerprint, provider, version keys, review status, validation errors, duration and fallback reason. They do not retain raw prompts, credentials or capabilities. English is the only accepted P0 language.

## Optional Microsoft integration

Mock is the complete default path and requires no account or paid call. The optional route is Microsoft Foundry `AIProjectClient(endpoint, credential=DefaultAzureCredential()).get_openai_client().responses.create(...)`, using an explicit deployment model. The installed optional versions and compatibility check are in `backend/requirements-microsoft.txt` and `scripts/check_microsoft_sdk.py`.

Activation fails closed unless existing resources/costs were approved, `MICROSOFT_INFERENCE_APPROVED=true`, a positive per-process `MICROSOFT_MAX_CALLS` limit, endpoint and deployment are supplied. Output tokens, input size, SDK network timeout and retries are bounded. No resources or identities are provisioned. The locally tested SDK check uses a fake credential and httpx mock transport, so it makes no external/billable calls. A real provider invocation remains unverified and requires approved existing access plus explicit limits. Installing this adapter does not make the demo Microsoft-integrated or fully AI-powered.

## Executable checks and measured results

Use `python -m pytest backend/tests -q`. Coverage includes strict schemas and fixture invariants, exact thresholds and near misses, zero denominators, time-window boundaries, possession integration, coverage/stoppages, period resets, all three actual planted windows/debounce, neutral/goal negative cases, duplicate/late/revised/deleted input, two isolated sessions, capability/no-spoiler API tests, cursor resync, idempotency, fake-clock controls, halftime/full-time locks, SQLite recovery/expiry, preferences, overlay pause/expiry, all configured mock failure classes, numeric-metric/player adversarial outputs, reversed/stale jobs and corrected recaps. Optional SDK bounds are tested without network calls.

The complete fake-clock replay observed 694 envelopes over 90 minute observations and confirmed all three pattern types in both halves. On this Windows development host with Python 3.12.3, a measured run’s maximum deterministic cutoff-state update was 108.0ms. This includes ingestion, snapshots and response construction; agent latency is measured separately in role traces. It is a local sample, not a production latency guarantee or an invented benchmark.

Remaining review: football expert signoff, a real Microsoft run with approved resources/cost limits, clean-machine Docker startup on a machine with Docker, and any public judging/publishing/submission actions. Synthetic mock completion and submission readiness are distinct.
