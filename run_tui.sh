#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# run_tui.sh — Launch the Smart Document Parser TUI
#
# Activates the virtual environment and starts the Textual app.
# Run setup.sh first if you haven't already.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

# ── Check venv exists ────────────────────────────────────────
if [[ ! -d "${VENV_DIR}" ]]; then
    echo "❌ Virtual environment not found at ${VENV_DIR}"
    echo "   Run ./setup.sh first to set up the environment."
    exit 1
fi

# ── Activate venv ────────────────────────────────────────────
# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

# ── Set PYTHONPATH to project root ───────────────────────────
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"

# ── Launch TUI ───────────────────────────────────────────────
cd "${SCRIPT_DIR}"
exec python -m tui.app "$@"
