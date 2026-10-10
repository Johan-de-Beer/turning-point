"""Exact counts and duration integration. Windows are (left, right]."""
from __future__ import annotations

from dataclasses import dataclass

from .chances import shot_quality
from .ingest import IngestionError, canonical_order, validate_state_sequence
from .models import Baseline, Coverage, EventEnvelope, EvidenceFact, Match, MetricSnapshot, PERIOD_MS, PlayerStats, TeamMetrics, WINDOW_MS, Window

DEFINITIONS = {
    "shots": "SHOT event count; a goal is one shot and is never counted twice.",
    "on_target": "Shots on target: SHOT outcomes goal or saved.",
    "duels": "Ground and aerial duels the team contested: every TACKLE event, whichever side made it.",
    "duels_won": "Duels the team won: its successful challenges plus the opponent's unsuccessful ones (the player in possession kept the ball).",
    "field_tilt": "The team's share of both teams' final-third passes (attempted passes into or within the attacking final third). Unavailable when neither team made one.",
    "final_third_passes": "Attempted passes that start or end in the attacking final third (x ≥ 66.67).",
    "xg": "Sum of the heuristic xG of the team's shots (see the chance-quality definitions).",
    "pass_accuracy": "Completed passes divided by attempted passes × 100; unavailable when no passes were attempted.",
    "final_third_entries": "Completed PASS or CARRY crossing x < 66.67 to x ≥ 66.67, once per event.",
    "box_entries": "Completed PASS or CARRY moving from outside to inside x ≥ 83 and 20 ≤ y ≤ 80, once per event.",
    "possession_share": "Owned in-play milliseconds divided by all known owned in-play milliseconds × 100. Stoppages and unknown state are excluded from the denominator.",
    "live_turnovers": "Direct opposing known possession transitions while play remains live; restarts and period boundaries are excluded.",
    "coverage": "A full 180-second current-period window, no unknown or invalid state, and at least 120 seconds of known in-play time are required.",
    "touches": "One modeled controlled touch per POSSESSION/PASS/CARRY/SHOT actor and per completed-pass recipient. These are event involvements, not all real-ball touches.",
    "involvement": "Unique observed events where the player is the actor or the recipient of a completed pass. Tackle actors count; textual mentions never count.",
    "coordinates": "Normalized team-relative synthetic event locations. Fixed display flips away in period 1 and home in period 2. They are not tracking samples or physical meters.",
}


def in_box(point) -> bool:
    return point.x >= 83 and 20 <= point.y <= 80


def final_third_pass(event) -> bool:
    """An attempted pass into or within the attacking final third."""
    return event.kind == "PASS" and max(event.detail.start.x, event.detail.end.x) >= 66.67


def crossing(e: EventEnvelope, metric: str) -> bool:
    event = e.payload
    if event.kind not in ("PASS", "CARRY") or (event.kind == "PASS" and not event.detail.completed):
        return False
    if metric == "final_third_entries":
        return event.detail.start.x < 66.67 <= event.detail.end.x
    return not in_box(event.detail.start) and in_box(event.detail.end)


@dataclass
class WindowResult:
    window: Window
    coverage: Coverage
    metrics: dict[str, TeamMetrics]
    live_turnovers: int
    sources: dict[tuple[str, str], list[str]]
    evidence_refs: list[str]


