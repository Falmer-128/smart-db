#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# setup.sh — Zero-Touch Setup Wizard for smart-db
#
# Handles: Package manager detection, Docker install, NVIDIA
#          GPU detection, nvidia-container-toolkit auto-install,
#          Docker group membership, venv creation, and TUI launch.
# ─────────────────────────────────────────────────────────────
set -e

echo ""
echo "══════════════════════════════════════════════"
echo "  🚀 smart-db — Zero-Touch Setup Wizard"
echo "══════════════════════════════════════════════"
echo ""

# ── Helpers ──────────────────────────────────────────────────
info()  { echo "   ℹ️  $*"; }
ok()    { echo "   ✅ $*"; }
warn()  { echo "   ⚠️  $*"; }
fail()  { echo "   ❌ $*"; exit 1; }
step()  { echo ""; echo "── $* ──────────────────────────────"; }

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# ── OS Detection ─────────────────────────────────────────────
if [[ -f /etc/os-release ]]; then
    # shellcheck source=/dev/null
    source /etc/os-release
    DISTRO_ID="${ID}"
    DISTRO_ID_LIKE="${ID_LIKE:-}"
    DISTRO_PRETTY="${PRETTY_NAME:-${ID}}"
else
    DISTRO_ID="unknown"
    DISTRO_ID_LIKE=""
    DISTRO_PRETTY="Unknown OS"
fi
info "Detected OS: ${DISTRO_PRETTY}"

# ── Determine base distro family ─────────────────────────────
is_debian_family() {
    [[ "${DISTRO_ID}" =~ ^(ubuntu|debian|linuxmint|pop|zorin|elementary|neon|astra)$ ]] ||
    [[ "${DISTRO_ID_LIKE}" == *"debian"* ]] ||
    [[ "${DISTRO_ID_LIKE}" == *"ubuntu"* ]]
}

is_arch_family() {
    [[ "${DISTRO_ID}" =~ ^(arch|endeavouros|manjaro|garuda|artix)$ ]] ||
    [[ "${DISTRO_ID_LIKE}" == *"arch"* ]]
}

# ── Determine package manager ────────────────────────────────
PKG_MANAGER=""
if command_exists apt-get; then
    PKG_MANAGER="apt-get"
elif command_exists dnf; then
    PKG_MANAGER="dnf"
elif command_exists pacman; then
    PKG_MANAGER="pacman"
else
    fail "Unsupported package manager. Please install dependencies manually."
fi
info "Package manager: ${PKG_MANAGER}"

install_package() {
    local package=$1
    info "Installing ${package}..."
    if [ "$PKG_MANAGER" = "apt-get" ]; then
        sudo apt-get update -qq && sudo apt-get install -y "$package"
    elif [ "$PKG_MANAGER" = "dnf" ]; then
        sudo dnf install -y "$package"
    elif [ "$PKG_MANAGER" = "pacman" ]; then
        sudo pacman -Sy --noconfirm "$package"
    fi
}

# ═════════════════════════════════════════════════════════════
# 1. CORE DEPENDENCY CHECKS
# ═════════════════════════════════════════════════════════════
step "1/8  Core dependency pre-flight"

if ! command_exists python3; then
    install_package python3
fi
ok "python3 found: $(python3 --version 2>&1)"

# For Debian/Ubuntu, python3-venv is often required separately
if [ "$PKG_MANAGER" = "apt-get" ]; then
    if ! dpkg -s python3-venv >/dev/null 2>&1; then
        install_package python3-venv
    fi
fi

if ! command_exists curl; then
    install_package curl
fi
ok "curl found"

if ! command_exists unrar; then
    install_package unrar
fi
ok "unrar found"

# LibreOffice headless — required for .doc → .pdf conversion
if ! command_exists libreoffice; then
    info "Installing LibreOffice (headless, for .doc conversion)..."
    if [ "$PKG_MANAGER" = "apt-get" ]; then
        sudo apt-get update -qq && sudo apt-get install -y libreoffice-core
    elif [ "$PKG_MANAGER" = "dnf" ]; then
        sudo dnf install -y libreoffice-core
    elif [ "$PKG_MANAGER" = "pacman" ]; then
        sudo pacman -Sy --noconfirm libreoffice-still
    fi
fi
ok "libreoffice found: $(libreoffice --version 2>&1 | head -1)"

