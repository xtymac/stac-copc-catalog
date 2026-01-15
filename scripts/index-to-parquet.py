#!/usr/bin/env python3
"""
STAC Catalog to GeoParquet Indexer

Converts static STAC catalog JSON files to GeoParquet format for use with
stac-fastapi-geoparquet. This enables dynamic /search API without a database.

Usage:
    python scripts/index-to-parquet.py [--catalog PATH] [--output DIR]

Example:
    python scripts/index-to-parquet.py --catalog catalog-combined --output stac-api/index
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry import shape, box

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_json(path: Path) -> Dict[str, Any]:
    """Load a JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def collect_items(catalog_dir: Path) -> tuple[List[Dict], List[Dict]]:
    """
    Recursively collect all STAC items and collections from a catalog directory.

    Returns:
        Tuple of (items, collections)
    """
    items = []
    collections = []

    # Find all JSON files
    for json_file in catalog_dir.rglob('*.json'):
        try:
            data = load_json(json_file)

            if data.get('type') == 'Feature':
                # This is a STAC Item
                # Add collection reference if not present
                if 'collection' not in data:
                    # Try to infer from parent directory
                    collection_file = json_file.parent.parent / 'collection.json'
                    if collection_file.exists():
                        collection_data = load_json(collection_file)
                        data['collection'] = collection_data.get('id')

                items.append(data)
                logger.info(f"Found item: {data.get('id')} in {json_file}")

            elif data.get('type') == 'Collection':
                collections.append(data)
                logger.info(f"Found collection: {data.get('id')} in {json_file}")

        except Exception as e:
            logger.warning(f"Error processing {json_file}: {e}")

    return items, collections


