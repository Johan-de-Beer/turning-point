# Submission readiness

This build is preparation, not a submitted entry. The user has authorized a public personal GitHub repository and public mock demo deployment; their verified status is recorded in `verification.md`. No paid resources or model calls are authorized, and nothing has been sent to judges.

The [official rules](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md), checked 5 October 2026, require a new original project, up to four team members, a pitch, a public GitHub repository, and a public working demo video under two minutes. They also require free accessible project/test-build access through judging. Submission deadline: 28 October 2026 at 08:59 SAST (27 October 23:59 Pacific). Recheck changes, entrant eligibility, rights, representative authorization, and timing before entry. Registration closes 20 October at 21:00 SAST. Judging ends 11 November at 09:59 SAST (10 November 23:59 Pacific, after daylight-saving time ends).

## Remaining work before claiming readiness

- [ ] Human football expert reviews event plausibility, heuristic thresholds, negative examples, and restrained wording.
- [ ] QA reviews measured acceptance results and remaining failures in `verification.md`.
- [ ] With approved existing credentials/resources and cost limits, run both Microsoft role stages and capture real redacted traces. Mock-only output must remain labeled.
- [ ] Confirm all dependency and asset licenses; own or have permission for every submitted component.
- [ ] Confirm the public mock demo's availability throughout judging and review its measured public-serving checks.
- [ ] Complete the English pitch below with actual technologies and measurements.
- [ ] Record a working demonstration under two minutes using `demo-script.md`.
- [ ] Obtain approval for publishing the demo video, creating paid resources, live model calls, or submitting; repository and existing-server deployment are already authorized.
- [ ] Appoint the authorized team representative; recheck official rules and submit required fields before the deadline.

## Local pitch draft

Turning Point is a second screen that turns synthetic football events into concise, evidence-backed match explanations. A server-controlled replay computes conservative patterns; separate analyst and evidence-editor roles validate narratives against the same observed facts. Casual and Analyst views adapt the presentation, while club/player favorites change focus without changing the score or evidence. The React/TypeScript interface includes an original schematic pitch, auditable cards, timed overlay JSON, and observed halftime/full-time recaps. The FastAPI backend stores local sessions in SQLite. The current default demo uses deterministic mock roles; a Microsoft Foundry provider adapter is available only after approved access and live verification. This is neither a production broadcast integration nor a predictive football model.

## Working-build packaging

Prepare the source archive plus lockfiles, native startup instructions, local and public Compose files, `.env.example`, synthetic fixture methodology, test commands/results, license inventory, and provider-status statement. Exclude `.env`, runtime databases, capabilities, logs, and development caches. A downloadable test build may meet judging-access needs after organizer confirmation; a local URL cannot serve remote judges. Preserve public demo access for the entire judging period. Publishing the source and mock demo is authorized; competition submission and video publication remain separate actions.
