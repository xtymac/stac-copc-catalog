"""
STAC Catalog Indexer Lambda

Triggered by S3 events when STAC catalog files are modified.
Regenerates Parquet index and uploads to S3.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry import shape
from shapely import wkt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

s3 = boto3.client('s3')

# Configuration
CATALOG_BUCKET = os.environ.get('CATALOG_BUCKET', 'stac-uixai-catalog')
INDEX_PREFIX = os.environ.get('INDEX_PREFIX', 'index')


def get_json_from_s3(bucket: str, key: str) -> Optional[Dict]:
    """Fetch and parse JSON from S3."""
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(response['Body'].read().decode('utf-8'))
    except Exception as e:
        logger.warning(f"Failed to read {key}: {e}")
        return None


def list_json_files(bucket: str, prefix: str = '') -> List[str]:
    """List all JSON files in S3 bucket/prefix."""
    keys = []
    paginator = s3.get_paginator('list_objects_v2')

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            if obj['Key'].endswith('.json'):
                keys.append(obj['Key'])

    return keys


def is_collection(data: Dict) -> bool:
    """Check if JSON is a STAC Collection."""
    return data.get('type') == 'Collection'


def is_item(data: Dict) -> bool:
    """Check if JSON is a STAC Item (Feature)."""
    return data.get('type') == 'Feature'


def extract_item_data(item: Dict, source_key: str) -> Dict[str, Any]:
    """Extract indexable fields from a STAC Item."""
    props = item.get('properties', {})
    geometry = item.get('geometry')

    # Convert geometry to WKT for storage
    geometry_wkt = None
    if geometry:
        try:
            geom = shape(geometry)
            geometry_wkt = wkt.dumps(geom)
        except:
            pass

    # Parse datetime
    dt = props.get('datetime')
    if dt:
        try:
            dt = pd.to_datetime(dt, utc=True)
        except:
            dt = None

    return {
        'id': item.get('id'),
        'collection': item.get('collection'),
        'title': props.get('title'),
        'datetime': dt,
        'bbox': json.dumps(item.get('bbox')) if item.get('bbox') else None,
        'geometry_wkt': geometry_wkt,
        'stac_version': item.get('stac_version', '1.1.0'),
        'links': json.dumps(item.get('links', [])),
        'assets': json.dumps(item.get('assets', {})),
        'item_json': json.dumps(item),
        'source_key': source_key,
        # Point cloud properties
        'pc_count': props.get('pc:count'),
        'pc_type': props.get('pc:type'),
        'pc_encoding': props.get('pc:encoding'),
        # Projection properties
        'proj_epsg': props.get('proj:epsg'),
    }


def extract_collection_data(collection: Dict, source_key: str) -> Dict[str, Any]:
    """Extract indexable fields from a STAC Collection."""
    extent = collection.get('extent', {})
    spatial = extent.get('spatial', {})
    temporal = extent.get('temporal', {})

    bbox = spatial.get('bbox', [[]])[0] if spatial.get('bbox') else None
    interval = temporal.get('interval', [[None, None]])[0] if temporal.get('interval') else [None, None]

    return {
        'id': collection.get('id'),
        'title': collection.get('title'),
        'description': collection.get('description'),
        'license': collection.get('license'),
        'bbox': json.dumps(bbox) if bbox else None,
        'start_datetime': interval[0] if interval else None,
        'end_datetime': interval[1] if len(interval) > 1 else None,
        'stac_version': collection.get('stac_version', '1.1.0'),
        'stac_extensions': collection.get('stac_extensions'),
        'links': json.dumps(collection.get('links', [])),
        'summaries': json.dumps(collection.get('summaries', {})),
        'providers': json.dumps(collection.get('providers', [])),
        'collection_json': json.dumps(collection),
        'source_key': source_key,
    }


def build_index(bucket: str) -> tuple[pd.DataFrame, pd.DataFrame, Dict]:
    """Scan S3 bucket and build index DataFrames."""
    items = []
    collections = []
    catalog_metadata = {
        'catalog_id': 'stac-catalog',
        'catalog_title': 'STAC Catalog',
        'stac_version': '1.1.0',
        'indexed_at': datetime.now(timezone.utc).isoformat(),
    }

    # List all JSON files
    json_files = list_json_files(bucket)
    logger.info(f"Found {len(json_files)} JSON files in {bucket}")

    # Skip index files, data directory, and English translations (to avoid duplicates)
    json_files = [k for k in json_files if not k.startswith('index/')
                  and not k.startswith('data/')
                  and not k.endswith('-en.json')]

    for key in json_files:
        data = get_json_from_s3(bucket, key)
        if not data:
            continue

        # Check if it's a catalog (root)
        if data.get('type') == 'Catalog':
            catalog_metadata['catalog_id'] = data.get('id', 'stac-catalog')
            catalog_metadata['catalog_title'] = data.get('title', 'STAC Catalog')
            catalog_metadata['stac_version'] = data.get('stac_version', '1.1.0')
            catalog_metadata['catalog_description'] = data.get('description', '')
            continue

        if is_collection(data):
            collections.append(extract_collection_data(data, key))
            logger.info(f"Indexed collection: {data.get('id')} from {key}")
        elif is_item(data):
            items.append(extract_item_data(data, key))
            logger.info(f"Indexed item: {data.get('id')} from {key}")

    items_df = pd.DataFrame(items) if items else pd.DataFrame()
    collections_df = pd.DataFrame(collections) if collections else pd.DataFrame()

    return items_df, collections_df, catalog_metadata


def upload_index_to_s3(bucket: str, prefix: str, items_df: pd.DataFrame,
                       collections_df: pd.DataFrame, metadata: Dict) -> None:
    """Upload index files to S3."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Write items parquet
        if not items_df.empty:
            items_file = tmppath / 'items.parquet'
            table = pa.Table.from_pandas(items_df)
            pq.write_table(table, items_file)
            s3.upload_file(str(items_file), bucket, f'{prefix}/items.parquet')
            logger.info(f"Uploaded items.parquet ({len(items_df)} items)")

        # Write collections parquet
        if not collections_df.empty:
            collections_file = tmppath / 'collections.parquet'
            table = pa.Table.from_pandas(collections_df)
            pq.write_table(table, collections_file)
            s3.upload_file(str(collections_file), bucket, f'{prefix}/collections.parquet')
            logger.info(f"Uploaded collections.parquet ({len(collections_df)} collections)")

        # Write metadata
        metadata_file = tmppath / 'catalog_metadata.json'
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        s3.upload_file(str(metadata_file), bucket, f'{prefix}/catalog_metadata.json')
        logger.info("Uploaded catalog_metadata.json")


