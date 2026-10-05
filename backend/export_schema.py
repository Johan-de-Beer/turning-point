"""Export authoritative public contracts without loading any fixture or secrets."""
import json
from pathlib import Path

from .models import EvidenceResponse, MatchMetadata, OverlayResponse, RecapResponse, SessionState


def export():
    path = Path(__file__).resolve().parent.parent / "docs" / "schema-v1.json"
    schemas = {model.__name__: model.model_json_schema() for model in (MatchMetadata, SessionState, EvidenceResponse, OverlayResponse, RecapResponse)}
    path.write_text(json.dumps(schemas, indent=2), encoding="utf-8")
    print(f"Exported {path}")


if __name__ == "__main__":
    export()
