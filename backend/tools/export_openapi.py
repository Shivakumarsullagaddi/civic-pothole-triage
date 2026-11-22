"""Write the FastAPI OpenAPI schema to a file (no server or database needed).

Usage (from backend/):
    python tools/export_openapi.py ../frontend/openapi.json
Then in frontend/: npm run gen:api
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
out.write_text(json.dumps(app.openapi(), indent=2))
print(f"Wrote {out}")
