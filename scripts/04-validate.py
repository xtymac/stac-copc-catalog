#!/usr/bin/env python3
"""
STAC Catalog Validation Script

Validates:
1. PySTAC structural validation
2. Point cloud extension compliance
3. Asset accessibility (optional URL checks)
4. PDAL readers.stac compatibility test (optional)

Usage:
    python 04-validate.py --catalog-dir ./catalog
    python 04-validate.py --catalog-dir ./catalog --check-urls
    python 04-validate.py --catalog-dir ./catalog --test-pdal https://stac.example.com/items/sample.json
"""

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import pystac
from pystac.validation import validate_all

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Point cloud extension required fields
PC_REQUIRED_FIELDS = ['pc:count', 'pc:type']
PC_RECOMMENDED_FIELDS = ['pc:encoding', 'pc:schemas', 'pc:density', 'pc:statistics']


def validate_stac_structure(catalog_path: Path) -> Dict[str, Any]:
    """
    Validate STAC catalog structure using PySTAC.

    Args:
        catalog_path: Path to catalog.json

    Returns:
        Validation results dictionary
    """
    results = {
        'valid': True,
        'errors': [],
        'warnings': [],
        'statistics': {
            'catalogs': 0,
            'collections': 0,
            'items': 0
        }
    }

    try:
        # Load catalog
        catalog = pystac.read_file(str(catalog_path))

        if not isinstance(catalog, pystac.Catalog):
            results['valid'] = False
            results['errors'].append({
                'type': 'structure',
                'message': 'Root file is not a valid STAC Catalog'
            })
            return results

        results['statistics']['catalogs'] = 1

        # Count and validate collections
        collections = list(catalog.get_children())
        results['statistics']['collections'] = len(collections)

        for collection in collections:
            if isinstance(collection, pystac.Collection):
                logger.info(f"Validating collection: {collection.id}")

                try:
                    # Validate collection
                    collection.validate()
                    logger.info(f"  [VALID] Collection: {collection.id}")
                except Exception as e:
                    results['valid'] = False
                    results['errors'].append({
                        'type': 'collection',
                        'id': collection.id,
                        'error': str(e)
                    })
                    logger.error(f"  [INVALID] Collection {collection.id}: {e}")

        # Count and validate items
        items = list(catalog.get_items(recursive=True))
        results['statistics']['items'] = len(items)

        for item in items:
            logger.info(f"Validating item: {item.id}")

            try:
                # Validate item structure
                validate_all(item.to_dict())
                logger.info(f"  [VALID] Item: {item.id}")

            except Exception as e:
                results['valid'] = False
                results['errors'].append({
                    'type': 'item',
                    'id': item.id,
                    'error': str(e)
                })
                logger.error(f"  [INVALID] Item {item.id}: {e}")

        logger.info(f"Found {len(collections)} collections and {len(items)} items")

    except Exception as e:
        results['valid'] = False
        results['errors'].append({
            'type': 'catalog',
            'error': str(e)
        })
        logger.error(f"Catalog validation failed: {e}")

    return results


def validate_pointcloud_extension(catalog_path: Path) -> Dict[str, Any]:
    """
    Validate point cloud extension fields on items.

    Args:
        catalog_path: Path to catalog.json

    Returns:
        Validation results dictionary
    """
    results = {
        'valid': True,
        'errors': [],
        'warnings': [],
        'items_checked': 0
    }

    try:
        catalog = pystac.read_file(str(catalog_path))

        for item in catalog.get_items(recursive=True):
            results['items_checked'] += 1

            # Check required fields
            for field in PC_REQUIRED_FIELDS:
                if field not in item.properties:
                    results['valid'] = False
                    results['errors'].append({
                        'item': item.id,
                        'field': field,
                        'type': 'missing_required'
                    })
                    logger.error(f"  {item.id}: Missing required field '{field}'")

            # Check recommended fields (warnings only)
            for field in PC_RECOMMENDED_FIELDS:
                if field not in item.properties:
                    results['warnings'].append({
                        'item': item.id,
                        'field': field,
                        'type': 'missing_recommended'
                    })
                    logger.warning(f"  {item.id}: Missing recommended field '{field}'")

            # Validate field values
            pc_count = item.properties.get('pc:count')
            if pc_count is not None and not isinstance(pc_count, int):
                results['errors'].append({
                    'item': item.id,
                    'field': 'pc:count',
                    'type': 'invalid_type',
                    'expected': 'integer',
                    'got': type(pc_count).__name__
                })
                logger.error(f"  {item.id}: pc:count should be integer, got {type(pc_count).__name__}")

            pc_type = item.properties.get('pc:type')
            if pc_type and pc_type not in ['lidar', 'eopc', 'radar', 'sonar', 'other']:
                results['warnings'].append({
                    'item': item.id,
                    'field': 'pc:type',
                    'type': 'non_standard_value',
                    'value': pc_type
                })

            # Check for data asset
            if 'data' not in item.assets:
                results['warnings'].append({
                    'item': item.id,
                    'type': 'missing_data_asset'
                })
                logger.warning(f"  {item.id}: No 'data' asset found")

    except Exception as e:
        results['valid'] = False
        results['errors'].append({
            'type': 'validation_error',
            'error': str(e)
        })

    return results


