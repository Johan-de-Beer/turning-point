# Tactical engine (tactics_v1)

The tactical engine measures how each fictional team defends, attacks and takes corners. It works from a synthetic 5 Hz tracking layer, not from the event stream alone. Everything is synthetic: clubs, players, positions and tendencies are generated. Nothing here is measured from real players.

`GET /api/sessions/{id}/tactics` returns the report for the replay's current observed prefix. The Tactics panel under the pitch shows it as findings per team (Defending, Attacking, Set pieces), a key-moment diagram, the numbers behind each finding and the definitions used.

## Why a tracking layer

Offside traps, marking, pressing speed, runs that defenders fall for and target-man timing all depend on where players are without the ball. A pass list cannot show them. So the generator now also produces short tracking episodes around the moments that matter:

- **attack**: about 3 s before and 1.5 s after a forward pass into the attacking 40%. Covers the defensive line, runners, markers and the block shifting toward the ball.
- **possession**: the first seconds of a possession in a team's own half. Covers the press and the escape from it.
- **corner**: from the corner being set up until the delivery lands. Covers the ball's curve, target runs and markers.

Frames agree with the recorded events: the ball is at the event's start position at the pass frame and at its end position at the last frame. Off-ball movement between events is illustrative, generated from each fictional player's hidden tendencies. Player speeds are velocity-limited, and a test checks that no opponent moves faster than 9.5 m/s.

## Hidden tendencies, measured blind

`backend/tactical_profiles.py` plants tendencies the analysis must find without seeing them. For example, Vale's left-back Luca Briar steps up late, Vale marks man-oriented, Harbor's striker triggers most presses and Harbor builds up short. The analysis code in `backend/tactics.py` only reads frames and events. Tests check that it never reads the tendencies or plans, that it recovers each planted tendency, and that no tendency key appears in an API response.

The report only uses episodes that are complete and whose anchor event has been delivered at the replay's cutoff. It cannot show a moment before the replay reaches it.

## What is measured and the reasoning

All coordinates are team-relative: each team attacks toward x = 100 on a nominal 105 × 68 m pitch. Thresholds are constants at the top of `backend/tactics.py`; the report's `definitions` carry the exact wording.

### Offside trap

Under Law 11, a player is offside if any part they can score with is nearer the goal line than both the ball and the second-last opponent, in the opponent's half, when a team-mate plays the ball. The goalkeeper counts as one of the two last opponents. The engine uses one point per player and the second-highest defending player including the goalkeeper. It does not model body parts, deliberate play or refereeing judgement.

A trap is three or more of the back four stepping toward halfway at 2 m/s or faster in the 1.8 s before the pass. Onset is the first of two consecutive frames above that speed. A defender stepping 250 ms or more after the line's median onset is late. Five frames (1 s) at 5 Hz bound the timing precision, so the threshold sits above one frame. Reported per team: traps, caught offside, broken traps, step speed, line height and flatness. Reported per defender: late steps, mean lag and runners left onside.

**Opportunity:** when one defender is repeatedly late, the runner on that flank is the attacker who can attack the space. For a team attacking toward x = 100, the defending left-back covers the attacker's right flank, so a late left-back is an opening for the right winger.

### Shape and marking

Compactness is the back four's front-to-back spread and the outfield block's width and length, before and at the pass. The shift to the ball is the block's lateral movement toward the ball's side in the 3 s before a pass. Players who take much longer than the unit's median to finish 90% of their shift are flagged.

Man-oriented and zonal marking differ in whether a defender follows a runner out of their zone. The engine counts how often the nearest defender drops with a run at 2 m/s or faster. Following 60% or more of runs counts as man-oriented, 35% or less as zonal, anything in between as mixed. Two weaknesses are measured:

- **Early release:** a defender leaves their assignment to engage the ball while that attacker becomes free.
- **Late reaction:** a defender starts dropping 450 ms or more after the run begins, roughly two frames beyond a normal reaction.

### Press

A press is an outfield player within 25 m of the ball running toward it at 4.5 m/s or faster for two frames within 3 s of a possession starting in the opponent's own half. The first such player is the trigger. The player on the ball at that moment is the target. Time to pressure runs from the trigger's onset until they are within 2.5 m of the ball.

The outcome is the first of these within 12 s: a pass back to the goalkeeper, a turnover, a pass or carry past halfway, or a stoppage. The engine compares pressed and unpressed possessions, including how quickly a press forces the ball back to the keeper. PPDA (passes allowed per defensive action) is the common public measure of pressing intensity. It needs defensive-action events the synthetic stream doesn't have, so the engine reports press rate, closing speed and outcomes instead.

**Target:** a player who is pressed much more often than the team's other players when they receive is reported as the press target.

### Runs in behind

A run is an attacker moving toward goal at 5.5 m/s or faster (19.8 km/h, the usual high-speed running threshold) for three consecutive frames, starting near the defensive line. Runs count whether or not the runner receives the ball. The key measure is whether the run drew a defender: a back-four defender in the runner's channel retreating at 2 m/s or faster, before the pass, within 1.2 s of the run's start. Reported per runner: runs, runs in behind, runs targeted, offside and drag rate.

### Chance creation and passes

The initiator is the first outfield player in a possession that reaches the final third or a chance to complete a pass or carry gaining at least 12 units or entering the final third. Goalkeepers are excluded. Time to chance runs from the start of the possession to the shot or box entry.

Decisive passes are completed forward passes into the attacking 40%. Each has its length, angle and speed. The angle is measured from straight at goal, positive to the passer's right. Speed is the mean ball speed over the tracked flight. A through ball is a pass from the attacking half to a runner already in stride.

### Build-up from the goalkeeper

A sequence starts when the goalkeeper has the ball and lasts until the possession ends or 20 s pass. It reports short against long starts, time to reach the middle and final thirds, pass accuracy, possessions lost in the team's own half, and lines broken. Lines broken counts the opponent's forward, midfield and back lines (mean x of each unit) a completed pass crosses.

### Corners

A ball struck with the inside of the right foot curves right to left from the kicker's view. So from the attacking team's left corner, a right-footed taker produces an inswinger and a left-footed taker an outswinger, and the reverse from the right corner. The spin's Magnus effect causes the curve. The engine measures swing from the ball's tracked curve and compares it with the swing expected from the taker's foot and side. Also reported: delivery speed and flight time, landing zone, accuracy (distance from the landing point to the nearest attacker), and each target man's time to reach the landing spot and arrival relative to the ball.

## Observations

Findings are short sentences with a sample size, the players involved, evidence ids and, where useful, a key moment. They are either a **tendency** (what a team does) or an **opportunity** (a repeated weakness an opponent could test). Small samples are suppressed or labelled. An opportunity doesn't claim a goal or chance would follow, and no finding claims causality.

## Limitations

- Synthetic tracking at 5 Hz, generated from fictional tendencies. Timings are only accurate to about one frame (200 ms).
- Off-ball motion between events is illustrative.
- Offside uses one point per player.
- Thresholds are documented conventions for this demo. They have not been calibrated against real tracking data or reviewed by a football analyst.
