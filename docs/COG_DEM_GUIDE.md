# Cloud Optimized GeoTIFF (COG) DEM Guide

This guide explains how to generate DEM products from point cloud data and serve them via TiTiler.

## Quick Start

### 1. Generate DEM from COPC

```bash
# Single file
python scripts/09-generate-dem.py \
  --input-file ./local/output/sample.copc.laz \
  --output-dir ./local/dem \
  --resolution 1.0

# Batch processing
python scripts/09-generate-dem.py \
  --input-dir ./local/output \
  --output-dir ./local/dem \
  --resolution 1.0 \
  --dem-type dem
```

### 2. Generate STAC Catalog

```bash
python scripts/10-generate-dem-stac.py \
  --data-dir ./local/dem \
  --catalog-dir ./catalog-dem \
  --base-url https://stac.uixai.org \
  --collection-id fujisan-dem \
  --title "Fujisan DEM Products"
```

### 3. Start TiTiler (requires Docker)

```bash
./scripts/11-start-titiler.sh start
./scripts/11-start-titiler.sh test
```

### 4. View in Browser

Open `cog-viewer/index.html` in a browser.

---

## DEM Types

| Type | Description | Use Case |
|------|-------------|----------|
| `dem` | Digital Elevation Model (max Z) | General terrain visualization |
| `dsm` | Digital Surface Model | Buildings, vegetation included |
| `dtm` | Digital Terrain Model | Bare earth only (requires ground classification) |
| `intensity` | LiDAR intensity raster | Surface reflectance analysis |
| `density` | Point density map | Data quality assessment |

---

## Resolution Guidelines

| Resolution | Use Case | File Size (1km²) |
|------------|----------|------------------|
| 0.5m | Engineering, urban modeling | ~8 MB |
| 1.0m | Standard (USGS QL2) | ~2 MB |
| 2.0m | Regional analysis | ~500 KB |
| 5.0m | Large area terrain | ~80 KB |

---

## API Endpoints (TiTiler)

### COG Info
```
GET /cog/info?url=<COG_URL>
```

### Tile Request
```
GET /cog/tiles/{z}/{x}/{y}.png?url=<COG_URL>&colormap_name=terrain
```

### Preview
```
GET /cog/preview.png?url=<COG_URL>&max_size=512&colormap_name=terrain
```

### Statistics
```
GET /cog/statistics?url=<COG_URL>
```

### Available Colormaps
- `terrain` - Elevation visualization
- `viridis` - Scientific data
- `plasma` - High contrast
- `inferno` - Heat map style
- `rainbow` - Classic rainbow

---

## STAC Integration

### Item Structure

Each DEM has a STAC Item with:
- `raster:bands` - Band metadata (nodata, data_type, unit, resolution)
- `proj:epsg` - Coordinate reference system
- `processing:software` - Tools used for generation
- `derived_from` link - Reference to source point cloud

### Example Asset

```json
{
  "data": {
    "href": "https://stac.uixai.org/dem/08LF6330_dem.tif",
    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
    "raster:bands": [{
      "nodata": -9999.0,
      "data_type": "float32",
      "unit": "meter",
      "spatial_resolution": 1.0
    }]
  }
}
```

---

## Workflow Diagram

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  LAS/LAZ     │────▶│    COPC      │────▶│   COG DEM    │
│  (raw data)  │     │  (indexed)   │     │  (raster)    │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │
       │                    │                    │
       ▼                    ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ 01-prepare   │     │ 02-generate  │     │ 10-generate  │
│ -data.py     │     │ -stac.py     │     │ -dem-stac.py │
└──────────────┘     └──────────────┘     └──────────────┘
                                                │
                                                ▼
                                         ┌──────────────┐
                                         │   TiTiler    │
                                         │  (tiles API) │
                                         └──────────────┘
                                                │
                                                ▼
                                         ┌──────────────┐
                                         │  COG Viewer  │
                                         │  (browser)   │
                                         └──────────────┘
```

---

## Compression Options

| Method | Best For | Compression Ratio |
|--------|----------|-------------------|
| `deflate` | General use (default) | Good |
| `lzw` | Fast decompression | Moderate |
| `zstd` | Maximum compression | Excellent |

---

## Troubleshooting

### COG Validation Failed
```bash
# Check if file is valid COG
gdalinfo -json your_file.tif | grep -A5 "layout"

# Re-convert to COG
gdal_translate input.tif output_cog.tif -of COG -co COMPRESS=DEFLATE
```

### TiTiler Connection Refused
```bash
# Check if Docker is running
docker ps