def check_asset_urls(catalog_path: Path, timeout: int = 10) -> Dict[str, Any]:
    """
    Check if asset URLs are accessible.

    Args:
        catalog_path: Path to catalog.json
        timeout: Request timeout in seconds

    Returns:
        URL check results dictionary
    """
    import urllib.request
    import urllib.error

    results = {
        'checked': 0,
        'accessible': 0,
        'failed': [],
        'errors': []
    }

    try:
        catalog = pystac.read_file(str(catalog_path))

        for item in catalog.get_items(recursive=True):
            for asset_key, asset in item.assets.items():
                url = asset.href

                # Skip relative URLs
                parsed = urlparse(url)
                if not parsed.scheme:
                    continue

                results['checked'] += 1
                logger.info(f"Checking: {url}")

                try:
                    req = urllib.request.Request(url, method='HEAD')
                    req.add_header('User-Agent', 'STAC-Validator/1.0')

                    with urllib.request.urlopen(req, timeout=timeout) as response:
                        if response.status == 200:
                            results['accessible'] += 1
                            logger.info(f"  [OK] {asset_key}")
                        else:
                            results['failed'].append({
                                'item': item.id,
                                'asset': asset_key,
                                'url': url,
                                'status': response.status
                            })
                            logger.warning(f"  [WARN] {asset_key}: status {response.status}")

                except urllib.error.HTTPError as e:
                    results['failed'].append({
                        'item': item.id,
                        'asset': asset_key,
                        'url': url,
                        'error': str(e)
                    })
                    logger.error(f"  [FAIL] {asset_key}: {e}")

                except Exception as e:
                    results['errors'].append({
                        'item': item.id,
                        'asset': asset_key,
                        'url': url,
                        'error': str(e)
                    })
                    logger.error(f"  [ERROR] {asset_key}: {e}")

    except Exception as e:
        results['errors'].append({
            'type': 'check_error',
            'error': str(e)
        })

    return results


