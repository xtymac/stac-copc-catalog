#!/bin/bash
# Install Dependencies for STAC COPC Catalog
#
# This script installs:
# - PDAL (via conda or brew)
# - Python dependencies (via pip)
#
# Usage: ./scripts/install-deps.sh [--conda|--brew]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_python() {
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log_info "Python version: $PYTHON_VERSION"
}

install_pdal_conda() {
    log_info "Installing PDAL via conda..."

    if ! command -v conda &> /dev/null; then
        log_error "Conda is not installed. Install Miniconda or Anaconda first."
        log_info "Download from: https://docs.conda.io/en/latest/miniconda.html"
        exit 1
    fi

    # Create or update conda environment
    if conda env list | grep -q "stac-copc"; then
        log_info "Updating existing conda environment 'stac-copc'..."
        conda activate stac-copc
        conda install -c conda-forge pdal python-pdal -y
    else
        log_info "Creating new conda environment 'stac-copc'..."
        conda create -n stac-copc python=3.11 pdal python-pdal -c conda-forge -y
        log_info "Activate with: conda activate stac-copc"
    fi
}

install_pdal_brew() {
    log_info "Installing PDAL via Homebrew..."

    if ! command -v brew &> /dev/null; then
        log_error "Homebrew is not installed"
        log_info "Install from: https://brew.sh"
        exit 1
    fi

    if brew list pdal &> /dev/null; then
        log_info "PDAL already installed via brew"
    else
        brew install pdal
    fi

    log_warn "Note: PDAL Python bindings are not available via brew."
    log_warn "Scripts will use PDAL CLI instead of Python API."
}

install_python_deps() {
    log_info "Installing Python dependencies..."

    cd "$PROJECT_ROOT"

    # Create virtual environment if not in conda
    if [[ -z "${CONDA_DEFAULT_ENV:-}" ]]; then
        if [ ! -d ".venv" ]; then
            log_info "Creating Python virtual environment..."
            python3 -m venv .venv
        fi

        log_info "Activating virtual environment..."
        source .venv/bin/activate
    fi

    # Upgrade pip
    pip install --upgrade pip

    # Install requirements
    pip install -r requirements.txt

    log_info "Python dependencies installed successfully"
}

verify_installation() {
    log_info "Verifying installation..."

    # Check PDAL
    if command -v pdal &> /dev/null; then
        PDAL_VERSION=$(pdal --version 2>&1 | head -n1)
        log_info "PDAL: $PDAL_VERSION"
    else
        log_error "PDAL not found in PATH"
        exit 1
    fi

    # Check Python packages
    python3 -c "import pystac; print(f'PySTAC: {pystac.__version__}')"
    python3 -c "import shapely; print(f'Shapely: {shapely.__version__}')"
    python3 -c "import pyproj; print(f'PyProj: {pyproj.__version__}')"
    python3 -c "import boto3; print(f'Boto3: {boto3.__version__}')"

    # Check for PDAL Python bindings (optional)
    if python3 -c "import pdal" 2>/dev/null; then
        python3 -c "import pdal; print(f'PDAL Python: available')"
    else
        log_warn "PDAL Python bindings not available (will use CLI)"
    fi

    log_info "All dependencies verified!"
}

print_usage() {
    echo "Usage: $0 [--conda|--brew]"
    echo ""
    echo "Options:"
    echo "  --conda    Install PDAL via conda (recommended, includes Python bindings)"
    echo "  --brew     Install PDAL via Homebrew (macOS, CLI only)"
    echo ""
    echo "If no option specified, will try conda first, then brew."
}

# Main
INSTALL_METHOD="${1:-auto}"

check_python

case "$INSTALL_METHOD" in
    --conda)
        install_pdal_conda
        install_python_deps
        ;;
    --brew)
        install_pdal_brew
        install_python_deps
        ;;
    --help|-h)
        print_usage
        exit 0
        ;;
    auto|*)
        if command -v conda &> /dev/null; then
            install_pdal_conda
        elif command -v brew &> /dev/null; then
            install_pdal_brew
        else
            log_error "Neither conda nor brew found. Please install one of them first."
            exit 1
        fi
        install_python_deps
        ;;
esac

verify_installation

log_info "============================================"
log_info "Installation complete!"
log_info ""
log_info "Next steps:"
log_info "  1. Copy .env.example to .env and configure"
log_info "  2. Place LAS/LAZ files in local/input/"
log_info "  3. Run: python scripts/01-prepare-data.py"
log_info "============================================"
