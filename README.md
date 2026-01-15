# STAC COPC Catalog

Static STAC Catalog for Cloud Optimized Point Cloud (COPC) data, hosted on AWS S3 with CloudFront.

## Features

- **COPC Format**: Cloud Optimized Point Cloud for efficient streaming
- **STAC Compliant**: Full point-cloud extension support
- **Static Hosting**: No servers required, just S3 + CloudFront
- **STAC Browser**: Web UI for browsing the catalog
- **Potree Viewer**: 3D point cloud visualization with bbox clipping
- **Selector UI**: OpenLayers map with spatial query and API code generation
- **Japanese CRS Support**: JGD2011 (EPSG:6669-6687) with proj4js transformation
- **Jupyter Notebook**: One-click "Open in Colab" integration

## Quick Start

```bash
# 1. Install dependencies
./scripts/install-deps.sh

# 2. Configure environment
cp .env.example .env
# Edit .env with your AWS settings

# 3. Prepare data (convert LAS/LAZ to COPC)
python scripts/01-prepare-data.py \
    --input-dir ./local/input \
    --output-dir ./local/output

# 4. Generate STAC catalog
python scripts/02-generate-stac.py \
    --data-dir ./local/output \
    --catalog-dir ./catalog \
    --base-url https://your-domain.com

# 5. Validate
python scripts/04-validate.py --catalog-dir ./catalog

# 6. Deploy to AWS
./scripts/03-deploy-aws.sh --create

# 7. Build STAC Browser (optional)
./scripts/05-build-browser.sh
./scripts/03-deploy-aws.sh --update
```

## Project Structure

```
Study STAC/
├── scripts/
│   ├── install-deps.sh        # Install PDAL + Python dependencies
│   ├── 01-prepare-data.py     # LAS/LAZ → COPC conversion
│   ├── 02-generate-stac.py    # Generate STAC catalog
│   ├── 03-deploy-aws.sh       # Deploy to AWS (S3 + CloudFront)
│   ├── 04-validate.py         # Validate STAC catalog
│   └── 05-build-browser.sh    # Build STAC Browser
├── config/
│   ├── aws/                   # AWS configuration templates
│   │   ├── bucket-policy.json
│   │   ├── cors-config.json
│   │   ├── lifecycle-rules.json
│   │   └── cloudfront-config.json
│   └── pdal/
│       └── las-to-copc.json   # PDAL pipeline template
├── catalog/                   # Generated STAC catalog (git tracked)
├── local/                     # Working directories (git ignored)
│   ├── input/                 # Source LAS/LAZ files
│   └── output/                # Generated COPC + metadata
├── stac-browser/              # STAC Browser build
├── potree-viewer/             # Potree 3D viewer & Selector UI
│   └── dist/
│       ├── index.html         # Potree viewer with bbox support
│       └── selector.html      # OpenLayers spatial query UI
└── docs/                      # Documentation (architecture, operations, API)
    ├── architecture.md
    ├── copc-conversion.md
    ├── copc-point-cloud-selector.md
    ├── API_COORDINATE_SYSTEM.md  # Coordinate system & bbox API
    ├── COG_DEM_GUIDE.md
    ├── CKAN_INTEGRATION_PATTERN.md
    └── COST_OPERATIONS.md
```

## Prerequisites

- **Python 3.9+**
- **PDAL 2.5+** (via conda or brew)
- **AWS CLI** configured with credentials
- **Node.js 18+** (for STAC Browser)

### Installing PDAL

```bash
# Option 1: Conda (recommended)
conda install -c conda-forge pdal python-pdal

# Option 2: Homebrew (macOS)
brew install pdal
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# AWS
AWS_REGION=ap-northeast-1
STAC_BUCKET_NAME=stac-copc-catalog

# Domain (optional, for custom domain)
STAC_DOMAIN=stac.example.com
ACM_CERTIFICATE_ARN=arn:aws:acm:us-east-1:...

# STAC
STAC_BASE_URL=https://stac.example.com
STAC_COLLECTION_ID=pointcloud-jgd2011
```

## Workflow

### 1. Data Preparation

Convert LAS/LAZ files to COPC format with metadata extraction:

```bash
# Single file
python scripts/01-prepare-data.py \
    --input-file ./data/sample.las \
    --output-dir ./local/output

# Directory
python scripts/01-prepare-data.py \
    --input-dir ./local/input \
    --output-dir ./local/output \
    --target-crs EPSG:6677  # Optional reprojection
```

Output:
- `*.copc.laz` - Cloud Optimized Point Cloud files
- `*.metadata.json` - Processing metadata (stats, bbox, schema)
- `processing_summary.json` - Overall summary

### 2. STAC Generation

Generate STAC catalog from processed data:

```bash
python scripts/02-generate-stac.py \
    --data-dir ./local/output \
    --catalog-dir ./catalog \
    --base-url https://stac.example.com \
    --collection-id pointcloud-jgd2011
```

### 3. Validation

Validate the generated catalog:

```bash
# Basic validation
python scripts/04-validate.py --catalog-dir ./catalog

# With URL checks
python scripts/04-validate.py --catalog-dir ./catalog --check-urls

# With PDAL compatibility test
python scripts/04-validate.py --catalog-dir ./catalog \
    --test-pdal https://stac.example.com/items/sample.json
```

### 4. Deployment