def flatten_properties(item: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten nested properties for Parquet storage."""
    flat = {}

    # Basic fields
    flat['id'] = item.get('id')
    flat['stac_version'] = item.get('stac_version', '1.0.0')
    flat['collection'] = item.get('collection')

    # Geometry and bbox
    if 'geometry' in item:
        flat['geometry'] = shape(item['geometry'])
    elif 'bbox' in item:
        bbox = item['bbox']
        flat['geometry'] = box(bbox[0], bbox[1], bbox[2], bbox[3])

    if 'bbox' in item:
        flat['bbox'] = item['bbox']

    # Properties
    props = item.get('properties', {})
    flat['datetime'] = props.get('datetime')
    flat['title'] = props.get('title', item.get('id'))

    # Point cloud extension properties
    flat['pc_count'] = props.get('pc:count')
    flat['pc_type'] = props.get('pc:type')
    flat['pc_encoding'] = props.get('pc:encoding')

    # Projection extension properties
    flat['proj_epsg'] = props.get('proj:epsg')
    if 'proj:bbox' in props:
        flat['proj_bbox'] = props['proj:bbox']

    # Assets - store as JSON string
    if 'assets' in item:
        flat['assets'] = json.dumps(item['assets'])

    # Links - store as JSON string
    if 'links' in item:
        flat['links'] = json.dumps(item['links'])

    # STAC extensions
    if 'stac_extensions' in item:
        flat['stac_extensions'] = item['stac_extensions']

    # Store full item as JSON for complete access
    flat['item_json'] = json.dumps(item)

    return flat


def flatten_collection(collection: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten collection for Parquet storage."""
    flat = {}

    flat['id'] = collection.get('id')
    flat['stac_version'] = collection.get('stac_version', '1.0.0')
    flat['title'] = collection.get('title', collection.get('id'))
    flat['description'] = collection.get('description', '')
    flat['license'] = collection.get('license', 'proprietary')

    # Extent
    extent = collection.get('extent', {})
    spatial = extent.get('spatial', {})
    temporal = extent.get('temporal', {})

    if 'bbox' in spatial and spatial['bbox']:
        bbox = spatial['bbox'][0]  # First bbox
        flat['bbox'] = bbox
        flat['geometry'] = box(bbox[0], bbox[1], bbox[2], bbox[3])

    if 'interval' in temporal and temporal['interval']:
        interval = temporal['interval'][0]
        flat['start_datetime'] = interval[0]
        flat['end_datetime'] = interval[1]

    # STAC extensions
    if 'stac_extensions' in collection:
        flat['stac_extensions'] = collection['stac_extensions']

    # Store summaries as JSON
    if 'summaries' in collection:
        flat['summaries'] = json.dumps(collection['summaries'])

    # Store providers as JSON
    if 'providers' in collection:
        flat['providers'] = json.dumps(collection['providers'])

    # Store links as JSON
    if 'links' in collection:
        flat['links'] = json.dumps(collection['links'])

    # Store full collection as JSON
    flat['collection_json'] = json.dumps(collection)

    return flat


def items_to_geoparquet(items: List[Dict], output_path: Path) -> None:
    """Convert items to GeoParquet format."""
    if not items:
        logger.warning("No items to convert")
        return

    # Flatten all items
    flat_items = [flatten_properties(item) for item in items]

    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(flat_items, crs="EPSG:4326")

    # Ensure datetime column is proper type
    if 'datetime' in gdf.columns:
        gdf['datetime'] = pd.to_datetime(gdf['datetime'], utc=True, errors='coerce')

    # Sort by datetime (desc) then id (asc) for stable ordering
    gdf = gdf.sort_values(
        by=['datetime', 'id'],
        ascending=[False, True],
        na_position='last'
    )

    # Write to GeoParquet
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(output_path, index=False)

    logger.info(f"Wrote {len(items)} items to {output_path}")
    logger.info(f"File size: {output_path.stat().st_size / 1024:.1f} KB")


def collections_to_geoparquet(collections: List[Dict], output_path: Path) -> None:
    """Convert collections to GeoParquet format."""
    if not collections:
        logger.warning("No collections to convert")
        return

    # Flatten all collections
    flat_collections = [flatten_collection(c) for c in collections]

    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(flat_collections, crs="EPSG:4326")

    # Write to GeoParquet
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(output_path, index=False)

    logger.info(f"Wrote {len(collections)} collections to {output_path}")
    logger.info(f"File size: {output_path.stat().st_size / 1024:.1f} KB")


def create_catalog_metadata(
    catalog_dir: Path,
    items_count: int,
    collections_count: int,
    output_path: Path
) -> None:
    """Create catalog metadata JSON file."""
    # Try to read root catalog
    catalog_file = catalog_dir / 'catalog.json'
    if catalog_file.exists():
        catalog = load_json(catalog_file)
    else:
        catalog = {
            'id': 'stac-catalog',
            'title': 'STAC Catalog',
            'description': 'Auto-indexed STAC catalog'
        }

    metadata = {
        'catalog_id': catalog.get('id'),
        'catalog_title': catalog.get('title'),
        'catalog_description': catalog.get('description'),
        'stac_version': catalog.get('stac_version', '1.0.0'),
        'indexed_at': datetime.utcnow().isoformat() + 'Z',
        'items_count': items_count,
        'collections_count': collections_count,
        'index_version': '1.0.0'
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    logger.info(f"Wrote catalog metadata to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Convert STAC catalog to GeoParquet index'
    )
    parser.add_argument(
        '--catalog',
        type=Path,
        default=Path('catalog-combined'),
        help='Path to STAC catalog directory (default: catalog-combined)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('stac-api/index'),
        help='Output directory for Parquet files (default: stac-api/index)'
    )
    parser.add_argument(
        '--upload-s3',
        type=str,
        default=None,
        help='S3 bucket to upload index files (e.g., s3://my-bucket/index/)'
    )

    args = parser.parse_args()

    # Resolve paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent

    catalog_dir = args.catalog
    if not catalog_dir.is_absolute():
        catalog_dir = project_dir / catalog_dir

    output_dir = args.output
    if not output_dir.is_absolute():
        output_dir = project_dir / output_dir

    logger.info(f"Processing catalog: {catalog_dir}")
    logger.info(f"Output directory: {output_dir}")

    # Collect items and collections
    items, collections = collect_items(catalog_dir)

    logger.info(f"Found {len(items)} items and {len(collections)} collections")

    # Convert to GeoParquet
    items_to_geoparquet(items, output_dir / 'items.parquet')
    collections_to_geoparquet(collections, output_dir / 'collections.parquet')

    # Create metadata
    create_catalog_metadata(
        catalog_dir,
        len(items),
        len(collections),
        output_dir / 'catalog_metadata.json'
    )

    # Upload to S3 if specified
    if args.upload_s3:
        import boto3
        s3 = boto3.client('s3')

        # Parse S3 URL
        s3_url = args.upload_s3.rstrip('/')
        if s3_url.startswith('s3://'):
            s3_url = s3_url[5:]
        bucket, prefix = s3_url.split('/', 1) if '/' in s3_url else (s3_url, '')

        # Upload files
        for file in output_dir.glob('*'):
            if file.is_file():
                key = f"{prefix}/{file.name}" if prefix else file.name
                logger.info(f"Uploading {file.name} to s3://{bucket}/{key}")
                s3.upload_file(str(file), bucket, key)

        logger.info(f"Uploaded index files to s3://{bucket}/{prefix}")

    logger.info("Indexing complete!")

    # Print summary
    print("\n" + "=" * 60)
    print("INDEX SUMMARY")
    print("=" * 60)
    print(f"Items indexed:       {len(items)}")
    print(f"Collections indexed: {len(collections)}")
    print(f"Output directory:    {output_dir}")
    print("\nFiles created:")
    for file in sorted(output_dir.glob('*')):
        size = file.stat().st_size
        print(f"  - {file.name}: {size / 1024:.1f} KB")
    print("=" * 60)


if __name__ == '__main__':
    main()
