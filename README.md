# Turning Point

[Live demo](https://football.thedebeer.co.za/) · [Public source on Johan de Beer's personal profile](https://github.com/Johan-de-Beer/turning-point)

A second screen for a fictional football match. A deterministic replay engine measures observed events; separate Football Analyst and Evidence Editor roles turn verified facts into explanations. React + TypeScript presents an interactive Blender stadium with a functional event-by-event football replay, the score, evidence, personalization, timed overlay JSON, and marker-gated recaps.

The default provider is a deterministic mock. It needs no account and makes no model calls. The optional Microsoft Foundry adapter stays disabled until existing resources, authentication, and a cost limit are explicitly approved. The public mock demo runs behind NGINX Proxy Manager with trusted HTTPS, a private backend network and bounded replay capacity. [Deployment](docs/deployment.md) and [verification](docs/verification.md) record its configuration and measured checks. Competition submission remains separate work.

The interface gives the pitch a wide broadcast view with a short match story alongside it. The original Blender stadium has a seating bowl, canopies, crowds, floodlights and LED boards. A single football follows each delivered synthetic pass, carry and shot between the supplied endpoints. The active actor and completed-pass recipient appear at the event's recorded positions, with player names, action, outcome and event time. Both teams switch physical ends at half-time. Movement between endpoints and its animation timing are illustrative; there is no real continuous ball tracking or off-ball player movement. Historic evidence highlights its exact event revision without replacing the live observation set. Drag the view, switch to Top view, reset the camera or expand it to fullscreen. Motion can be disabled, and reduced-motion preferences are respected. The editable Blender source and regeneration script are included.

## Run on Windows

Requires Python 3.12+, Node.js 22.12+ (tested development versions: Python 3.12.3, Node 24.13.0, npm 11.6.2), and PowerShell. From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

The command creates `.venv`, installs pinned dependencies, and opens [http://127.0.0.1:5173](http://127.0.0.1:5173). Both services bind to loopback. On subsequent runs, add `-NoInstall`; add `-NoBrowser` to keep the browser closed. Logs and the local SQLite database are in `.runtime/`, which Git ignores.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop.ps1
```

Stop retains replay data. Browser session capabilities live in `sessionStorage`. Backend recovery pauses saved replays; use Play to resume. Capabilities isolate synthetic replays without user accounts.

Manual startup in two terminals:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -c backend\requirements.lock.txt
$env:PROVIDER = 'mock'
$env:MICROSOFT_INFERENCE_APPROVED = 'false'
$env:DATABASE_PATH = '.runtime/turning-point.sqlite3'
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

```powershell
Set-Location frontend
npm ci
npm run dev
```

Vite proxies `/api` to the backend. The backend exposes [health](http://127.0.0.1:8000/api/health) and [interactive API documentation](http://127.0.0.1:8000/docs). Requests that access or control sessions require their browser-generated Bearer capability.

## Local Docker path

```powershell
docker compose up --build
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Compose exposes only loopback ports, checks both services, and stores SQLite in a named `replay-data` volume. The frontend build context is `frontend/`; server fixtures cannot enter its image. The backend listens on all interfaces only inside its container. Stop with `docker compose down` (data retained). Docker startup also forces `mock` and disallows inference.

`.env.example` documents configuration. No real key belongs in this repository or any `VITE_*` variable. A copied `.env` is ignored. Native direct startup reads process environment variables; the startup script supplies safe mock defaults rather than parsing `.env`.

For the optional local correction demo, stop the app, set `$env:FIXTURE_CORRECTION = '1'`, start it, and restart the replay to create a fresh generation. A delayed shot revision exercises score and explanation correction. Clear that environment variable (or set it to `0`) before the standard demo. Mock failure options in `MOCK_FAILURE` include `timeout`, `transient`, `invalid_json`, `wrong_number`, `invented_goal`, `unsupported_player`, `causal`, and `future_reference`; these test transparent rejection/fallback without an account.

## Verify and demonstrate

```powershell
.\.venv\Scripts\python.exe -m pytest -q
Set-Location frontend
npm test
npm run build
```

With both services running, from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\api_smoke.py
node scripts\browser-qa.mjs
node scripts\pitch_functional_qa.mjs
.\.venv\Scripts\python.exe scripts\audit_client_artifacts.py
.\.venv\Scripts\python.exe -m scripts.measure_replay
```

The browser check uses installed Microsoft Edge or Playwright Chromium, covers a complete real-clock replay, and saves responsive screenshots to `docs/screenshots/`. The separate functional-pitch check compares actual scene mesh coordinates and active event identity with independently captured API records, including both team orientations, shot outcomes, pause/resume, historic inspection, reload and restart. If neither browser is installed, run `npx playwright install chromium` from `frontend/` first. The browser check's optional image comparison requires Pillow: `python -m pip install Pillow==11.2.1`, or set `TP_IMAGE_PYTHON` to a Python executable containing it. Pillow is a QA-only dependency. Local HTTP/browser measurements are saved in `.runtime/`; the deterministic benchmark measures clock/metric work separately from agent latency. Read the scope of each measured result in [verification](docs/verification.md).

Start a replay in Casual mode at the default 12× speed to read the individual actions. Select 60× for a short demonstration: the full match takes about 90 seconds, excluding pauses. Pause on a new insight, open “Why this insight?”, switch to Analyst, select a fictional player, and inspect the overlay JSON. Use Previous/Next observed event and Replay this event to inspect a recorded action while preserving the live replay queue. Drag the stadium camera, switch to Top view, or enter native fullscreen; reduced motion and a Motion toggle are supported. An ordinary pause freezes the ball's current progress. At half-time and full-time, remaining delivered actions finish without moving the server cutoff. Continue explicitly at half-time. The full-time recap stays locked before the final marker.

## Project notes

- [Product and interaction design](docs/design.md)
- [Architecture](docs/architecture.md) and [API contract](docs/api-contract.md)
- [Blender stadium source and animation behavior](docs/stadium-assets.md)
- [Technical decisions and verified primary sources](docs/technical-decisions.md)
- [Public hosting and release procedure](docs/deployment.md) and [public backend bounds](docs/public-demo-backend.md)
- [Acceptance checklist](docs/acceptance.md) and [measured verification](docs/verification.md)
- [Demo script](docs/demo-script.md), [submission checklist](docs/submission.md), and [licenses](docs/licenses.md)

Synthetic clubs, adult players, events, and original schematic assets only. “Turning point” labels an observed pattern; it does not establish causality or predict a result. English is the supported language. Football-expert review and real-provider traces remain required before any claims about a finished competition entry.
