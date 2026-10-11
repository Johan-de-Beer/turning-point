# Principles of play (principles_v1)

`GET /api/sessions/{id}/principles` returns, for the observed prefix of the match only, a report on the principles a coach or analyst talks about: the team's structure in build-up and in rest defence (2+3, 3+2 and so on), winger roles and attacking width, the pressing system (man, zonal or hybrid by unit), pressing triggers and cover shadows, man-marking tightness and free men, counter-movements (drop-and-sprint, opposite runs, decoy runs, crisscross runs at corners), third-man combinations, and a match report written in the order a professional analyst works. The app shows it in the **Principles of play** panel under Phases of play. Every moment has a **Show** button that highlights its event on the pitch.

Everything is synthetic. The clubs, players, events and 5 Hz player positions are fictional. The thresholds are documented conventions, not calibrated against real tracking data. The report never reads the generator's hidden tendencies; tests check that it recovers what was planted.

## Structure: build-up and rest defence

Every 200 ms in settled possession (outside transitions and set pieces), the deepest five outfield players are sorted by depth and split into a **base** line and a **screen** in front of it at their largest depth gap, if that gap is 4 m or more. Otherwise they are one flat line of five. The shape is named by the two line counts: **2+3** is two centre-backs with three in front, **3+2** a back three with two in front, **4+1** a back four with one holding midfielder.

- **Build-up:** with the ball in the team's own half.
- **Rest defence:** with the ball in the final third. Also reported: the average number of outfield players 10 m or more goal-side of the ball, the share of time with three or fewer (over-committed), and each final-third loss by the shape at that moment, with counters, shots and xG conceded.

## Wingers and width

While the team has the ball in the opponent's half, a winger is **inverted** when they spend 40% or more of that time 18 m or more from the touchline, a **touchline** winger when they average 8 m or less from it, and **balanced** otherwise. The row also shows the preferred foot (a public player attribute), so an inverted winger on the opposite foot stands out, plus cut-ins (carries from the wide channel into the centre), shots, how many of them were central, and the share of time the full-back on that side was wider than the winger. **Width** is the outfield spread in settled final-third possession, with central entries and crosses.

## Pressing system, triggers and marking

- **Man, zonal or hybrid.** During the opponent's settled build-up, each second: does a player's nearest opponent move 3 m or more over the next 2 s, and does the player go with that opponent? A player who follows 55% of the time or more is man-oriented, 35% or less zonal. Units (front three, midfield three, back four) take the majority; the team is man-to-man or zonal when every unit agrees and hybrid when they differ.
- **Spare at the back:** the back four minus the opponent's players positioned behind the team's midfield line. **Most often left free:** the opponent player most often without a defender within 8 m during its build-up, which is how leaving one centre-back free shows up.
- **Triggers:** opponent passes ending in its own half, by type (back to the keeper, to a full-back, to a centre-back, into midfield, other), and how often the receiver was pressured within 3 s. A trigger shows up as a much higher rate on one kind of pass.
- **Cover shadow:** of pressured receptions by the keeper or a centre-back, how often the presser's approach came within 30° of the line to the holding midfielder. **Forced wide:** the share of opponent build-ups whose first entry into the middle third was wide.
- **Marking tightness:** the distance from each opponent to the nearest defender by distance from the ball (under 15 m, 15 to 30 m, over 30 m). **Free receptions:** passes received in the middle or final third with no defender within 5 m, and how many of those came between the back four and the midfield line.

## Counter-movements and third man

Counter-movements are read only in settled possession (5 s or more after the ball was won), so ordinary transition running does not count.

| Movement | Definition |
| --- | --- |
| Drop-and-sprint | An attacker drops 4 m or more toward their own goal within 1.6 s, then sprints forward at 6 m/s or more, gaining 8 m in 2 s, starting within 2 s of the drop. |
| Opposite runs | Two team-mates within 15 m across the pitch: one drops 4 m while the other runs 5 m forward and ends within 8 m of where the first started. |
| Decoy run | An attacker runs 6 m forward in 1 s and the nearest defender retreats 3 m with the runner; found when a team-mate receives within 12 m of where that defender stood. |
| Crisscross | At a corner, two attackers in the last 20 m swap order across the pitch in the 3 s before the delivery. |

**Drew** means the nearest defender stepped 2 m or more out with the drop or run; **found** means the movement was followed by a pass to the space or the runner within 3 s.

A **third-man combination** is A to B, then B to C (not A) within 3 s of A's pass, with C receiving further forward than A played from. The report counts them by zone, how often the direct lane from A to C was blocked, how often C was free on arrival, metres gained, and whether the move reached the final third or a shot.

## Match report

One summary per team in the order the analysis articles recommend: in possession, out of possession, attack to defence, defence to attack, set pieces, then **strengths to keep**, **weaknesses an opponent could target**, and the key player (the most expected threat added, if at least 0.02 xT). Each line is built from numbers in this report and in Phases of play, carries its sample, and links up to two moments. It says what happened, not why.

## Planted habits and what the analysis measures

The generator plants these habits in the hidden tactical profiles. The analysis only sees events and positions. Measured on the demo fixture (seed 42) at full time:

| Habit | Harbor Athletic | Vale United | Measured result (full match) |
| --- | --- | --- | --- |
| Rest defence | 2+3 (CBs base; LB, DM, RCM screen) | 3+2 (RB and CBs base; DM, RCM screen) | Harbor 2+3 41% of rest-defence time; Vale 3+2 63% |
| Build-up | DM drops in (from phases_v1) | Back four | Harbor 2+3 70%; Vale 4+1 52% |
| Wingers | RW inverts (left-footed) | LW hugs the touchline | harbor_10 inverted, 98% inside, opposite foot; vale_11 touchline, 5.2 m from the line |
| Pressing system | Zonal | Two central midfielders man-mark Harbor's eights | Harbor zonal in every unit; Vale hybrid, midfield man (vale_07, vale_08 follow) |
| Pressing triggers | Hunt back passes to the keeper and passes to a centre-back | None | Back pass to the keeper pressured 15 of 21 (71%) vs Vale 0 of 6 |
| Counter-movement | Striker drop-and-sprint every 25 s | Striker drops while the CAM runs past (opposite runs) | harbor_09 54 drop-and-sprints (next 8); vale_08 + vale_09 72 opposite runs (next 12) |
| Third man | Keeper to the dropping DM, set first time for a CB, 75% of short goal kicks | None | Harbor 25 combinations (top pattern GK, DM, LCB 7) vs Vale 5 |

The man-marking midfielders explain why Vale press passes into midfield hard (72% pressured) without any trigger being planted: they are already next to their man.

## Effect on earlier rounds

The new habits change some running: Harbor's drop-and-sprint striker and inverted right winger are now the top two in high-speed running, and the workload test says so with a comment. Vale's striker drop (phases_v1) now runs in a 12 s cycle (7 s dropped, 5 s up) so the opposite runs read as movements rather than a fixed position. The xT grid and contract samples were refitted and regenerated; the tests that compare them still pass.

## Limitations

- Off-ball movement between events is illustrative; the 5 Hz positions are generated.
- Structures use the deepest five outfield players and one depth gap. Real analysts also judge width, the opponent's front line and who is responsible for whom.
- Man-orientation is read from whether a player moves with the nearest opponent, which also happens when two players simply run the same way.
- Counter-movements use fixed distances and windows. They show the pattern of a movement, not its intent.
- Third-man combinations need two passes inside 3 s. The synthetic stream spaces most passes further apart, so the count is mostly the planted build-up combination.
- The match report applies fixed rules to one match; it is a starting point for analysis, not a verdict.
