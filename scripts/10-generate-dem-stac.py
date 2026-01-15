#!/usr/bin/env python3
"""
STAC Catalog Generator for DEM (Cloud Optimized GeoTIFF) Data

Generates STAC catalog, collection, and items with raster extension
for DEM products derived from point cloud data.

Usage:
    python 10-generate-dem-stac.py --data-dir ./local/dem --catalog-dir ./catalog-dem --base-url https://stac.example.com

    # Integrate with existing point cloud catalog
    python 10-generate-dem-stac.py --data-dir ./local/dem --catalog-dir ./catalog --base-url https://stac.example.com --existing-catalog
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pystac
from pystac import Asset, Catalog, Collection, Item, Link, Provider

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# STAC Extension URLs
RASTER_EXTENSION = "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
PROJ_EXTENSION = "https://stac-extensions.github.io/projection/v1.1.0/schema.json"
FILE_EXTENSION = "https://stac-extensions.github.io/file/v2.1.0/schema.json"
PROCESSING_EXTENSION = "https://stac-extensions.github.io/processing/v1.2.0/schema.json"

# COG media type
COG_MEDIA_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"

# DEM types descriptions
DEM_TYPE_INFO = {
    'dem': {
        'title': 'Digital Elevation Model',
        'description': 'Surface elevation model using maximum Z values from point cloud'
    },
    'dsm': {
        'title': 'Digital Surface Model',
        'description': 'Surface model including buildings and vegetation (first return maximum)'
    },
    'dtm': {
        'title': 'Digital Terrain Model',
        'description': 'Bare earth terrain model derived from ground-classified points'
    },
    'intensity': {
        'title': 'Intensity Raster',
        'description': 'LiDAR return intensity values rasterized to grid'
    },
    'density': {
        'title': 'Point Density',
        'description': 'Point count per grid cell from source point cloud'
    }
}

# Default provider
DEFAULT_PROVIDER = Provider(
    name="PLATEAU / GSI Japan",
    description="Japanese national mapping and 3D city model project - DEM products",
    roles=["producer", "processor"],
    url="https://www.mlit.go.jp/plateau/"
)


def load_dem_metadata_files(data_dir: Path) -> List[Dict[str, Any]]:
    """Load all DEM metadata JSON files from data directory."""
    # Look for DEM-specific metadata files
    patterns = ['*_dem.metadata.json', '*_dsm.metadata.json', '*_dtm.metadata.json',
                '*_intensity.metadata.json', '*_density.metadata.json']

    metadata_files = []
    for pattern in patterns:
        metadata_files.extend(data_dir.glob(pattern))

    # Also check for generic metadata files
    metadata_files.extend(data_dir.glob('*.metadata.json'))

    # Deduplicate
    metadata_files = list(set(metadata_files))
    metadata_files = sorted(metadata_files)

    logger.info(f"Found {len(metadata_files)} DEM metadata files")

    all_metadata = []
    for mf in metadata_files:
        try:
            with open(mf) as f:
                meta = json.load(f)
                # Only include DEM metadata (has dem_type field)
                if 'dem_type' in meta and 'error' not in meta:
                    meta['_metadata_file'] = str(mf)
                    all_metadata.append(meta)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse {mf.name}: {e}")

    return all_metadata


def extract_epsg_from_crs(crs_wkt: str) -> Optional[int]:
    """Extract EPSG code from CRS WKT string.

    For projected CRS, we want the EPSG of the projected system (the last one),
    not the base geographic CRS.
    """
    if not crs_wkt:
        return None

    import re

    # Find all EPSG IDs in the WKT
    # WKT2 format: ID["EPSG",6676]
    matches = re.findall(r'ID\["EPSG",(\d+)\]', crs_wkt)
    if matches:
        # Return the last one (the projected CRS EPSG, not the base geographic CRS)
        return int(matches[-1])

    # WKT1 format: AUTHORITY["EPSG","6676"]
    matches = re.findall(r'AUTHORITY\["EPSG","(\d+)"\]', crs_wkt)
    if matches:
        return int(matches[-1])

    return None


def convert_bbox_to_wgs84(
    bbox: List[float],
    source_epsg: int
) -> List[float]:
    """Convert bbox from source CRS to WGS84."""
    if source_epsg == 4326:
        return bbox[:4] if len(bbox) >= 4 else bbox

    try:
        from pyproj import Transformer, CRS

        source_crs = CRS.from_epsg(source_epsg)
        wgs84 = CRS.from_epsg(4326)

        # Create transformer
        transformer = Transformer.from_crs(source_crs, wgs84, always_xy=True)

        # Transform corners
        min_x, min_y = bbox[0], bbox[1]
        max_x, max_y = bbox[2], bbox[3]

        # Transform all four corners
        corners = [
            (min_x, min_y),
            (min_x, max_y),
            (max_x, min_y),
            (max_x, max_y)
        ]

        transformed = [transformer.transform(x, y) for x, y in corners]
        lons = [t[0] for t in transformed]
        lats = [t[1] for t in transformed]

        return [min(lons), min(lats), max(lons), max(lats)]

    except Exception as e:
        logger.warning(f"CRS conversion failed: {e}, using original bbox")
        return bbox[:4] if len(bbox) >= 4 else bbox


def create_dem_collection(
    collection_id: str,
    title: str,
    description: str,
    all_metadata: List[Dict[str, Any]],
    base_url: str
) -> Collection:
    """Create STAC collection for DEM data."""

    # Calculate collection extent from all items
    bboxes = [m.get('bbox', [0, 0, 0, 0]) for m in all_metadata]
    epsgs = [extract_epsg_from_crs(m.get('crs', '')) for m in all_metadata]
    epsgs = [e for e in epsgs if e is not None]

    collection_epsg = epsgs[0] if epsgs else 4326

    # Convert all bboxes to WGS84
    wgs84_bboxes = []
    for i, bbox in enumerate(bboxes):
        epsg = epsgs[i] if i < len(epsgs) and epsgs[i] else 4326
        wgs84_bbox = convert_bbox_to_wgs84(bbox, epsg)
        wgs84_bboxes.append(wgs84_bbox)

    # Calculate overall extent
    if wgs84_bboxes:
        extent_bbox = [
            min(b[0] for b in wgs84_bboxes),
            min(b[1] for b in wgs84_bboxes),
            max(b[2] for b in wgs84_bboxes),
            max(b[3] for b in wgs84_bboxes)
        ]
    else:
        extent_bbox = [-180, -90, 180, 90]

    spatial_extent = pystac.SpatialExtent(bboxes=[extent_bbox])
    temporal_extent = pystac.TemporalExtent(
        intervals=[[datetime.now(timezone.utc), None]]
    )
    extent = pystac.Extent(spatial=spatial_extent, temporal=temporal_extent)

    # Create collection
    collection = Collection(
        id=collection_id,
        title=title,
        description=description,
        license="proprietary",
        extent=extent,
        stac_extensions=[RASTER_EXTENSION, PROJ_EXTENSION],
        providers=[DEFAULT_PROVIDER]
    )

    # Add collection-level properties
    if collection_epsg:
        collection.extra_fields["proj:epsg"] = collection_epsg

    # Get unique DEM types
    dem_types = list(set(m.get('dem_type', 'dem') for m in all_metadata))
    resolutions = list(set(m.get('resolution', 1.0) for m in all_metadata))

    # Add summaries
    collection.extra_fields["summaries"] = {
        "dem_type": dem_types,
        "resolution": sorted(resolutions),
        "raster:bands": [{
            "data_type": "float32",
            "nodata": -9999.0,
            "unit": "meter"
        }]
    }

    if epsgs:
        collection.extra_fields["summaries"]["proj:epsg"] = list(set(epsgs))

    return collection


def create_item_from_dem_metadata(
    metadata: Dict[str, Any],
    base_url: str,
    collection_id: str
) -> Item:
    """Create STAC item from DEM metadata."""

    output_file = metadata.get('output_file', 'unknown.tif')
    source_file = metadata.get('source_file', 'unknown')
    dem_type = metadata.get('dem_type', 'dem')

    # Item ID from output filename
    item_id = Path(output_file).stem

    # Get EPSG from CRS
    crs_wkt = metadata.get('crs', '')
    epsg = extract_epsg_from_crs(crs_wkt) or 4326

    # Get bbox and convert to WGS84
    bbox = metadata.get('bbox', [0, 0, 0, 0])
    bbox_wgs84 = convert_bbox_to_wgs84(bbox, epsg)

    # Create geometry from bbox
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [bbox_wgs84[0], bbox_wgs84[1]],
            [bbox_wgs84[2], bbox_wgs84[1]],
            [bbox_wgs84[2], bbox_wgs84[3]],
            [bbox_wgs84[0], bbox_wgs84[3]],
            [bbox_wgs84[0], bbox_wgs84[1]]
        ]]
    }

    # Get DEM type info
    dem_info = DEM_TYPE_INFO.get(dem_type, DEM_TYPE_INFO['dem'])

    # Create item
    item = Item(
        id=item_id,
        geometry=geometry,
        bbox=bbox_wgs84,
        datetime=datetime.now(timezone.utc),
        properties={
            "title": f"{item_id} - {dem_info['title']}",
            "description": f"{dem_info['description']}. Derived from {source_file}",
            "dem_type": dem_type,
            "resolution": metadata.get('resolution', 1.0),
            "source_pointcloud": source_file
        },
        stac_extensions=[RASTER_EXTENSION, PROJ_EXTENSION, FILE_EXTENSION, PROCESSING_EXTENSION]
    )

    # Add projection extension properties
    item.properties["proj:epsg"] = epsg
    item.properties["proj:shape"] = [metadata.get('height', 0), metadata.get('width', 0)]

    # Add processing extension
    item.properties["processing:software"] = {
        "PDAL": "writers.gdal",
        "GDAL": "COG driver"
    }

    # Build asset URL
    asset_url = f"{base_url.rstrip('/')}/{collection_id}/{output_file}"

    # Create data asset with raster extension
    data_asset = Asset(
        href=asset_url,
        media_type=COG_MEDIA_TYPE,
        title=dem_info['title'],
        description=dem_info['description'],
        roles=["data"]
    )

    # Add raster extension properties
    data_asset.extra_fields["raster:bands"] = [{
        "nodata": metadata.get('nodata', -9999.0),
        "data_type": metadata.get('data_type', 'float32'),
        "unit": "meter" if dem_type in ['dem', 'dsm', 'dtm'] else None,
        "spatial_resolution": metadata.get('resolution', 1.0)
    }]

    # Add file extension
    data_asset.extra_fields["file:size"] = metadata.get('file_size_bytes', 0)

    item.add_asset("data", data_asset)

    # Add link to source point cloud if available
    # This would need the point cloud STAC URL
    if source_file:
        source_stem = Path(source_file).stem.replace('.copc', '')
        item.add_link(Link(
            rel="derived_from",
            target=f"../pointcloud/{source_stem}.json",
            media_type="application/geo+json",
            title=f"Source point cloud: {source_file}"
        ))

    return item


def create_catalog(
    catalog_id: str,
    title: str,
    description: str
) -> Catalog:
    """Create root STAC catalog."""
    return Catalog(
        id=catalog_id,
        title=title,
        description=description,
        catalog_type=pystac.CatalogType.RELATIVE_PUBLISHED
    )


def save_catalog(
    catalog: Catalog,
    catalog_dir: Path
) -> None:
    """Save catalog with all items to disk."""
    catalog_dir.mkdir(parents=True, exist_ok=True)
    catalog.normalize_hrefs(str(catalog_dir))
    catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
    logger.info(f"Catalog saved to: {catalog_dir}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate STAC catalog for DEM (COG) data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --data-dir ./local/dem --catalog-dir ./catalog-dem --base-url https://stac.example.com
  %(prog)s --data-dir ./local/dem --catalog-dir ./catalog-dem --base-url https://stac.example.com --collection-id fujisan-dem
        """
    )

    parser.add_argument(
        '--data-dir', '-d',
        type=Path,
        required=True,
        help='Directory containing DEM files and metadata'
    )

    parser.add_argument(
        '--catalog-dir', '-c',
        type=Path,
        required=True,
        help='Output directory for STAC catalog'
    )

    parser.add_argument(
        '--base-url', '-u',
        type=str,
        required=True,
        help='Base URL for COG assets (e.g., https://stac.example.com)'
    )

    parser.add_argument(
        '--catalog-id',
        type=str,
        default='dem-catalog',
        help='Catalog ID (default: dem-catalog)'
    )

    parser.add_argument(
        '--collection-id',
        type=str,
        default='dem-products',
        help='Collection ID (default: dem-products)'
    )

    parser.add_argument(
        '--title',
        type=str,
        default='DEM Products',
        help='Collection title'
    )

    parser.add_argument(
        '--description',
        type=str,
        default='Digital Elevation Models derived from LiDAR point clouds',
        help='Collection description'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load metadata
    all_metadata = load_dem_metadata_files(args.data_dir)

    if not all_metadata:
        logger.error(f"No DEM metadata found in: {args.data_dir}")
        sys.exit(1)

    logger.info(f"Found {len(all_metadata)} DEM products")

    # Create catalog
    catalog = create_catalog(
        catalog_id=args.catalog_id,
        title=f"{args.title} STAC Catalog",
        description=f"STAC catalog containing {args.description}"
    )

    # Create collection
    collection = create_dem_collection(
        collection_id=args.collection_id,
        title=args.title,
        description=args.description,
        all_metadata=all_metadata,
        base_url=args.base_url
    )

    # Create items
    items_created = 0
    for metadata in all_metadata:
        try:
            item = create_item_from_dem_metadata(
                metadata,
                args.base_url,
                args.collection_id
            )
            collection.add_item(item)
            items_created += 1
            logger.debug(f"Created item: {item.id}")
        except Exception as e:
            logger.error(f"Failed to create item from {metadata.get('output_file', 'unknown')}: {e}")

    # Add collection to catalog
    catalog.add_child(collection)

    # Save catalog
    save_catalog(catalog, args.catalog_dir)

    logger.info("=" * 60)
    logger.info(f"STAC catalog generation complete!")
    logger.info(f"  Items created: {items_created}")
    logger.info(f"  Collection: {args.collection_id}")
    logger.info(f"  Catalog: {args.catalog_dir}")

    sys.exit(0)


if __name__ == '__main__':
    main()
