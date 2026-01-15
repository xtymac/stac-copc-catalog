#!/usr/bin/env python3
"""
LAS/LAZ to COPC Conversion Script with Metadata Extraction

Converts Japanese regional point cloud data (PLATEAU-style) to COPC format
with full statistics extraction for STAC catalog generation.

Usage:
    python 01-prepare-data.py --input-dir ./local/input --output-dir ./local/output
    python 01-prepare-data.py --input-file ./data/sample.las --output-dir ./local/output
    python 01-prepare-data.py --input-dir ./local/input --output-dir ./local/output --source-crs EPSG:6677
    python 01-prepare-data.py --input-dir ./local/input --output-dir ./local/output --source-crs EPSG:6677 --target-crs EPSG:4326
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Try to import tqdm for progress bars
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    def tqdm(iterable, **kwargs):
        return iterable

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Japanese CRS mappings (JGD2011 zones)
JGD2011_ZONES = {
    1: 6669, 2: 6670, 3: 6671, 4: 6672, 5: 6673,
    6: 6674, 7: 6675, 8: 6676, 9: 6677, 10: 6678,
    11: 6679, 12: 6680, 13: 6681, 14: 6682, 15: 6683,
    16: 6684, 17: 6685, 18: 6686, 19: 6687
}

# JGD2011 Geographic CRS
JGD2011_GEOGRAPHIC = 6668


def check_pdal_installed() -> bool:
    """Check if PDAL CLI is available."""
    try:
        result = subprocess.run(
            ['pdal', '--version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip().split('\n')[0]
            logger.info(f"PDAL version: {version}")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False


def get_file_info(input_file: Path, timeout: int = 300) -> Dict[str, Any]:
    """
    Extract metadata from LAS/LAZ file using PDAL info.

    Args:
        input_file: Path to LAS/LAZ file
        timeout: Timeout in seconds

    Returns:
        Dictionary with file metadata
    """
    cmd = ['pdal', 'info', '--all', str(input_file)]

    logger.debug(f"Running: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout
    )

    if result.returncode != 0:
        raise RuntimeError(f"PDAL info failed: {result.stderr}")

    return json.loads(result.stdout)


def build_pipeline(
    input_file: Path,
    output_file: Path,
    source_crs: Optional[str] = None,
    target_crs: Optional[str] = None,
    extract_stats: bool = True
) -> List[Dict[str, Any]]:
    """
    Build PDAL pipeline for LAS to COPC conversion.

    Args:
        input_file: Input LAS/LAZ file path
        output_file: Output COPC file path
        source_crs: CRS to assign to source file (if missing from file)
        target_crs: Optional target CRS for reprojection
        extract_stats: Whether to extract statistics

    Returns:
        List of pipeline stages
    """
    stages = []

    # Reader with optional override_srs for files without CRS
    reader_config = {
        "type": "readers.las",
        "filename": str(input_file)
    }
    if source_crs:
        reader_config["override_srs"] = source_crs
    stages.append(reader_config)

    # Reprojection (if target CRS specified)
    if target_crs:
        stages.append({
            "type": "filters.reprojection",
            "out_srs": target_crs
        })

    # Metadata extraction filters
    if extract_stats:
        stages.append({"type": "filters.info"})

        stages.append({
            "type": "filters.stats",
            "dimensions": "X,Y,Z,Intensity,ReturnNumber,NumberOfReturns,Classification",
            "enumerate": "Classification,ReturnNumber,NumberOfReturns"
        })

        stages.append({
            "type": "filters.hexbin",
            "edge_size": 10,
            "threshold": 1
        })

    # COPC writer
    stages.append({
        "type": "writers.copc",
        "filename": str(output_file),
        "forward": "all"
    })

    return stages


def convert_to_copc(
    input_file: Path,
    output_file: Path,
    source_crs: Optional[str] = None,
    target_crs: Optional[str] = None,
    timeout: int = 3600
) -> Dict[str, Any]:
    """
    Convert LAS/LAZ to COPC with metadata extraction.

    Args:
        input_file: Input LAS/LAZ file path
        output_file: Output COPC file path
        source_crs: CRS to assign to source file (if missing from file)
        target_crs: Optional target CRS for reprojection
        timeout: Timeout in seconds

    Returns:
        Dictionary with conversion results and metadata
    """
    import tempfile

    # Build pipeline
    pipeline_stages = build_pipeline(input_file, output_file, source_crs, target_crs)
    pipeline_json = {"pipeline": pipeline_stages}

    # Write pipeline to temp file
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.json',
        delete=False
    ) as f:
        json.dump(pipeline_json, f, indent=2)
        pipeline_file = Path(f.name)

    # Metadata output file
    metadata_file = output_file.with_suffix('.pipeline-metadata.json')

    try:
        # Execute PDAL pipeline
        cmd = [
            'pdal', 'pipeline',
            str(pipeline_file),
            f'--metadata={metadata_file}'
        ]

        logger.debug(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if result.returncode != 0:
            raise RuntimeError(f"PDAL pipeline failed: {result.stderr}")

        # Read metadata
        if metadata_file.exists():
            with open(metadata_file) as f:
                pipeline_metadata = json.load(f)
        else:
            pipeline_metadata = {}

        # Extract relevant metadata (use source_crs if no target_crs)
        effective_crs = target_crs or source_crs
        metadata = extract_metadata(pipeline_metadata, effective_crs)

        # If metadata extraction failed, read directly from output COPC file
        if metadata['point_count'] == 0:
            try:
                copc_info = get_file_info(output_file, timeout=60)
                copc_meta = copc_info.get('metadata', {})
                metadata['point_count'] = copc_meta.get('count', 0)
                metadata['bbox'] = [
                    float(copc_meta.get('minx', 0)),
                    float(copc_meta.get('miny', 0)),
                    float(copc_meta.get('minz', 0)),
                    float(copc_meta.get('maxx', 0)),
                    float(copc_meta.get('maxy', 0)),
                    float(copc_meta.get('maxz', 0))
                ]
                # Get CRS from COPC file if not set
                if not metadata.get('epsg'):
                    srs = copc_meta.get('srs', {})
                    wkt = srs.get('compoundwkt', '') or copc_meta.get('comp_spatialreference', '')
                    if 'EPSG' in wkt:
                        import re
                        match = re.search(r'AUTHORITY\["EPSG","(\d+)"\]\]$', wkt)
                        if match:
                            metadata['epsg'] = int(match.group(1))
                    metadata['crs'] = wkt
            except Exception as e:
                logger.warning(f"Could not read metadata from output file: {e}")

        metadata['source_file'] = input_file.name
        metadata['output_file'] = output_file.name
        metadata['file_size_bytes'] = output_file.stat().st_size
        metadata['processing_time'] = datetime.now().isoformat()

        return metadata

    finally:
        # Cleanup temp files
        pipeline_file.unlink(missing_ok=True)
        metadata_file.unlink(missing_ok=True)


def extract_metadata(
    pipeline_metadata: Dict[str, Any],
    target_crs: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extract relevant metadata from PDAL pipeline output.

    Args:
        pipeline_metadata: Raw PDAL pipeline metadata
        target_crs: Target CRS used in conversion

    Returns:
        Cleaned metadata dictionary
    """
    meta = pipeline_metadata.get('metadata', {})

    # Find readers.las metadata
    readers_meta = {}
    for key, value in meta.items():
        if 'readers.las' in key or 'readers' in key:
            if isinstance(value, dict):
                readers_meta = value
                break

    # Find stats metadata
    stats_meta = {}
    for key, value in meta.items():
        if 'filters.stats' in key or 'stats' in key:
            if isinstance(value, dict):
                stats_meta = value
                break

    # Find hexbin metadata
    hexbin_meta = {}
    for key, value in meta.items():
        if 'filters.hexbin' in key or 'hexbin' in key:
            if isinstance(value, dict):
                hexbin_meta = value
                break

    # Find info metadata
    info_meta = {}
    for key, value in meta.items():
        if 'filters.info' in key or 'info' in key:
            if isinstance(value, dict):
                info_meta = value
                break

    # Extract point count
    point_count = readers_meta.get('count', 0)
    if not point_count:
        point_count = readers_meta.get('num_points', 0)

    # Extract bbox
    bbox = extract_bbox(stats_meta, readers_meta)

    # Extract CRS
    crs = target_crs
    if not crs:
        crs = readers_meta.get('comp_spatialreference', '')
        if not crs:
            crs = readers_meta.get('srs', {}).get('compoundwkt', '')

    # Extract EPSG if possible
    epsg = None
    if crs:
        if 'EPSG:' in str(crs):
            try:
                epsg = int(str(crs).split('EPSG:')[1].split()[0].strip('"\''))
            except (ValueError, IndexError):
                pass

    return {
        'point_count': point_count,
        'bbox': bbox,
        'statistics': stats_meta.get('statistic', []),
        'schema': extract_schema(info_meta, readers_meta),
        'density': hexbin_meta.get('avg_pt_per_sq_unit', 0),
        'geometry': hexbin_meta.get('boundary_json'),
        'crs': crs,
        'epsg': epsg
    }


