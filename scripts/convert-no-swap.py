#!/usr/bin/env python3
"""
正确的LAS到COPC转换脚本 - 不交换X/Y轴

山梨县点云数据的LAS文件坐标格式已经是正确的（X=Easting, Y=Northing），
直接转换即可，不需要交换X/Y轴。

Usage:
    python scripts/convert-no-swap.py --input-dir ./local/input --output-dir ./local/output-fixed-v3 --epsg 6676
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime


def convert_file(input_file: Path, output_dir: Path, epsg: int = 6676) -> dict:
    """转换单个LAS文件到COPC（不交换X/Y）"""
    output_file = output_dir / f"{input_file.stem}.copc.laz"

    # 简单的Pipeline - 直接转换，不交换坐标
    pipeline = {
        "pipeline": [
            {
                "type": "readers.las",
                "filename": str(input_file)
            },
            {
                "type": "writers.copc",
                "filename": str(output_file),
                "a_srs": f"EPSG:{epsg}"
            }
        ]
    }

    pipeline_file = output_dir / f"{input_file.stem}_pipeline.json"
    with open(pipeline_file, 'w') as f:
        json.dump(pipeline, f, indent=2)

    print(f"Converting: {input_file.name} -> {output_file.name}")

    try:
        result = subprocess.run(
            ['pdal', 'pipeline', str(pipeline_file)],
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            print(f"  Failed: {result.stderr}")
            return {"success": False, "error": result.stderr}

        # 获取文件信息
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
            "coordinate_fix": "none (original coordinates preserved)"
        }
        with open(metadata_file, 'w') as f:
            json.dump(full_metadata, f, indent=2)

        print(f"  Success: {metadata.get('point_count', 0):,} points, {file_size / 1024 / 1024:.1f} MB")

        # 删除临时Pipeline文件
        pipeline_file.unlink()

        return {"success": True, **full_metadata}

    except subprocess.TimeoutExpired:
        print(f"  Timeout")
        return {"success": False, "error": "Timeout"}
    except Exception as e:
        print(f"  Error: {e}")
        return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description='LAS到COPC转换（保持原始坐标）')
    parser.add_argument('--input-dir', '-i', type=Path, required=True)
    parser.add_argument('--output-dir', '-o', type=Path, required=True)
    parser.add_argument('--epsg', type=int, default=6676)

    args = parser.parse_args()

    if not args.input_dir.exists():
        print(f"输入目录不存在: {args.input_dir}")
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    las_files = sorted(args.input_dir.glob('*.las'))
    if not las_files:
        las_files = sorted(args.input_dir.glob('*.laz'))

    if not las_files:
        print("未找到LAS/LAZ文件")
        sys.exit(1)

    print(f"找到 {len(las_files)} 个文件")
    print(f"输出目录: {args.output_dir}")
    print(f"坐标系: EPSG:{args.epsg}")
    print("=" * 60)

    results = []
    for las_file in las_files:
        result = convert_file(las_file, args.output_dir, args.epsg)
        results.append(result)

    success = sum(1 for r in results if r.get('success'))
    print("=" * 60)
    print(f"完成: {success}/{len(results)} 成功")


if __name__ == '__main__':
    main()
