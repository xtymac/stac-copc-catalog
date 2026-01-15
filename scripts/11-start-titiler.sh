#!/bin/bash
#
# Start TiTiler Dynamic Tile Server
#
# Usage:
#   ./scripts/11-start-titiler.sh          # Start server
#   ./scripts/11-start-titiler.sh stop     # Stop server
#   ./scripts/11-start-titiler.sh status   # Check status
#   ./scripts/11-start-titiler.sh logs     # View logs
#   ./scripts/11-start-titiler.sh test     # Test with local COG
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TITILER_DIR="$PROJECT_DIR/titiler"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Detect docker compose command (new: "docker compose", old: "$DOCKER_COMPOSE")
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
elif $DOCKER_COMPOSE version &> /dev/null; then
    DOCKER_COMPOSE="$DOCKER_COMPOSE"
else
    echo -e "${RED}Error: Docker Compose is not installed.${NC}"
    echo "Install Docker Desktop or run: brew install $DOCKER_COMPOSE"
    exit 1
fi

cd "$TITILER_DIR"

case "${1:-start}" in
    start)
        echo -e "${GREEN}Starting TiTiler...${NC}"
        $DOCKER_COMPOSE up -d
        echo ""
        echo -e "${GREEN}TiTiler is starting...${NC}"
        echo ""
        echo "Endpoints:"
        echo "  - API Docs:    http://localhost:8080/docs"
        echo "  - Health:      http://localhost:8080/healthz"
        echo "  - COG Info:    http://localhost:8080/cog/info?url=<COG_URL>"
        echo "  - COG Tiles:   http://localhost:8080/cog/tiles/{z}/{x}/{y}.png?url=<COG_URL>"
        echo "  - COG Preview: http://localhost:8080/cog/preview.png?url=<COG_URL>"
        echo ""
        echo "Example (local file):"
        echo "  curl 'http://localhost:8080/cog/info?url=file:///data/dem/08LF6330_dem.tif'"
        echo ""
        echo "Example (remote COG):"
        echo "  curl 'http://localhost:8080/cog/info?url=https://stac.uixai.org/dem/08LF6330_dem.tif'"
        echo ""
        ;;

    stop)
        echo -e "${YELLOW}Stopping TiTiler...${NC}"
        $DOCKER_COMPOSE down
        echo -e "${GREEN}TiTiler stopped.${NC}"
        ;;

    restart)
        echo -e "${YELLOW}Restarting TiTiler...${NC}"
        $DOCKER_COMPOSE restart
        echo -e "${GREEN}TiTiler restarted.${NC}"
        ;;

    status)
        echo "TiTiler Status:"
        $DOCKER_COMPOSE ps
        echo ""
        echo "Health check:"
        curl -s http://localhost:8080/healthz 2>/dev/null && echo " - Healthy" || echo -e "${RED}Not running${NC}"
        ;;

    logs)
        $DOCKER_COMPOSE logs -f
        ;;

    test)
        echo -e "${GREEN}Testing TiTiler with local COG...${NC}"
        echo ""

        # Check if server is running
        if ! curl -s http://localhost:8080/healthz > /dev/null 2>&1; then
            echo -e "${RED}TiTiler is not running. Start it first with: $0 start${NC}"
            exit 1
        fi

        # Find a local COG file
        COG_FILE=$(find "$PROJECT_DIR/local/dem" -name "*.tif" -type f | head -1)

        if [ -z "$COG_FILE" ]; then
            echo -e "${YELLOW}No local COG files found. Generate DEMs first.${NC}"
            exit 1
        fi

        COG_NAME=$(basename "$COG_FILE")
        echo "Testing with: $COG_NAME"
        echo ""

        # Test COG info endpoint
        echo "1. Getting COG info..."
        curl -s "http://localhost:8080/cog/info?url=file:///data/dem/$COG_NAME" | python3 -m json.tool
        echo ""

        # Test statistics endpoint
        echo "2. Getting statistics..."
        curl -s "http://localhost:8080/cog/statistics?url=file:///data/dem/$COG_NAME" | python3 -m json.tool
        echo ""

        # Test preview endpoint (save to file)
        echo "3. Generating preview image..."
        PREVIEW_FILE="$PROJECT_DIR/local/dem/${COG_NAME%.tif}_preview.png"
        curl -s "http://localhost:8080/cog/preview.png?url=file:///data/dem/$COG_NAME&colormap_name=terrain" -o "$PREVIEW_FILE"
        echo "Preview saved to: $PREVIEW_FILE"
        echo ""

        echo -e "${GREEN}All tests passed!${NC}"
        ;;

    *)
        echo "Usage: $0 {start|stop|restart|status|logs|test}"
        exit 1
        ;;
esac