def extract_bbox(
    stats_meta: Dict[str, Any],
    readers_meta: Dict[str, Any]
) -> List[float]:
    """Extract 6D bounding box [minx, miny, minz, maxx, maxy, maxz]."""
    # Try stats metadata first
    bbox_info = stats_meta.get('bbox', {})

    if 'native' in bbox_info:
        native = bbox_info['native'].get('bbox', {})
    elif 'EPSG:4326' in bbox_info:
        native = bbox_info['EPSG:4326'].get('bbox', {})
    else:
        native = bbox_info.get('bbox', bbox_info)

    if native:
        return [
            float(native.get('minx', 0)),
            float(native.get('miny', 0)),
            float(native.get('minz', 0)),
            float(native.get('maxx', 0)),
            float(native.get('maxy', 0)),
            float(native.get('maxz', 0))
        ]

    # Fallback to readers metadata
    return [
        float(readers_meta.get('minx', 0)),
        float(readers_meta.get('miny', 0)),
        float(readers_meta.get('minz', 0)),
        float(readers_meta.get('maxx', 0)),
        float(readers_meta.get('maxy', 0)),
        float(readers_meta.get('maxz', 0))
    ]


def extract_schema(
    info_meta: Dict[str, Any],
    readers_meta: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Extract dimension schema."""
    schema = info_meta.get('schema', {})
    dims = schema.get('dimensions', [])

    if dims:
        return dims

    # Fallback to readers metadata
    return readers_meta.get('dimensions', [])


def find_input_files(input_path: Path) -> List[Path]:
    """
    Find all LAS/LAZ files in input path.

    Args:
        input_path: File or directory path

    Returns:
        List of input file paths
    """
    if input_path.is_file():
        return [input_path]

    if input_path.is_dir():
        files = []
        for ext in ['*.las', '*.laz', '*.LAS', '*.LAZ']:
            files.extend(input_path.glob(ext))
        return sorted(files)

    return []


def process_files(
    input_files: List[Path],
    output_dir: Path,
    source_crs: Optional[str] = None,
    target_crs: Optional[str] = None,
    timeout: int = 3600
) -> List[Dict[str, Any]]:
    """
    Process multiple LAS/LAZ files.

    Args:
        input_files: List of input file paths
        output_dir: Output directory
        source_crs: CRS to assign to source files (if missing)
        target_crs: Optional target CRS for reprojection
        timeout: Timeout per file in seconds

    Returns:
        List of processing results
    """
    results = []

    for i, input_file in enumerate(tqdm(input_files, desc="Converting"), 1):
        output_file = output_dir / f"{input_file.stem}.copc.laz"
        metadata_file = output_dir / f"{input_file.stem}.metadata.json"

        logger.info(f"[{i}/{len(input_files)}] Processing: {input_file.name}")

        try:
            # Convert to COPC
            metadata = convert_to_copc(
                input_file,
                output_file,
                source_crs,
                target_crs,
                timeout
            )

            # Save metadata
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            results.append(metadata)

            logger.info(
                f"  -> Created: {output_file.name} "
                f"({metadata['point_count']:,} points, "
                f"{metadata['file_size_bytes'] / 1024 / 1024:.1f} MB)"
            )

        except Exception as e:
            logger.error(f"  -> Failed: {e}")
            results.append({
                'source_file': input_file.name,
                'error': str(e),
                'processing_time': datetime.now().isoformat()
            })

    return results


def write_summary(
    output_dir: Path,
    results: List[Dict[str, Any]]
) -> Path:
    """Write processing summary JSON."""
    summary_file = output_dir / 'processing_summary.json'

    successful = [r for r in results if 'error' not in r]
    failed = [r for r in results if 'error' in r]

    total_points = sum(r.get('point_count', 0) for r in successful)
    total_size = sum(r.get('file_size_bytes', 0) for r in successful)

    summary = {
        'processed_at': datetime.now().isoformat(),
        'total_files': len(results),
        'successful': len(successful),
        'failed': len(failed),
        'total_points': total_points,
        'total_size_bytes': total_size,
        'total_size_mb': round(total_size / 1024 / 1024, 2),
        'files': results
    }

    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary_file


def main():
    parser = argparse.ArgumentParser(
        description='Convert LAS/LAZ to COPC with metadata extraction',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --input-dir ./local/input --output-dir ./local/output
  %(prog)s --input-file ./data/sample.las --output-dir ./local/output
  %(prog)s --input-dir ./local/input --output-dir ./local/output --target-crs EPSG:6677
        """
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        '--input-dir', '-i',
        type=Path,
        help='Directory containing LAS/LAZ files'
    )
    input_group.add_argument(
        '--input-file', '-f',
        type=Path,
        help='Single LAS/LAZ file to process'
    )

    parser.add_argument(
        '--output-dir', '-o',
        type=Path,
        required=True,
        help='Output directory for COPC files and metadata'
    )

    parser.add_argument(
        '--source-crs', '-s',
        type=str,
        default=None,
        help='Assign CRS to source files if missing (e.g., EPSG:6677 for JGD2011 Zone 9)'
    )

    parser.add_argument(
        '--target-crs', '-c',
        type=str,
        default=None,
        help='Target CRS for reprojection (e.g., EPSG:4326 for WGS84)'
    )

    parser.add_argument(
        '--timeout', '-t',
        type=int,
        default=3600,
        help='Timeout per file in seconds (default: 3600)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check PDAL
    if not check_pdal_installed():
        logger.error("PDAL is not installed or not in PATH")
        logger.error("Install with: conda install -c conda-forge pdal")
        logger.error("Or: brew install pdal")
        sys.exit(1)

    # Find input files
    input_path = args.input_dir or args.input_file
    input_files = find_input_files(input_path)

    if not input_files:
        logger.error(f"No LAS/LAZ files found in: {input_path}")
        sys.exit(1)

    logger.info(f"Found {len(input_files)} point cloud file(s) to process")

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Process files
    results = process_files(
        input_files,
        args.output_dir,
        args.source_crs,
        args.target_crs,
        args.timeout
    )

    # Write summary
    summary_file = write_summary(args.output_dir, results)

    # Print summary
    successful = sum(1 for r in results if 'error' not in r)
    failed = sum(1 for r in results if 'error' in r)

    logger.info("=" * 60)
    logger.info("PROCESSING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Summary: {summary_file}")
    logger.info("")
    logger.info("Next step: python scripts/02-generate-stac.py")

    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
