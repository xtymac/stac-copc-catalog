#!/usr/bin/env python3
"""
STAC Catalog Generator for COPC Point Cloud Data

Generates STAC catalog, collection, and items with the point-cloud extension
for Japanese regional datasets.

Supports two modes:
1. Multi-file mode (default): Creates items for each COPC file in data-dir
2. Unified mode (--unified): Creates a single item for one merged COPC file

Usage:
    # Multi-file mode
    python 02-generate-stac.py --data-dir ./local/output --catalog-dir ./catalog --base-url https://stac.example.com

    # Unified mode (single COPC)
    python 02-generate-stac.py --unified --data-dir ./local/output-unified --catalog-dir ./catalog --base-url https://stac.example.com
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
from pystac.extensions.pointcloud import (
    PointcloudExtension,
    Schema,
    SchemaType,
    Statistic,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# STAC Extension URLs
PC_EXTENSION = "https://stac-extensions.github.io/pointcloud/v1.0.0/schema.json"
PROJ_EXTENSION = "https://stac-extensions.github.io/projection/v1.1.0/schema.json"
FILE_EXTENSION = "https://stac-extensions.github.io/file/v2.1.0/schema.json"

# COPC media types
COPC_MEDIA_TYPE = "application/vnd.laszip+copc"
COPC_MEDIA_TYPE_ALT = "application/vnd.copc+laz"  # Alternative for some tools

# Default provider for Japanese datasets
DEFAULT_PROVIDER = Provider(
    name="PLATEAU / GSI Japan",
    description="Japanese national mapping and 3D city model project",
    roles=["producer", "licensor"],
    url="https://www.mlit.go.jp/plateau/"
)


def load_metadata_files(data_dir: Path) -> List[Dict[str, Any]]:
    """
    Load all metadata JSON files from data directory.

    Args:
        data_dir: Directory containing .metadata.json files

    Returns:
        List of metadata dictionaries
    """
    metadata_files = sorted(data_dir.glob('*.metadata.json'))
    logger.info(f"Found {len(metadata_files)} metadata files")

    all_metadata = []
    for mf in metadata_files:
        try:
            with open(mf) as f:
                meta = json.load(f)
                if 'error' not in meta:
                    all_metadata.append(meta)
                else:
                    logger.warning(f"Skipping failed file: {mf.name}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse {mf.name}: {e}")

    return all_metadata


def convert_geometry_to_wgs84(
    geometry: Dict[str, Any],
    source_epsg: int
) -> Optional[Dict[str, Any]]:
    """
    Convert geometry from source CRS to WGS84 (EPSG:4326).

    Args:
        geometry: GeoJSON geometry dictionary
        source_epsg: Source EPSG code

    Returns:
        Converted geometry or None on failure

    Note:
        Although EPSG standards define Japanese Plane Rectangular CS with
        X=Northing, Y=Easting, most Japanese LAS files store coordinates
        in standard GIS format (X=Easting, Y=Northing). This function
        uses always_xy=True with direct coordinate mapping.
    """
    if not geometry or source_epsg == 4326:
        return geometry

    try:
        import pyproj
        from shapely.geometry import mapping, shape
        from shapely.ops import transform

        source = pyproj.CRS.from_epsg(source_epsg)
        target = pyproj.CRS.from_epsg(4326)
        transformer = pyproj.Transformer.from_crs(
            source, target, always_xy=True
        )

        geom = shape(geometry)

        # With always_xy=True, direct transformation works correctly
        # Japanese LAS files already store X=Easting, Y=Northing
        transformed = transform(transformer.transform, geom)

        return mapping(transformed)

    except Exception as e:
        logger.warning(f"Geometry conversion failed: {e}")
        return None


def convert_bbox_to_wgs84(
    bbox: List[float],
    source_epsg: int
) -> List[float]:
    """
    Convert 6D bbox from source CRS to WGS84.

    Args:
        bbox: [minx, miny, minz, maxx, maxy, maxz]
        source_epsg: Source EPSG code

    Returns:
        Converted bbox [minlon, minlat, maxlon, maxlat] in WGS84

    Note:
        Although EPSG standards define Japanese Plane Rectangular CS with
        X=Northing, Y=Easting, most Japanese LAS files store coordinates
        in standard GIS format (X=Easting, Y=Northing). This function
        uses always_xy=True with direct coordinate mapping.
    """
    if source_epsg == 4326:
        return [bbox[0], bbox[1], bbox[3], bbox[4]]

    try:
        import pyproj

        source = pyproj.CRS.from_epsg(source_epsg)
        target = pyproj.CRS.from_epsg(4326)
        transformer = pyproj.Transformer.from_crs(
            source, target, always_xy=True
        )

        # With always_xy=True, input is (x, y) = (easting, northing)
        # Japanese LAS files already store X=Easting, Y=Northing
        # So direct mapping works correctly
        minlon, minlat = transformer.transform(bbox[0], bbox[1])
        maxlon, maxlat = transformer.transform(bbox[3], bbox[4])

        return [minlon, minlat, maxlon, maxlat]

    except Exception as e:
        logger.warning(f"Bbox conversion failed: {e}, using original values")
        return [bbox[0], bbox[1], bbox[3], bbox[4]]


def create_catalog(
    catalog_id: str,
    title: str,
    description: str
) -> Catalog:
    """Create root STAC catalog."""
    catalog = Catalog(
        id=catalog_id,
        title=title,
        description=description,
        catalog_type=pystac.CatalogType.SELF_CONTAINED
    )

    return catalog


def create_collection(
    collection_id: str,
    title: str,
    description: str,
    all_metadata: List[Dict[str, Any]],
    base_url: str
) -> Collection:
    """
    Create STAC collection for point cloud data.

    Args:
        collection_id: Collection ID
        title: Collection title
        description: Collection description
        all_metadata: List of item metadata for extent calculation
        base_url: Base URL for assets

    Returns:
        STAC Collection
    """
    def get_epsg_from_metadata(m: Dict[str, Any]) -> Optional[int]:
        """Extract EPSG from metadata (either 'epsg' or 'source_crs' field)."""
        epsg = m.get('epsg')
        if epsg:
            return epsg
        source_crs = m.get('source_crs', '')
        if 'EPSG:' in source_crs:
            try:
                return int(source_crs.split('EPSG:')[1].split()[0])
            except (ValueError, IndexError):
                pass
        return None

    # Calculate collection extent from all items
    bboxes = [m.get('bbox', [0, 0, 0, 0, 0, 0]) for m in all_metadata]
    epsgs = [get_epsg_from_metadata(m) for m in all_metadata]
    epsgs = [e for e in epsgs if e is not None]

    # Use first EPSG for collection
    collection_epsg = epsgs[0] if epsgs else None

    # Convert all bboxes to WGS84 for extent
    wgs84_bboxes = []
    for i, bbox in enumerate(bboxes):
        epsg = get_epsg_from_metadata(all_metadata[i]) or 4326
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

    # Create collection with extensions
    collection = Collection(
        id=collection_id,
        title=title,
        description=description,
        license="proprietary",
        extent=extent,
        stac_extensions=[PC_EXTENSION, PROJ_EXTENSION],
        providers=[DEFAULT_PROVIDER]
    )

    # Add collection-level point cloud properties
    collection.extra_fields["pc:type"] = "lidar"
    collection.extra_fields["pc:encoding"] = COPC_MEDIA_TYPE

    if collection_epsg:
        collection.extra_fields["proj:epsg"] = collection_epsg

    # Add summaries
    total_points = sum(m.get('point_count', 0) for m in all_metadata)
    collection.extra_fields["summaries"] = {
        "pc:count": {
            "minimum": min(m.get('point_count', 0) for m in all_metadata),
            "maximum": max(m.get('point_count', 0) for m in all_metadata)
        },
        "pc:type": ["lidar"],
        "pc:encoding": [COPC_MEDIA_TYPE]
    }

    if epsgs:
        collection.extra_fields["summaries"]["proj:epsg"] = list(set(epsgs))

    return collection


def create_schema_from_meta(dim: Dict[str, Any]) -> Schema:
    """Create Schema object from dimension metadata."""
    dim_name = dim.get('name', 'Unknown')
    dim_size = dim.get('size', 4)
    dim_type_str = dim.get('type', 'floating')

    # Map PDAL types to STAC types
    type_mapping = {
        'floating': SchemaType.FLOATING,
        'signed': SchemaType.SIGNED,
        'unsigned': SchemaType.UNSIGNED,
        'double': SchemaType.FLOATING,
        'float': SchemaType.FLOATING,
        'int8': SchemaType.SIGNED,
        'int16': SchemaType.SIGNED,
        'int32': SchemaType.SIGNED,
        'int64': SchemaType.SIGNED,
        'uint8': SchemaType.UNSIGNED,
        'uint16': SchemaType.UNSIGNED,
        'uint32': SchemaType.UNSIGNED,
        'uint64': SchemaType.UNSIGNED,
    }

    dim_type = type_mapping.get(dim_type_str.lower(), SchemaType.FLOATING)

    return Schema.create(
        name=dim_name,
        size=dim_size,
        type=dim_type
    )


def create_statistic_from_meta(stat: Dict[str, Any]) -> Statistic:
    """Create Statistic object from stats metadata."""
    return Statistic.create(
        name=stat.get('name', 'Unknown'),
        average=stat.get('average'),
        count=stat.get('count'),
        maximum=stat.get('maximum'),
        minimum=stat.get('minimum'),
        stddev=stat.get('stddev'),
        variance=stat.get('variance')
    )


def create_item_from_metadata(
    metadata: Dict[str, Any],
    base_url: str,
    collection_id: str
) -> Item:
    """
    Create STAC item from COPC metadata.

    Args:
        metadata: Metadata dictionary from conversion
        base_url: Base URL for assets
        collection_id: Parent collection ID

    Returns:
        STAC Item
    """
    source_file = metadata.get('source_file', 'unknown')
    item_id = Path(source_file).stem

    # Get source EPSG
    epsg = metadata.get('epsg', 4326)

    # Get bbox and convert to WGS84
    bbox_6d = metadata.get('bbox', [0, 0, 0, 0, 0, 0])
    bbox_4d = convert_bbox_to_wgs84(bbox_6d, epsg)

    # Get or create geometry
    geometry = metadata.get('geometry')
    if geometry and epsg != 4326:
        geometry = convert_geometry_to_wgs84(geometry, epsg)

    if not geometry:
        # Create bbox polygon
        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [bbox_4d[0], bbox_4d[1]],
                [bbox_4d[2], bbox_4d[1]],
                [bbox_4d[2], bbox_4d[3]],
                [bbox_4d[0], bbox_4d[3]],
                [bbox_4d[0], bbox_4d[1]]
            ]]
        }

    # Create item
    item = Item(
        id=item_id,
        geometry=geometry,
        bbox=bbox_4d,
        datetime=datetime.now(timezone.utc),
        properties={
            "title": item_id,
            "description": f"COPC point cloud from {source_file}"
        },
        stac_extensions=[PC_EXTENSION, PROJ_EXTENSION, FILE_EXTENSION]
    )

    # Apply point cloud extension
    pc_ext = PointcloudExtension.ext(item, add_if_missing=True)

    pc_ext.count = metadata.get('point_count', 0)
    pc_ext.type = "lidar"
    pc_ext.encoding = COPC_MEDIA_TYPE
    pc_ext.density = metadata.get('density', 0)

    # Add schemas
    schemas = []
    for dim in metadata.get('schema', []):
        try:
            schema = create_schema_from_meta(dim)
            schemas.append(schema)
        except Exception as e:
            logger.debug(f"Failed to create schema for {dim}: {e}")

    if schemas:
        pc_ext.schemas = schemas

    # Add statistics
    statistics = []
    for stat in metadata.get('statistics', []):
        try:
            statistic = create_statistic_from_meta(stat)
            statistics.append(statistic)
        except Exception as e:
            logger.debug(f"Failed to create statistic for {stat}: {e}")

    if statistics:
        pc_ext.statistics = statistics

    # Add projection info
    if epsg:
        item.properties['proj:epsg'] = epsg

    # Add native bbox (6D)
    item.properties['proj:bbox'] = bbox_6d

    # Add COPC data asset
    output_file = metadata.get('output_file', f'{item_id}.copc.laz')
    file_size = metadata.get('file_size_bytes', 0)

    item.add_asset(
        key="data",
        asset=Asset(
            href=f"{base_url}/data/{output_file}",
            title="COPC Point Cloud Data",
            description="Cloud Optimized Point Cloud (COPC) format",
            media_type=COPC_MEDIA_TYPE,
            roles=["data"],
            extra_fields={
                "file:size": file_size
            }
        )
    )

    # Add metadata asset
    metadata_filename = Path(output_file).stem.replace('.copc', '') + '.metadata.json'
    item.add_asset(
        key="metadata",
        asset=Asset(
            href=f"{base_url}/data/{metadata_filename}",
            title="Processing Metadata",
            description="PDAL processing metadata and statistics",
            media_type="application/json",
            roles=["metadata"]
        )
    )

    return item


def create_unified_item(
    metadata: Dict[str, Any],
    base_url: str,
    collection_id: str,
    item_id: str = "unified-pointcloud"
) -> Item:
    """
    Create STAC item for unified (merged) COPC file.

    Args:
        metadata: Metadata dictionary from merge script
        base_url: Base URL for assets
        collection_id: Parent collection ID
        item_id: Item ID (default: unified-pointcloud)

    Returns:
        STAC Item
    """
    # Get EPSG from metadata or source_crs
    epsg = metadata.get('epsg')
    if not epsg and metadata.get('source_crs'):
        # Parse EPSG from source_crs string like "EPSG:6676"
        source_crs = metadata.get('source_crs', '')
        if 'EPSG:' in source_crs:
            try:
                epsg = int(source_crs.split('EPSG:')[1].split()[0])
            except (ValueError, IndexError):
                pass
    epsg = epsg or 4326

    # Get bbox and convert to WGS84
    bbox_6d = metadata.get('bbox', [0, 0, 0, 0, 0, 0])
    bbox_4d = convert_bbox_to_wgs84(bbox_6d, epsg)

    # Create bbox polygon geometry
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [bbox_4d[0], bbox_4d[1]],
            [bbox_4d[2], bbox_4d[1]],
            [bbox_4d[2], bbox_4d[3]],
            [bbox_4d[0], bbox_4d[3]],
            [bbox_4d[0], bbox_4d[1]]
        ]]
    }

    # Create item
    item = Item(
        id=item_id,
        geometry=geometry,
        bbox=bbox_4d,
        datetime=datetime.now(timezone.utc),
        properties={
            "title": "Unified Point Cloud",
            "description": f"Merged COPC point cloud containing {metadata.get('point_count', 0):,} points"
        },
        stac_extensions=[PC_EXTENSION, PROJ_EXTENSION, FILE_EXTENSION]
    )

    # Apply point cloud extension
    pc_ext = PointcloudExtension.ext(item, add_if_missing=True)

    pc_ext.count = metadata.get('point_count', 0)
    pc_ext.type = "lidar"
    pc_ext.encoding = COPC_MEDIA_TYPE_ALT  # Use standard COPC media type

    # Add schemas if available
    schemas = []
    for dim in metadata.get('schema', []):
        try:
            schema = create_schema_from_meta(dim)
            schemas.append(schema)
        except Exception as e:
            logger.debug(f"Failed to create schema for {dim}: {e}")

    if schemas:
        pc_ext.schemas = schemas

    # Add statistics if available
    statistics = []
    for stat in metadata.get('statistics', []):
        try:
            statistic = create_statistic_from_meta(stat)
            statistics.append(statistic)
        except Exception as e:
            logger.debug(f"Failed to create statistic for {stat}: {e}")

    if statistics:
        pc_ext.statistics = statistics

    # Add projection info
    item.properties['proj:epsg'] = epsg
    item.properties['proj:bbox'] = bbox_6d

    # Add source files info
    source_files = metadata.get('source_files', [])
    if source_files:
        item.properties['source_file_count'] = len(source_files)

    # Add COPC data asset
    output_file = metadata.get('output_file', 'unified.copc.laz')
    file_size = metadata.get('file_size_bytes', 0)

    item.add_asset(
        key="data",
        asset=Asset(
            href=f"{base_url}/data/{output_file}",
            title="Unified COPC Point Cloud",
            description="Cloud Optimized Point Cloud (COPC) - single unified file for on-demand access",
            media_type=COPC_MEDIA_TYPE_ALT,
            roles=["data"],
            extra_fields={
                "file:size": file_size
            }
        )
    )

    # Add metadata asset
    metadata_filename = Path(output_file).stem.replace('.copc', '') + '.metadata.json'
    item.add_asset(
        key="metadata",
        asset=Asset(
            href=f"{base_url}/data/{metadata_filename}",
            title="Processing Metadata",
            description="Merge processing metadata and statistics",
            media_type="application/json",
            roles=["metadata"]
        )
    )

    return item


def generate_unified_catalog(
    data_dir: Path,
    catalog_dir: Path,
    catalog_id: str,
    collection_id: str,
    base_url: str,
    title: Optional[str] = None,
    description: Optional[str] = None
) -> Tuple[Catalog, int]:
    """
    Generate STAC catalog for unified (single) COPC file.

    Args:
        data_dir: Directory containing unified.copc.laz and metadata
        catalog_dir: Output directory for STAC catalog
        catalog_id: Catalog ID
        collection_id: Collection ID
        base_url: Base URL for hosted catalog
        title: Optional catalog title
        description: Optional catalog description

    Returns:
        Tuple of (Catalog, item_count)
    """
    # Find metadata file for unified COPC
    metadata_files = list(data_dir.glob('*.metadata.json'))
    if not metadata_files:
        raise ValueError(f"No metadata file found in {data_dir}")

    # Use first metadata file (should be unified.metadata.json)
    metadata_file = metadata_files[0]
    logger.info(f"Using metadata file: {metadata_file.name}")

    with open(metadata_file) as f:
        metadata = json.load(f)

    if 'error' in metadata:
        raise ValueError(f"Metadata contains error: {metadata['error']}")

    logger.info(f"Point count: {metadata.get('point_count', 0):,}")

    # Create catalog
    catalog = create_catalog(
        catalog_id=catalog_id,
        title=title or "Unified COPC Catalog",
        description=description or "Single unified Cloud Optimized Point Cloud (COPC) for on-demand access"
    )

    # Create collection with single item metadata
    collection = create_collection(
        collection_id=collection_id,
        title=f"Unified Point Cloud - {collection_id}",
        description="Single merged LiDAR point cloud in COPC format for cloud-native access",
        all_metadata=[metadata],
        base_url=base_url
    )

    # Create unified item
    item = create_unified_item(metadata, base_url, collection_id)
    collection.add_item(item)
    logger.info(f"Created unified item: {item.id}")

    # Add collection to catalog
    catalog.add_child(collection)

    # Normalize hrefs and save
    catalog.normalize_and_save(
        root_href=str(catalog_dir),
        catalog_type=pystac.CatalogType.SELF_CONTAINED
    )

    logger.info(f"Catalog saved to: {catalog_dir}")

    return catalog, 1


def generate_catalog(
    data_dir: Path,
    catalog_dir: Path,
    catalog_id: str,
    collection_id: str,
    base_url: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    unified_mode: bool = False
) -> Tuple[Catalog, int]:
    """
    Generate complete STAC catalog from processed COPC files.

    Args:
        data_dir: Directory containing COPC files and metadata
        catalog_dir: Output directory for STAC catalog
        catalog_id: Catalog ID
        collection_id: Collection ID
        base_url: Base URL for hosted catalog
        title: Optional catalog title
        description: Optional catalog description
        unified_mode: If True, generate catalog for single unified COPC

    Returns:
        Tuple of (Catalog, item_count)
    """
    # Use unified mode if requested
    if unified_mode:
        return generate_unified_catalog(
            data_dir=data_dir,
            catalog_dir=catalog_dir,
            catalog_id=catalog_id,
            collection_id=collection_id,
            base_url=base_url,
            title=title,
            description=description
        )

    # Load metadata
    all_metadata = load_metadata_files(data_dir)

    if not all_metadata:
        raise ValueError("No valid metadata files found")

    logger.info(f"Processing {len(all_metadata)} items")

    # Create catalog
    catalog = create_catalog(
        catalog_id=catalog_id,
        title=title or "STAC COPC Catalog",
        description=description or "Static STAC catalog for Cloud Optimized Point Cloud (COPC) data"
    )

    # Create collection
    collection = create_collection(
        collection_id=collection_id,
        title=f"Point Cloud Collection - {collection_id}",
        description="LiDAR point cloud data in COPC format",
        all_metadata=all_metadata,
        base_url=base_url
    )

    # Create items
    for metadata in all_metadata:
        try:
            item = create_item_from_metadata(metadata, base_url, collection_id)
            collection.add_item(item)
            logger.info(f"  Created item: {item.id}")
        except Exception as e:
            logger.error(f"  Failed to create item: {e}")

    # Add collection to catalog
    catalog.add_child(collection)

    # Normalize hrefs and save
    catalog.normalize_and_save(
        root_href=str(catalog_dir),
        catalog_type=pystac.CatalogType.SELF_CONTAINED
    )

    item_count = len(list(catalog.get_items(recursive=True)))
    logger.info(f"Catalog saved to: {catalog_dir}")

    return catalog, item_count


def main():
    parser = argparse.ArgumentParser(
        description='Generate STAC catalog from COPC data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Multi-file mode (default)
  %(prog)s --data-dir ./local/output --catalog-dir ./catalog --base-url https://stac.example.com

  # Unified mode (single COPC file)
  %(prog)s --unified --data-dir ./local/output-unified --catalog-dir ./catalog --base-url https://stac.example.com
        """
    )

    parser.add_argument(
        '--data-dir', '-d',
        type=Path,
        required=True,
        help='Directory containing COPC files and metadata'
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
        help='Base URL for the hosted catalog (e.g., https://stac.example.com)'
    )

    parser.add_argument(
        '--catalog-id',
        type=str,
        default='stac-copc-catalog',
        help='Catalog ID (default: stac-copc-catalog)'
    )

    parser.add_argument(
        '--collection-id',
        type=str,
        default='pointcloud-jgd2011',
        help='Collection ID (default: pointcloud-jgd2011)'
    )

    parser.add_argument(
        '--title',
        type=str,
        default=None,
        help='Catalog title'
    )

    parser.add_argument(
        '--description',
        type=str,
        default=None,
        help='Catalog description'
    )

    parser.add_argument(
        '--unified',
        action='store_true',
        help='Unified mode: generate catalog for single merged COPC file'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate data directory
    if not args.data_dir.exists():
        logger.error(f"Data directory does not exist: {args.data_dir}")
        sys.exit(1)

    # Create catalog directory
    args.catalog_dir.mkdir(parents=True, exist_ok=True)

    try:
        catalog, item_count = generate_catalog(
            data_dir=args.data_dir,
            catalog_dir=args.catalog_dir,
            catalog_id=args.catalog_id,
            collection_id=args.collection_id,
            base_url=args.base_url.rstrip('/'),
            title=args.title,
            description=args.description,
            unified_mode=args.unified
        )

        logger.info("=" * 60)
        logger.info("STAC CATALOG GENERATED")
        logger.info("=" * 60)
        logger.info(f"Catalog ID: {args.catalog_id}")
        logger.info(f"Collection ID: {args.collection_id}")
        logger.info(f"Items: {item_count}")
        logger.info(f"Output: {args.catalog_dir}")
        logger.info("")
        logger.info("Next step: python scripts/04-validate.py --catalog-dir ./catalog")

    except Exception as e:
        logger.error(f"Failed to generate catalog: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
