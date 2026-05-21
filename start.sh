#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# start.sh — Zero-Touch Deployment for Smart Document Parser
# Handles: Docker install, buildx, Live USB overlay fix,
#          image build, and container execution.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

IMAGE_NAME="smart-parser"
DAEMON_JSON="/etc/docker/daemon.json"

# ── Helpers ──────────────────────────────────────────────────
info()  { echo "   ℹ️  $*"; }
ok()    { echo "   ✅ $*"; }
warn()  { echo "   ⚠️  $*"; }
fail()  { echo "   ❌ $*"; exit 1; }
step()  { echo ""; echo "── $* ──────────────────────────────"; }

echo ""
echo "══════════════════════════════════════════════"
echo "  🚀 Smart Document Parser — Zero-Touch Deploy"
echo "══════════════════════════════════════════════"

# ═════════════════════════════════════════════════════════════
# 1. DOCKER INSTALLATION
# ═════════════════════════════════════════════════════════════
step "1/5  Docker pre-flight check"

if command -v docker &>/dev/null; then
    ok "Docker already installed: $(docker --version 2>/dev/null || echo 'unknown')"
else
    warn "Docker is not installed. Starting auto-install..."

    # ── OS Detection ─────────────────────────────────────────
    if [[ ! -f /etc/os-release ]]; then
        fail "Cannot detect OS (/etc/os-release missing). Install Docker manually: https://docs.docker.com/get-docker/"
    fi

    # shellcheck source=/dev/null
    source /etc/os-release
    info "Detected OS: ${PRETTY_NAME:-${ID}} (ID=${ID}, ID_LIKE=${ID_LIKE:-none})"

    # ── Determine package manager & install ──────────────────
    install_apt() {
        info "Installing via get.docker.sh..."
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        rm -f get-docker.sh
        ok "get.docker.sh installation complete."
    }

    install_pacman() {
        info "Installing via pacman..."
        sudo pacman -Sy --noconfirm docker docker-buildx docker-compose
        ok "pacman installation complete."
    }

    case "${ID}" in
        ubuntu|debian|astra)    install_apt ;;
        arch|endeavouros)       install_pacman ;;
        *)
            if [[ "${ID_LIKE:-}" == *"debian"* || "${ID_LIKE:-}" == *"ubuntu"* ]]; then
                info "Derivative distro (${ID}) → using apt-get path."
                install_apt
            elif [[ "${ID_LIKE:-}" == *"arch"* ]]; then
                info "Derivative distro (${ID}) → using pacman path."
                install_pacman
            else
                fail "Unsupported OS '${PRETTY_NAME:-${ID}}'. Install Docker manually: https://docs.docker.com/get-docker/"
            fi
            ;;
    esac

    # Verify
    command -v docker &>/dev/null || fail "Docker binary not found after installation."
    ok "Docker installed: $(docker --version 2>/dev/null)"
fi

# ═════════════════════════════════════════════════════════════
# 2. BUILDX CHECK
# ═════════════════════════════════════════════════════════════
step "2/5  Buildx availability"

if sudo docker buildx version &>/dev/null; then
    ok "Buildx available: $(sudo docker buildx version 2>/dev/null)"
    USE_BUILDX=true
else
    warn "Buildx not found — will use legacy builder."
    USE_BUILDX=false
fi

# ═════════════════════════════════════════════════════════════
# 3. LIVE USB / OVERLAY FILESYSTEM SELF-HEALING
# ═════════════════════════════════════════════════════════════
step "3/5  Filesystem & storage-driver check"

ROOT_FSTYPE=$(df -T / | awk 'NR==2 {print $2}')
info "Root filesystem type: ${ROOT_FSTYPE}"

if [[ "${ROOT_FSTYPE}" == "overlay" ]]; then
    warn "Overlay root detected — likely a Live USB environment."
    info "Docker's default overlay2 driver will fail on overlay-on-overlay."
    info "Applying fix: setting storage-driver to 'vfs' in ${DAEMON_JSON}."

    sudo mkdir -p "$(dirname "${DAEMON_JSON}")"

    # Idempotent: only write if not already configured correctly
    if [[ -f "${DAEMON_JSON}" ]] && grep -q '"vfs"' "${DAEMON_JSON}" 2>/dev/null; then
        ok "daemon.json already contains vfs driver — no changes needed."
    else
        echo '{"storage-driver": "vfs"}' | sudo tee "${DAEMON_JSON}" >/dev/null
        ok "Wrote ${DAEMON_JSON} with storage-driver=vfs."
    fi
else
    ok "Standard filesystem (${ROOT_FSTYPE}) — using Docker's default storage driver."
fi

# ═════════════════════════════════════════════════════════════
# 4. DOCKER DAEMON — ENABLE & (RE)START
# ═════════════════════════════════════════════════════════════
step "4/5  Docker daemon"

if command -v systemctl &>/dev/null; then
    sudo systemctl enable docker 2>/dev/null || true
    sudo systemctl restart docker
    ok "Docker daemon is enabled and running."
else
    warn "systemctl not found — assuming Docker daemon is managed externally."
fi

# Quick smoke test
sudo docker info >/dev/null 2>&1 || fail "Docker daemon is not responding. Check 'sudo journalctl -xeu docker'."
ok "Docker daemon healthy."

# ═════════════════════════════════════════════════════════════
# 5. BUILD & RUN
# ═════════════════════════════════════════════════════════════
step "5/5  Build & run '${IMAGE_NAME}'"

info "Building image..."
if [[ "${USE_BUILDX}" == true ]]; then
    sudo docker buildx build -t "${IMAGE_NAME}" .
else
    sudo docker build -t "${IMAGE_NAME}" .
fi
ok "Image '${IMAGE_NAME}' built successfully."

echo ""
info "Running container..."
info "   INPUT     → $(pwd)/INPUT"
info "   PROCESSED → $(pwd)/PROCESSED"
echo ""

sudo docker run --rm \
    -v "$(pwd)/INPUT:/app/INPUT" \
    -v "$(pwd)/PROCESSED:/app/PROCESSED" \
    "${IMAGE_NAME}"

echo ""
echo "══════════════════════════════════════════════"
echo "  🏁 Deployment complete. All done!"
echo "══════════════════════════════════════════════"
