# COPC 格式转换指南

## 什么是 COPC?

**COPC (Cloud Optimized Point Cloud)** 是一种针对云端优化的点云格式。

| 特性 | 传统 LAS/LAZ | COPC |
|-----|-------------|------|
| 加载方式 | 必须下载完整文件 | 支持流式加载（按需加载） |
| 网页预览 | 需要完整下载 | 可直接在浏览器预览 |
| 数据结构 | 线性存储 | 八叉树金字塔结构 |
| 文件大小 | 基准 | 略大（约 5-10%） |

简单来说：**COPC 让点云可以像地图瓦片一样，用户看到哪里就加载哪里**。

---

## PDAL 工作原理

### 什么是 PDAL?

**PDAL (Point Data Abstraction Library)** 是点云处理的"瑞士军刀"，类似于图像处理中的 GDAL。

```
PDAL 之于点云  =  GDAL 之于栅格图像  =  FFmpeg 之于视频
```

### 核心概念：Pipeline（管道）

PDAL 使用**管道模式**处理数据，由三种组件组成：

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Reader  │ -> │  Filter  │ -> │  Filter  │ -> │  Writer  │
│  读取器   │    │  过滤器   │    │  过滤器   │    │  写入器   │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
     │               │               │               │
   读取LAS        坐标变换        统计计算        输出COPC
```

| 组件类型 | 作用 | 常用示例 |
|---------|-----|---------|
| **Reader** | 读取输入文件 | `readers.las`, `readers.copc` |
| **Filter** | 处理/变换数据 | `filters.reprojection`, `filters.stats` |
| **Writer** | 输出结果文件 | `writers.copc`, `writers.las` |

### Pipeline JSON 示例

本项目使用的转换管道 (`config/pdal/las-to-copc.json`)：

```json
{
  "pipeline": [
    {
      "type": "readers.las",
      "filename": "input.las"
    },
    {
      "type": "filters.stats",
      "dimensions": "X,Y,Z,Intensity,Classification"
    },
    {
      "type": "writers.copc",
      "filename": "output.copc.laz"
    }
  ]
}
```

执行管道：
```bash
pdal pipeline my-pipeline.json
```

### 常用 Filter 说明

| Filter | 功能 | 使用场景 |
|--------|-----|---------|
| `filters.reprojection` | 坐标系转换 | JGD2011 -> WGS84 |
| `filters.stats` | 统计信息提取 | 获取点数、边界框 |
| `filters.range` | 按属性过滤 | 只保留地面点 |
| `filters.crop` | 空间裁剪 | 按边界框裁剪 |
| `filters.assign` | 赋值 | 设置分类值 |
| `filters.hexbin` | 密度计算 | 计算点密度 |

### 命令行 vs Python

**命令行方式：**
```bash
# 简单转换
pdal translate input.las output.copc.laz

# 使用管道文件
pdal pipeline convert.json

# 查看信息
pdal info input.las --stats
```

**Python 方式：**
```python
import pdal

pipeline = pdal.Pipeline(json.dumps({
    "pipeline": [
        {"type": "readers.las", "filename": "input.las"},
        {"type": "writers.copc", "filename": "output.copc.laz"}
    ]
}))
pipeline.execute()

# 获取元数据
metadata = pipeline.metadata
```

### 数据流动过程

```
                    ┌─────────────────────────────────────┐
                    │           PDAL Pipeline              │
                    │                                      │
  input.las ───────>│  Reader -> Filter -> ... -> Writer  │───────> output.copc.laz
                    │     │                         │      │
                    │     v                         v      │
                    │  [点云数组在内存中流动处理]          │
                    │                                      │
                    └─────────────────────────────────────┘
                                      │
                                      v
                              metadata.json (统计信息)
```

**关键特点：**
- 流式处理：不需要一次性加载全部数据到内存
- 可组合：多个 Filter 可以串联
- 可扩展：支持自定义 Filter 插件

---

## 快速开始

### 1. 安装 PDAL

```bash
# macOS
brew install pdal

