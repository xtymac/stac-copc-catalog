#!/bin/bash
# Run STAC API locally for development

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Activate virtual environment
if [ -d "$PROJECT_DIR/.venv" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
elif [ -d "$SCRIPT_DIR/.venv" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

# Check if index exists
if [ ! -d "$SCRIPT_DIR/index" ]; then
    echo "Index not found. Generating..."
    cd "$PROJECT_DIR"
    python scripts/index-to-parquet.py --catalog catalog-combined --output stac-api/index
fi

# Set environment variables
export INDEX_PATH="$SCRIPT_DIR/index"
export STAC_API_TITLE="STAC COPC API (Local)"

# Run uvicorn
cd "$SCRIPT_DIR"
echo "Starting STAC API at http://localhost:8000"
echo "Swagger UI: http://localhost:8000/docs"
echo ""
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