def test_pdal_stac_reader(item_url: str, timeout: int = 120) -> Dict[str, Any]:
    """
    Test PDAL readers.stac compatibility.

    Args:
        item_url: URL to STAC item JSON
        timeout: PDAL execution timeout

    Returns:
        Test results dictionary
    """
    results = {
        'valid': False,
        'error': None,
        'point_count': 0,
        'metadata': {}
    }

    try:
        # Check if PDAL is available
        version_check = subprocess.run(
            ['pdal', '--version'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if version_check.returncode != 0:
            results['error'] = "PDAL not available"
            return results

        # Build PDAL pipeline
        pipeline = {
            "pipeline": [
                {
                    "type": "readers.stac",
                    "filename": item_url,
                    "asset_names": ["data"]
                },
                {
                    "type": "filters.stats"
                }
            ]
        }

        # Write pipeline to temp file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False
        ) as f:
            json.dump(pipeline, f)
            pipeline_file = Path(f.name)

        # Metadata output file
        metadata_file = pipeline_file.with_suffix('.metadata.json')

        try:
            # Execute PDAL
            cmd = [
                'pdal', 'pipeline',
                str(pipeline_file),
                f'--metadata={metadata_file}'
            ]

            logger.info(f"Running PDAL pipeline: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.returncode == 0:
                results['valid'] = True

                # Read metadata if available
                if metadata_file.exists():
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                        results['metadata'] = metadata

                        # Extract point count
                        for key, value in metadata.get('metadata', {}).items():
                            if 'readers' in key and isinstance(value, dict):
                                results['point_count'] = value.get('count', 0)
                                break

                logger.info(f"PDAL test passed: {results['point_count']} points")
            else:
                results['error'] = result.stderr or "PDAL pipeline failed"
                logger.error(f"PDAL test failed: {results['error']}")

        finally:
            # Cleanup
            pipeline_file.unlink(missing_ok=True)
            metadata_file.unlink(missing_ok=True)

    except subprocess.TimeoutExpired:
        results['error'] = f"PDAL execution timed out after {timeout}s"
    except FileNotFoundError:
        results['error'] = "PDAL not installed or not in PATH"
    except Exception as e:
        results['error'] = str(e)

    return results


def write_report(
    output_file: Path,
    structure_results: Dict[str, Any],
    pc_results: Dict[str, Any],
    url_results: Optional[Dict[str, Any]] = None,
    pdal_results: Optional[Dict[str, Any]] = None
) -> None:
    """Write validation report to JSON file."""
    report = {
        'timestamp': __import__('datetime').datetime.now().isoformat(),
        'structural_validation': structure_results,
        'pointcloud_extension': pc_results,
        'overall_valid': structure_results['valid'] and pc_results['valid']
    }

    if url_results:
        report['url_accessibility'] = url_results

    if pdal_results:
        report['pdal_compatibility'] = pdal_results
        report['overall_valid'] = report['overall_valid'] and pdal_results['valid']

    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description='Validate STAC catalog',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --catalog-dir ./catalog
  %(prog)s --catalog-dir ./catalog --check-urls
  %(prog)s --catalog-dir ./catalog --test-pdal https://stac.example.com/items/sample.json
        """
    )

    parser.add_argument(
        '--catalog-dir', '-c',
        type=Path,
        required=True,
        help='Directory containing STAC catalog'
    )

    parser.add_argument(
        '--check-urls',
        action='store_true',
        help='Check if asset URLs are accessible'
    )

    parser.add_argument(
        '--test-pdal',
        type=str,
        default=None,
        help='URL of STAC item to test with PDAL readers.stac'
    )

    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=None,
        help='Output file for validation report (default: catalog-dir/validation_report.json)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Find catalog.json
    catalog_path = args.catalog_dir / 'catalog.json'
    if not catalog_path.exists():
        logger.error(f"Catalog not found: {catalog_path}")
        sys.exit(1)

    print("=" * 60)
    print("STAC CATALOG VALIDATION")
    print("=" * 60)
    print()

    # 1. Structural validation
    print("1. Structural Validation")
    print("-" * 40)
    structure_results = validate_stac_structure(catalog_path)
    print()

    # 2. Point cloud extension validation
    print("2. Point Cloud Extension Validation")
    print("-" * 40)
    pc_results = validate_pointcloud_extension(catalog_path)
    print()

    # 3. URL accessibility (optional)
    url_results = None
    if args.check_urls:
        print("3. URL Accessibility Check")
        print("-" * 40)
        url_results = check_asset_urls(catalog_path)
        print()

    # 4. PDAL test (optional)
    pdal_results = None
    if args.test_pdal:
        print("4. PDAL readers.stac Test")
        print("-" * 40)
        pdal_results = test_pdal_stac_reader(args.test_pdal)
        print()

    # Write report
    output_file = args.output or (args.catalog_dir / 'validation_report.json')
    write_report(output_file, structure_results, pc_results, url_results, pdal_results)

    # Print summary
    print("=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    all_valid = structure_results['valid'] and pc_results['valid']

    print(f"Structural:          {'PASS' if structure_results['valid'] else 'FAIL'}")
    print(f"  - Collections: {structure_results['statistics']['collections']}")
    print(f"  - Items: {structure_results['statistics']['items']}")
    print(f"  - Errors: {len(structure_results['errors'])}")

    print(f"Point Cloud Extension: {'PASS' if pc_results['valid'] else 'FAIL'}")
    print(f"  - Items checked: {pc_results['items_checked']}")
    print(f"  - Errors: {len(pc_results['errors'])}")
    print(f"  - Warnings: {len(pc_results['warnings'])}")

    if url_results:
        print(f"URL Accessibility:   {url_results['accessible']}/{url_results['checked']} accessible")

    if pdal_results:
        print(f"PDAL Compatibility:  {'PASS' if pdal_results['valid'] else 'FAIL'}")
        if pdal_results['valid']:
            print(f"  - Points: {pdal_results['point_count']:,}")
        if pdal_results.get('error'):
            print(f"  - Error: {pdal_results['error']}")
        all_valid = all_valid and pdal_results['valid']

    print()
    print(f"Overall: {'PASS' if all_valid else 'FAIL'}")
    print(f"Report: {output_file}")
    print()

    if all_valid:
        print("Next step: ./scripts/03-deploy-aws.sh --create")
    else:
        print("Please fix the validation errors before deploying.")

    sys.exit(0 if all_valid else 1)


if __name__ == '__main__':
    main()
