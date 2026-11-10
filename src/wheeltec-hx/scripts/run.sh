#!/usr/bin/env bash
# wheeltec-hx 运行入口（Git Bash / Linux）：PYTHONPATH=src python -m app.main …
cd "$(dirname "$0")/.." || exit 1
PYTHONPATH=src python -m app.main "$@"
