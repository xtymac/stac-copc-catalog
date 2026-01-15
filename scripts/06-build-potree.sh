#!/bin/bash
# Build Potree Viewer for Static Deployment with COPC Support
#
# This script:
# - Clones Potree from GitHub (develop branch with COPC support)
# - Locks to a specific commit for reproducibility
# - Builds static assets
# - Prepares distribution directory for S3 deployment
#
# Usage:
#   ./06-build-potree.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Potree configuration
POTREE_SRC_DIR="$PROJECT_ROOT/potree-src"
POTREE_DIST_DIR="$PROJECT_ROOT/potree-viewer/dist"
POTREE_CUSTOM_DIR="$PROJECT_ROOT/potree-viewer/custom"

# Lock to specific commit for reproducibility (develop branch)
POTREE_COMMIT="c53cf7f7e692ee27bc4c2c623fe17bd678d25558"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

check_prerequisites() {
    log_step "Checking prerequisites..."

    if ! command -v node &> /dev/null; then
        log_error "Node.js is required but not installed"
        log_info "Install with: brew install node"
        exit 1
    fi

    if ! command -v npm &> /dev/null; then
        log_error "npm is required but not installed"
        exit 1
    fi

    if ! command -v git &> /dev/null; then
        log_error "git is required but not installed"
        exit 1
    fi

    NODE_VERSION=$(node --version)
    log_info "Node.js version: $NODE_VERSION"
}

clone_or_update_potree() {
    log_step "Setting up Potree source..."

    if [ -d "$POTREE_SRC_DIR/.git" ]; then
        log_info "Potree source exists, checking out locked commit..."
        cd "$POTREE_SRC_DIR"
        git fetch origin develop
        git checkout "$POTREE_COMMIT"
    else
        log_info "Cloning Potree repository..."
        git clone https://github.com/potree/potree.git "$POTREE_SRC_DIR"
        cd "$POTREE_SRC_DIR"
        git checkout "$POTREE_COMMIT"
    fi

    CURRENT_COMMIT=$(git rev-parse HEAD)
    log_info "Using Potree commit: $CURRENT_COMMIT"
}

build_potree() {
    log_step "Building Potree..."

    cd "$POTREE_SRC_DIR"

    # Install dependencies
    log_info "Installing npm dependencies..."
    npm install

    # Note: npm install already runs build via postinstall script
    # but we run it explicitly to ensure it's done
    if [ ! -f "build/potree/potree.js" ]; then
        log_info "Running build..."
        npm run build
    fi

    if [ ! -f "build/potree/potree.js" ]; then
        log_error "Build failed: build/potree/potree.js not found"
        exit 1
    fi

    log_info "Build successful"
}

prepare_distribution() {
    log_step "Preparing distribution directory..."

    # Clean and create dist directory
    rm -rf "$POTREE_DIST_DIR"
    mkdir -p "$POTREE_DIST_DIR"

    cd "$POTREE_SRC_DIR"

    # Copy build output (potree.js, potree.css, resources, workers, etc.)
    log_info "Copying build/potree/..."
    cp -r build/potree/* "$POTREE_DIST_DIR/"

    # Copy libs (three.js, jquery, proj4, copc, etc.)
    log_info "Copying libs/..."
    cp -r libs "$POTREE_DIST_DIR/"

    # Copy custom HTML page
    if [ -f "$POTREE_CUSTOM_DIR/index.html" ]; then
        log_info "Copying custom index.html..."
        cp "$POTREE_CUSTOM_DIR/index.html" "$POTREE_DIST_DIR/"
    else
        log_warn "Custom index.html not found at: $POTREE_CUSTOM_DIR/index.html"
    fi

    # Show distribution summary
    log_info "Distribution prepared at: $POTREE_DIST_DIR"
    log_info "Contents:"
    ls -la "$POTREE_DIST_DIR/" | head -20
}

show_summary() {
    echo ""
    log_info "============================================"
    log_info "Potree Build Complete"
    log_info "============================================"
    log_info ""
    log_info "Commit: $POTREE_COMMIT"
    log_info "Output: $POTREE_DIST_DIR"
    log_info ""
    log_info "To test locally:"
    log_info "  cd \"$POTREE_DIST_DIR\""
    log_info "  npx http-server -p 8080 --cors"
    log_info "  # Open http://localhost:8080/?files=https://stac.uixai.org/data/08LF6238.copc.laz"
    log_info ""
    log_info "To deploy:"
    log_info "  ./scripts/03-deploy-aws.sh --update"
    log_info ""
}

# Main
check_prerequisites
clone_or_update_potree
build_potree
prepare_distribution
show_summary
