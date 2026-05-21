#!/usr/bin/env bash
set -e

echo "Starting Zero-Touch Setup Wizard for smart-db..."

# Helper to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Determine package manager
PKG_MANAGER=""
if command_exists apt-get; then
    PKG_MANAGER="apt-get"
elif command_exists dnf; then
    PKG_MANAGER="dnf"
elif command_exists pacman; then
    PKG_MANAGER="pacman"
else
    echo "Error: Unsupported package manager. Please install dependencies manually."
    exit 1
fi

install_package() {
    local package=$1
    echo "Installing ${package}..."
    if [ "$PKG_MANAGER" = "apt-get" ]; then
        sudo apt-get update -qq && sudo apt-get install -y "$package"
    elif [ "$PKG_MANAGER" = "dnf" ]; then
        sudo dnf install -y "$package"
    elif [ "$PKG_MANAGER" = "pacman" ]; then
        sudo pacman -Sy --noconfirm "$package"
    fi
}

# 1. Dependency checks and auto-installation
if ! command_exists python3; then
    install_package python3
fi

# For Debian/Ubuntu, python3-venv is often required separately
if [ "$PKG_MANAGER" = "apt-get" ]; then
    if ! dpkg -s python3-venv >/dev/null 2>&1; then
        install_package python3-venv
    fi
fi

if ! command_exists curl; then
    install_package curl
fi

if ! command_exists docker; then
    if [ "$PKG_MANAGER" = "apt-get" ]; then
        install_package docker.io
    else
        install_package docker
    fi
fi

if ! command_exists docker-compose && ! docker compose version >/dev/null 2>&1; then
    install_package docker-compose
fi

# 2. Ensure Docker Daemon is started
if command_exists systemctl; then
    if ! systemctl is-active --quiet docker; then
        echo "Starting Docker service..."
        sudo systemctl enable --now docker
    fi
fi

# Warn if docker requires sudo (user not in docker group)
if ! docker ps >/dev/null 2>&1; then
    echo "Warning: Cannot connect to docker daemon. You may need to run this script with sudo or add your user to the docker group."
    echo "Attempting to proceed..."
    sleep 2
fi

echo "All prerequisites met. Setting up virtual environment..."

# 3. Create .venv if it doesn't exist
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip quietly
python3 -m pip install --upgrade pip >/dev/null 2>&1 || true

# Install required dependencies
echo "Installing Python dependencies (textual, python-dotenv)..."
pip install textual python-dotenv >/dev/null 2>&1

# 4. Execute the Textual TUI entry point
echo "Launching Setup Wizard..."
python3 -m tui.app
