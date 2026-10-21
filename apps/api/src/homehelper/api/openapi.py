"""Write the OpenAPI schema the web app's TypeScript types are generated from (spec §18.5).

    uv run python -m homehelper.api.openapi apps/web/lib/api/openapi.json

CI regenerates it and fails if the committed file (or the types) differ.
"""

import json
import sys
from pathlib import Path
from typing import Any

from homehelper.core.config import Settings
from homehelper.main import create_app


def openapi_schema() -> dict[str, Any]:
    # Fixed settings: the schema must not depend on the developer's environment or `.env`.
    app = create_app(Settings(_env_file=None, app_env="test", langfuse_public_key=""))  # type: ignore[call-arg]
    return app.openapi()


def main() -> None:
    text = json.dumps(openapi_schema(), indent=2, sort_keys=True) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