# OpenCV system dependencies — required by PaddleOCR
if [ "$PKG_MANAGER" = "apt-get" ]; then
    if ! dpkg -s libgl1 >/dev/null 2>&1 || ! dpkg -s libglib2.0-0 >/dev/null 2>&1; then
        info "Installing OpenCV system dependencies (libgl1, libglib2.0-0)..."
        sudo apt-get update -qq && sudo apt-get install -y libgl1 libglib2.0-0
    fi
elif [ "$PKG_MANAGER" = "dnf" ]; then
    rpm -q mesa-libGL >/dev/null 2>&1 || sudo dnf install -y mesa-libGL
    rpm -q glib2 >/dev/null 2>&1   || sudo dnf install -y glib2
elif [ "$PKG_MANAGER" = "pacman" ]; then
    pacman -Qi mesa >/dev/null 2>&1  || sudo pacman -Sy --noconfirm mesa
    pacman -Qi glib2 >/dev/null 2>&1 || sudo pacman -Sy --noconfirm glib2
fi
ok "OpenCV system dependencies satisfied."

# ═════════════════════════════════════════════════════════════
# 2. DOCKER INSTALLATION
# ═════════════════════════════════════════════════════════════
step "2/8  Docker pre-flight"

if ! command_exists docker || ! docker compose version >/dev/null 2>&1; then
    warn "Docker or Docker Compose V2 is missing. Starting auto-install..."
    if [ "$PKG_MANAGER" = "apt-get" ] || [ "$PKG_MANAGER" = "dnf" ]; then
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        rm -f get-docker.sh
    elif [ "$PKG_MANAGER" = "pacman" ]; then
        sudo pacman -Sy --noconfirm docker docker-buildx docker-compose
    fi
    command_exists docker || fail "Docker binary not found after installation."
    ok "Docker installed: $(docker --version 2>/dev/null)"
else
    ok "Docker already installed: $(docker --version 2>/dev/null)"
fi

# ═════════════════════════════════════════════════════════════
# 3. DOCKER DAEMON
# ═════════════════════════════════════════════════════════════
step "3/8  Docker daemon"

if command_exists systemctl; then
    if ! systemctl is-active --quiet docker; then
        info "Starting Docker service..."
        sudo systemctl enable --now docker
    fi
    ok "Docker daemon is running."
else
    warn "systemctl not found — assuming Docker daemon is managed externally."
fi

# ═════════════════════════════════════════════════════════════
# 4. DOCKER GROUP MEMBERSHIP
# ═════════════════════════════════════════════════════════════
step "4/8  Docker group membership"

if groups "$USER" 2>/dev/null | grep -qw docker; then
    ok "User '${USER}' is already in the 'docker' group."
else
    warn "User '${USER}' is NOT in the 'docker' group."
    info "Adding '${USER}' to the 'docker' group..."
    sudo usermod -aG docker "$USER"
    ok "Added '${USER}' to 'docker' group."
    echo ""
    warn "╔══════════════════════════════════════════════════════════╗"
    warn "║  You MUST log out and log back in (or reboot) for the   ║"
    warn "║  docker group change to take effect.                    ║"
    warn "║                                                         ║"
    warn "║  After re-login, re-run: ./setup.sh                     ║"
    warn "╚══════════════════════════════════════════════════════════╝"
    echo ""
fi

# Quick smoke test — try without sudo first, fall back to sudo
if ! docker ps >/dev/null 2>&1; then
    if ! sudo docker ps >/dev/null 2>&1; then
        warn "Cannot connect to Docker daemon. You may need to re-login for group changes."
        info "Attempting to proceed..."
        sleep 2
    else
        info "Docker requires sudo — group changes may not have taken effect yet."
    fi
fi

# ═════════════════════════════════════════════════════════════
# 5. NVIDIA GPU DETECTION & CONTAINER TOOLKIT
# ═════════════════════════════════════════════════════════════
step "5/8  NVIDIA GPU & Container Toolkit"

NVIDIA_GPU_FOUND=false

# Detect NVIDIA GPU via lspci
if command_exists lspci; then
    if lspci | grep -qi nvidia; then
        NVIDIA_GPU_FOUND=true
        ok "NVIDIA GPU detected via lspci."
    fi
else
    # Fallback: try nvidia-smi directly
    if command_exists nvidia-smi; then
        NVIDIA_GPU_FOUND=true
        ok "NVIDIA GPU detected via nvidia-smi."
    fi
fi

