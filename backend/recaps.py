"""Marker-gated observed recaps. Never read a precomputed fixture outcome."""
from __future__ import annotations

from .ingest import canonical_order
from .metrics import player_statistics, score
from .models import EvidenceFact, Recap, RecapVariant, StoryBeat, Window


def locked_recap(session, phase: str) -> Recap:
    return Recap(recap_id=f"recap_{session.session_id}_{session.generation}_{phase}_locked", phase=phase,
        cutoff_snapshot_id=None, generation=session.generation, data_epoch=session.data_epoch,
        score={}, story_beats=[], facts=[], fact_ids=[], variants={}, status="locked")


def build_recap(match, session, phase: str, snap, corrected: bool = False) -> Recap:
    cutoff = snap.as_of_ms
    records = {r.event_id: r for r in canonical_order(session.ingestor.records) if r.payload.event_time_ms <= cutoff}
    observed_score = score(match, records)
    start = 0  # Both recaps summarize all observed play to their delivered marker.
    facts = []
    for team in (match.home.team_id, match.away.team_id):
        selected = [r for r in records.values() if r.payload.team_id == team]
        for metric in ("goals", "shots", "completed_passes"):
            sources = [r for r in selected if
                (metric == "goals" and r.payload.kind == "SHOT" and r.payload.detail.outcome == "goal") or
                (metric == "shots" and r.payload.kind == "SHOT") or
                (metric == "completed_passes" and r.payload.kind == "PASS" and r.payload.detail.completed)]
            facts.append(EvidenceFact(fact_id=f"f_recap_{session.session_id}_{session.generation}_{session.data_epoch}_{phase}_{team}_{metric}",
                metric=metric, subject_id=team, numeric_value=len(sources), unit="count", window=Window(start_ms=start, end_ms=cutoff),
                source_event_refs=[r.ref for r in sources]))
    # Distinct strongest approved observed episodes, three maximum. Preference only ranks.
    available = [i for i in session.insights if i.status in ("ready", "corrected") and i.data_epoch == session.data_epoch
                 and i.observed_window.end_ms <= cutoff and i.variants]
    available.sort(key=lambda i: (session.preferences.favorite_team_id in i.subject_ids,
                                 session.preferences.favorite_player_id in i.supported_player_ids,
                                 len(i.facts), i.observed_window.end_ms), reverse=True)
    chosen = []
    for insight in available:
        if insight.pattern not in {i.pattern for i in chosen}:
            chosen.append(insight)
        if len(chosen) == 3:
            break
    variants = {}
    stats = player_statistics(match, records)
    player = next((p for p in match.roster if p.player_id == session.preferences.favorite_player_id), None)
    player_summary = None
    if player and stats[player.player_id].involvement:
        p = stats[player.player_id]
        # Player summary numeric claims also get computed recap facts.
        for metric, value in (("involvement", p.involvement), ("shots", p.shots), ("passes_completed", p.passes_completed)):
            player_sources = [r.ref for r in records.values() if
                (metric == "involvement" and r.ref in p.event_refs) or
                (metric == "shots" and r.payload.player_id == player.player_id and r.payload.kind == "SHOT") or
                (metric == "passes_completed" and r.payload.player_id == player.player_id and r.payload.kind == "PASS" and r.payload.detail.completed)]
            facts.append(EvidenceFact(fact_id=f"f_recap_{session.session_id}_{session.generation}_{session.data_epoch}_{phase}_{player.player_id}_{metric}",
                metric=metric, subject_id=player.player_id, numeric_value=value, unit="count", window=Window(start_ms=0, end_ms=cutoff),
                source_event_refs=player_sources))
        player_summary = f"{player.display_name} took part in {p.involvement} recorded actions, completed {p.passes_completed} passes and took {p.shots} shots."
    elif player:
        player_summary = f"No recorded actions for {player.display_name} yet."
    for mode in ("casual", "analyst"):
        beats = [StoryBeat(insight_id=i.insight_id, headline=i.variants[mode].headline, explanation=i.variants[mode].explanation,
                          fact_ids=i.variants[mode].fact_ids, observed_window=i.observed_window) for i in chosen]
        period_name = "Half-time" if phase == "half_time" else "Full-time"
        heading = f"{period_name}: {match.home.short_name} {observed_score[match.home.team_id]} – {observed_score[match.away.team_id]} {match.away.short_name}"
        shot_counts = {f.subject_id: int(f.numeric_value) for f in facts if f.metric == "shots" and f.subject_id in observed_score}
        if mode == "casual":
            if observed_score[match.home.team_id] == observed_score[match.away.team_id]:
                score_story = f"The teams are level at {observed_score[match.home.team_id]}–{observed_score[match.away.team_id]}."
            else:
                winner = match.home if observed_score[match.home.team_id] > observed_score[match.away.team_id] else match.away
                score_story = f"{winner.display_name} {'lead' if phase == 'half_time' else 'finish ahead'}, {observed_score[match.home.team_id]}–{observed_score[match.away.team_id]}."
            prose = score_story + " Here are the spells that shaped the match story."
        else:
            prose = (f"{match.home.display_name} took {shot_counts[match.home.team_id]} shots; {match.away.display_name} took {shot_counts[match.away.team_id]}. "
                     "Compare the key spells below and open their supporting events. These patterns describe play; they do not prove its causes.")
        variants[mode] = RecapVariant(headline=heading, explanation=prose, story_beats=beats,
                                     fact_ids=[f.fact_id for f in facts] + [f.fact_id for i in chosen for f in i.facts], player_summary=player_summary)
    return Recap(recap_id=f"recap_{session.session_id}_{session.generation}_{session.data_epoch}_{phase}", phase=phase,
        cutoff_snapshot_id=snap.snapshot_id, generation=session.generation, data_epoch=session.data_epoch,
        score=observed_score, story_beats=variants[session.preferences.mode].story_beats,
        facts=facts + [f for i in chosen for f in i.facts], fact_ids=[f.fact_id for f in facts] + [f.fact_id for i in chosen for f in i.facts],
        variants=variants, status="corrected" if corrected else "ready", cutoff_ms=cutoff,
        correction_notice="A corrected event changed this recap. The score and statistics have been updated." if corrected else None)
