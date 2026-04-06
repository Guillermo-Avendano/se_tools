"""Regression check for deterministic adelete advisory in SE Tools context."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agent.core import _direct_advisory_answer


def _wrapped_question(user_question: str, command_template: str) -> str:
    return (
        "SE Tools context for this turn:\n"
        "tool=MobiusRemoteCLI | repo=SOURCE | worker=worker-3 | "
        f"operation=adelete | command={command_template}\n\n"
        "Use this context when it is relevant to the user's question. "
        "Do not claim hidden state beyond what is provided here.\n\n"
        f"User question:\n{user_question}"
    )


def main() -> None:
    cmd_template = "adelete -s Mobius -u ADMIN -r {CONTENT_CLASS} -c -n -y ALL -o"
    question = _wrapped_question(
        "How to delete only content from before March 2021",
        cmd_template,
    )

    answer = _direct_advisory_answer(question, doc_context="")
    expected = f"{cmd_template} -t 20210228235959"

    assert answer == expected, f"Unexpected answer:\n{answer}\nExpected:\n{expected}"
    print("OK: deterministic advisory returns full command with month-year cutoff timestamp")


if __name__ == "__main__":
    main()
