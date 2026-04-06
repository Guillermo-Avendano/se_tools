"""Runtime regression check for deterministic adelete advisory in SE Tools context.

This script calls the running agent API and validates that month-year phrasing
("before March 2021") yields a full adelete command with the expected -t cutoff.
"""

import json
import urllib.request


def main() -> None:
    cmd_template = "adelete -s Mobius -u ADMIN -r {CONTENT_CLASS} -c -n -y ALL -o"
    payload = {
        "question": "How to delete only content from before March 2021",
        "session_id": "regression-adelete-month-year",
        "context_hint": (
            "tool=MobiusRemoteCLI | repo=SOURCE | worker=worker-3 | "
            f"operation=adelete | command={cmd_template}"
        ),
    }

    req = urllib.request.Request(
        "http://localhost:8000/ask",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    answer = body.get("answer", "")
    expected = f"{cmd_template} -t 20210228235959"

    assert answer == expected, f"Unexpected answer:\n{answer}\nExpected:\n{expected}"
    print("OK: advisory regression passed")


if __name__ == "__main__":
    main()
