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
Default Casual, no favorites, English, accelerated 60x replay explained. Start creates a capability-isolated session. Server owns clock; pause freezes every eligibility interval. Half stops at 45:00; Continue releases the second period. Restart clears derived state and increments generation. No future seek. Mode changes presentation density but preserves fact IDs. Favorites affect ordering and player context, never global statistics. Every card opens its original evidence window. Selected evidence event highlights only its marker. Overlay can be previewed/exported only during its 90-second simulated validity. Optional pause-on-insight supports demos.

Empty/warming up: explain why a full observed window is required. Loading: retain context with skeleton/status. Paused/halftime/ended: explicit status and next action. Reconnecting/offline: preserve last valid cutoff and offer retry. Invalid event: diagnostic rejection, no fabrication. Insufficient evidence: no confirmed card. Timeout/rejected narrative: labeled template fallback and inspectable trace. Correction: retract stale overlay, correct score and recap, show notice. Unavailable language: English-only notice. Significant insights use polite live announcement; replay ticks do not.

## Accessibility and animation
Semantic buttons and labels, keyboard dialogs with focus restoration, non-color identifiers, text equivalents to graphics, reduced-motion preference, no audio or rapid flashing, 200% zoom, 360/768/1440px checks. The 3D pitch uses an original Blender stadium, lit turf, goals, discrete event-arrow reveals and shot rings. Animation illustrates observed events and does not represent continuous measured ball or player tracking. An SVG pitch remains available if WebGL fails. See `stadium-assets.md` for source assets and regeneration.

## Public-demo visual refinement

The overview now gives the pitch roughly seventy percent of the desktop match-room width, with a compact editorial narrative beside it. Statistics form a short band beneath the pitch. Player focus, the latest four events and an episode timeline use fine rules and spacing rather than repeated nested cards. Provenance and full metric/evidence detail remain available in dedicated inspectors. The landing page uses a large typographic introduction and an exploratory stadium view.

The refined palette is near-black `#0d151c`, surface `#111f2a`, off-white `#f2f2ec`, secondary `#a5b3bd`, and borders `#2b3942`. Mint/cyan/amber retain their existing meaning. Main prose remains 16px. Public deployment uses the same functional interface and clearly labels synthetic data and mock narratives.