def handler(event, context):
    """Lambda handler for S3 events."""
    logger.info(f"Received event: {json.dumps(event)}")

    # Handle scheduled warmup
    if event.get('source') == 'aws.events':
        return {'statusCode': 200, 'body': 'warmup'}

    # Handle S3 events
    records = event.get('Records', [])
    if not records:
        logger.info("No records in event, running full reindex")
    else:
        # Log which files changed
        for record in records:
            s3_info = record.get('s3', {})
            bucket = s3_info.get('bucket', {}).get('name')
            key = s3_info.get('object', {}).get('key')
            logger.info(f"S3 event: {record.get('eventName')} on {bucket}/{key}")

    try:
        # Build index
        logger.info(f"Building index from bucket: {CATALOG_BUCKET}")
        items_df, collections_df, metadata = build_index(CATALOG_BUCKET)

        logger.info(f"Index built: {len(items_df)} items, {len(collections_df)} collections")

        # Upload to S3
        upload_index_to_s3(CATALOG_BUCKET, INDEX_PREFIX, items_df, collections_df, metadata)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Index rebuilt successfully',
                'items': len(items_df),
                'collections': len(collections_df),
                'indexed_at': metadata['indexed_at']
            })
        }

    except Exception as e:
        logger.error(f"Error building index: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


if __name__ == '__main__':
    # For local testing
    result = handler({}, None)
    print(json.dumps(result, indent=2))
