#!/usr/bin/env python3
"""
Merge Multiple LAS/LAZ Files into a Single COPC File

Combines all point cloud files in a directory into one unified COPC file,
enabling cloud-native, on-demand access with spatial indexing.

Usage:
    python 07-merge-to-single-copc.py --input-dir ./local/input --output-file ./local/output-unified/unified.copc.laz
    python 07-merge-to-single-copc.py --input-dir ./local/input --output-file ./output.copc.laz --source-crs EPSG:6676
"""

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


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


def find_input_files(input_dir: Path) -> List[Path]:
    """
    Find all LAS/LAZ/COPC files in input directory.

    Args:
        input_dir: Directory containing point cloud files

    Returns:
        Sorted list of input file paths
    """
    files = []
    for ext in ['*.las', '*.laz', '*.LAS', '*.LAZ', '*.copc.laz']:
        files.extend(input_dir.glob(ext))
    # Remove duplicates (*.laz may match *.copc.laz)
    files = list(set(files))
    return sorted(files)


def get_file_info(file_path: Path, timeout: int = 120) -> Dict[str, Any]:
    """
    Get point cloud file metadata using PDAL info.

    Args:
        file_path: Path to LAS/LAZ file
        timeout: Timeout in seconds

    Returns:
        Dictionary with file metadata
    """
    cmd = ['pdal', 'info', '--summary', str(file_path)]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout
    )

    if result.returncode != 0:
        raise RuntimeError(f"PDAL info failed: {result.stderr}")

    return json.loads(result.stdout)


def build_merge_pipeline(
    input_files: List[Path],
    output_file: Path,
    source_crs: Optional[str] = None,
    target_crs: Optional[str] = None
) -> Dict[str, Any]:
    """
    Build PDAL pipeline for merging multiple files into single COPC.

    Args:
        input_files: List of input file paths
        output_file: Output COPC file path
        source_crs: CRS to assign to source files (e.g., EPSG:6676)
        target_crs: Optional target CRS for reprojection

    Returns:
        PDAL pipeline dictionary
    """
    stages = []

    # Add readers for all input files
    for f in input_files:
        reader_config = {
            "type": "readers.las",
            "filename": str(f)
        }
        if source_crs:
            reader_config["override_srs"] = source_crs
        stages.append(reader_config)

    # Merge all inputs
    stages.append({"type": "filters.merge"})

    # Optional reprojection
    if target_crs:
        stages.append({
            "type": "filters.reprojection",
            "out_srs": target_crs
        })

    # Extract statistics for metadata
    stages.append({
        "type": "filters.stats",
        "dimensions": "X,Y,Z,Intensity,ReturnNumber,NumberOfReturns,Classification",
        "enumerate": "Classification,ReturnNumber,NumberOfReturns"
    })

    # COPC writer
    writer_config = {
        "type": "writers.copc",
        "filename": str(output_file),
        "forward": "all"  # Preserve all metadata
    }
    stages.append(writer_config)

    return {"pipeline": stages}


