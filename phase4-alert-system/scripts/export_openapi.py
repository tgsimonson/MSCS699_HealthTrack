"""write the generated openapi document to docs/openapi.json and docs/openapi.yaml

the live, interactive version is served by the running app at /docs (swagger ui) and /redoc
"""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("HT_DATABASE_URL", "sqlite://")

from app.main import app  # noqa: E402

DOCS = Path(__file__).resolve().parents[1] / "docs"


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    spec = app.openapi()
    (DOCS / "openapi.json").write_text(json.dumps(spec, indent=2))
    try:
        import yaml
        (DOCS / "openapi.yaml").write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=120))
    except ImportError:
        pass
    ops = sum(len(v) for v in spec["paths"].values())
    print(f"wrote docs/openapi.json ({len(spec['paths'])} paths, {ops} operations)")


if __name__ == "__main__":
    main()
