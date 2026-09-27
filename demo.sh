#!/usr/bin/env bash

set -u

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT" || exit 1

if [ -z "${GOOGLE_API_KEY:-}" ]; then
    if [ ! -f .env ] || ! grep -Eq '^[[:space:]]*GOOGLE_API_KEY[[:space:]]*=[[:space:]]*[^[:space:]]+' .env; then
        echo "GOOGLE_API_KEY is required; export it or add it to .env before running the demo."
        exit 1
    fi
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required; install it before running the demo."
    exit 1
fi

if command -v codex >/dev/null 2>&1 && codex login status >/dev/null 2>&1; then
    approval="yes"
elif command -v claude >/dev/null 2>&1 && claude auth status >/dev/null 2>&1; then
    approval="yes"
else
    approval="no"
fi

knowledge_question="What is RAG?"
code_request="create hello.py that prints hello world"
raw_transcript="demo-transcript.txt"
clean_transcript="demo/demo-transcript.txt"

mkdir -p demo

# Manual recording: install asciinema, then run `asciinema rec demo/demo.cast -c ./demo.sh`.
# Convert the cast to SVG or GIF with a compatible renderer such as svg-term or agg.
# Replace the README transcript block with `![Demo](demo/demo.svg)` after exporting the animation.

printf '%s\n' "$knowledge_question" "$code_request" "$approval" \
    | uv run main.py >"$raw_transcript" 2>&1

uv run python - \
    "$raw_transcript" \
    "$clean_transcript" \
    "$approval" \
    "$knowledge_question" \
    "$code_request" <<'PY'
import re
import sys
from pathlib import Path

raw_path, clean_path, approval, knowledge_question, code_request = sys.argv[1:]
text = Path(raw_path).read_text(encoding="utf-8", errors="replace")
text = re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text)

prompt = "Enter message : "
start = text.find(prompt)
if start == -1:
    raise SystemExit(f"Demo output did not contain the expected prompt; inspect {raw_path}.")

text = text[start:]
traceback_start = text.find("Traceback (most recent call last):")
if traceback_start != -1:
    text = text[:traceback_start]

sections = text.split(prompt)
if len(sections) < 3:
    raise SystemExit(f"Demo did not reach the coding request; inspect {raw_path}.")

knowledge_output = sections[1].strip()
approval_output = sections[2].strip()
approval_output = approval_output.replace("\n> ", f"\n> {approval}\n", 1)
approval_output = approval_output.replace("\n Approve?", "\nApprove?", 1)

cleaned = (
    f"Enter message : {knowledge_question}\n"
    f"{knowledge_output}\n\n"
    f"Enter message : {code_request}\n"
    f"{approval_output}\n"
)
cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines()).strip() + "\n"
Path(clean_path).write_text(cleaned, encoding="utf-8")
PY

clean_status=$?
if [ "$clean_status" -ne 0 ]; then
    exit "$clean_status"
fi

echo "Raw output: $raw_transcript"
echo "Clean transcript: $clean_transcript"
