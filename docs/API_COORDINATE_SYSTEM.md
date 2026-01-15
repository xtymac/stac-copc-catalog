# API 坐标系支持

本文档描述 STAC COPC Catalog 的坐标系支持和空间查询 API。

## 概述

COPC 数据保持原始坐标系（如日本平面直角坐标系 JGD2011），以确保毫米级精度。API 支持两种坐标系的 bbox 查询：

| 坐标系 | 精度 | 用途 |
|--------|------|------|
| **原始坐标系** (EPSG:6669-6687) | 毫米级 | 专业测量、工程应用 |
| **WGS84** (EPSG:4326) | 米级 | 地图显示、Web 应用 |

## 支持的日本平面直角坐标系 (JGD2011)

| Zone | EPSG | 中央经度 | 适用地区 |
|------|------|----------|----------|
| 1 | 6669 | 129.5° | 长崎县西部 |
| 2 | 6670 | 131° | 福�的 |
| 3 | 6671 | 132.1667° | 山口县 |
| 4 | 6672 | 133.5° | 香川县 |
| 5 | 6673 | 134.3333° | �的�的 |
| 6 | 6674 | 136° | 石川县 |
| 7 | 6675 | 137.1667° | 富山县 |
| **8** | **6676** | **138.5°** | **山梨县、静冈县（富士山地区）** |
| **9** | **6677** | **139.8333°** | **东京都、神奈川县** |
| 10 | 6678 | 140.8333° | �的城县 |
| 11 | 6679 | 140.25° | 北海道南部 |
| 12 | 6680 | 142.25° | 北海道中部 |
| 13 | 6681 | 144.25° | 北海道东部 |

## Selector 界面

### 功能

1. **OpenLayers 地图** - 显示 WGS84 底图，叠加数据集边界
2. **proj4js 坐标转换** - WGS84 ↔ 原始坐标系实时转换
3. **双坐标显示** - 框选后同时显示 WGS84 和原始坐标系 bbox
4. **API 代码生成** - 自动生成使用原始坐标系的代码示例
5. **Jupyter Notebook** - 一键生成可在 Colab 运行的 notebook

### URL

```
https://stac.uixai.org/potree/selector.html
```

### 坐标显示示例

```
Selected Bbox:
WGS84: [138.727123, 35.361234, 138.731456, 35.365678]
EPSG:6676 (Zone 8): [12684.53, -36999.49, 13089.08, -36836.87] m
```

## Potree Viewer API

### URL 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `files` | string | COPC 文件 URL（多个用逗号分隔） |
| `bbox` | string | 边界框 `minX,minY,maxX,maxY` |
| `bbox_crs` | number | bbox 坐标系 EPSG 代码（可选） |
| `pointSize` | number | 点大小（默认 1） |
| `budget` | number | 点预算（默认 5000000） |
| `c` | string | 颜色模式：rgba, rgb, elevation, intensity |

### bbox 自动检测

Viewer 会根据坐标值自动判断坐标系：
- `|值| > 180` → 原始坐标系（米）
- `|值| ≤ 180` → WGS84（度）

### 示例 URL

```bash
# 原始坐标系 bbox（推荐，更精确）
https://stac.uixai.org/potree/index.html?files=https://stac.uixai.org/data/kasugai_station.copc.laz&bbox=12684.53,-36999.49,13089.08,-36836.87

# WGS84 bbox（自动检测）
https://stac.uixai.org/potree/index.html?files=https://stac.uixai.org/data/kasugai_station.copc.laz&bbox=138.727,35.361,138.731,35.365
```

## Python API

### 使用 laspy（简单，适合 Colab）

```python
import laspy
import numpy as np
import requests
from io import BytesIO

# COPC 文件 URL
url = 'https://stac.uixai.org/data/kasugai_station.copc.laz'

# bbox 使用原始坐标系（EPSG:6676，单位：米）
bbox = [12684.53, -36999.49, 13089.08, -36836.87]  # [minX, minY, maxX, maxY]

# 下载并读取
response = requests.get(url)
with laspy.open(BytesIO(response.content)) as las_file:
    las = las_file.read()

# 过滤 bbox 范围
mask = ((las.x >= bbox[0]) & (las.x <= bbox[2]) &
        (las.y >= bbox[1]) & (las.y <= bbox[3]))

filtered_x = las.x[mask]
filtered_y = las.y[mask]
filtered_z = las.z[mask]

print(f'Filtered points: {len(filtered_x):,}')
```

### 使用 PDAL（高效，适合本地）

PDAL 利用 COPC 空间索引，通过 HTTP Range Requests 只下载所需数据块。

