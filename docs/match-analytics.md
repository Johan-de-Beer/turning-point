# Live match analytics (analytics_v2)

`GET /api/sessions/{id}/analytics` returns, for the observed prefix of the match only: field tilt, chance quality (xG), defensive line height, player workload and possession value, plus (since analytics_v2) game state, heatmaps, xGoT and goals prevented, tempo, PPDA, chance creation (touches in the box, Zone 14, key passes, xA), packing and a VAEP-style value. Those are described in the second half of this note. The app shows it in the **Live analytics** panel, which refreshes as the replay moves on. Match numbers (the three-minute window) also gained shots on target, duels won, xG and field tilt.

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

## Game state (analytics_v2)

The scoreline from each team's view: winning, drawing or losing. A goal's own shot counts in the state before it (so the equaliser was taken "losing"). For each state a team has been in, a row gives the minutes spent there and, for those minutes only: possession, field tilt, passes, shots, xG, xG per shot, goals, box touches, xOVA, VAEP and VAEP per action, PPDA, vertical progression, directness and the settled back-four height. Each shot also carries the shooter's game state. One match has few goals, so a state can last only minutes; the rows are context for the other numbers, not a verdict.

Planted (hidden) behaviour, re-measured by the tests: Harbor drop their out-of-possession line by about 8 m while they lead. The split shows it (their settled back four sits about 2 m deeper while winning than while drawing; the ball's position softens the raw drop).

## Heatmaps

A 12 x 8 grid in the team's attacking direction (left to right), for each team and each player, in four kinds:

- **Touches** (event-based): gaining the ball, passes, receptions, carries (at their end) and shots.
- **Positions** (tracking-based): seconds spent in each cell, sampled once a second from the continuous 5 Hz synthetic positions, so off-ball positioning counts too.
- **Passes received** and **Defensive actions** (duels contested and interceptions): event-specific maps.

The panel shows the share of the weight by third and by channel beside the map. A hot zone shows where play happens, not how well it went, and it carries the game state with it.

## Goalkeeping: xGoT and goals prevented

Goals and saved shots now record a synthetic **placement**: where the ball crossed the goal line (`y_m`, metres from the centre, positive to the shooter's right; `z_m`, height) and its pace (`speed_mps`). It comes from a fourth seeded stream, so every other event is unchanged. **xGoT** (post-shot xG) is a logistic of:

| Input | Effect on the log-odds |
| --- | --- |
| Pre-shot xG | +0.5 × its log-odds |
| Reach: distance from a central keeper's hands, √((|y| / 3.66)² + ((z − 1.0) / 1.44)²) | +2.0 per unit (0 at the keeper, about 1.3 in a top corner) |
| Pace | +0.1 per m/s above 20 |

with an intercept of −2.4, clipped to 0.02–0.97 (a central, soft shot from the penalty spot ≈ 0.04; a top-corner strike at 28 m/s ≈ 0.6). Off-target and blocked shots have none. **Goals prevented (xGP)** = xGoT faced − goals conceded per keeper; **placement added** = a team's xGoT − the pre-shot xG of the same shots. Planted: Harbor's keeper makes many more hard saves than Vale's, so Harbor's xGP is clearly positive and Vale's is not.

## Tempo and pressing

- **Vertical progression:** net metres the ball moved toward goal per second of possession.
- **Passes per final-third entry:** completed passes in a possession before it first reaches x ≥ 66.67 (counting the entering pass), for possessions starting outside it.
- **Directness:** forward ÷ (lateral + backward) passes, where forward or backward means at least 5 m of depth.
- **Possession length** by the third it started in; **progressive passes** (at least 30 m closer to goal within the own half, 15 m across halfway, 10 m in the opponent's half); **regain to progressive pass** (median seconds after an open-play regain). Also by 15 minutes, to show tempo changes.
- **PPDA:** the opponent's attempted passes in their own 60% of the pitch ÷ this team's duels and interceptions there.

These recover planted behaviour: Harbor build short from the back (longer possessions from their own third) and press more (lower PPDA).

## Chance creation

**Touches in the box** (x ≥ 83, 20 ≤ y ≤ 80, receptions included), **box entries**, **Zone 14** touches and entries (66.67 ≤ x < 83, 33.3 ≤ y ≤ 66.7), **key passes** (the last completed pass to a teammate who then shoots; the receiver may carry first but no one else may touch it, and the pass must reach the final third unless the shot is first time), **first-time key passes** (the article's stricter count), **assists**, **xA** (xG of the shots a player's key passes set up), key-pass type (cross, cutback, through ball, pass, corner) and origin (wide or central), and xG per box touch. In the synthetic end-to-end spells the keepers' long balls go straight to a forward who carries and shoots, so the keepers show up as creators there.

## Packing

For each completed forward pass or carry, the outfield opponents whose depth lay between the ball's start and end, from the continuous synthetic positions at the frame nearest the action. **Passing packing rate** = opponents bypassed by passes ÷ all pass attempts; **dribbling packing rate** = by carries ÷ carries; also defenders (opponent back four) bypassed and line-breaking actions (3 or more bypassed). Every bypassed player counts the same, wherever they were.

## xOVA and VAEP

**xOVA** (expected offensive value added) is the existing possession value: the scoring side only. The **VAEP-style** value adds the conceding side. A team holding the ball at p has scoring chance V(p) and conceding chance ρ·V(p̄), where p̄ is the mirrored spot (the opponent's view) and ρ = 0.1 the counter-attack risk; VAEP = Δscoring − Δconceding. A lost pass or dispossession is charged the full swing to the opponent holding the ball; the defender who wins it (a successful tackle, or an interception: the open-play regain right after an opponent's lost pass) is credited with half of that swing. A shot ends the possession's conceding risk. It is a transparent analogue on the location value surface, not the trained VAEP model, and like it values on-ball actions only.

## Contract samples

`frontend/src/lib/fixtures/analytics-20min.json` and `tactics-15min.json` are the backend's own reports; regenerate them with `python -m scripts.write_contract_samples` after changing the generator or report wording (backend tests enforce they match).
