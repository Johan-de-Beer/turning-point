# Turning Point — product and design

## Product brief
An evidence-led second screen for a reproducible synthetic football replay. Casual fans ask “What changed, and why should I care?” Analysts ask “Which observations support that interpretation?” Success is start replay → see an observed pattern → inspect its events → switch audience mode → select a fictional player → read a marker-gated recap. No predictions or causal claims.

## Screen map and components
Start/preferences → Match room → Evidence dialog / Preferences dialog / Overlay JSON dialog → Halftime recap → Continue → Full-time recap.
Components: masthead, original team monograms, scoreboard, clock, replay controls, mode segmented control, 3D schematic pitch, current narrative, metric comparison rows, insight timeline, event feed, searchable player selector, player statistics, evidence inspector, pipeline diagnostics, recap cards, accessible dialogs.

## Tokens
Background #0B1220; surfaces #111C2D and #152033; text #F8FAFC; secondary #CBD5E1; teal #5EEAD4; Harbor cyan #38BDF8; Vale amber #FBBF24. System sans-serif; 16px base; tabular clocks; 8px spacing; 12px card radius. Editorial display titles with tight tracking. Focus: 2px teal outline with offset. Distinguish teams with names, initials and shirt numbers as well as color. Contrast must be measured against final surfaces.

## Responsive wireframes
1440px: masthead / fixture scoreboard / replay toolbar / [large pitch + current insight | event/evidence rail] / [match pulse + metrics | player focus] / timeline + diagnostics.
768px: scoreboard / toolbar / pitch / insight / two-column metrics + player focus / event feed.
360px: compact scoreboard / controls / current explanation / pitch / metrics / player focus / timeline. Evidence is a full-width dialog, never a compressed desktop table.

## Interaction and state specification
Default Casual, no favorites, English, readable 12x replay with optional 60x. Start creates a capability-isolated session. Server owns clock; pause freezes every eligibility interval and the current football movement. Half stops at 45:00; Continue releases the second period while preserving unfinished observed actions. Restart clears derived state and increments generation. No future seek. Mode changes presentation density but preserves fact IDs. Favorites affect ordering and player context, never global statistics. Every card opens its original evidence window. Selected evidence displays its exact historic event revision; Replay this event animates that action once without changing the live frame or server clock. Overlay can be previewed/exported only during its 90-second simulated validity. Optional pause-on-insight supports demos.

Empty/warming up: explain why a full observed window is required. Loading: retain context with skeleton/status. Paused/halftime/ended: explicit status and next action. Reconnecting/offline: preserve last valid cutoff and offer retry. Invalid event: diagnostic rejection, no fabrication. Insufficient evidence: no confirmed card. Timeout/rejected narrative: labeled template fallback and inspectable trace. Correction: retract stale overlay, correct score and recap, show notice. Unavailable language: English-only notice. Significant insights use polite live announcement; replay ticks do not.

## Accessibility and animation
Semantic buttons and labels, keyboard dialogs with focus restoration, non-color identifiers, text equivalents to graphics, reduced-motion preference, no audio or rapid flashing, 200% zoom, 360/768/1440px checks. The 3D pitch uses an original Blender stadium, lit turf, goals and one textured football that follows delivered pass, carry and shot endpoints. Active participant names, event time and outcome identify the action; a current route and progress strip accompany the ball. With motion enabled, each queued movement reaches a visible intermediate point and endpoint, including dense deliveries on slow render frames. Animation illustrates synthetic recorded events and does not represent continuous measured ball or player tracking. An SVG pitch remains available if WebGL fails. See `stadium-assets.md` for source assets and regeneration.

## Analysis-desk refresh (October 2026)

The interface returns to the original prompt's palette and is rebuilt as feature components under `frontend/src/features/` (start, match, evidence, recap, diagnostics, preferences). Tokens live once, on `:root` in `frontend/src/styles.css`; `src/lib/contrast.test.ts` reads that file and fails if any text token drops below WCAG 4.5:1 on any surface, or form borders below 3:1.

| Token | Value | Use |
| --- | --- | --- |
| `--bg` / `--bg-raised` | `#0B1220` / `#0F1829` | Page, inset wells |
| `--surface` / `--surface-2` / `--surface-3` | `#152033` / `#1B2940` / `#22324C` | Cards, raised rows, tracks |
| `--text` / `--text-2` / `--text-3` | `#F8FAFC` / `#CBD5E1` / `#94A3B8` | Primary, secondary, tertiary text |
| `--teal` / `--teal-soft` / `--teal-ink` | `#5EEAD4` / `#0F3A3D` / `#042F2E` | Emphasis, secondary buttons, text on teal |
| `--home` / `--away` | `#38BDF8` / `#FBBF24` | Fictional team colours (always paired with initials or names) |
| `--border-input` | `#64748B` | Form-control boundaries (≥3:1) |

System sans-serif, 16px body, tabular numerals for clock/score/metrics, 8px spacing scale, 12px card radius, 2px teal focus outline.

**Match room, 1440px.** A sticky header carries the persistent scoreboard (team crests with initials, score, clock, period/status), the synthetic and provider status, preferences, the replay toolbar (play/pause/continue, restart, speed, a "Synthetic replay · 60× accelerated" chip, Casual/Analyst) and a 90-minute match timeline. The timeline shows observed progress, a half-time divider, every confirmed insight window at its original match time (opens its evidence) and goals (highlight the shot on the pitch). Below, the main column holds the current insight above the schematic pitch and lower-third overlay; the right activity rail holds the insight timeline, a 12-event feed and recap links. Match numbers and player focus sit beneath.

**768px.** Single main column; the activity rail becomes two columns (timeline, events) above the recap links; metrics and player focus stack.

**360px.** Scoreboard card, controls, current explanation, pitch, insight timeline, events, recaps, numbers, player focus. The header is not pinned on phones; a slim score strip appears once it scrolls away. Dialogs become bottom sheets with a drag-handle cue. Wide tables scroll inside their own region. The header also stops pinning on short viewports (≤600px tall), so 200% zoom never hides content under it.

**Casual vs Analyst.** Both use the same insight and fact IDs. Casual adds up to three plain-language fact chips built only from computed facts (for example "67% of the ball · HBR"), a one-line pattern glossary, and keeps the evidence one button away. Analyst shows the metric grid, metric definitions, coverage and the prior-window comparison by default, and analyst recaps lead with the measured facts before the story beats.

**Player focus.** The feed can be narrowed to the favourite player (actor or completed-pass recipient, matching the server's involvement definition). Goals and period markers stay visible and are labelled "match context". The insight card states whether the selected player appears in the insight's evidence or is shown only as match context. Player stats show involvements, modelled touches, passes, passes received, shots and goals or tackles, with the server's own definitions.

**Evidence inspector.** Opens with a summary (pattern, team, window, rule checks passed, fact and record counts, coverage gate), then separately tagged Measured facts, Heuristic rule checks and Limitations sections, coverage/baseline and the supporting event-version table.

**Performance.** The Three.js stadium is code-split and loaded after first paint, with a labelled placeholder, so the main bundle no longer carries WebGL code.
