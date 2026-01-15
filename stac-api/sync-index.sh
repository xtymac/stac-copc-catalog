#!/bin/bash
# Sync STAC catalog index to S3
# Run this after making changes to the catalog

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

CATALOG_DIR="${PROJECT_DIR}/catalog-combined"
INDEX_DIR="${SCRIPT_DIR}/index"
BUCKET="stac-uixai-catalog"
INDEX_PREFIX="index"

echo "=== STAC Index Sync ==="
echo "Catalog: ${CATALOG_DIR}"
echo "Index: ${INDEX_DIR}"
echo "S3: s3://${BUCKET}/${INDEX_PREFIX}/"
echo ""

# Step 1: Generate index
echo ">>> Step 1: Generating Parquet index..."
cd "$PROJECT_DIR"
source .venv/bin/activate 2>/dev/null || true
python scripts/index-to-parquet.py --catalog catalog-combined --output stac-api/index

# Step 2: Upload to S3
echo ""
echo ">>> Step 2: Uploading index to S3..."
aws s3 sync "${INDEX_DIR}" "s3://${BUCKET}/${INDEX_PREFIX}/" --delete

echo ""
echo "=== Sync Complete ==="
echo "API will auto-refresh within 60 seconds"
echo ""
echo "To force immediate refresh:"
echo "  curl -X POST https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/admin/refresh-index"
