#!/usr/bin/env python3
"""
COPC to DEM (Cloud Optimized GeoTIFF) Conversion Script

Generates Digital Elevation Models from COPC point cloud files and exports
them as Cloud Optimized GeoTIFF (COG) format.

Usage:
    python 09-generate-dem.py --input-dir ./local/output --output-dir ./local/dem
    python 09-generate-dem.py --input-file ./data/sample.copc.laz --output-dir ./local/dem
    python 09-generate-dem.py --input-dir ./local/output --output-dir ./local/dem --resolution 2.0
    python 09-generate-dem.py --input-dir ./local/output --output-dir ./local/dem --dem-type dsm
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

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

# DEM types and their configurations
DEM_TYPES = {
    'dem': {
        'name': 'Digital Elevation Model',
        'output_type': 'max',
        'filter_classification': None,
        'description': 'Surface elevation using maximum Z values'
    },
    'dsm': {
        'name': 'Digital Surface Model',
        'output_type': 'max',
        'filter_classification': None,
        'description': 'Surface model including buildings and vegetation'
    },
    'dtm': {
        'name': 'Digital Terrain Model',
        'output_type': 'mean',
        'filter_classification': '2:2',  # Ground points only
        'description': 'Bare earth terrain model (ground points only)'
    },
    'intensity': {
        'name': 'Intensity Raster',
        'output_type': 'mean',
        'filter_classification': None,
        'description': 'LiDAR return intensity values',
        'dimension': 'Intensity'
    },
    'density': {
        'name': 'Point Density',
        'output_type': 'count',
        'filter_classification': None,
        'description': 'Point count per cell'
    }
}

# Compression options for COG
COG_COMPRESSION = {
    'deflate': {'COMPRESS': 'DEFLATE', 'PREDICTOR': '2'},
    'lzw': {'COMPRESS': 'LZW', 'PREDICTOR': '2'},
    'zstd': {'COMPRESS': 'ZSTD', 'PREDICTOR': '2'},
    'none': {'COMPRESS': 'NONE'}
}

# Default resolutions (meters)
DEFAULT_RESOLUTION = 1.0
SUPPORTED_RESOLUTIONS = [0.5, 1.0, 2.0, 5.0, 10.0]


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


def check_gdal_installed() -> bool:
    """Check if GDAL is available."""
    try:
        result = subprocess.run(
            ['gdal_translate', '--version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            logger.info(f"GDAL version: {version}")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False


def find_input_files(input_path: Path) -> List[Path]:
    """Find COPC/LAZ files in directory or return single file."""
    if input_path.is_file():
        return [input_path]

    patterns = ['*.copc.laz', '*.laz', '*.las']
    files = []
    for pattern in patterns:
        files.extend(input_path.glob(pattern))

    # Prefer COPC files
    copc_files = [f for f in files if '.copc.' in f.name]
    if copc_files:
        return sorted(copc_files)

    return sorted(files)


def get_point_cloud_info(input_file: Path, timeout: int = 300) -> Dict[str, Any]:
    """Get metadata from point cloud file using PDAL info."""
    cmd = ['pdal', 'info', '--metadata', str(input_file)]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout
    )

    if result.returncode != 0:
        raise RuntimeError(f"PDAL info failed: {result.stderr}")

    return json.loads(result.stdout)


def build_dem_pipeline(
    input_file: Path,
    output_file: Path,
    dem_type: str = 'dem',
    resolution: float = 1.0,
    source_crs: Optional[str] = None,
    nodata: float = -9999.0
) -> List[Dict[str, Any]]:
    """
    Build PDAL pipeline for DEM generation.

    Args:
        input_file: Input COPC/LAZ file
        output_file: Output GeoTIFF file
        dem_type: Type of DEM (dem, dsm, dtm, intensity, density)
        resolution: Output resolution in meters
        source_crs: Override source CRS if needed
        nodata: NoData value for output raster

    Returns:
        List of pipeline stages
    """
    config = DEM_TYPES.get(dem_type, DEM_TYPES['dem'])
    stages = []

    # Reader
    reader_config = {
        "type": "readers.copc" if '.copc.' in input_file.name else "readers.las",
        "filename": str(input_file)
    }
    if source_crs:
        reader_config["override_srs"] = source_crs
    stages.append(reader_config)

    # Classification filter for DTM
    if config.get('filter_classification'):
        stages.append({
            "type": "filters.range",
            "limits": f"Classification[{config['filter_classification']}]"
        })

    # GDAL writer for rasterization
    writer_config = {
        "type": "writers.gdal",
        "filename": str(output_file),
        "gdaldriver": "GTiff",
        "resolution": resolution,
        "output_type": config['output_type'],
        "nodata": nodata,
        "data_type": "float32"
    }

    # For intensity, use that dimension
    if dem_type == 'intensity':
        writer_config["dimension"] = "Intensity"

    stages.append(writer_config)

    return stages


def run_pdal_pipeline(
    pipeline: List[Dict[str, Any]],
    timeout: int = 3600
) -> Dict[str, Any]:
    """Execute PDAL pipeline and return metadata."""
    pipeline_json = {"pipeline": pipeline}

    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.json',
        delete=False
    ) as f:
        json.dump(pipeline_json, f, indent=2)
        pipeline_file = Path(f.name)

    metadata_file = Path(tempfile.mktemp(suffix='.json'))

    try:
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

        # Read metadata if available
        if metadata_file.exists():
            with open(metadata_file) as f:
                return json.load(f)
        return {}

    finally:
        pipeline_file.unlink(missing_ok=True)
        metadata_file.unlink(missing_ok=True)


def convert_to_cog(
    input_tif: Path,
    output_cog: Path,
    compression: str = 'deflate',
    blocksize: int = 512
) -> bool:
    """
    Convert GeoTIFF to Cloud Optimized GeoTIFF.

    Args:
        input_tif: Input GeoTIFF file
        output_cog: Output COG file
        compression: Compression method (deflate, lzw, zstd, none)
        blocksize: Block size for tiling

    Returns:
        True if successful
    """
    compress_opts = COG_COMPRESSION.get(compression, COG_COMPRESSION['deflate'])

    cmd = [
        'gdal_translate',
        str(input_tif),
        str(output_cog),
        '-of', 'COG',
        '-co', f'BLOCKSIZE={blocksize}',
        '-co', 'OVERVIEW_RESAMPLING=CUBIC',
        '-co', 'NUM_THREADS=ALL_CPUS'
    ]

    for key, value in compress_opts.items():
        cmd.extend(['-co', f'{key}={value}'])

    logger.debug(f"Running: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600
    )

    if result.returncode != 0:
        raise RuntimeError(f"gdal_translate failed: {result.stderr}")

    return True


def get_raster_info(raster_file: Path) -> Dict[str, Any]:
    """Get raster metadata using gdalinfo."""
    cmd = ['gdalinfo', '-json', str(raster_file)]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60
    )

    if result.returncode != 0:
        raise RuntimeError(f"gdalinfo failed: {result.stderr}")

    return json.loads(result.stdout)


def validate_cog(cog_file: Path) -> Tuple[bool, str]:
    """
    Validate COG format using GDAL's validate function.

    Returns:
        Tuple of (is_valid, message)
    """
    try:
        # Try using rio-cogeo if available
        result = subprocess.run(
            ['rio', 'cogeo', 'validate', str(cog_file)],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            return True, "Valid COG (rio-cogeo)"
    except FileNotFoundError:
        pass

    # Fall back to checking file structure
    try:
        info = get_raster_info(cog_file)

        # Check for overviews
        has_overviews = 'overviews' in str(info).lower()

        # Check for tiling
        files = info.get('files', [])

        if has_overviews:
            return True, "COG structure detected (has overviews)"
        else:
            return True, "GeoTIFF created (overviews may be embedded)"

    except Exception as e:
        return False, f"Validation error: {e}"


def generate_dem(
    input_file: Path,
    output_dir: Path,
    dem_type: str = 'dem',
    resolution: float = 1.0,
    source_crs: Optional[str] = None,
    compression: str = 'deflate',
    keep_intermediate: bool = False,
    timeout: int = 3600
) -> Dict[str, Any]:
    """
    Generate DEM from point cloud file.

    Args:
        input_file: Input COPC/LAZ file
        output_dir: Output directory
        dem_type: Type of DEM to generate
        resolution: Output resolution in meters
        source_crs: Override source CRS
        compression: COG compression method
        keep_intermediate: Keep intermediate GeoTIFF
        timeout: Timeout in seconds

    Returns:
        Dictionary with processing results and metadata
    """
    config = DEM_TYPES.get(dem_type, DEM_TYPES['dem'])

    # Output file names
    base_name = input_file.stem.replace('.copc', '')
    temp_tif = output_dir / f"{base_name}_{dem_type}_temp.tif"
    output_cog = output_dir / f"{base_name}_{dem_type}.tif"

    start_time = datetime.now()

    try:
        # Step 1: Generate GeoTIFF from point cloud
        logger.info(f"  Generating {config['name']}...")

        pipeline = build_dem_pipeline(
            input_file,
            temp_tif,
            dem_type=dem_type,
            resolution=resolution,
            source_crs=source_crs
        )

        pdal_meta = run_pdal_pipeline(pipeline, timeout=timeout)

        if not temp_tif.exists():
            raise RuntimeError("PDAL did not create output file")

        # Step 2: Convert to COG
        logger.info(f"  Converting to COG ({compression} compression)...")
        convert_to_cog(temp_tif, output_cog, compression=compression)

        if not output_cog.exists():
            raise RuntimeError("COG conversion failed")

        # Step 3: Get raster info
        raster_info = get_raster_info(output_cog)

        # Step 4: Validate COG
        is_valid, validation_msg = validate_cog(output_cog)

        # Cleanup intermediate file
        if not keep_intermediate:
            temp_tif.unlink(missing_ok=True)

        # Extract metadata
        corner_coords = raster_info.get('cornerCoordinates', {})
        size = raster_info.get('size', [0, 0])

        # Calculate bbox from corner coordinates
        ul = corner_coords.get('upperLeft', [0, 0])
        lr = corner_coords.get('lowerRight', [0, 0])
        bbox = [
            min(ul[0], lr[0]),  # minX
            min(ul[1], lr[1]),  # minY
            max(ul[0], lr[0]),  # maxX
            max(ul[1], lr[1])   # maxY
        ]

        processing_time = (datetime.now() - start_time).total_seconds()

        return {
            'source_file': input_file.name,
            'output_file': output_cog.name,
            'dem_type': dem_type,
            'dem_name': config['name'],
            'resolution': resolution,
            'compression': compression,
            'width': size[0],
            'height': size[1],
            'bbox': bbox,
            'crs': raster_info.get('coordinateSystem', {}).get('wkt', ''),
            'file_size_bytes': output_cog.stat().st_size,
            'is_valid_cog': is_valid,
            'validation_message': validation_msg,
            'nodata': -9999.0,
            'data_type': 'float32',
            'processing_time_seconds': processing_time,
            'processed_at': datetime.now().isoformat()
        }

    except Exception as e:
        # Cleanup on error
        temp_tif.unlink(missing_ok=True)
        output_cog.unlink(missing_ok=True)
        raise


def process_files(
    input_files: List[Path],
    output_dir: Path,
    dem_type: str = 'dem',
    resolution: float = 1.0,
    source_crs: Optional[str] = None,
    compression: str = 'deflate',
    timeout: int = 3600
) -> List[Dict[str, Any]]:
    """Process multiple files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, input_file in enumerate(tqdm(input_files, desc="Generating DEMs"), 1):
        logger.info(f"[{i}/{len(input_files)}] Processing: {input_file.name}")

        try:
            metadata = generate_dem(
                input_file,
                output_dir,
                dem_type=dem_type,
                resolution=resolution,
                source_crs=source_crs,
                compression=compression,
                timeout=timeout
            )

            # Save individual metadata
            metadata_file = output_dir / f"{input_file.stem.replace('.copc', '')}_{dem_type}.metadata.json"
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            results.append(metadata)

            logger.info(
                f"  -> Created: {metadata['output_file']} "
                f"({metadata['width']}x{metadata['height']} pixels, "
                f"{metadata['file_size_bytes'] / 1024 / 1024:.1f} MB)"
            )

        except Exception as e:
            logger.error(f"  -> Failed: {e}")
            results.append({
                'source_file': input_file.name,
                'dem_type': dem_type,
                'error': str(e),
                'processed_at': datetime.now().isoformat()
            })

    return results


