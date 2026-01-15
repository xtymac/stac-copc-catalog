#!/usr/bin/env python3
"""
修复LAS文件的坐标轴问题

部分日本点云数据的X/Y轴定义与EPSG标准相反，
此脚本重新转换LAS文件为COPC，并交换X/Y轴。

Usage:
    python scripts/fix-coordinates.py --input-dir ./local/input --output-dir ./local/output-fixed
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def create_swap_pipeline(input_file: Path, output_file: Path, epsg: int = 6677) -> dict:
    """
    创建带X/Y轴交换的PDAL Pipeline

    Args:
        input_file: 输入LAS文件路径
        output_file: 输出COPC文件路径
        epsg: 坐标系EPSG代码

    Returns:
        Pipeline字典
    """
    return {
        "pipeline": [
            {
                "type": "readers.las",
                "filename": str(input_file)
            },
            {
                "type": "filters.ferry",
                "dimensions": "X=>SwapTemp"
            },
            {
                "type": "filters.assign",
                "value": ["X = Y", "Y = SwapTemp"]
            },
            {
                "type": "filters.stats"
            },
            {
                "type": "writers.copc",
                "filename": str(output_file),
                "a_srs": f"EPSG:{epsg}"
            }
        ]
    }


def convert_file(input_file: Path, output_dir: Path, epsg: int = 6677) -> dict:
    """
    转换单个文件

    Returns:
        包含转换结果的字典
    """
    output_file = output_dir / f"{input_file.stem}.copc.laz"
    pipeline = create_swap_pipeline(input_file, output_file, epsg)

    # 写入临时Pipeline文件
    pipeline_file = output_dir / f"{input_file.stem}_pipeline.json"
    with open(pipeline_file, 'w') as f:
        json.dump(pipeline, f, indent=2)

    logger.info(f"Converting: {input_file.name} -> {output_file.name}")

    try:
        result = subprocess.run(
            ['pdal', 'pipeline', str(pipeline_file)],
            capture_output=True,
            text=True,
            timeout=600  # 10分钟超时
        )

        if result.returncode != 0:
            logger.error(f"  Failed: {result.stderr}")
            return {
                "source_file": input_file.name,
                "success": False,
                "error": result.stderr
            }

        # 获取输出文件信息
        file_size = output_file.stat().st_size if output_file.exists() else 0

        # 获取元数据
        info_result = subprocess.run(
            ['pdal', 'info', str(output_file), '--metadata'],
            capture_output=True,
            text=True
        )

        metadata = {}
        if info_result.returncode == 0:
            try:
                info_data = json.loads(info_result.stdout)
                meta = info_data.get('metadata', {})
                metadata = {
                    "point_count": meta.get('count', 0),
                    "bbox": [
                        meta.get('minx', 0), meta.get('miny', 0), meta.get('minz', 0),
                        meta.get('maxx', 0), meta.get('maxy', 0), meta.get('maxz', 0)
                    ],
                    "epsg": epsg
                }
            except json.JSONDecodeError:
                pass

        # 保存元数据
        metadata_file = output_dir / f"{input_file.stem}.metadata.json"
        full_metadata = {
            **metadata,
            "source_file": input_file.name,
            "output_file": output_file.name,
            "file_size_bytes": file_size,
            "processing_time": datetime.now().isoformat(),
            "coordinate_fix": "X/Y axes swapped"
        }
        with open(metadata_file, 'w') as f:
            json.dump(full_metadata, f, indent=2)

        logger.info(f"  Success: {metadata.get('point_count', 0):,} points, {file_size / 1024 / 1024:.1f} MB")

        # 删除临时Pipeline文件
        pipeline_file.unlink()

        return {
            "source_file": input_file.name,
            "success": True,
            **full_metadata
        }

    except subprocess.TimeoutExpired:
        logger.error(f"  Timeout: {input_file.name}")
        return {
            "source_file": input_file.name,
            "success": False,
            "error": "Timeout"
        }
    except Exception as e:
        logger.error(f"  Error: {e}")
        return {
            "source_file": input_file.name,
            "success": False,
            "error": str(e)
        }


def main():
    parser = argparse.ArgumentParser(
        description='修复LAS文件的坐标轴问题（交换X/Y轴）'
    )

    parser.add_argument(
        '--input-dir', '-i',
        type=Path,
        required=True,
        help='输入LAS文件目录'
    )

    parser.add_argument(
        '--output-dir', '-o',
        type=Path,
        required=True,
        help='输出COPC文件目录'
    )

    parser.add_argument(
        '--epsg',
        type=int,
        default=6677,
        help='坐标系EPSG代码 (默认: 6677 - JGD2011 Zone 9)'
    )

    args = parser.parse_args()

    # 验证输入目录
    if not args.input_dir.exists():
        logger.error(f"输入目录不存在: {args.input_dir}")
        sys.exit(1)

    # 创建输出目录
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 获取所有LAS文件
    las_files = sorted(args.input_dir.glob('*.las'))
    if not las_files:
        las_files = sorted(args.input_dir.glob('*.laz'))

    if not las_files:
        logger.error("未找到LAS/LAZ文件")
        sys.exit(1)

    logger.info(f"找到 {len(las_files)} 个文件待处理")
    logger.info(f"输出目录: {args.output_dir}")
    logger.info(f"坐标系: EPSG:{args.epsg}")
    logger.info("=" * 60)

    # 转换所有文件
    results = []
    for las_file in las_files:
        result = convert_file(las_file, args.output_dir, args.epsg)
        results.append(result)

    # 保存汇总报告
    summary_file = args.output_dir / "processing_summary.json"
    summary = {
        "total_files": len(results),
        "successful": sum(1 for r in results if r.get('success')),
        "failed": sum(1 for r in results if not r.get('success')),
        "epsg": args.epsg,
        "coordinate_fix": "X/Y axes swapped",
        "processing_time": datetime.now().isoformat(),
        "files": results
    }
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)

    # 输出汇总
    logger.info("=" * 60)
    logger.info("处理完成")
    logger.info(f"  成功: {summary['successful']}")
    logger.info(f"  失败: {summary['failed']}")
    logger.info(f"  汇总: {summary_file}")


if __name__ == '__main__':
    main()
