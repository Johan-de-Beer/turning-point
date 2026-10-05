# Public mock demo backend

The public demo uses the same fictional replay through a same-origin frontend gateway. It does not need accounts and does not make external model calls. The backend must run as **one Python worker**, stay on the private Docker network, and receive traffic only from that gateway. HTTPS terminates at NGINX Proxy Manager.

## Configuration

Set these explicitly in the deployment environment:

```dotenv
PUBLIC_DEMO=true
PROVIDER=mock
MOCK_FAILURE=none
ALLOWED_ORIGINS=https://football.thedebeer.co.za
ALLOWED_HOSTS=football.thedebeer.co.za,localhost,127.0.0.1,backend
# Use the exact private IP of the frontend gateway, with /32 for IPv4.
TRUSTED_PROXY_NETWORKS=<frontend-private-ip>/32
MAX_SESSIONS=32
MAX_PLAYING_SESSIONS=4
SESSION_IDLE_SECONDS=1800
SESSION_MAX_AGE_SECONDS=21600
SESSION_READY_SECONDS=120
SESSION_ENDED_SECONDS=900
DISCONNECTED_PAUSE_SECONDS=30
IDEMPOTENCY_TTL_SECONDS=3600
MAX_IDEMPOTENCY_ENTRIES=2048
MAX_IDEMPOTENCY_PER_SCOPE=64
MODEL_TIMEOUT_SECONDS=3
MICROSOFT_INFERENCE_APPROVED=false
MICROSOFT_MAX_CALLS=0
```

Public mode refuses an external provider, insecure/wildcard CORS origins and wildcard Host configuration. `/docs`, `/redoc` and `/openapi.json` are unavailable. `/api/health` remains a small dependency-free readiness route. The schema remains available in the repository for development.

The frontend gateway must trust the client-IP header **only** from its configured NPM peer, then overwrite `X-Real-IP` for the backend. The backend accepts that header only when its direct peer matches `TRUSTED_PROXY_NETWORKS`. Leave the trust setting empty if there is no controlled gateway; never trust every address. Do not enable Uvicorn’s wildcard proxy-header trust or expose the backend port publicly.

Run Uvicorn with one worker, a connection/concurrency limit of 64, keep-alive timeout of five seconds and h11 incomplete-event limit of 16,384 bytes. Disable backend access logging. Gateway access logs should use the URI path without query strings or Authorization headers. Cursor values, capabilities and request bodies must stay out of logs. Restrict the frontend listener so the reverse proxy is the public entry point.

## Bounds and recovery

The ASGI guard bounds bodies and total headers to 16KB and URLs to 2KB. Chunked bodies are counted before dispatch; reading a body has a five-second deadline. API responses use `Cache-Control: no-store`, `nosniff` and a no-referrer policy. Cross-origin API requests are rejected in public mode.

Token buckets have bounded memory (4,096 entries). Limits are 40 requests/second globally, 20/second per client IP, six immediate session creations with one replenished every 20 seconds, eight reads/second per capability, and ten writes/minute per capability with an initial burst of 12. Public limits return structured 429 errors with retry guidance. A shared household or office can share the client-IP quota; these are deliberately small demonstration limits.

Sessions have independent clocks/capabilities and a cap of 32 retained sessions/four playing replays in the deployment configuration. An unstarted session expires after two minutes. A replay pauses after 30 seconds without client requests, checked during periodic maintenance. Idle sessions expire after 30 minutes, completed recaps after 15 minutes, and every session after six hours. Expiration removes its canonical state, snapshots and role traces and cancels pending jobs. The browser can start a new replay after expiry.

SQLite control retries retain compressed original results for one hour, with 64 records per scope and 2,048 records globally. Capacity is checked before a mutation. Expired entries are pruned; restart removes obsolete derived snapshots/traces. Role traces are capped at 64 per session. The fixture is immutable and bounded, and the explanation queue remains capped at eight jobs/two concurrent roles.

Routine replay checkpoints are throttled to twice a second in public mode to limit disk writes. Controls, approved role outputs, corrections and period boundaries force a checkpoint. A hard process crash can roll back ordinary progression to the last checkpoint, at most roughly half a second of wall time; recovery resumes paused from the persisted, cutoff-safe prefix. It never obtains a future score or recap.

## Limits of this deployment

Capability tokens isolate synthetic replays; they are not user accounts or production authentication. The account-free demo can still be exhausted by coordinated clients. When capacity is reached, it reports a busy state instead of creating unbounded work. These application bounds complement the proxy’s connection/body limits and container resource limits; they do not provide a distributed abuse or DDoS service.

No external provider is activated by public mode. Microsoft SDK compatibility remains tested with a local mock transport only. Football patterns are descriptive demo heuristics over synthetic events, not predictions or proof of causality.

The public-specific tests cover origin/Host/provider gates, private gateway IP trust, rate-bucket refill and bounded memory, streamed request limits, session/playing capacity, absolute/idle/lifecycle expiry, compressed idempotency capacity/TTL, derived cleanup, and four isolated complete replays. The entire backend suite continues to cover evidence, no-spoiler boundaries, corrections and stale asynchronous jobs. The Docker host’s actual public performance and reverse-proxy routing must be checked after deployment; local tests do not establish a production SLA.