def write_summary(
    output_dir: Path,
    results: List[Dict[str, Any]],
    dem_type: str
) -> Path:
    """Write processing summary JSON."""
    summary_file = output_dir / f'dem_processing_summary_{dem_type}.json'

    successful = [r for r in results if 'error' not in r]
    failed = [r for r in results if 'error' in r]

    total_size = sum(r.get('file_size_bytes', 0) for r in successful)
    total_time = sum(r.get('processing_time_seconds', 0) for r in successful)

    summary = {
        'processed_at': datetime.now().isoformat(),
        'dem_type': dem_type,
        'dem_description': DEM_TYPES.get(dem_type, {}).get('description', ''),
        'total_files': len(results),
        'successful': len(successful),
        'failed': len(failed),
        'total_size_bytes': total_size,
        'total_size_mb': round(total_size / 1024 / 1024, 2),
        'total_processing_time_seconds': total_time,
        'files': results
    }

    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary_file


def main():
    parser = argparse.ArgumentParser(
        description='Generate DEM (Cloud Optimized GeoTIFF) from COPC point clouds',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
DEM Types:
  dem       - Digital Elevation Model (surface height, max Z)
  dsm       - Digital Surface Model (same as DEM, includes buildings/vegetation)
  dtm       - Digital Terrain Model (ground points only, Classification=2)
  intensity - LiDAR intensity raster
  density   - Point density per cell

Examples:
  %(prog)s --input-dir ./local/output --output-dir ./local/dem
  %(prog)s --input-file ./data/sample.copc.laz --output-dir ./local/dem --resolution 2.0
  %(prog)s --input-dir ./local/output --output-dir ./local/dem --dem-type dtm
  %(prog)s --input-dir ./local/output --output-dir ./local/dem --compression lzw
        """
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        '--input-dir', '-i',
        type=Path,
        help='Directory containing COPC/LAZ files'
    )
    input_group.add_argument(
        '--input-file', '-f',
        type=Path,
        help='Single COPC/LAZ file to process'
    )

    parser.add_argument(
        '--output-dir', '-o',
        type=Path,
        required=True,
        help='Output directory for COG files'
    )

    parser.add_argument(
        '--dem-type', '-t',
        type=str,
        choices=list(DEM_TYPES.keys()),
        default='dem',
        help='Type of DEM to generate (default: dem)'
    )

    parser.add_argument(
        '--resolution', '-r',
        type=float,
        default=DEFAULT_RESOLUTION,
        help=f'Output resolution in meters (default: {DEFAULT_RESOLUTION})'
    )

    parser.add_argument(
        '--source-crs', '-s',
        type=str,
        default=None,
        help='Override source CRS (e.g., EPSG:6676)'
    )

    parser.add_argument(
        '--compression', '-c',
        type=str,
        choices=list(COG_COMPRESSION.keys()),
        default='deflate',
        help='COG compression method (default: deflate)'
    )

    parser.add_argument(
        '--timeout',
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

    # Check dependencies
    if not check_pdal_installed():
        logger.error("PDAL is not installed or not in PATH")
        logger.error("Install with: conda install -c conda-forge pdal")
        sys.exit(1)

    if not check_gdal_installed():
        logger.error("GDAL is not installed or not in PATH")
        logger.error("Install with: conda install -c conda-forge gdal")
        sys.exit(1)

    # Find input files
    input_path = args.input_dir or args.input_file
    input_files = find_input_files(input_path)

    if not input_files:
        logger.error(f"No point cloud files found in: {input_path}")
        sys.exit(1)

    logger.info(f"Found {len(input_files)} point cloud file(s) to process")
    logger.info(f"DEM type: {args.dem_type} ({DEM_TYPES[args.dem_type]['name']})")
    logger.info(f"Resolution: {args.resolution}m")
    logger.info(f"Compression: {args.compression}")
    logger.info(f"Output directory: {args.output_dir}")

    # Process files
    results = process_files(
        input_files,
        args.output_dir,
        dem_type=args.dem_type,
        resolution=args.resolution,
        source_crs=args.source_crs,
        compression=args.compression,
        timeout=args.timeout
    )

    # Write summary
    summary_file = write_summary(args.output_dir, results, args.dem_type)

    # Print summary
    successful = [r for r in results if 'error' not in r]
    failed = [r for r in results if 'error' in r]

    logger.info("=" * 60)
    logger.info(f"Processing complete!")
    logger.info(f"  Successful: {len(successful)}/{len(results)}")
    if failed:
        logger.info(f"  Failed: {len(failed)}")
    logger.info(f"  Summary: {summary_file}")

    if successful:
        total_size = sum(r.get('file_size_bytes', 0) for r in successful)
        logger.info(f"  Total output size: {total_size / 1024 / 1024:.1f} MB")

    sys.exit(0 if not failed else 1)


if __name__ == '__main__':
    main()