# Check TiTiler logs
./scripts/11-start-titiler.sh logs
```

### CORS Issues
Ensure TiTiler is started with CORS enabled (default in docker-compose.yml).

---

## Performance Tips

1. **Use appropriate resolution** - Don't oversample sparse point clouds
2. **Enable HTTP/2** - Better tile loading performance
3. **Use CDN** - Cache tiles at edge locations
4. **Compress COGs** - DEFLATE or ZSTD for best web performance

---

## Manual DEM Workflow (PDAL + GDAL)

This section documents the manual workflow for generating DEM products with Shaded Relief visualization and 3D terrain viewing.

### 1. Point Cloud → DEM (PDAL)

Create a pipeline JSON file:

```json
{
  "pipeline": [
    {"type": "readers.copc", "filename": "source.copc.laz"},
    {"type": "filters.range", "limits": "Classification![7:7]"},
    {"type": "writers.gdal",
     "filename": "output_dem.tif",
     "resolution": 1.0,
     "output_type": "mean",
     "data_type": "float32",
     "nodata": -9999}
  ]
}
```

Run the pipeline:
```bash
pdal pipeline dem_pipeline.json
```

**Parameters:**
- `Classification![7:7]` - Excludes noise points (class 7)
- `resolution: 1.0` - 1 meter resolution
- `output_type: mean` - Average Z value per cell
- `nodata: -9999` - Standard nodata value

### 2. Shaded Relief COG Generation (GDAL)

#### Step 1: Create Color Ramp
```bash
cat > color_ramp.txt << 'EOF'
nv 0 0 0 0
2486 34 139 34
2600 144 238 144
2800 255 255 0
3000 255 165 0
3200 255 69 0
3400 220 20 60
3600 139 0 0
3757 255 255 255
EOF
```

**Note:** Adjust elevation values to match your data range. Use `nv` (nodata value) as first entry for transparency.

#### Step 2: Generate Color Relief with Alpha
```bash
gdaldem color-relief dem.tif color_ramp.txt colorrelief.tif -alpha
```

#### Step 3: Generate Hillshade
```bash
gdaldem hillshade dem.tif hillshade.tif -z 1.5 -compute_edges
```

#### Step 4: Blend Hillshade with Color Relief
```bash
# Blend each RGB band
gdal_calc.py -A colorrelief.tif --A_band=1 -B hillshade.tif \
  --calc="numpy.clip(A * (0.3 + B/255.0 * 0.7), 0, 255)" \
  --outfile=blend_r.tif --type=Byte --quiet

gdal_calc.py -A colorrelief.tif --A_band=2 -B hillshade.tif \
  --calc="numpy.clip(A * (0.3 + B/255.0 * 0.7), 0, 255)" \
  --outfile=blend_g.tif --type=Byte --quiet

gdal_calc.py -A colorrelief.tif --A_band=3 -B hillshade.tif \
  --calc="numpy.clip(A * (0.3 + B/255.0 * 0.7), 0, 255)" \
  --outfile=blend_b.tif --type=Byte --quiet

# Extract alpha band
gdal_translate -b 4 colorrelief.tif alpha.tif -q

# Merge into RGBA
gdalbuildvrt -separate visual.vrt blend_r.tif blend_g.tif blend_b.tif alpha.tif
gdal_translate visual.vrt visual_rgba.tif
```

#### Step 5: Convert to WGS84 COG
```bash
# Reproject to WGS84
gdalwarp -t_srs EPSG:4326 -r bilinear visual_rgba.tif visual_wgs84.tif

