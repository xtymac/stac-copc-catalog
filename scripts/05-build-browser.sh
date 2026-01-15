#!/bin/bash
# Build STAC Browser for Static Deployment
#
# This script:
# - Clones STAC Browser from GitHub
# - Configures for S3/static hosting (hash mode)
# - Builds the static site
#
# Usage:
#   ./05-build-browser.sh
#   STAC_CATALOG_URL=https://stac.example.com/catalog.json ./05-build-browser.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BROWSER_DIR="$PROJECT_ROOT/stac-browser"

# Load environment variables
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration
CATALOG_URL="${STAC_CATALOG_URL:-}"
STAC_BROWSER_VERSION="${STAC_BROWSER_VERSION:-3.2.0}"
CATALOG_TITLE="${STAC_CATALOG_TITLE:-STAC COPC Catalog}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check Node.js
    if ! command -v node &> /dev/null; then
        log_error "Node.js is not installed"
        log_info "Install from: https://nodejs.org/"
        exit 1
    fi

    NODE_VERSION=$(node -v)
    log_info "Node.js version: $NODE_VERSION"

    # Check npm
    if ! command -v npm &> /dev/null; then
        log_error "npm is not installed"
        exit 1
    fi

    NPM_VERSION=$(npm -v)
    log_info "npm version: $NPM_VERSION"

    # Check git
    if ! command -v git &> /dev/null; then
        log_error "git is not installed"
        exit 1
    fi
}

clone_or_update_browser() {
    log_info "Setting up STAC Browser v$STAC_BROWSER_VERSION..."

    if [ -d "$BROWSER_DIR/src" ]; then
        log_info "STAC Browser source exists, checking version..."

        cd "$BROWSER_DIR/src"

        # Check if we're on the right version
        CURRENT_TAG=$(git describe --tags --exact-match 2>/dev/null || echo "")

        if [ "$CURRENT_TAG" = "v$STAC_BROWSER_VERSION" ]; then
            log_info "Already on version $STAC_BROWSER_VERSION"
            return
        fi

        log_info "Updating to version $STAC_BROWSER_VERSION..."
        git fetch --tags
        git checkout "v$STAC_BROWSER_VERSION"
    else
        log_info "Cloning STAC Browser..."
        mkdir -p "$BROWSER_DIR"

        git clone --depth 1 --branch "v$STAC_BROWSER_VERSION" \
            https://github.com/radiantearth/stac-browser.git \
            "$BROWSER_DIR/src"
    fi
}

configure_browser() {
    log_info "Configuring STAC Browser..."

    cd "$BROWSER_DIR/src"

    # Determine catalog URL
    if [ -z "$CATALOG_URL" ]; then
        # Try to construct from .env values
        if [ -n "${STAC_DOMAIN:-}" ]; then
            CATALOG_URL="https://$STAC_DOMAIN/catalog.json"
        elif [ -n "${STAC_BASE_URL:-}" ]; then
            CATALOG_URL="$STAC_BASE_URL/catalog.json"
        else
            log_warn "No CATALOG_URL specified, using placeholder"
            CATALOG_URL="https://your-domain.com/catalog.json"
        fi
    fi

    log_info "Catalog URL: $CATALOG_URL"

    # Create config.js if needed
    if [ -f "config.js" ]; then
        log_info "config.js already exists, backing up..."
        cp config.js config.js.bak
    fi

    # Note: STAC Browser v3.x uses environment variables during build
    # We'll set these when running npm build
}

install_dependencies() {
    log_info "Installing dependencies..."

    cd "$BROWSER_DIR/src"

    # Clean install
    if [ -d "node_modules" ]; then
        log_info "Cleaning existing node_modules..."
        rm -rf node_modules
    fi

    npm ci

    log_info "Dependencies installed"
}