def execute_pipeline(
    pipeline: Dict[str, Any],
    metadata_file: Optional[Path] = None,
    timeout: int = 7200
) -> Dict[str, Any]:
    """
    Execute PDAL pipeline.

    Args:
        pipeline: PDAL pipeline dictionary
        metadata_file: Optional path to save pipeline metadata
        timeout: Timeout in seconds (default 2 hours)

    Returns:
        Pipeline execution metadata
    """
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.json',
        delete=False
    ) as f:
        json.dump(pipeline, f, indent=2)
        pipeline_file = Path(f.name)

    try:
        cmd = ['pdal', 'pipeline', str(pipeline_file)]

        if metadata_file:
            cmd.append(f'--metadata={metadata_file}')

        logger.info(f"Executing PDAL pipeline...")
        logger.debug(f"Command: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if result.returncode != 0:
            raise RuntimeError(f"PDAL pipeline failed: {result.stderr}")

        # Read metadata if available
        if metadata_file and metadata_file.exists():
            with open(metadata_file) as f:
                return json.load(f)

        return {}

    finally:
        pipeline_file.unlink(missing_ok=True)


def extract_merged_metadata(
    output_file: Path,
    pipeline_metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Extract metadata from merged COPC file.

    Args:
        output_file: Path to output COPC file
        pipeline_metadata: Metadata from pipeline execution

    Returns:
        Cleaned metadata dictionary
    """
    # Get info from output file
    try:
        info = get_file_info(output_file)
        summary = info.get('summary', {})
    except Exception as e:
        logger.warning(f"Could not read output file info: {e}")
        summary = {}

    # Extract bbox from stats
    stats_meta = {}
    meta = pipeline_metadata.get('metadata', {})
    for key, value in meta.items():
        if 'filters.stats' in key:
            if isinstance(value, dict):
                stats_meta = value
                break

    bbox_info = stats_meta.get('bbox', {})
    native_bbox = bbox_info.get('native', {}).get('bbox', {})

    if native_bbox:
        bbox = [
            float(native_bbox.get('minx', 0)),
            float(native_bbox.get('miny', 0)),
            float(native_bbox.get('minz', 0)),
            float(native_bbox.get('maxx', 0)),
            float(native_bbox.get('maxy', 0)),
            float(native_bbox.get('maxz', 0))
        ]
    else:
        bbox = [
            float(summary.get('bounds', {}).get('minx', 0)),
            float(summary.get('bounds', {}).get('miny', 0)),
            float(summary.get('bounds', {}).get('minz', 0)),
            float(summary.get('bounds', {}).get('maxx', 0)),
            float(summary.get('bounds', {}).get('maxy', 0)),
            float(summary.get('bounds', {}).get('maxz', 0))
        ]

    return {
        'point_count': summary.get('num_points', 0),
        'bbox': bbox,
        'statistics': stats_meta.get('statistic', []),
        'file_size_bytes': output_file.stat().st_size,
        'processing_time': datetime.now().isoformat()
    }


def main():
    parser = argparse.ArgumentParser(
        description='Merge multiple LAS/LAZ files into a single COPC file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --input-dir ./local/input --output-file ./local/output-unified/unified.copc.laz
  %(prog)s --input-dir ./local/input --output-file ./output.copc.laz --source-crs EPSG:6676
        """
    )

    parser.add_argument(
        '--input-dir', '-i',
        type=Path,
        required=True,
        help='Directory containing LAS/LAZ files to merge'
    )

    parser.add_argument(
        '--output-file', '-o',
        type=Path,
        required=True,
        help='Output COPC file path'
    )

    parser.add_argument(
        '--source-crs', '-s',
        type=str,
        default=None,
        help='Assign CRS to source files (e.g., EPSG:6676 for JGD2011 Zone 8)'
    )

    parser.add_argument(
        '--target-crs', '-t',
        type=str,
        default=None,
        help='Target CRS for reprojection (optional)'
    )

    parser.add_argument(
        '--timeout',
        type=int,
        default=7200,
        help='Timeout in seconds (default: 7200 = 2 hours)'
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
        sys.exit(1)

    # Find input files
    input_files = find_input_files(args.input_dir)

    if not input_files:
        logger.error(f"No LAS/LAZ files found in: {args.input_dir}")
        sys.exit(1)

    logger.info(f"Found {len(input_files)} point cloud file(s) to merge:")
    for f in input_files:
        logger.info(f"  - {f.name}")

    # Create output directory
    args.output_file.parent.mkdir(parents=True, exist_ok=True)

    # Build pipeline
    pipeline = build_merge_pipeline(
        input_files,
        args.output_file,
        args.source_crs,
        args.target_crs
    )

    logger.info(f"Pipeline stages: {len(pipeline['pipeline'])}")

    # Metadata output file
    metadata_file = args.output_file.with_suffix('.pipeline-metadata.json')

    # Execute pipeline
    start_time = datetime.now()
    logger.info("Starting merge... (this may take a while)")

    try:
        pipeline_metadata = execute_pipeline(
            pipeline,
            metadata_file,
            args.timeout
        )
    except subprocess.TimeoutExpired:
        logger.error(f"Pipeline timed out after {args.timeout} seconds")
        sys.exit(1)

    elapsed = datetime.now() - start_time
    logger.info(f"Merge completed in {elapsed}")

    # Extract metadata
    metadata = extract_merged_metadata(args.output_file, pipeline_metadata)

    # Add source info
    metadata['source_files'] = [f.name for f in input_files]
    metadata['source_crs'] = args.source_crs
    metadata['target_crs'] = args.target_crs
    metadata['output_file'] = args.output_file.name

    # Save metadata
    final_metadata_file = args.output_file.with_suffix('.metadata.json')
    with open(final_metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # Cleanup temp metadata
    metadata_file.unlink(missing_ok=True)

    # Print summary
    logger.info("=" * 60)
    logger.info("MERGE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Output file: {args.output_file}")
    logger.info(f"File size: {metadata['file_size_bytes'] / 1024 / 1024:.1f} MB")
    logger.info(f"Point count: {metadata['point_count']:,}")
    logger.info(f"Bbox: {metadata['bbox']}")
    logger.info(f"Metadata: {final_metadata_file}")
    logger.info("")
    logger.info("Next steps:")
    logger.info("  1. python scripts/02-generate-stac.py --unified-mode ...")
    logger.info("  2. python scripts/08-demo-bbox-query.py")
    logger.info("  3. ./scripts/03-deploy-aws.sh")


if __name__ == '__main__':
    main()