# Convert to COG
gdal_translate -of COG -co COMPRESS=DEFLATE visual_wgs84.tif dem_visual.cog.tif
```

#### Step 6: Elevation COG
```bash
gdalwarp -t_srs EPSG:4326 -r bilinear dem.tif dem_wgs84.tif
gdal_translate -of COG -co COMPRESS=DEFLATE dem_wgs84.tif dem.cog.tif
```

### 3. STAC Item Structure

```json
{
  "type": "Feature",
  "stac_version": "1.1.0",
  "stac_extensions": [
    "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
    "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
    "https://stac-extensions.github.io/file/v2.1.0/schema.json"
  ],
  "id": "my-dem",
  "properties": {
    "title": "My DEM",
    "datetime": "2025-12-16T00:00:00Z",
    "proj:epsg": 4326,
    "resolution_meters": 1.0
  },
  "assets": {
    "visual": {
      "href": "https://example.com/data/dem_visual.cog.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "title": "Shaded Relief (COG)",
      "roles": ["visual", "overview"]
    },
    "elevation": {
      "href": "https://example.com/data/dem.cog.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "title": "Elevation Data (COG)",
      "raster:bands": [{
        "data_type": "float32",
        "nodata": -9999,
        "unit": "meter",
        "statistics": {"minimum": 100, "maximum": 500}
      }],
      "roles": ["data", "elevation"]
    }
  }
}
```

---

## 3D Terrain Viewer

The terrain viewer is a standalone HTML application for visualizing DEM data in 3D.

### Technology Stack

| Component | Library | Version |
|-----------|---------|---------|
| 3D Rendering | Three.js | 0.160.0 |
| Camera Control | OrbitControls | Three.js addon |
| COG Loading | GeoTIFF.js | 2.0.7 |

### Features

- **Vertical Exaggeration**: 0.5x - 10x adjustable
- **Color Modes**: Elevation Colors / Grayscale / Hillshade
- **Light Direction**: 0° - 360° adjustable
- **Wireframe Mode**: Toggle mesh wireframe
- **Auto Subsampling**: Downsamples to 512x512 max for performance

### URL Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `dem` | DEM COG URL | `?dem=https://example.com/dem.cog.tif` |
| `url` | Alias for dem | `?url=https://example.com/dem.cog.tif` |

### Deployment

The viewer is a single HTML file deployed to S3:
- **S3 Path**: `s3://stac-uixai-catalog/terrain/index.html`
- **URL**: `https://stac.uixai.org/terrain/index.html`

### Rendering Pipeline

```
COG URL
   │
   ▼
GeoTIFF.fromUrl()
   │
   ▼
image.readRasters()
   │
   ▼
PlaneGeometry (400x400 units)
   │
   ▼
Set vertex heights (elevation * verticalScale * exaggeration)
   │
   ▼
Apply vertex colors (elevation → color)
   │
   ▼
MeshPhongMaterial
   │
   ▼
THREE.Mesh → Scene → Render
```

### Vertical Scale Calculation

The viewer calculates proper vertical scale based on real-world proportions:

```javascript
// If coordinates are in degrees, convert to meters
const metersPerDegLon = 111320 * Math.cos(latMid * Math.PI / 180);
const metersPerDegLat = 110540;
const realExtent = Math.max(extentX * metersPerDegLon, extentY * metersPerDegLat);

// Calculate scale factor
const geometryWidth = 400;
const verticalScale = geometryWidth / realExtent;

// Apply to vertices
positions[vertexIndex + 2] = (elevation - minElevation) * verticalScale * exaggeration;
```

---

## STAC Browser Integration

### DEM Item Detection

DEM items are detected by checking for COG assets with `elevation` or `visual` roles:

```javascript
// Map.vue - isDemItem computed property
const isCog = asset.type === 'image/tiff; application=geotiff; profile=cloud-optimized';
const hasElevationRole = Array.isArray(asset.roles) && asset.roles.includes('elevation');
const hasVisualRole = Array.isArray(asset.roles) && asset.roles.includes('visual');
return isCog && (hasElevationRole || hasVisualRole);
```

### Performance Optimization

DEM items skip the heavy `stacLayer()` call and display a simple bbox polygon instead:

```javascript
// Map.vue - showStacLayer method
if (this.isDemItem && this.stac.isItem()) {
  const geojsonBbox = {
    type: 'Feature',
    geometry: {
      type: 'Polygon',
      coordinates: [[
        [bbox[0], bbox[1]], [bbox[2], bbox[1]],
        [bbox[2], bbox[3]], [bbox[0], bbox[3]],
        [bbox[0], bbox[1]]
      ]]
    }
  };
  this.stacLayer = L.geoJSON(geojsonBbox, {
    style: { color: '#3388ff', weight: 2, fillOpacity: 0.1 }
  });
  return;  // Skip stacLayer() call
}
```

### "Show on map" Button Hidden

DEM assets hide the "Show on map" dropdown option since 3D viewing is preferred:

```javascript
// HrefActions.vue - isDemCogAsset computed property
isDemCogAsset() {
  const isCog = this.data.type === 'image/tiff; application=geotiff; profile=cloud-optimized';
  const roles = this.data.roles;
  return isCog && (roles.includes('elevation') || roles.includes('visual'));
}
```

### "View in 3D" Button

Added to StacHeader.vue for DEM items with a link to the terrain viewer:

```javascript
// StacHeader.vue
terrainViewerUrl() {
  const params = new URLSearchParams();
  params.set('dem', this.demAssetUrl);
  if (this.data && this.data.bbox) {
    params.set('bbox', this.data.bbox.join(','));
  }
  return '/terrain/index.html?' + params.toString();
}
```