build_browser() {
    log_info "Building STAC Browser..."

    cd "$BROWSER_DIR/src"

    # Set environment variables for build
    # See: https://github.com/radiantearth/stac-browser#environment-variables
    export SB_catalogUrl="$CATALOG_URL"
    export SB_catalogTitle="$CATALOG_TITLE"
    export SB_historyMode="hash"  # Required for S3/static hosting
    export SB_pathPrefix="/browser/"  # Critical: sets publicPath for assets
    export SB_allowExternalAccess="true"
    # Don't set SB_stacProxyUrl - leave it unset for static hosting
    export SB_useTileLayerComponent="true"

    # Optional: Point cloud specific settings
    export SB_cardViewMode="cards"
    export SB_showThumbnailsAsAssets="true"

    # Language settings are configured directly in src/config.js
    # (SB_supportedLocales env var doesn't work correctly with array values)

    log_info "Building with configuration:"
    log_info "  SB_catalogUrl: $SB_catalogUrl"
    log_info "  SB_catalogTitle: $SB_catalogTitle"
    log_info "  SB_historyMode: $SB_historyMode"

    # Run build
    npm run build

    log_info "Build complete"
}

copy_output() {
    log_info "Copying build output..."

    # Remove old dist
    rm -rf "$BROWSER_DIR/dist"

    # Copy new build
    cp -r "$BROWSER_DIR/src/dist" "$BROWSER_DIR/dist"

    # Count files
    FILE_COUNT=$(find "$BROWSER_DIR/dist" -type f | wc -l | tr -d ' ')

    log_info "Copied $FILE_COUNT files to: $BROWSER_DIR/dist"
}

create_fallback_index() {
    # Create a simple fallback HTML if build fails
    log_info "Creating fallback index.html..."

    mkdir -p "$BROWSER_DIR/dist"

    cat > "$BROWSER_DIR/dist/index.html" << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>STAC COPC Catalog</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            line-height: 1.6;
        }
        h1 { color: #333; }
        a { color: #0066cc; }
        code {
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
        }
        pre {
            background: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }
    </style>
</head>
<body>
    <h1>STAC COPC Catalog</h1>
    <p>This is a static STAC catalog for Cloud Optimized Point Cloud (COPC) data.</p>

    <h2>API Endpoints</h2>
    <ul>
        <li><a href="catalog.json">catalog.json</a> - Root catalog</li>
        <li><a href="collections/">collections/</a> - Collections</li>
    </ul>

    <h2>Access with Python</h2>
    <pre><code>import pystac_client

catalog = pystac_client.Client.open("./catalog.json")
for item in catalog.get_items():
    print(item.id, item.assets["data"].href)
</code></pre>

    <h2>Access with PDAL</h2>
    <pre><code>pdal info --readers.stac.filename="./items/sample.json" \
          --readers.stac.asset_names="data"
</code></pre>

    <p><em>Note: STAC Browser build failed. This is a fallback page.</em></p>
</body>
</html>
EOF

    log_info "Fallback index.html created"
}

print_summary() {
    echo ""
    log_info "============================================"
    log_info "STAC BROWSER BUILD COMPLETE"
    log_info "============================================"
    echo ""
    log_info "Output: $BROWSER_DIR/dist/"
    log_info "Catalog URL: $CATALOG_URL"
    echo ""
    log_info "To preview locally:"
    log_info "  cd $BROWSER_DIR/dist && python -m http.server 8080"
    log_info "  Open: http://localhost:8080/"
    echo ""
    log_info "To deploy:"
    log_info "  ./scripts/03-deploy-aws.sh --update"
}

# Main
check_prerequisites

# Try full build
if clone_or_update_browser && install_dependencies && build_browser; then
    copy_output
    print_summary
else
    log_warn "Full build failed, creating fallback..."
    create_fallback_index

    echo ""
    log_warn "============================================"
    log_warn "STAC BROWSER BUILD INCOMPLETE"
    log_warn "============================================"
    echo ""
    log_warn "A fallback index.html has been created."
    log_warn "You can still access the catalog directly via JSON endpoints."
    echo ""
    log_info "Output: $BROWSER_DIR/dist/"
fi
