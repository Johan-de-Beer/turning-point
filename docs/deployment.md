# Public demo deployment

The user authorized publishing this demo at `football.thedebeer.co.za` through the existing NGINX Proxy Manager and publishing the source to the personal GitHub account. DNS remains the user's responsibility. Existing apps, DNS records, proxy hosts, accounts, and certificates are retained.

## Topology

NGINX Proxy Manager 2.15.1 runs on the existing Pi, `192.168.10.2`, with HTTP/HTTPS on 80/443 and its existing administration endpoint on 81. It forwards only this hostname to the frontend at `192.168.10.58:5177` on server-1. HTTPS terminates at NPM. React assets and `/api` share one origin. The FastAPI port is never published.

The dedicated `turning-point-private` Docker network is internal: `10.203.77.0/28`, frontend `.2`, backend `.3`. The frontend also uses `turning-point-ingress` (`10.203.78.0/28`) for its LAN port. These ranges and port 5177 were checked against existing routes/networks/listeners before use. The frontend trusts `X-Real-IP` only from `192.168.10.2` and replaces forwarded headers itself. The backend trusts only `10.203.77.2/32`. NPM's existing proxy template overwrites `X-Real-IP` with its connection peer; an Internet client cannot supply an arbitrary rate-limit identity. See the [NGINX real-IP documentation](https://nginx.org/en/docs/http/ngx_http_realip_module.html).

## Release and persistence

Run from Windows with the configured SSH alias and Docker permissions:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
```

The script uploads an explicitly filtered source bundle, builds two images, starts only Compose project `turning-point`, waits for health, and then updates `/home/balanceworx/turning-point/current`. Each release has a separate directory and image tag. No `.env`, credentials, local database, node_modules, development environment, logs, or capabilities enter the bundle. Registry base images are pinned to the digests actually pulled on the server. Dependency constraints/lockfiles are applied during the build.

The named volume `turning-point-replay-data` holds SQLite and is retained by ordinary `docker compose down` or redeployment. Before replacing a running backend, the deploy script uses SQLite's backup API and copies a consistent snapshot to the private server `backups` directory (directory mode 700, file mode 600). Container root filesystems are read-only, both applications run without root, capabilities are dropped, and logs are rotated. Backend limits are one CPU / 512 MiB; frontend limits are half a CPU / 128 MiB. The backend uses one worker and no request access log. Frontend logs contain method, path, status, size, and duration, excluding query strings, addresses, and authorization headers. This host already runs unrelated apps; this project does not prune images, stop their containers, or change global Docker/NPM settings.

On server-1:

```sh
cd /home/balanceworx/turning-point/current
export RELEASE_TAG="$(cat release-tag)"
docker compose -f docker-compose.production.yml ps
docker compose -f docker-compose.production.yml logs --tail 50
```

To roll back, select a previous directory under `releases`, export its `release-tag`, and run `docker compose -f docker-compose.production.yml up -d --wait` there. Then point `current` at that selected directory. Do not use `down -v`: that deletes replay data. A rollback is compatible only with the stored schema; keep a database backup before migrations.

Use Python's SQLite backup API inside the backend container for a consistent backup while the service runs, then copy that backup from the container to `/home/balanceworx/turning-point/backups`. Backups contain temporary replay state and capability hashes and belong only in private server storage. The public repository must never contain them.

## Public mock limits

Public deployment always sets `PUBLIC_DEMO=true`, `PROVIDER=mock`, `MICROSOFT_INFERENCE_APPROVED=false`, and `MICROSOFT_MAX_CALLS=0`. The backend's runtime network is internal. API documentation is disabled. Exact HTTPS origin and host allowlists are set. Bearer session capabilities isolate replays; this is an account-free demonstration, not an account authentication system.

Capacity is 32 retained sessions and four playing sessions. Ready sessions expire after 120 seconds from creation or restart, completed recaps after 15 minutes, idle sessions after 30 minutes, and all sessions after six hours from original creation. Playback pauses when polling stops for 30 seconds (maintenance checks every ten seconds). Request bodies/headers are bounded to 16 KiB; URLs are bounded to 2 KiB. Rate-limit memory is bounded; counted API requests (excluding health and OPTIONS) refill globally at 40/second, per-IP at 20/second, session creation at three/minute (burst six), capability reads at eight/second, and writes at ten/minute (burst twelve). Idempotency results are compressed and have bounded counts/TTL; stored snapshots are JSON. These are modest demo abuse controls, not distributed DDoS protection or a production security certification.

NPM adds a dedicated host, disables caching and access logging for it, and uses a certificate covering only the requested domain. Discovery found no existing covering wildcard/domain certificate, so a new free Let's Encrypt certificate is required. [NPM's official setup](https://nginxproxymanager.com/setup/) documents its existing data and certificate storage. Certificate issuance depends on DNS and inbound challenge routing; no DNS change is performed by these scripts.

## Verification status

Read `verification.md` for measured checks. Hosting discovery, SSH/Docker permissions, NPM administration access, unused port/network ranges, base-image pulls, source filtering, and production Compose validation have passed. Deployment and final redesigned browser checks are recorded there only after they actually run.
