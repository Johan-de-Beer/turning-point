# Technical decisions — checked 5 October 2026

## Environment and boundaries

The repository initially contained only `.git`; no application or repository instructions existed. Development host: Windows, PowerShell, Python 3.12.3, Node 24.13.0, npm 11.6.2. Local Docker CLI 28.0.4 is present; its local Linux engine is unavailable. Server-1 has Docker/Compose access for the separately authorized public release. The visual revision adds an original Blender asset; it uses no third-party football imagery.

React + TypeScript + Vite is the frontend. FastAPI + Pydantic owns validation, clock, ingestion, metrics, candidates, and role handoffs. SQLite provides local transactional persistence in one backend process. One polling transport is sufficient for this MVP. Docker exposes `127.0.0.1:5173` and `127.0.0.1:8000`; the frontend image builds only `frontend/`. The native launch script forces mock mode. Dependency versions are recorded in lockfiles and the license inventory; measured tests belong in `verification.md`.

## Microsoft integration choice

The coherent optional route is the current Microsoft Foundry projects Python SDK: `AIProjectClient`, a project OpenAI client, then the Responses API. The [official quickstart](https://learn.microsoft.com/en-us/azure/foundry/quickstarts/get-started-code) specifies Azure AI Projects 2.x and `azure-ai-projects>=2.3.0`, authenticated using Azure Identity. Its projects API differs from 1.x. The two application roles receive only immutable observed evidence and produce strict structured outputs. We do not provision hosted agents or resources.

The [Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/) and [agents in workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/agents-in-workflows) were inspected. Framework adoption is optional; role separation is implemented in ordinary application orchestration. Installing a package alone does not demonstrate a Microsoft integration or establish award suitability. The optional adapter was checked offline against installed `azure-ai-projects==2.7.0`, `azure-identity==1.26.0`, and `openai==3.24.0` in an isolated `.sdk-check` environment. `scripts/check_microsoft_sdk.py` uses an in-memory HTTP mock to verify SDK client creation/options, Responses serialization, and output parsing; it makes zero network/model calls. Four local adapter guard tests passed. This establishes offline SDK compatibility only. A real call requires user-approved existing access and an explicit cost limit; none is authorized by this local-build request.

## Rules and release decisions

The [official hackathon rules](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md) were rechecked today. Up to four entrants may form a team. Submission closes 27 October 2026, 23:59 Pacific, which is 28 October 2026, 08:59 SAST. Registration closes 20 October at noon Pacific, or 21:00 SAST. Entry needs a public repository, public working demo video shorter than two minutes, pitch, and a free accessible project/test build for judging. The theme calls for an AI-powered solution, and baseline judging considers featured technologies. Therefore the mock local build is not described as a completed AI-powered submission.

The later user request authorizes public deployment on the existing server through NGINX Proxy Manager and a public personal GitHub repository. DNS remains user-managed. It does not authorize paid resources, model calls, new external authentication resources, or competition submission. Public mode enforces mock inference and adds bounded request/session/storage controls described in `deployment.md`; the local mock path remains reproducible. The optional adapter requires `MICROSOFT_INFERENCE_APPROVED=true` and a separately approved per-process call budget (`MICROSOFT_MAX_CALLS`, default zero); output-token and network limits do not by themselves establish a monetary cost limit.

## Measurement policy

Measure deterministic update latency separately from agent latency. Record host, fixture event count, commands, result counts, and actual limitations. Do not claim clean-machine setup, Docker runtime, accessibility audit, football validation, or live-provider success unless those checks occurred. Keep demo footage consistent with the measured application.