# Linux (Ubuntu/Debian)
sudo apt install pdal

# Conda
conda install -c conda-forge pdal
```

### 2. 单文件转换

```bash
# 最简单的转换
pdal translate input.las output.copc.laz

# 指定坐标系（日本 JGD2011 Zone 9）
pdal translate input.las output.copc.laz \
  --readers.las.override_srs="EPSG:6677"
```

### 3. 批量转换（使用项目脚本）

```bash
# 将 local/input 目录下的所有 LAS/LAZ 转换为 COPC
python scripts/01-prepare-data.py \
  --input-dir ./local/input \
  --output-dir ./local/output

# 指定源坐标系
python scripts/01-prepare-data.py \
  --input-dir ./local/input \
  --output-dir ./local/output \
  --source-crs EPSG:6677
```

---

## 转换流程详解

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  LAS/LAZ    │ --> │    PDAL     │ --> │    COPC     │
│  点云文件   │     │   转换处理   │     │  .copc.laz  │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           v
                    ┌─────────────┐
                    │  元数据JSON  │
                    │ .metadata   │
                    └─────────────┘
```

转换过程会：
1. 读取原始 LAS/LAZ 文件
2. 提取统计信息（点数、边界框、分类等）
3. 构建八叉树空间索引
4. 输出 COPC 格式文件
5. 生成元数据 JSON 文件

---

## 日本点云数据处理

### 常用坐标系 (JGD2011 平面直角坐标系)

| 区域 | EPSG 代码 | 覆盖范围 |
|-----|----------|---------|
| Zone 1 | EPSG:6669 | 长崎县、�的�的一部分 |
| Zone 8 | EPSG:6676 | 新潟县、长野县、山梨县、静冈县 |
| Zone 9 | EPSG:6677 | 东京都、福岛县、栃木群、�的城县、千叶县、神奈川县 |
| Zone 10 | EPSG:6678 | 青森县、秋田县、山形县、�的手县、宫城县 |

### 转换示例

```bash
# 东京都点云（Zone 9）
python scripts/01-prepare-data.py \
  --input-dir ./local/input \
  --output-dir ./local/output \
  --source-crs EPSG:6677

# 转换为 WGS84（可选，用于全球兼容）
python scripts/01-prepare-data.py \
  --input-dir ./local/input \
  --output-dir ./local/output \
  --source-crs EPSG:6677 \
  --target-crs EPSG:4326
```

---

## 转换成功了吗？3 种方法验证

### 方法 1：命令行快速检查

```bash
# 看看文件基本信息（有多少点、范围多大）
pdal info output.copc.laz

# 示例输出：
# {
#   "file_size": 52428800,     <- 文件大小（字节）
#   "num_points": 12345678,    <- 点的数量
#   "minx": 139.5, "maxx": 139.6,  <- 经度范围
#   "miny": 35.6,  "maxy": 35.7,   <- 纬度范围
#   "minz": 0,     "maxz": 100     <- 高度范围（米）
# }
```

**判断标准：**
- `num_points` > 0 = 有数据
- `minx/maxx/miny/maxy` 合理 = 坐标正确
- 文件能打开不报错 = 格式正确

### 方法 2：网页预览（最直观）

打开浏览器访问：

| 方式 | 地址 | 说明 |
|-----|------|-----|
| 本项目查看器 | https://stac.uixai.org/viewer/ | 支持多文件 |
| copc.io | https://viewer.copc.io | 拖拽上传即可 |

**看到点云 = 转换成功！**

### 方法 3：桌面软件打开

