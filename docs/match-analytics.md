# Live match analytics (analytics_v1)

`GET /api/sessions/{id}/analytics` returns, for the observed prefix of the match only: field tilt, chance quality (xG), defensive line height, player workload and possession value. The app shows it in the **Live analytics** panel, which refreshes as the replay moves on. Match numbers (the three-minute window) also gained shots on target, duels won, xG and field tilt.

Everything is synthetic. The clubs, players, events and player tracks are fictional, and the models below are transparent heuristics. Nothing here is a validated or trained model.

## Positions, duels and body parts

- Each roster player has a specific position (`role`): GK, RB, CB, LB, CDM, CM, CAM, RW, ST, LW. Events in the feed and on the pitch read "Name (ST)".
- Duels are `TACKLE` events. A ground duel is recorded when a side wins the ball off a player in possession, and when a carrier rides a challenge. An aerial duel is recorded at each corner delivery. The actor is always the defending player, and `successful` means that defender won. **Duels won** for a team = its successful challenges + the opponent's unsuccessful ones. Duels have their own id series (`duel_0001`…), so the original events keep their ids and the tactical tracking that is seeded by event id is unchanged.
- Shots record `body_part` (right foot, left foot, head).

## Field tilt

A team's share of both teams' **final-third passes**: attempted passes into or within the attacking final third (x ≥ 66.67 at the start or end). It is reported for the match so far, the last 10 minutes and each 15-minute interval, next to possession for the same window, so "lots of the ball but little territory" (and the reverse) is visible. It counts where passes happen, not their quality, and it understates direct counter-attacks.

## Chance quality (xG)

Each shot gets a probability from a logistic function of:

| Input | Effect on the log-odds |
| --- | --- |
| Goal-mouth angle (radians) | +1.4 per radian |
| Distance to goal centre (m) | −0.12 per metre |
| Set-up | through ball +0.45, cutback +0.35, other pass 0, individual (carry / no assist) −0.1, corner −0.25, cross −0.35 |
| Body part | header −0.9 |

with an intercept of −0.6, clipped to 0.01–0.95. The coefficients were picked so reference shots land near textbook values (penalty spot in open play ≈ 0.27, six-yard line ≈ 0.6, 30 m ≈ 0.02). They are not fitted to data, so xG ranks chances within this sample; it is not a calibrated probability. **xG against** is the opponent's xG.

**Chance type:** Major when the shot's xG ≥ 0.30, Minor otherwise. In the Tactics panel, decisive passes no longer show the pass angle; the Chance column shows Major / Minor / None with the xG of the first shot later in that possession beneath it ("no shot" when the chance was a box entry without a shot).

## Possession value

A location value surface V(x, y) plays the role of expected threat: a baseline of 0.006 plus 0.75 × the open-play xG from that spot × a weight for how often play at that depth reaches a shot (a logistic in x centred at 78). An action's value is V(after) − V(before):

- completed pass or carry: V(end) − V(start);
- lost pass: −V(start);
- shot: its xG − V(where it was taken);
- dispossessed (lost a duel on the ball): −V(where the ball was lost), credited to the player who had it.

Values are shown in percentage points of scoring chance. Defensive actions and off-ball runs are not valued, and the opponent's gain from a turnover is not added.

## Continuous movement layer

The tactical tracking in `backend/tracking.py` only covers short episodes (about half the match). Workload and line height need every frame, so `backend/movement.py` runs all 22 players at 5 Hz for both halves. Each player is a velocity- and acceleration-limited follower of a target: their position in a tracking episode where one exists (matching that episode's pace), the ball when they hold it, and otherwise a formation spot that slides with the ball in and out of possession. Hidden fictional tendencies (line depth, work rate, a late fade) drive it; `backend/analytics.py` never reads them, and tests recover them from the measurements (Harbor defend higher than Vale, Harbor's right-back covers the most ground of their back four, Vale's left winger the least of their front three, Vale's attacking midfielder fades late).

## Defensive line height

Out of possession in live play only, distances from the team's own goal line in metres:

- **Back four:** mean depth of the four defenders (the "intended" line).
- **Deepest:** the deepest outfield player (exposure to balls in behind).
- **Team centroid:** mean depth of the ten outfield players.
- **Gap to midfield** and **back-four width**.

Reported for the match, the last 5 minutes, by 15 minutes, and by phase: settled, the first 5 s after losing the ball, and 1 s before each opponent shot. **Block:** high when the settled back-four mean is ≥ 42 m, low under 30 m, mid otherwise (at least 30 s of settled defending needed).

## Player workload (external load only)

Distance; high-speed running (≥ 5.5 m/s, 19.8 km/h); sprint distance and efforts (≥ 7 m/s, 25.2 km/h, at least 1 s); accelerations and decelerations (beyond ±3 m/s² for at least 0.4 s); a composite load (sum of velocity changes ÷ 10, arbitrary units); top speed; metres per minute for the match and the last 10 minutes. A player is flagged when their last-10-minute intensity (as a share of their own match average) is 10 or more points below the team's median outfield trend after 30 minutes. That is a description of running, not an injury or fatigue diagnosis.

Internal load (heart rate, HRV, RPE, wellness) and the acute:chronic workload ratio are deliberately absent: they need physiological data and weeks of history that a single synthetic match does not have, and inventing them would be fabrication.

## Contract samples

`frontend/src/lib/fixtures/analytics-20min.json` and `tactics-15min.json` are the backend's own reports; regenerate them with `python -m scripts.write_contract_samples` after changing the generator or report wording (backend tests enforce they match).
