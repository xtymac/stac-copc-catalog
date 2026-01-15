#!/usr/bin/env python3
"""
COPC Bounding Box Query Demo

Demonstrates cloud-native, on-demand point cloud access by querying
a COPC file with a bounding box. Only downloads the requested region,
not the entire file.

Usage:
    python 08-demo-bbox-query.py --url https://stac.uixai.org/data/unified.copc.laz --bbox 51200,-49200,51400,-49000
    python 08-demo-bbox-query.py --file ./local/output-unified/unified.copc.laz --bbox 51200,-49200,51400,-49000 --output subset.laz
    python 08-demo-bbox-query.py --url https://stac.uixai.org/data/unified.copc.laz --bbox 51200,-49200,51400,-49000 --json
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import pdal
    HAS_PDAL = True
except ImportError:
    HAS_PDAL = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def parse_bbox(bbox_str: str) -> Tuple[float, float, float, float]:
    """
    Parse bounding box string.

    Args:
        bbox_str: Comma-separated bbox "xmin,ymin,xmax,ymax"

    Returns:
        Tuple of (xmin, ymin, xmax, ymax)
    """
    parts = [float(x.strip()) for x in bbox_str.split(',')]
    if len(parts) == 4:
        return tuple(parts)
    elif len(parts) == 6:
        # 6D bbox: xmin,ymin,zmin,xmax,ymax,zmax -> use xy only
        return (parts[0], parts[1], parts[3], parts[4])
    else:
        raise ValueError(f"Invalid bbox format: {bbox_str}. Expected 4 or 6 values.")


def query_copc_bbox(
    source: str,
    bbox: Tuple[float, float, float, float],
    output_file: Optional[str] = None,
    limit: int = 0
) -> Dict[str, Any]:
    """
    Query COPC file by bounding box.

    COPC files support HTTP range requests, so only the data within
    the bbox is downloaded - not the entire file.

    Args:
        source: URL or local path to COPC file
        bbox: Bounding box (xmin, ymin, xmax, ymax)
        output_file: Optional path to save subset as LAZ
        limit: Maximum points to return (0 = unlimited)

    Returns:
        Dictionary with query results
    """
    if not HAS_PDAL:
        raise ImportError("PDAL Python bindings required. Install with: pip install pdal")

    xmin, ymin, xmax, ymax = bbox

    # PDAL bounds format: ([xmin, xmax], [ymin, ymax])
    bounds = f"([{xmin}, {xmax}], [{ymin}, {ymax}])"

    # Determine reader type
    if source.startswith(('http://', 'https://')):
        reader_type = "readers.copc"
    else:
        # Local file - check extension
        if source.endswith('.copc.laz'):
            reader_type = "readers.copc"
        else:
            reader_type = "readers.las"

    # Build pipeline stages
    stages = [
        {
            "type": reader_type,
            "filename": source
        },
        {
            "type": "filters.crop",
            "bounds": bounds
        }
    ]

    # Optional point limit
    if limit > 0:
        stages.append({
            "type": "filters.head",
            "count": limit
        })

    # Optional output file
    if output_file:
        stages.append({
            "type": "writers.las",
            "filename": output_file,
            "compression": "laszip"
        })

    pipeline_json = json.dumps({"pipeline": stages})

    logger.info(f"Source: {source}")
    logger.info(f"Bbox: {bbox}")
    logger.info(f"Bounds filter: {bounds}")

    try:
        pipeline = pdal.Pipeline(pipeline_json)
        point_count = pipeline.execute()

        logger.info(f"Query returned {point_count:,} points")

        # Get point arrays
        arrays = pipeline.arrays
        if len(arrays) > 0 and len(arrays[0]) > 0:
            points = arrays[0]

            # Calculate statistics
            result = {
                "source": source,
                "bbox": list(bbox),
                "point_count": len(points),
                "dimensions": list(points.dtype.names) if hasattr(points, 'dtype') else []
            }

            # Add coordinate ranges if numpy available
            if HAS_NUMPY and hasattr(points, 'dtype'):
                result["stats"] = {
                    "X": {"min": float(points['X'].min()), "max": float(points['X'].max())},
                    "Y": {"min": float(points['Y'].min()), "max": float(points['Y'].max())},
                    "Z": {"min": float(points['Z'].min()), "max": float(points['Z'].max())}
                }

            if output_file:
                result["output_file"] = output_file
                result["output_size_bytes"] = Path(output_file).stat().st_size

            return result
        else:
            return {
                "source": source,
                "bbox": list(bbox),
                "point_count": 0,
                "message": "No points found in bbox"
            }

    except Exception as e:
        error_msg = str(e)

        # Provide helpful error messages
        if "SSL" in error_msg or "certificate" in error_msg.lower():
            logger.error("SSL/TLS error - check certificate configuration")
        elif "404" in error_msg or "not found" in error_msg.lower():
            logger.error("File not found - check URL/path")
        elif "timeout" in error_msg.lower():
            logger.error("Request timeout - server may be slow or unreachable")

        raise RuntimeError(f"Query failed: {error_msg}")


def points_to_json(
    source: str,
    bbox: Tuple[float, float, float, float],
    limit: int = 10000
) -> Dict[str, Any]:
    """
    Query COPC and return points as JSON.

    Args:
        source: URL or local path to COPC file
        bbox: Bounding box (xmin, ymin, xmax, ymax)
        limit: Maximum points (default 10000 to avoid huge JSON)

    Returns:
        Dictionary with points as list of dicts
    """
    if not HAS_PDAL:
        raise ImportError("PDAL Python bindings required")

    xmin, ymin, xmax, ymax = bbox
    bounds = f"([{xmin}, {xmax}], [{ymin}, {ymax}])"

    # Determine reader type
    reader_type = "readers.copc" if source.startswith(('http://', 'https://')) or source.endswith('.copc.laz') else "readers.las"

    stages = [
        {"type": reader_type, "filename": source},
        {"type": "filters.crop", "bounds": bounds},
        {"type": "filters.head", "count": limit}
    ]

    pipeline = pdal.Pipeline(json.dumps({"pipeline": stages}))
    pipeline.execute()

    arrays = pipeline.arrays
    if len(arrays) > 0 and len(arrays[0]) > 0:
        points = arrays[0]

        # Convert to list of dicts (JSON-friendly)
        point_list = []
        for p in points:
            point_dict = {
                "x": float(p['X']),
                "y": float(p['Y']),
                "z": float(p['Z'])
            }
            if 'Intensity' in points.dtype.names:
                point_dict["intensity"] = int(p['Intensity'])
            if 'Classification' in points.dtype.names:
                point_dict["classification"] = int(p['Classification'])
            point_list.append(point_dict)

        return {
            "bbox": list(bbox),
            "count": len(point_list),
            "limit_applied": limit,
            "points": point_list
        }

    return {
        "bbox": list(bbox),
        "count": 0,
        "points": []
    }


def main():
    parser = argparse.ArgumentParser(
        description='Query COPC point cloud by bounding box',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Query remote COPC (only downloads bbox region)
  %(prog)s --url https://stac.uixai.org/data/unified.copc.laz --bbox 51200,-49200,51400,-49000

  # Query local COPC file
  %(prog)s --file ./local/output-unified/unified.copc.laz --bbox 51200,-49200,51400,-49000

  # Save subset as LAZ file
  %(prog)s --url https://stac.uixai.org/data/unified.copc.laz --bbox 51200,-49200,51400,-49000 --output subset.laz

  # Output as JSON (for API demonstration)
  %(prog)s --url https://stac.uixai.org/data/unified.copc.laz --bbox 51200,-49200,51400,-49000 --json --limit 1000

Note: Coordinates should be in the COPC file's native CRS (e.g., JGD2011 Zone 8 / EPSG:6676)
        """
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        '--url', '-u',
        type=str,
        help='URL to remote COPC file'
    )
    source_group.add_argument(
        '--file', '-f',
        type=str,
        help='Path to local COPC file'
    )

    parser.add_argument(
        '--bbox', '-b',
        type=str,
        required=True,
        help='Bounding box: xmin,ymin,xmax,ymax (in native CRS)'
    )

    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help='Output LAZ file path (optional)'
    )

    parser.add_argument(
        '--json', '-j',
        action='store_true',
        help='Output points as JSON'
    )

    parser.add_argument(
        '--limit', '-l',
        type=int,
        default=0,
        help='Maximum points to return (0 = unlimited, default for JSON: 10000)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check dependencies
    if not HAS_PDAL:
        logger.error("PDAL Python bindings not found")
        logger.error("Install with: pip install pdal")
        logger.error("Or: conda install -c conda-forge python-pdal")
        sys.exit(1)

    # Parse bbox
    try:
        bbox = parse_bbox(args.bbox)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # Determine source
    source = args.url or args.file

    # Execute query
    try:
        if args.json:
            # JSON output mode
            limit = args.limit if args.limit > 0 else 10000
            result = points_to_json(source, bbox, limit)
            print(json.dumps(result, indent=2))
        else:
            # Standard query
            result = query_copc_bbox(
                source,
                bbox,
                args.output,
                args.limit
            )

            # Print summary
            print()
            print("=" * 60)
            print("QUERY RESULT")
            print("=" * 60)
            print(f"Source: {result['source']}")
            print(f"Bbox: {result['bbox']}")
            print(f"Points: {result['point_count']:,}")

            if 'stats' in result:
                print(f"X range: {result['stats']['X']['min']:.2f} - {result['stats']['X']['max']:.2f}")
                print(f"Y range: {result['stats']['Y']['min']:.2f} - {result['stats']['Y']['max']:.2f}")
                print(f"Z range: {result['stats']['Z']['min']:.2f} - {result['stats']['Z']['max']:.2f}")

            if 'output_file' in result:
                size_mb = result['output_size_bytes'] / 1024 / 1024
                print(f"Output: {result['output_file']} ({size_mb:.2f} MB)")

            if 'dimensions' in result and result['dimensions']:
                print(f"Dimensions: {', '.join(result['dimensions'][:10])}...")

    except Exception as e:
        logger.error(str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()
