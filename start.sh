#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# start.sh — Smart cross-platform deploy for Smart Document Parser
# ─────────────────────────────────────────────────────────────
set -euo pipefail

IMAGE_NAME="smart-parser"

echo "══════════════════════════════════════════"
echo "  Smart Document Parser — Docker Deploy"
echo "══════════════════════════════════════════"
echo ""

# ── 1. Pre-flight: check if Docker is installed ─────────────
if command -v docker &>/dev/null; then
    echo "✅ Docker found: $(docker --version)"
else
    echo "⚠️  Docker is not installed. Attempting auto-install..."
    echo ""

    # ── 2. OS Detection via /etc/os-release ──────────────────
    if [[ ! -f /etc/os-release ]]; then
        echo "❌ ERROR: Cannot detect OS (/etc/os-release not found)."
        echo "   Please install Docker manually:"
        echo "   https://docs.docker.com/get-docker/"
        exit 1
    fi

    # Source the file to get $ID and $ID_LIKE variables
    # shellcheck source=/dev/null
    source /etc/os-release

    echo "   Detected OS: ${PRETTY_NAME:-${ID}}"
    echo ""

    # ── 3. Auto-installation per distro family ───────────────
    case "${ID}" in
        ubuntu|debian|astra)
            echo "📦 Installing Docker via apt-get (${ID})..."
            sudo apt-get update -qq
            sudo apt-get install -y docker.io
            sudo systemctl enable --now docker
            ;;
        arch|endeavouros)
            echo "📦 Installing Docker via pacman (${ID})..."
            sudo pacman -Sy --noconfirm docker
            sudo systemctl enable --now docker
            ;;
        *)
            # Fall back: check ID_LIKE for derivative distros
            if [[ "${ID_LIKE:-}" == *"debian"* || "${ID_LIKE:-}" == *"ubuntu"* ]]; then
                echo "📦 Installing Docker via apt-get (${ID}, debian-like)..."
                sudo apt-get update -qq
                sudo apt-get install -y docker.io
                sudo systemctl enable --now docker
            elif [[ "${ID_LIKE:-}" == *"arch"* ]]; then
                echo "📦 Installing Docker via pacman (${ID}, arch-like)..."
                sudo pacman -Sy --noconfirm docker
                sudo systemctl enable --now docker
            else
                echo "❌ ERROR: Unsupported OS '${PRETTY_NAME:-${ID}}'."
                echo "   Please install Docker manually:"
                echo "   https://docs.docker.com/get-docker/"
                exit 1
            fi
            ;;
    esac

    # Verify installation succeeded
    if ! command -v docker &>/dev/null; then
        echo "❌ ERROR: Docker installation failed."
        echo "   Please install Docker manually:"
        echo "   https://docs.docker.com/get-docker/"
        exit 1
    fi

    echo ""
    echo "✅ Docker installed: $(docker --version)"
fi

echo ""

# ── 4. Build the image ───────────────────────────────────────
echo "🔨 Building image '${IMAGE_NAME}' ..."
echo ""
sudo docker build -t "${IMAGE_NAME}" .

echo ""
echo "✅ Build complete."
echo ""

# ── 5. Run the container ─────────────────────────────────────
echo "🚀 Running container ..."
echo "   INPUT     → $(pwd)/INPUT"
echo "   PROCESSED → $(pwd)/PROCESSED"
echo ""

sudo docker run --rm \
    -v "$(pwd)/INPUT:/app/INPUT" \
    -v "$(pwd)/PROCESSED:/app/PROCESSED" \
    "${IMAGE_NAME}"

echo ""
echo "🏁 Done."
