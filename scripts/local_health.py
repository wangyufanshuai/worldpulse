from __future__ import annotations

import argparse
import json
from urllib.request import urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the local WorldPulse API health and release contract.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010/api")
    args = parser.parse_args()
    result = {}
    for name in ("health", "version"):
        with urlopen(f"{args.base_url.rstrip('/')}/{name}", timeout=5) as response:
            result[name] = json.load(response)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["health"].get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
