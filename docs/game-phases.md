# Phases of play (phases_v1)

`GET /api/sessions/{id}/phases` returns, for the observed prefix of the match only, a report organised around the phases of play: how long each team spent in possession, out of possession, in transition and at set pieces; what happened in each attacking transition and after each loss (counter-press and rest defence); the defensive block and its line height in different situations, with recovery runs and keeper sweeps behind a high line; progressive carries and expected threat (xT); full-back roles and positional rotations; possession against control; pressing over time; finishing; and analyst notes that pair each number with moments to watch on the replay. The app shows it in the **Phases of play** panel under Live analytics. Every moment has a **Show** button that highlights its event on the pitch.

Everything is synthetic. The clubs, players, events and 5 Hz player positions are fictional. The thresholds below are documented conventions, not calibrated against real tracking data, and xT is fitted on other synthetic matches from the same generator. The report never reads the generator's hidden tendencies; tests check that it recovers what was planted.

## Quantitative and qualitative

The articles behind this round make one point repeatedly: numbers say how often and where, the pictures say why. So each analyst note has three parts: the **quantitative** line (with its sample size), **watch for** (what the replay can show that the numbers cannot: compactness, who covers, which run opened the lane), and up to three **moments**. Notes never claim a cause, and small samples carry a caveat.

## Phases of play

Every live-ball second of a team belongs to one of six phases:

| Phase | Definition |
| --- | --- |
| Attacking | Settled possession. Goal kicks and kick-offs start here. |
| Attacking transition | The first 10 s after an open-play regain, extended to 15 s while it is a counter (it reached the final third within 10 s). |
| Attacking set piece | The first 10 s after a corner, free kick or throw-in. |
| Defending, defensive transition, defending set piece | The mirror image, from the opponent's possession. |

Each phase row reports time, share, passes, final-third entries, xT added, and shots, xG and goals for and against. Shots are credited to the phase their possession was in at the time.

**Attacking transitions:** regains, counters (final third within 10 s), median time to the final third, recycled (first action sideways or back), lost again within 5 s, shots and xG within 15 s, all by third where the ball was won.

## Counter-press and rest defence

After each open-play loss, from the synthetic positions:

- **Pressed** when a player other than the one who lost the ball gets within 3 m of it within 3 s. Only players who were more than 3 m away at the loss count, so a defender who was already standing next to the ball does not make every loss look pressed.
- **Pack:** how many of the team's outfield players are within 10 m of the ball 2 s after the loss.
- **Won back within 5 / 10 s** comes from the events. **Bypassed:** the opponent moved the ball 20 m or more upfield within 10 s.
- **Rest defence:** outfield players goal-side of the ball at the moment of the loss, and how many of them were back-four defenders.

## Blocks, line snapshots and recovery

Settled defending time (out of possession, outside transitions and set pieces) is classed every 200 ms by the back four's mean depth: **high** from 42 m, **low** under 30 m, **mid** in between (the same thresholds as the defensive-line block in Live analytics). For each block the report gives length (deepest to highest outfield player), width, the gap between the back four and midfield, defenders in the box while the ball is in the defending third, opponent final-third entries and the share forced wide, crosses faced, shots and the share from outside the box, xG against, PPDA, regains and counters started.

**Line snapshots** (still open from earlier rounds): the back four and front line during the opponent's first build-up (the first 8 s of a possession it starts in its own third from a restart or its keeper) and during a high press (the opponent has the ball in its own third with one of the team's players within 5 m), against settled defending.

**Recovery behind a high line** (also still open): balls in behind are opponent completed passes ending nearer goal than the deepest outfield player, within 45 m of goal. For each, the back four's mean retreat and fastest recovery speed over 5 s, the keeper's starting distance from the goal line and the furthest the keeper came in that time, and a **sweep** when the keeper left the penalty area.

## Progressive carries and expected threat (xT)

A **progressive carry** moves the ball at least 10 m closer to the centre of the opponent's goal (5 m from x ≥ 60) and ends further forward (the StatsBomb / FBref convention). A **take-on** is a carry that beat a challenge.