```python
import pdal
import json

url = 'https://stac.uixai.org/data/kasugai_station.copc.laz'
bbox = [12684.53, -36999.49, 13089.08, -36836.87]

pipeline_json = {
    "pipeline": [
        {
            "type": "readers.copc",
            "filename": url,
            # bounds 格式: ([minX, maxX], [minY, maxY])
            "bounds": f"([{bbox[0]}, {bbox[2]}], [{bbox[1]}, {bbox[3]}])"
        }
    ]
}

pipeline = pdal.Pipeline(json.dumps(pipeline_json))
pipeline.execute()

points = pipeline.arrays[0]
print(f'Loaded {len(points):,} points')
```

### PDAL Pipeline (命令行)

```json
{
  "pipeline": [
    {
      "type": "readers.copc",
      "filename": "https://stac.uixai.org/data/kasugai_station.copc.laz",
      "bounds": "([12684.53, 13089.08], [-36999.49, -36836.87])"
    },
    {
      "type": "writers.las",
      "filename": "subset.las",
      "a_srs": "EPSG:6676"
    }
  ]
}
```

运行：
```bash
pdal pipeline pipeline.json
```

## JavaScript API

```javascript
import { Copc } from 'copc';

const url = 'https://stac.uixai.org/data/kasugai_station.copc.laz';
const bbox = [12684.53, -36999.49, 13089.08, -36836.87];

async function loadPoints() {
    const copc = await Copc.create(url);
    const view = copc.create_view({
        bounds: {
            minx: bbox[0], miny: bbox[1],
            maxx: bbox[2], maxy: bbox[3]
        }
    });

    for await (const points of view) {
        console.log('Points:', points);
    }
}

loadPoints();
```

## Jupyter Notebook 集成

Selector 界面提供 "Open in Colab" 按钮，自动生成包含以下内容的 notebook：

1. **依赖安装** - laspy, matplotlib
2. **数据下载和读取** - 使用 laspy 读取 COPC
3. **bbox 过滤** - 使用原始坐标系 bbox
4. **可视化** - matplotlib 2D 散点图
5. **导出 LAS** - 保存过滤后的点云

### Notebook 结构

```
# COPC Point Cloud Spatial Query
## 快速开始 (Colab 推荐)
### Step 1: Install Dependencies
### Step 2: Download and Read Point Cloud
### Step 3: Filter by Bounding Box
### Step 4: Visualize
### Step 5: Save to LAS File

---
## 高级: PDAL (本地环境推荐)
### pipeline.json 模板
### Python 代码示例
```

## 坐标转换

### WGS84 → 原始坐标系

使用 proj4js（JavaScript）：

```javascript
import proj4 from 'proj4';

// 注册 JGD2011 Zone 8
proj4.defs('EPSG:6676', '+proj=tmerc +lat_0=36 +lon_0=138.5 +k=0.9999 +x_0=0 +y_0=0 +ellps=GRS80 +units=m +no_defs');

// 转换 WGS84 → EPSG:6676
const [x, y] = proj4('EPSG:4326', 'EPSG:6676', [138.73, 35.36]);
console.log(`X: ${x}, Y: ${y}`);  // 米
```

### 原始坐标系 → WGS84

```javascript
const [lon, lat] = proj4('EPSG:6676', 'EPSG:4326', [12684.53, -36999.49]);
console.log(`Lon: ${lon}, Lat: ${lat}`);  // 度
```

## STAC Item 坐标信息

每个 STAC Item 包含坐标系信息：

```json
{
  "properties": {
    "proj:epsg": 6676,
    "proj:bbox": [12684.53, -37381.72, 13917.88, -36487.81, 780.54, 820.12]
  },
  "bbox": [138.727, 35.361, 138.740, 35.369]
}
```

| 字段 | 坐标系 | 说明 |
|------|--------|------|
| `bbox` | WGS84 | GeoJSON 标准 bbox（用于地图显示） |
| `proj:bbox` | 原始坐标系 | 6D bbox [minX, minY, minZ, maxX, maxY, maxZ]（用于精确查询） |
| `proj:epsg` | - | 原始坐标系 EPSG 代码 |

## 性能对比

| 方法 | 下载量 | 适用场景 |
|------|--------|----------|
| **PDAL + bounds** | 只下载 bbox 区域 | 本地环境，大文件 |
| **laspy + filter** | 下载整个文件 | Colab，小文件（<100MB） |
| **Potree viewer** | 按需流式加载 | Web 可视化 |

## 注意事项

1. **精度** - 使用原始坐标系可保持毫米级精度，WGS84 转换会引入米级误差
2. **bbox 格式** - PDAL 使用 `([minX, maxX], [minY, maxY])`，其他使用 `[minX, minY, maxX, maxY]`
3. **HTTP Range Requests** - 只有 PDAL 支持 COPC 的空间索引优化
4. **坐标检测** - Potree viewer 根据数值大小自动判断坐标系类型