Deploy to AWS:

```bash
# First time: create all infrastructure
./scripts/03-deploy-aws.sh --create

# Update content
./scripts/03-deploy-aws.sh --update

# Just sync files
./scripts/03-deploy-aws.sh --sync-only

# Check status
./scripts/03-deploy-aws.sh --status
```

### 5. STAC Browser

Build and deploy the web frontend:

```bash
./scripts/05-build-browser.sh
./scripts/03-deploy-aws.sh --update
```

## Accessing the Catalog

### URLs

After deployment:
- **Catalog**: `https://your-domain.com/catalog.json`
- **Collection**: `https://your-domain.com/collections/pointcloud-jgd2011/collection.json`
- **Items**: `https://your-domain.com/collections/pointcloud-jgd2011/items/*.json`
- **Data**: `https://your-domain.com/data/*.copc.laz`
- **Browser**: `https://your-domain.com/browser/`
- **Selector**: `https://your-domain.com/potree/selector.html` (spatial query UI)
- **Potree Viewer**: `https://your-domain.com/potree/index.html`

### Python (pystac-client)

```python
from pystac_client import Client

catalog = Client.open("https://stac.example.com/catalog.json")

for collection in catalog.get_collections():
    print(collection.id, collection.title)

for item in catalog.get_items():
    print(item.id)
    print(f"  Points: {item.properties['pc:count']:,}")
    print(f"  URL: {item.assets['data'].href}")
```

### PDAL

```bash
# Read via STAC
pdal info \
    --readers.stac.filename="https://stac.example.com/items/sample.json" \
    --readers.stac.asset_names="data"

# Pipeline
pdal pipeline <<EOF
{
    "pipeline": [
        {
            "type": "readers.stac",
            "filename": "https://stac.example.com/items/sample.json",
            "asset_names": ["data"]
        },
        {
            "type": "filters.stats"
        }
    ]
}
EOF
```

### QGIS

1. Install STAC plugin
2. Add catalog URL: `https://stac.example.com/catalog.json`
3. Browse collections and items
4. Load COPC layers directly

### Spatial Query (bbox)

Use native coordinate system for higher precision:

```bash
# PDAL with bbox (efficient - only downloads bbox region)
pdal pipeline <<EOF
{
  "pipeline": [
    {
      "type": "readers.copc",
      "filename": "https://stac.example.com/data/sample.copc.laz",
      "bounds": "([12684, 13089], [-36999, -36836])"
    },
    {
      "type": "writers.las",
      "filename": "subset.las",
      "a_srs": "EPSG:6676"
    }
  ]
}
EOF
```

See [docs/API_COORDINATE_SYSTEM.md](docs/API_COORDINATE_SYSTEM.md) for full API documentation.

## Web UI

### Selector (Spatial Query)

Interactive map for selecting point cloud regions:

1. Open `https://your-domain.com/potree/selector.html`
2. Select a dataset from the sidebar
3. Draw a bounding box on the map
4. View bbox in both WGS84 and native CRS
5. Copy API code (Python, PDAL, JavaScript)
6. Click "Open in Colab" to generate Jupyter notebook

Features:
- **OpenLayers** map with satellite imagery
- **proj4js** coordinate transformation (WGS84 ↔ JGD2011)
- **Dual coordinate display** - shows bbox in both coordinate systems
- **API code generation** - ready-to-use code snippets
- **Jupyter notebook export** - one-click Colab integration

### Potree Viewer

3D point cloud visualization with bbox clipping:

```
https://your-domain.com/potree/index.html?files=<COPC_URL>&bbox=<minX,minY,maxX,maxY>
```

Parameters:
- `files`: COPC file URL (comma-separated for multiple)
- `bbox`: Bounding box (auto-detects native vs WGS84)
- `pointSize`: Point size (default: 1)
- `budget`: Point budget (default: 5,000,000)
- `c`: Color mode (rgba, elevation, intensity)

## Point Cloud Extension

Each STAC item includes:

```json
{
  "pc:count": 12345678,
  "pc:type": "lidar",
  "pc:encoding": "application/vnd.laszip+copc",
  "pc:density": 15.2,
  "pc:schemas": [
    {"name": "X", "size": 8, "type": "floating"},
    {"name": "Y", "size": 8, "type": "floating"},
    {"name": "Z", "size": 8, "type": "floating"}
  ],
  "pc:statistics": [
    {"name": "Z", "min": 0, "max": 100, "mean": 45.2}
  ],
  "proj:epsg": 6677,
  "proj:bbox": [minx, miny, minz, maxx, maxy, maxz]
}
```

## Cost Estimate

Monthly cost for 100 GB of data with moderate traffic:

| Component | Cost |
|-----------|------|
| S3 Storage | ~$2.50 |
| CloudFront | ~$8-15 |
| Route 53 | ~$0.50 |
| **Total** | **~$12-20/month** |

See [docs/COST_OPERATIONS.md](docs/COST_OPERATIONS.md) for details.

## License

MIT License - see [LICENSE](LICENSE) for details.

## References

- [STAC Specification](https://stacspec.org/)
- [Point Cloud Extension](https://github.com/stac-extensions/pointcloud)
- [COPC Specification](https://copc.io/)
- [PDAL Documentation](https://pdal.io/)
- [STAC Browser](https://github.com/radiantearth/stac-browser)
