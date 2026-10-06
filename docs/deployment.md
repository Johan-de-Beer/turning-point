# Public demo deployment

The user authorized publishing this demo at `football.thedebeer.co.za` through the existing NGINX Proxy Manager and publishing the source to the personal GitHub account. DNS remains the user's responsibility. Existing apps, DNS records, proxy hosts, accounts, and certificates are retained.

## Topology

NGINX Proxy Manager 2.15.1 runs on the existing Pi, `192.168.10.2`, with HTTP/HTTPS on 80/443 and its existing administration endpoint on 81. It forwards only this hostname to the frontend at `192.168.10.58:5177` on server-1. HTTPS terminates at NPM, with Cloudflare in front under the user's current DNS configuration. React assets and `/api` share one origin. The FastAPI port is never published.

The dedicated `turning-point-private` Docker network is internal: `10.203.77.0/28`, frontend `.2`, backend `.3`. The frontend also uses `turning-point-ingress` (`10.203.78.0/28`) for its LAN port. These ranges and port 5177 were checked against existing routes/networks/listeners before use. The frontend trusts `X-Real-IP` only from `192.168.10.2` and replaces forwarded headers itself. The backend trusts only `10.203.77.2/32`. See the [NGINX real-IP documentation](https://nginx.org/en/docs/http/ngx_http_realip_module.html).

The football NPM host overrides inherited real-IP behavior with only Cloudflare's freshly fetched [IPv4](https://www.cloudflare.com/ips-v4) and [IPv6](https://www.cloudflare.com/ips-v6) ranges and `CF-Connecting-IP`. NPM then replaces `X-Real-IP` with that verified peer identity. Direct connections use their socket address and ignore forged Cloudflare headers. Cloudflare documents the [client-IP header behavior](https://developers.cloudflare.com/fundamentals/reference/http-headers/). `docker/npm-football.conf` records this host's Advanced configuration; it is applied only to football, preserving global settings and other hosts. A direct HTTPS check with seven idempotent creates and changing forged headers yielded six successes then 429, confirming the direct quota was not reset by those headers. One session was reused.

## Automatic deployment

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every push to `main`, on pull requests, and through manual `workflow_dispatch`. The backend and frontend jobs use GitHub-hosted `ubuntu-latest` runners. They install locked dependencies, run the application tests and frontend production build, and exercise the deployment scripts with Linux tests. The deployment job depends on both jobs passing.

Deployment is restricted to `Johan-de-Beer/turning-point`, `refs/heads/main`, and `push` or `workflow_dispatch` events. The deployment job does not run for pull requests; application verification jobs use hosted runners. External-fork workflows require approval under the repository's `all_external_contributors` policy. The deployment labels are `[self-hosted, linux, x64, server-1, turning-point]`; the dedicated repository runner is named `server-1-turning-point`, installed at `/home/balanceworx/turning-point-runner` and operated by `balanceworx` through user systemd with existing `Linger=yes`. The existing GVK organization runner remains unchanged.

The verified runner service is `/home/balanceworx/.config/systemd/user/turning-point-runner.service`, enabled and running as `balanceworx`; its runner directory has mode 700. Existing user lingering keeps it available after logout and at boot without a system-wide service or sudo changes. GitHub reports the repository runner online with labels `self-hosted`, `Linux`, `X64`, `server-1`, and `turning-point`. Runner availability verifies setup, not execution of a deployment. Inspect it as `balanceworx`:

```sh
systemctl --user status turning-point-runner.service
journalctl --user -u turning-point-runner.service --no-pager -n 50
```

Restart only this runner when needed with `systemctl --user restart turning-point-runner.service`.

Future pushes to `main` deploy automatically after these checks. To retry a failed run manually, select **Actions → Verify and deploy Turning Point → Run workflow → main**. Dispatching a different branch runs verification but does not deploy. Before deployment, the workflow compares its checked-out SHA with the current `main` SHA and skips an obsolete queued commit. Main runs do not cancel a deployment while containers are being replaced; pull-request checks can be canceled by newer changes.

The runner executes `bash scripts/deploy.sh SOURCE SHA RELEASE`, with the checked-out workspace, tested commit SHA and a release identity derived from the Actions run ID, attempt and abbreviated commit. It stages filtered source and a public `/release.json` commit/release marker, builds the same two production images, and operates only Compose project `turning-point`. Filtered application files use mode 644 and extracted source directories use mode 755 so the non-root containers can read them, regardless of checkout permissions; archives, release roots and backups retain private outer permissions. The runner does not require SSH deployment credentials: it runs on server-1 itself.

The Bash script and Windows manual path serialize deployment with `/home/balanceworx/turning-point/.deploy.lock` using `flock`. Automatic deployment retains `turning-point-replay-data`, takes a consistent SQLite backup before replacing the backend, waits for healthy containers, checks Nginx configuration and API health through the LAN gateway, and compares the served `/release.json` with its staged commit/release marker. It advances `current` only after verification. If deployment or health checks fail after replacement, it restores the previous release's images while retaining the previous release pointer. Image rollback preserves the data volume; database-schema recovery is a separate operation requiring a compatible schema and the private backup. These LAN gateway checks do not establish an external DNS/TLS check; public HTTPS verification remains separately recorded.

The new automatic pipeline's execution result must be recorded after an actual GitHub Actions run. The historical release evidence below does not validate the newly introduced workflow or runner.

## Manual release and persistence

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

NPM adds a dedicated host, disables caching and access logging for it, and uses a certificate covering only the requested domain. Discovery found no existing covering wildcard/domain certificate, so a new free Let's Encrypt certificate was issued. [NPM's official setup](https://nginxproxymanager.com/setup/) documents its existing data and certificate storage. Certificate issuance depends on DNS and inbound challenge routing; no DNS change is performed by these scripts.

## Previously verified release

Release `20261005-215011-54fd5f1` was verified running on server-1 with both read-only/non-root containers healthy. Backend image ID: `f46576018d7065675a97421d60a2bcb7611c9b77c81ded4356019084502b79ea`; frontend image ID: `b5d178d39f9d93aa0d8678020dc8644030b0f094722b3d5b6624a8672d8336de`. The source bundle contained 65 filtered files (754,846 bytes), SHA256 `3e87260d1f7aae7bd71b8f988f25622df33de53ce322e7d21f90f0b82dba7871`, independently checked on the server. Application code matched public GitHub commit `54fd5f168a855ccbe627c2542c3aaba4e4c6ccc0`; the deployed JavaScript was `index-NJz0WD-2.js`. The repeat deployment retained the named SQLite volume and created a consistent 7,634,944-byte backup with mode 600 in the private backup directory.

This release upgrades the synthetic fixture to `synthetic_v2`. Saved v1 replays are retired by the backend rather than mixing different event sequences and coordinates; the browser returns to a fresh replay while retaining local preferences. This is temporary demo-session expiry, not deletion of the retained volume or unrelated data.

NPM Proxy Host ID 37 points to the LAN upstream; certificate ID 59 covers `football.thedebeer.co.za`, expires 3 January 2027 at 19:24:38 UTC, and has forced HTTPS and nginx online. During the original host/TLS/real-IP setup, the prior 36 proxy-host records retained the same SHA256: `6027af2f85dc0c4ea53eef0a91f77818b13934c4744d04c766d9462af268a344`. The v2 application upgrade did not modify NPM, certificates or DNS. Direct domain-SNI TLS passed during initial hosting verification; normal-DNS trusted HTTPS, the exact bundle and API health passed for this recorded release, including an independently executed GitHub-hosted check. Read `verification.md` for measured browser/API results and remaining limitations.
