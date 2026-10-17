#!/usr/bin/env bash
set -euo pipefail

git submodule update --init --recursive

echo "FIRBO source ready."
echo
echo "OpenJarvis: packages/openjarvis"
echo "OmniRoute:  packages/omniroute"
echo
echo "Next:"
echo "  1. cp .env.example .env"
echo "  2. Start OmniRoute using its pinned README"
echo "  3. python -m venv .venv && . .venv/bin/activate"
echo "  4. pip install -r services/orchestrator/requirements.txt"
echo "  5. uvicorn services.orchestrator.app:app --host 127.0.0.1 --port 8787"
