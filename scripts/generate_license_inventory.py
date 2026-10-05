"""Record package metadata; this inventory is not a replacement for license texts."""
from __future__ import annotations

import importlib.metadata as md
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def python_packages() -> list[tuple[str, str, str]]:
    sdk_directory = ROOT / ".sdk-check/Lib/site-packages"
    optional_distributions = {dist.metadata["Name"].lower().replace("_", "-"): dist for dist in md.distributions(path=[str(sdk_directory)])} if sdk_directory.exists() else {}
    wanted = []
    for path in (ROOT / "backend").glob("requirements*.txt"):
        for line in path.read_text().splitlines():
            if line.strip() and not line.startswith(("#", "-")):
                wanted.append(re.split(r"[<=>\[; ]", line.strip())[0])
    rows = {}
    while wanted:
        name = wanted.pop()
        normalized = name.lower().replace("_", "-")
        if normalized in rows:
            continue
        try:
            distribution = md.distribution(name)
        except md.PackageNotFoundError:
            distribution = optional_distributions.get(normalized)
            if distribution is None:
                rows[normalized] = (name, "not installed", "not verified")
                continue
        meta = distribution.metadata
        license_value = meta.get("License-Expression") or meta.get("License") or ""
        if not license_value or len(license_value) > 120:
            classifiers = meta.get_all("Classifier") or []
            license_value = "; ".join(c.split(" :: ")[-1] for c in classifiers if c.startswith("License ::")) or "Review distribution LICENSE"
        rows[normalized] = (meta["Name"], distribution.version, license_value.replace("\n", " "))
        for raw in distribution.requires or []:
            # Only runtime dependencies without environment markers are traversed.
            # The installed environment freeze separately records platform packages.
            try:
                from packaging.requirements import Requirement
                requirement = Requirement(raw)
                if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                    wanted.append(requirement.name)
            except ImportError:
                if ";" not in raw:
                    wanted.append(re.split(r"[<=>\[; ]", raw)[0])
    return sorted(rows.values(), key=lambda row: row[0].lower())


def npm_packages() -> list[tuple[str, str, str]]:
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    rows = {}
    for path, item in lock["packages"].items():
        if not path or "node_modules/" not in path:
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        license_value = item.get("license")
        installed_manifest = ROOT / "frontend" / path / "package.json"
        if not license_value and installed_manifest.exists():
            license_value = json.loads(installed_manifest.read_text()).get("license")
        rows[(name, item.get("version", "unknown"))] = (name, item.get("version", "unknown"), str(license_value or "Review package LICENSE"))
    return sorted(rows.values(), key=lambda row: (row[0].lower(), row[1]))


def table(rows: list[tuple[str, str, str]]) -> str:
    return "| Package | Version | Metadata license |\n| --- | --- | --- |\n" + "\n".join("| " + " | ".join(value.replace("|", "\\|") for value in row) + " |" for row in rows)


def main() -> None:
    content = """# Dependency and asset license inventory

Generated from installed Python distribution metadata (default `.venv` plus optional
`.sdk-check` where present) and the frontend npm lockfile. Optional SDK packages do
not enter the default mock runtime.
Pinned direct versions live in `backend/requirements*.txt` and `frontend/package-lock.json`.
Preserve the corresponding upstream LICENSE/NOTICE texts when redistributing packages;
metadata alone does not complete license compliance. Packages marked unverified need review.

Application assets: fictional names, synthetic fixtures, original Blender stadium and code-built pitch geometry,
and system fonts. No match footage, club marks, player likenesses, external font downloads,
or copyrighted music are included. Lucide icons retain their upstream ISC license. A project
source license remains the owner's choice; this inventory grants no rights beyond upstream terms.

The original stadium was generated with Blender 5.2.2 LTS (GPL-3.0-or-later tool).
Blender is a development tool and is not shipped with the application. Its license does
not impose GPL on this original generated artwork. The editable `.blend`, generated
`.glb`, and reproducible script are included; see `stadium-assets.md`. Official release
source: https://download.blender.org/release/Blender5.2/.

## Python runtime and test dependencies

Optional screenshot QA uses Pillow 11.2.1 (MIT-CMU, verified from installed
distribution metadata). It is not installed in the application containers or
required for native app startup.

""" + table(python_packages()) + "\n\n## Frontend lockfile (including platform/test/build dependencies)\n\n" + table(npm_packages()) + "\n"
    (ROOT / "docs/licenses.md").write_text(content, encoding="utf-8")
    print("Wrote docs/licenses.md")


if __name__ == "__main__":
    main()
