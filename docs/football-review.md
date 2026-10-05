# Synthetic fixture methodology and football review

The fixture is original synthetic event data for Harbor Athletic and Vale United, with fictional adult rosters. `backend/generator.py` uses a seeded pseudorandom generator. Its private server phase plan alternates neutral periods, deliberately planted conservative pattern windows, and a few score events. The seed, phase labels, complete fixture, and test assertion manifest are never sent through ordinary match metadata or agent inputs. Agents see only facts computed from delivered event versions.

The generator owns period, in-play state, possession owner/identifier, actors, legal recipients, discrete normalized coordinates, and shot outcomes. Strict Pydantic validation and ingestion state checks validate the entire generated fixture before replay. Pass recipients belong to the actor's team and differ from the passer; in-play events require a current possession; stoppages end play; period markers delimit two 45-minute halves. Score is computed from `SHOT` outcomes, with no second goal event that could double count. The optional correction changes an observed goal shot to a saved shot at a later delivery time, exercising score/evidence invalidation.

Locations describe individual event origins/destinations in normalized team-relative units. The fixed pitch transform flips the away team in period one and the home team in period two. These points do not establish physical distances, velocity, player tracking, formation, defensive shape, or a continuous ball path. A schematic animation reveals discrete observed pass/carry/shot markers only.

Pattern windows deliberately sit inside the configured rules rather than hoping random data confirms them. Possession share is integrated from owned in-play duration, not event frequency. Each current window spans 180 simulated seconds with the left boundary excluded; the previous 180-second window supplies a comparison only when complete and eligible. Known play must cover at least 120 seconds and unknown state must be zero. Two eligible evaluations five seconds apart confirm a candidate; two failed evaluations close it. The assertion manifest and negative cases belong in server-side tests.

## Human expert checklist — review pending

- [ ] Review the entire event list for plausible frequency of passes, carries, shots, stoppages, and direct ownership transitions; legal schemas alone do not prove football realism.
- [ ] Check actor/recipient assignments and possession continuity. The P0 generator models discrete events, not detailed off-ball movement.
- [ ] Pressure: at least 60% possession, five final-third entries, three shots, and at most one opponent shot in the same eligible window. Verify the football wording remains conservative.
- [ ] Sterile possession: at least 65% possession and 15 completed passes, with at most one shot and one box entry. Check that jargon is explained for Casual viewers.
- [ ] End-to-end: each side has at least two shots, at least six live turnovers overall, and each side has 35–65% possession inclusive. Restarts and period boundaries must not create turnovers.
- [ ] Verify neutral windows and near misses do not receive confident pattern labels, and isolated goals are not automatically treated as pattern changes.
- [ ] Confirm counts, window boundaries, event versions, known/stopped/unknown duration, and any baseline match the evidence inspector.
- [ ] Inspect both audience variants: the story and certainty agree even when information density differs.
- [ ] Reject wording about intent, fatigue, confidence, formations, prediction, tactical causation, or a player's influence beyond supported involvement.
- [ ] Confirm favorite-player association is supported by event actor/recipient evidence; team context remains visible when the player has no role.
- [ ] Review halftime/full-time story selection against eligible observations and correction notices.

Reviewer name/date and specific changes should be added after human review. Until then, the fixture is validated for implemented legality and tests only; football plausibility and heuristic thresholds remain unvalidated by a domain expert.
