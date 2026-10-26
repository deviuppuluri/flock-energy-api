"""Save the API's OpenAPI specification to openapi.json in the project root.

Run from the project root:   python scripts/export_openapi.py

FastAPI builds the spec automatically from the code, so this file can never
disagree with the real endpoints as long as you re-run it after every change.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402

output = ROOT / "openapi.json"
output.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
print(f"Saved {output}")