**xT** follows Karun Singh's method on a 12 × 8 grid. For each zone the fit counts the share of actions that are shots and moves, the mean xG of shots there (a smoothed scoring rate, because a few dozen matches have too few goals per zone) and where moves arrive under control; a failed pass, or a possession that ends while the ball is held, arrives nowhere. Value iteration solves xT(z) = s(z)·g(z) + m(z)·Σ T(z, z')·xT(z'). A completed pass or carry is worth xT(end) − xT(start).

- Training: synthetic seeds 1–24 (24 matches, 18,460 actions, 1,270 shots, converged in 26 iterations). The demo seed (24017) is excluded, and `fit()` refuses it, so the demo match is out of sample.
- `python -m scripts.fit_xt` refits and rewrites `backend/xt_grid.json`. A backend test checks that the committed grid matches a fresh fit.
- Values rise to about 16% next to the opponent's box. The team's own third (about 4%) is higher than midfield (about 2.5%) because the synthetic keepers often play long balls that reach a forward directly. That is a habit of the generator, not of football, and it is listed in the report's limitations.

**xT against possession value:** possession value in Live analytics is a hand-set surface that rises steadily toward goal. xT is learned from how play moves, so it shows where this (synthetic) play actually leads to shots.

## Full-back roles and rotations

From the synthetic positions while the team has the ball:

- **Inverted:** 40% or more of build-up time 18 m or more from the touchline.
- **Overlapping / underlapping:** gets ahead of its winger, outside (≥ 3 m wider) or inside (≥ 3 m narrower), for 1 s or more, at least 3 times and twice as often as the other way.
- **Holding:** stays under 52 m from its own goal on average with the ball in the final third.
- Otherwise balanced; at least 60 s in possession is needed.

**Rotations** are swaps held for 2 s or more: the holding midfielder dropping between the centre-backs, the striker dropping behind the most advanced central midfielder, a full-back overlapping or underlapping, a full-back stepping inside before the final third. Each row compares the final-third rate of possessions with the rotation against those without it. That is association, not cause.

## Possession against control, pressing and finishing

- **Control read** compares possession with field tilt: control with territory (both ≥ 55%), possession without penetration (≥ 55% of the ball, < 50% of the final-third passes), territory without the ball, pinned back, or balanced. **Purposeful** possessions reach the final third or a shot; **sterile** ones string five or more completed passes without either.
- **Pressing over time:** PPDA by half and by 15 minutes, and high regains (open-play regains from x ≥ 60) with the shots that followed within 15 s.
- **Finishing:** goals minus xG per shooter. One match is far too small a sample to call anyone a good or poor finisher.

## What the generator plants (so tests can recover it)

The hidden movement profiles gained four habits this round. The analysis never reads them; `backend/tests/test_phases.py` checks that the report recovers each one.

| Habit | Harbor Athletic | Vale United | Measured result (full match) |
| --- | --- | --- | --- |
| Counter-press after a loss | 3 nearest players hunt the ball for 4 s, after 80% of losses | 1 player for 1.2 s, after 40% | Pressed 83% vs 27%; pack 3.0 vs 2.1 |
| Full-backs | RB overlaps, LB inverts | LB underlaps, RB holds | Overlapping, inverted, underlapping, holding |
| Rotations | DM drops between the centre-backs | Striker drops deep | DM drops 52 vs 14 episodes; striker drops 92 vs 14 |
| Keeper | Sweeps behind the line | Stays on the line | 2 sweeps vs 0 |

Counter-press hunters inside the tracking episodes run at 4.2 m/s, under the 4.5 m/s press threshold the tactics engine uses, so the press triggers planted in earlier rounds are unchanged. The new habits change some running: a holding full-back covers about 7.4 km, and Vale's striker covers less ground because the striker drops into midfield instead of running in behind. The workload tests were adjusted with comments to say so.

## Limitations

- Phases, counters and set pieces use fixed windows. Real analysts judge where a transition ends by the shape of both teams.
- Counter-pressing, blocks, recovery runs, full-back roles and rotations come from synthetic positions, so they show what the generator planted plus noise.
- Free kicks and throw-ins are rare or absent in the synthetic events, so the set-piece phase is mostly corners.
- xT inherits the generator's habits. It is not a model of real football.
- One match is a small sample. Read rates with their counts, and the notes as prompts for what to watch.