def calculate_window(records: dict[str, EventEnvelope], team_ids: list[str], period: int, start: int, end: int,
                     invalid_state_transitions: list[tuple[int, int, int]] | None = None) -> WindowResult:
    period_start = (period - 1) * PERIOD_MS
    start = max(start, period_start)
    all_events = [r for r in canonical_order(records) if r.payload.period == period and r.payload.event_time_ms <= end]
    events = [r for r in all_events if start < r.payload.event_time_ms <= end]
    owned = dict.fromkeys(team_ids, 0)
    sources: dict[tuple[str, str], list[str]] = {}
    evidence = set(e.ref for e in events)
    unknown = stoppage = 0
    state_valid = True
    live, owner, state_ref = True, None, None
    state_invalid = False
    affected_invalid_state = False
    period_started = False
    period_closed = False
    possession_id = None
    last_time = period_start
    turnovers: list[str] = []

    def integrate(until: int, endpoint_ref: str | None = None):
        nonlocal unknown, stoppage, affected_invalid_state
        duration = max(0, min(until, end) - max(last_time, start))
        if not duration:
            return
        if state_invalid:
            affected_invalid_state = True
        state_refs = [ref for ref in (state_ref, endpoint_ref) if ref]
        sources.setdefault(("match", "possession_duration"), []).extend(state_refs)
        evidence.update(state_refs)
        if not live:
            stoppage += duration
        elif owner in owned:
            owned[owner] += duration
            if state_ref:
                sources.setdefault((owner, "possession_share"), []).append(state_ref)
                evidence.add(state_ref)
        else:
            unknown += duration

    stream = [(e.payload.event_time_ms, e.delivery_seq, e) for e in all_events]
    stream.extend((t, seq, None) for t, p, seq in (invalid_state_transitions or []) if p == period and t <= end)
    for t, _seq, record in sorted(stream, key=lambda row: (row[0], row[1])):
        if record is None:
            integrate(t)
            live, owner, state_ref, state_invalid = True, None, None, True
            last_time = t
            continue
        event = record.payload
        integrate(t, record.ref if event.kind in ("PERIOD_START", "PERIOD_END", "STOPPAGE", "POSSESSION") else None)
        if event.kind == "PERIOD_START":
            live, owner, state_ref = True, None, record.ref
            state_invalid = False
            period_started, period_closed, possession_id = True, False, None
        elif not period_started or period_closed:
            live, owner, state_ref, state_invalid = True, None, None, True
        elif event.kind in ("PERIOD_END", "STOPPAGE"):
            live, owner, state_ref = False, None, record.ref
            state_invalid = False
            possession_id = None
            period_closed = event.kind == "PERIOD_END"
        elif event.kind == "POSSESSION":
            if start < t <= end and live and owner in owned and owner != event.team_id:
                turnovers.extend([state_ref, record.ref])
            live, owner, state_ref = True, event.team_id, record.ref
            state_invalid = False
            possession_id = event.possession_id
        elif not live or owner is None or event.possession_id != possession_id or (event.kind != "TACKLE" and event.team_id != owner):
            live, owner, state_ref, state_invalid = True, None, None, True
        last_time = t
    integrate(end)
    state_valid = state_valid and not affected_invalid_state
    known = sum(owned.values())
    full_window = end - start >= WINDOW_MS
    eligible = full_window and known >= 120_000 and unknown == 0 and state_valid
    coverage = Coverage(status="eligible" if eligible else "warming_up" if not full_window else "insufficient_evidence",
                        eligible=eligible, known_in_play_ms=known, owned_in_play_ms=owned,
                        stoppage_ms=stoppage, unknown_state_ms=unknown, state_valid=state_valid)
    result = {}
    quality = shot_quality(records, all_events)
    third = {team: [r for r in events if r.payload.team_id == team and final_third_pass(r.payload)]
             for team in team_ids}
    tilt_total = sum(len(v) for v in third.values())
    for team in team_ids:
        selected = [r for r in events if r.payload.team_id == team]
        tackles = [r for r in events if r.payload.kind == "TACKLE"]
        won = [r for r in tackles if (r.payload.team_id == team) == r.payload.detail.successful]
        shots = [r for r in selected if r.payload.kind == "SHOT"]
        passes = [r for r in selected if r.payload.kind == "PASS"]
        completed = [r for r in passes if r.payload.detail.completed]
        on_target = [r for r in shots if r.payload.detail.outcome in ("goal", "saved")]
        goals = [r for r in shots if r.payload.detail.outcome == "goal"]
        entries = [r for r in selected if crossing(r, "final_third_entries")]
        boxes = [r for r in selected if crossing(r, "box_entries")]
        for metric, refs in (("shots", shots), ("on_target", on_target), ("attempted_passes", passes),
                             ("completed_passes", completed), ("final_third_entries", entries), ("box_entries", boxes), ("goals", goals)):
            sources[(team, metric)] = [r.ref for r in refs]
        sources[(team, "pass_accuracy")] = [r.ref for r in passes]
        sources[(team, "duels")] = [r.ref for r in tackles]
        sources[(team, "duels_won")] = [r.ref for r in won]
        sources[(team, "final_third_passes")] = [r.ref for r in third[team]]
        sources[(team, "field_tilt")] = [r.ref for rows in third.values() for r in rows]
        sources[(team, "xg")] = [r.ref for r in shots]
        result[team] = TeamMetrics(shots=len(shots), on_target=len(on_target), completed_passes=len(completed),
            attempted_passes=len(passes), pass_accuracy=100 * len(completed) / len(passes) if passes else None,
            final_third_entries=len(entries), box_entries=len(boxes), possession_share=100 * owned[team] / known if known else None,
            goals=len(goals), duels=len(tackles), duels_won=len(won), final_third_passes=len(third[team]),
            field_tilt=100 * len(third[team]) / tilt_total if tilt_total else None,
            xg=round(sum(quality[r.event_id].xg for r in shots if r.event_id in quality), 2))
    sources[("match", "live_turnovers")] = list(dict.fromkeys(turnovers))
    evidence.update(turnovers)
    sources = {k: list(dict.fromkeys(v)) for k, v in sources.items()}
    return WindowResult(Window(start_ms=start, end_ms=end), coverage, result, len(turnovers) // 2, sources, sorted(evidence))


def snapshot(match: Match, records: dict[str, EventEnvelope], session_id: str, generation: int, data_epoch: int,
             cutoff_ms: int, period: int, delivery_cursor: int,
             invalid_state_transitions: list[tuple[int, int, int]] | None = None) -> MetricSnapshot:
    teams = [match.home.team_id, match.away.team_id]
    result = calculate_window(records, teams, period, cutoff_ms - WINDOW_MS, cutoff_ms, invalid_state_transitions)
    baseline = None
    if cutoff_ms - (period - 1) * PERIOD_MS >= 2 * WINDOW_MS:
        previous = calculate_window(records, teams, period, cutoff_ms - 2 * WINDOW_MS, cutoff_ms - WINDOW_MS, invalid_state_transitions)
        if previous.coverage.eligible:
            baseline = Baseline(window=previous.window, coverage=previous.coverage, team_metrics=previous.metrics, live_turnovers=previous.live_turnovers)
    return MetricSnapshot(snapshot_id=f"snap_{session_id}_{generation}_{data_epoch}_{period}_{cutoff_ms}",
        session_id=session_id, generation=generation, data_epoch=data_epoch, as_of_ms=cutoff_ms,
        delivery_cursor=delivery_cursor, period=period, window=result.window, coverage=result.coverage,
        team_metrics=result.metrics, live_turnovers=result.live_turnovers, baseline=baseline, evidence_refs=result.evidence_refs)


def facts_for_snapshot(match: Match, records: dict[str, EventEnvelope], snap: MetricSnapshot,
                       metrics: list[tuple[str, str]]) -> list[EvidenceFact]:
    result = calculate_window(records, [match.home.team_id, match.away.team_id], snap.period, snap.window.start_ms, snap.window.end_ms)
    facts = []
    for team, metric in metrics:
        value = snap.live_turnovers if metric == "live_turnovers" else getattr(snap.team_metrics[team], metric)
        if value is None:
            continue
        # Possession percent needs both teams' ownership intervals for its denominator.
        refs = result.sources.get((team, metric), [])
        if metric == "possession_share":
            refs = result.sources.get(("match", "possession_duration"), [])
        facts.append(EvidenceFact(fact_id=f"f_{snap.snapshot_id}_{team}_{metric}", metric=metric,
            subject_id=team, numeric_value=value, unit="percent" if metric in ("possession_share", "pass_accuracy", "field_tilt") else "count",
            window=snap.window, source_event_refs=refs))
    return facts


def score(match: Match, records: dict[str, EventEnvelope], cutoff_ms: int | None = None) -> dict[str, int]:
    result = {match.home.team_id: 0, match.away.team_id: 0}
    for r in canonical_order(records):
        e = r.payload
        if (cutoff_ms is None or e.event_time_ms <= cutoff_ms) and e.kind == "SHOT" and e.detail.outcome == "goal":
            result[e.team_id] += 1
    return result


def player_statistics(match: Match, records: dict[str, EventEnvelope], cutoff_ms: int | None = None) -> dict[str, PlayerStats]:
    result = {p.player_id: PlayerStats(player_id=p.player_id, team_id=p.team_id, involvement=0, touches=0,
        passes_attempted=0, passes_completed=0, passes_received=0, carries=0, shots=0, on_target=0, goals=0, tackles=0,
        duels=0, duels_won=0, event_refs=[]) for p in match.roster}
    for record in canonical_order(records):
        e = record.payload
        if cutoff_ms is not None and e.event_time_ms > cutoff_ms:
            continue
        actor = result.get(e.player_id)
        if actor:
            actor.involvement += 1
            actor.event_refs.append(record.ref)
            if e.kind in ("POSSESSION", "PASS", "CARRY", "SHOT"):
                actor.touches += 1
            if e.kind == "PASS":
                actor.passes_attempted += 1
                actor.passes_completed += int(e.detail.completed)
                if e.detail.completed:
                    recipient = result[e.detail.recipient_id]
                    recipient.involvement += 1
                    recipient.touches += 1
                    recipient.passes_received += 1
                    recipient.event_refs.append(record.ref)
            elif e.kind == "SHOT":
                actor.shots += 1
                actor.on_target += int(e.detail.outcome in ("goal", "saved"))
                actor.goals += int(e.detail.outcome == "goal")
            elif e.kind == "CARRY":
                actor.carries += 1
            elif e.kind == "TACKLE":
                actor.tackles += int(e.detail.contest == "ground")
                actor.duels += 1
                actor.duels_won += int(e.detail.successful)
    return result
