"""Create a source-only deployment bundle; never include local credentials/data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_DIRS = {".git", ".venv", ".sdk-check", ".runtime", "node_modules", "dist", "__pycache__", ".pytest_cache", "coverage", "test-results", "playwright-report"}
BLOCKED_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db"}


def package(output: Path) -> dict:
    roots = [ROOT / name for name in ("backend", "server_data", "frontend", "docker", "docker-compose.production.yml", ".dockerignore")]
    candidates = []
    for source in roots:
        candidates.extend(source.rglob("*") if source.is_dir() else [source])
    files = []
    for path in sorted(candidates):
        relative = path.relative_to(ROOT)
        if path.is_symlink():
            raise ValueError(f"Deployment source cannot contain symlinks: {relative}")
        if not path.is_file() or any(part in BLOCKED_DIRS for part in relative.parts):
            continue
        if path.name == ".env" or path.name.startswith(".env.") or path.suffix in BLOCKED_SUFFIXES or ".sqlite" in path.name or ".db-" in path.name:
            continue
        files.append((path, relative.as_posix()))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for path, relative in files:
            archive.add(path, arcname=relative, recursive=False)
    return {"file_count": len(files), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "bytes": output.stat().st_size}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.output), indent=2))
