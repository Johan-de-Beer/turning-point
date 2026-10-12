# Football concepts reference: formations and principles of play

Background for whoever works on the analysis engine next. It summarises, in our own words, two explainer articles Johan shared (The Football Analyst, "Football Formations Explained", 7 January 2024, and "Principles of Play", 8 January 2024) and maps each idea to what the engine measures. It is not shown in the app.

## Formations

**What a formation is.** A formation is the team's base structure: who stands where, and so who is responsible for which space. It is written back to front without the keeper (4-3-3; coaches sometimes write 1-4-3-3 to include the keeper). It matters because it decides how a team controls space (wide and stretched, or compact and central), where it can outnumber the opponent (three central midfielders against two), and how it suits a game state (more attackers when chasing a goal, a back five when protecting a lead).

**Common shapes and their trade-offs.**

| Shape | Strengths | Weak spots |
| --- | --- | --- |
| 4-4-2 | Balanced and simple; wide midfielders help both full-backs and attack | Can be outnumbered by a three-man midfield; needs disciplined wide players to track back |
| 4-3-3 | Width from wingers, three central midfielders, suits high pressing and quick transitions | Heavy running for midfielders and wingers; exposed to counters when the full-backs push high |
| 3-5-2 | Wing-backs give width and cover; five in midfield for control; two strikers | Wing-backs need huge fitness; space in the wide defensive areas |
| 4-2-3-1 | Two holding midfielders for solidity; a creative three behind the striker | The lone striker can be isolated; depends on the number 10 to link play |
| 3-4-3 | Front three overload; wing-backs give width; three centre-backs | Wing-backs again; crosses when they are caught upfield |

**Modern shape changes.** The team-sheet number is a starting point. Teams change shape by phase:

- In possession a 4-3-3 often becomes a **2-3-5** (full-backs into midfield or high and wide, wingers and an eight joining the striker) or a **3-2-5** (one full-back stays as a third centre-back).
- Out of possession the same team often drops into a compact **4-4-2** (an eight steps up beside the striker, wingers drop into a midfield four) or a **4-5-1**.
- Roles drive this: inverted full-backs step into midfield, false nines drop off the centre-backs, wing-backs provide all the width.
- Teams also change shape during a match in response to the score, substitutions or the opponent's changes.

## Principles of play

Principles are the shared rules behind the movements: they stay the same whatever the formation, and they let players improvise in a coordinated way when the game becomes chaotic. A team with strong principles plays consistently, solves problems without waiting for instructions, keeps its lines connected, and reacts better in transitions.

**In possession**

1. *Create space:* width to stretch the block, depth to pin the back line, players between the lines to unsettle midfielders; often several at once (a striker pinning both centre-backs while a midfielder drops into the pocket below).
2. *Support the ball:* the player on the ball needs a vertical option (ahead), a horizontal option (beside, for security) and a diagonal option (to play round pressure).
3. *Break lines with purpose:* find the free man between the lines, use third-man combinations to get round cover shadows, invite pressure to open lanes; timing matters as much as the pass.
4. *Prepare for transition:* rest defenders placed to stop counters, midfielders close enough to counter-press. Every attacking principle is also a defensive one.

**Out of possession**

1. *Protect the centre* first, then the wide corridors.
2. *Force predictability:* steer the opponent toward the touchline, a full-back or a pressing trap.
3. *Control depth:* the line's height should match the pressure on the ball. Late or no pressure: drop. Clean pressure: step up and squeeze.
4. *Collective movement:* when one player presses, the next ones shift (winger presses, midfielder shifts; centre-back steps, full-back narrows; pivot jumps, back line adjusts).

**Transitions**

- *Attacking:* go forward at once, attack with the nearest players, or secure the ball first and then speed up; early runs pin defenders.
- *Defensive:* counter-press for 3 to 5 seconds, close the central routes before chasing the ball, sprint back into the base block, delay rather than dive in.

## Where the engine measures each idea

| Idea | Measured in | Notes |
| --- | --- | --- |
| Team-sheet formation vs. shape by phase (2-3-5, 3-2-5, 4-4-2, 4-5-1) | Principles: `structures.formations`, `team_sheet` | Build-up, attack and defending shapes from average positions; see [principles of play](principles-of-play.md) |
| Build-up and rest-defence base (2+3, 3+2) | Principles: `structures.build_up`, `rest_defence` | Deepest five, every 200 ms |
| Inverted full-backs, overlaps, rotations, false-nine drops | Phases: `fullbacks`, `rotations` | [game phases](game-phases.md) |
| Inverted and touchline wingers, width | Principles: `wingers`, `width` | |
| Width, depth, between the lines | Principles: `width`, `marking.free_between_lines`; Analytics: line gap | |
| Support options (vertical, horizontal, diagonal) | Principles: `structures.support` | Open options around the player on the ball, once a second |
| Third man, cover shadows | Principles: `third_man`, `pressing.cover_shadow` | |
| Rest defence and counter-press | Principles: `structures.behind_ball`; Phases: `transitions` | Counter-press window is 3 s for pressure, 5 s for regains |
| Protect the centre, force predictability | Principles: `pressing.forced_wide_share`; Phases: `blocks.wide_entry_share` | |
| Control depth (line height vs. pressure) | Principles: `pressing.depth_read`, `drop_when_free_m` | Compared at the same ball depth |
| Collective movement | Tactics: shift to the ball, late reactions, offside-line steps | [tactical engine](tactical-engine.md) |
| Game state | Advanced metrics: game-state splits, leading side's line drop | [advanced metrics](match-analytics.md) |

Ideas the engine does not measure: formation changes by substitution or by score within a match (shapes are read over the observed prefix), "living the principles" as a team trait, and intent. The engine reports what the positions and events show, not why.