if [ "$NVIDIA_GPU_FOUND" = true ]; then
    # ── Check if nvidia-container-toolkit is installed ────────
    if command_exists nvidia-ctk; then
        ok "nvidia-container-toolkit is already installed."
    else
        warn "nvidia-container-toolkit is NOT installed. Starting OS-aware auto-install..."

        if is_debian_family; then
            info "Using Debian/Ubuntu installation path..."

            # Add NVIDIA GPG key
            info "Adding NVIDIA GPG key..."
            curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
                | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null

            # Add NVIDIA container toolkit repository
            info "Adding NVIDIA container toolkit repository..."
            curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
                | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
                | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null

            # Install the toolkit
            sudo apt-get update -qq
            sudo apt-get install -y nvidia-container-toolkit

        elif is_arch_family; then
            info "Using Arch Linux installation path..."
            sudo pacman -Sy --noconfirm nvidia-container-toolkit

        else
            warn "Unsupported distro '${DISTRO_PRETTY}' for automatic nvidia-container-toolkit install."
            warn "Please install nvidia-container-toolkit manually:"
            warn "  https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
        fi

        # Verify installation
        if command_exists nvidia-ctk; then
            ok "nvidia-container-toolkit installed successfully."
        else
            warn "nvidia-container-toolkit installation may have failed. Continuing anyway..."
        fi
    fi

    # ── Configure Docker runtime for NVIDIA ──────────────────
    if command_exists nvidia-ctk; then
        info "Configuring NVIDIA container runtime for Docker..."
        sudo nvidia-ctk runtime configure --runtime=docker 2>/dev/null || true
        ok "NVIDIA runtime configured."

        # Restart Docker to pick up the new runtime
        if command_exists systemctl; then
            info "Restarting Docker daemon to apply NVIDIA runtime..."
            sudo systemctl restart docker
            ok "Docker restarted with NVIDIA GPU support."
        fi
    fi
else
    info "No NVIDIA GPU detected. Skipping container toolkit setup."
    info "The system will use CPU-only mode for LLM inference."
fi

# ═════════════════════════════════════════════════════════════
# 6. PYTHON VIRTUAL ENVIRONMENT & TUI LAUNCH
# ═════════════════════════════════════════════════════════════
step "6/8  Python environment & dependencies"

# Create .venv if it doesn't exist
if [ ! -d ".venv" ]; then
    info "Creating virtual environment..."
    python3 -m venv .venv
fi
ok "Virtual environment ready."

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip quietly
python3 -m pip install --upgrade pip >/dev/null 2>&1 || true


# Install required dependencies
info "Installing Python dependencies..."
pip install -r requirements.txt >/dev/null 2>&1
pip install paddlepaddle paddleocr pymupdf tabulate langchain-text-splitters google-generativeai python-dotenv markitdown mammoth xlrd openpyxl pandas >/dev/null 2>&1
ok "All Python dependencies installed."

info "Pre-downloading PaddleOCR models (ru)..."
python3 -c "from paddleocr import PaddleOCR; PaddleOCR(use_textline_orientation=True, lang='ru')"
ok "PaddleOCR models downloaded."

# ═════════════════════════════════════════════════════════════
# 7. INGESTION DAEMON LIFECYCLE
# ═════════════════════════════════════════════════════════════
step "7/8  Ingestion daemon lifecycle"

DAEMON_SCRIPT="ingestion_daemon.py"
DAEMON_LOG="daemon.log"
DAEMON_PID_FILE=".daemon.pid"

# Kill any existing/zombie instances
if [ -f "$DAEMON_PID_FILE" ]; then
    OLD_PID=$(cat "$DAEMON_PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        info "Stopping existing daemon (PID: $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
        # Force kill if it didn't stop gracefully
        kill -0 "$OLD_PID" 2>/dev/null && kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$DAEMON_PID_FILE"
fi

# Also kill any orphaned processes matching the daemon script name
pkill -f "python3.*${DAEMON_SCRIPT}" 2>/dev/null || true
sleep 0.5

# Start the daemon in the background
info "Starting ingestion daemon in background..."
nohup python3 "$DAEMON_SCRIPT" >> "$DAEMON_LOG" 2>&1 &
DAEMON_PID=$!
echo "$DAEMON_PID" > "$DAEMON_PID_FILE"
ok "Ingestion daemon started (PID: $DAEMON_PID). Logs → $DAEMON_LOG"

# ═════════════════════════════════════════════════════════════
# 8. TUI LAUNCH
# ═════════════════════════════════════════════════════════════

# Launch the TUI
echo ""
echo "══════════════════════════════════════════════"
echo "  ✨ Launching Setup Wizard..."
echo "══════════════════════════════════════════════"
echo ""
python3 -m tui.app