下载 [CloudCompare](https://cloudcompare.org/)（免费），直接拖入 `.copc.laz` 文件。

---

## 转换后得到了什么？

转换完成后，`local/output` 文件夹里会有这些文件：

```
local/output/
│
├── 08LF6238.copc.laz        <- 点云数据（可以在网页预览）
├── 08LF6238.metadata.json   <- 这个点云的"身份证"
│
├── 08LF6239.copc.laz
├── 08LF6239.metadata.json
│
└── processing_summary.json  <- 所有文件的处理报告
```

### 文件说明

| 文件 | 是什么 | 有什么用 |
|-----|-------|---------|
| `.copc.laz` | 点云数据 | 上传到服务器，用户可以在网页预览 |
| `.metadata.json` | 元数据 | 记录点数、范围等信息，用于生成目录 |
| `processing_summary.json` | 汇总报告 | 检查哪些成功、哪些失败 |

### 元数据长什么样？

```json
{
  "point_count": 12345678,        // 有 1234 万个点
  "bbox": [139.5, 35.6, 0, 139.6, 35.7, 100],  // 范围：经度、纬度、高度
  "file_size_bytes": 52428800,    // 文件大小：约 50MB
  "epsg": 6677,                   // 坐标系代号
  "source_file": "08LF6238.las"   // 原始文件名
}
```

**通俗解释：**
- `point_count` = 这个点云有多少个"点"（像素的 3D 版本）
- `bbox` = 这块数据覆盖的地理范围（一个 3D 的盒子）
- `epsg` = 用的什么"地图投影"（日本用 6677，全球用 4326）

---

## 常见问题

### Q: 转换后文件变大了？
A: 正常现象。COPC 需要存储空间索引结构，通常比原始 LAZ 大 5-10%。换来的是流式加载能力。

### Q: 坐标系丢失了？
A: 使用 `--source-crs` 参数指定原始坐标系：
```bash
python scripts/01-prepare-data.py --source-crs EPSG:6677 ...
```

### Q: 转换很慢？
A: 点云转换是计算密集型任务。每亿点大约需要 5-10 分钟。可以通过 `--timeout` 调整超时时间。

### Q: 如何只转换部分文件？
A: 使用 `--input-file` 指定单个文件：
```bash
python scripts/01-prepare-data.py --input-file ./local/input/sample.las ...
```

---

## 日本点云数据的坐标系说明

### 背景知识

日本平面直角坐标系（JGD2011）的EPSG标准定义与常规GIS软件的默认行为有所不同：

| | EPSG标准定义 | 常规GIS软件默认 |
|---|---|---|
| **X轴** | 北向 (Northing) | 东向 (Easting) |
| **Y轴** | 东向 (Easting) | 北向 (Northing) |

但实际上，大多数日本点云数据的LAS文件已经按照**常规GIS格式**存储（X=Easting, Y=Northing），这与pyproj等库使用 `always_xy=True` 时的预期一致。

### 正确的转换方法

**对于山梨县及大多数日本点云数据，直接转换即可，无需交换X/Y轴：**

```json
{
  "pipeline": [
    {
      "type": "readers.las",
      "filename": "input.las"
    },
    {
      "type": "writers.copc",
      "filename": "output.copc.laz",
      "a_srs": "EPSG:6676"
    }
  ]
}
```

### 合并多个LAS文件

```json
{
  "pipeline": [
    {
      "type": "readers.las",
      "filename": "/path/to/data/*.las"
    },
    {
      "type": "filters.merge"
    },
    {
      "type": "writers.copc",
      "filename": "merged_output.copc.laz",
      "a_srs": "EPSG:6676"
    }
  ]
}
```

### 验证坐标正确性

转换完成后，使用 pyproj 验证坐标：

```python
from pyproj import Transformer

# 使用 always_xy=True，输入顺序为 (x, y) = (easting, northing)
transformer = Transformer.from_crs('EPSG:6676', 'EPSG:4326', always_xy=True)

# 从 pdal info 获取的坐标（minx, miny）
minx = 11614.87   # Easting
miny = -37831.21  # Northing

# 转换为经纬度
lon, lat = transformer.transform(minx, miny)
print(f"经纬度: {lat:.6f}°N, {lon:.6f}°E")
print(f"Google Maps: https://www.google.com/maps?q={lat},{lon}")
```

**判断标准：** 转换后的经纬度应该与数据来源地一致（例如山梨县春日居町约为 35.66°N, 138.63°E）。

### 常见错误：不必要的X/Y交换

如果转换时错误地交换了X/Y轴，会导致：
- 在地图上显示位置偏差几十甚至几百公里
- STAC Browser 地图预览显示错误位置

**错误示例（不要使用）：**
```json
{
  "pipeline": [
    {"type": "readers.las", "filename": "input.las"},
    {"type": "filters.ferry", "dimensions": "X=>SwapTemp"},
    {"type": "filters.assign", "value": ["X = Y", "Y = SwapTemp"]},
    {"type": "writers.copc", "filename": "output.copc.laz", "a_srs": "EPSG:6676"}
  ]
}
```

### 数据来源验证

处理新数据源时，建议先用小样本验证坐标正确性：

1. 转换一个文件
2. 用上述 pyproj 脚本验证经纬度
3. 在 Google Maps 上确认位置
4. 确认无误后批量处理

---

## 实际案例：富士山点云数据

### 数据来源

- **来源**: [山梨县点云数据 (geospatial.jp)](https://www.geospatial.jp/ckan/dataset/yamanashi-pointcloud-2024)
- **文件**: 52 个 LAS 文件（08ME 开头）
- **坐标系**: EPSG:6676 (JGD2011 Zone VIII)

### GIS 中显示的原始坐标

```
=== 原始坐标 (EPSG:6676) ===
X: 19600 ~ 20000 (Easting，米)
Y: -68700 ~ -68400 (Northing，米)
Z: 2507.01 ~ 2702.19 (海拔，米)
```

### 转换后的 WGS84 坐标

```
=== WGS84 坐标 ===
经度: 138.715730°E
纬度: 35.380566°N
```

### 位置验证

| 位置 | 纬度 | 经度 |
|------|------|------|
| **数据覆盖区域** | 35.38°N | 138.72°E |
| 富士山顶 | 35.3606°N | 138.7274°E |
| 富士山五合目 | 35.37°N | 138.73°E |

**结论**: 数据位于富士山西北坡，海拔 2500-2700m，位置正确。

[Google Maps 验证链接](https://www.google.com/maps?q=35.38056593117259,138.71572958867364)

### 转换命令

```bash
# 使用 convert-no-swap.py 脚本（直接转换，不交换X/Y）
python scripts/convert-no-swap.py \
  --input-dir ./local/input-fujisan \
  --output-dir ./local/output-fujisan \
  --epsg 6676
```

### 验证脚本

```python
from pyproj import Transformer

# 创建坐标转换器
transformer = Transformer.from_crs('EPSG:6676', 'EPSG:4326', always_xy=True)

# 富士山数据的坐标范围
minx, miny = 19600.0, -68700.0  # 从 pdal info 获取

# 转换为 WGS84
lon, lat = transformer.transform(minx, miny)

print(f"=== GIS中显示的原始坐标 (EPSG:6676) ===")
print(f"X: {minx} (Easting)")
print(f"Y: {miny} (Northing)")
print()
print(f"=== 转换后的WGS84坐标 ===")
print(f"经度: {lon:.6f}°E")
print(f"纬度: {lat:.6f}°N")
print(f"Google Maps: https://www.google.com/maps?q={lat},{lon}")
print()
print(f"=== 参考位置 ===")
print(f"富士山顶: 35.3606°N, 138.7274°E")
print(f"富士山五合目: 约 35.37°N, 138.73°E")
```

---

## 下一步

转换完成后，运行以下命令生成 STAC 目录：

```bash
python scripts/02-generate-stac.py
```

详情请参考 [architecture.md](./architecture.md)。
