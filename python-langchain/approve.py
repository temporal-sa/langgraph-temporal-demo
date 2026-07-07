"""Optional CLI: approve or reject a pending purchase through the HTTP API.

    uv run approve.py <conversation-id>            # approve
    uv run approve.py <conversation-id> --reject   # reject
    uv run approve.py <conversation-id> --api http://localhost:8001
"""

import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: uv run approve.py <conversation-id> [--reject] [--api URL]")

    conversation_id = sys.argv[1]
    approved = "--reject" not in sys.argv
    api_url = _arg_value("--api", "http://localhost:8001").rstrip("/")
    payload = json.dumps({"approved": approved}).encode()
    request = Request(
        f"{api_url}/conversations/{conversation_id}/approve",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request) as response:
            body = json.loads(response.read() or b"{}")
    except HTTPError as e:
        detail = json.loads(e.read() or b"{}").get("error", e.reason)
        sys.exit(f"approval failed: {detail}")

    print(f"{'approved' if approved else 'rejected'} -> {body.get('status', 'sent')}")


def _arg_value(flag: str, default: str) -> str:
    if flag not in sys.argv:
        return default
    index = sys.argv.index(flag)
    try:
        return sys.argv[index + 1]
    except IndexError:
        sys.exit(f"{flag} requires a value")


if __name__ == "__main__":
    main()
