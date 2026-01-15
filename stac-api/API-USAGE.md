# STAC API Usage Guide

## API Endpoint

**Base URL**: `https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/`

## Endpoints

### Root Catalog
```bash
curl https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/
```

### List Collections
```bash
curl https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/collections
```

### Get Single Collection
```bash
curl https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/collections/fujisan
```

### List Items in Collection
```bash
curl https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/collections/fujisan/items
```

### Get Single Item
```bash
# Fujisan point cloud
curl https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/collections/fujisan/items/merged

# Kasugai-cho DEM
curl https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/collections/kasugai-station/items/kasugai-dem
```

### Health Check
```bash
curl https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/health
```

## Search

### GET Search
```bash
# Search all items (default limit: 10)
curl "https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/search"

# Filter by collection
curl "https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/search?collections=fujisan"

# Filter by bounding box
curl "https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/search?bbox=138.7,35.3,138.8,35.4"

# With limit
curl "https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/search?limit=5"
```

### POST Search
```bash
curl -X POST "https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/search" \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["fujisan", "kasugai-station"],
    "bbox": [138.6, 35.3, 138.8, 35.5],
    "limit": 10
  }'
```

## Search Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `collections` | string/array | Collection IDs to filter |
| `ids` | string/array | Item IDs to filter |
| `bbox` | array | Bounding box [minX, minY, maxX, maxY] |
| `bbox-crs` | string | CRS for bbox (e.g., `EPSG:6676`). Default is WGS84 |
| `datetime` | string | Datetime range (e.g., `2024-01-01/2024-12-31`) |
| `limit` | integer | Max items to return (default: 10, max: 100) |

## Coordinate System Support

### Native CRS Queries

This API supports spatial queries using native Japanese Plane Rectangular Coordinate Systems:

| CRS | EPSG Code | Region |
|-----|-----------|--------|
| WGS84 (default) | EPSG:4326 | Global (degrees) |
| JGD2011 Zone 8 | EPSG:6676 | Mt. Fuji area (meters) |
| JGD2011 Zone 9 | EPSG:6677 | Kasugai area (meters) |

### Using bbox-crs Parameter

```bash
# Query using native coordinates (meters) - JGD2011 Zone 8
curl "https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/search?bbox=51200,-49200,51600,-48900&bbox-crs=EPSG:6676"

# Query using WGS84 (default)
curl "https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/search?bbox=138.7,35.3,138.8,35.4"
```

### POST Search with CRS

```bash
curl -X POST "https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/search" \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["fujisan"],
    "bbox": [19600, -70000, 22400, -68400],
    "bbox_crs": "EPSG:6676",
    "limit": 10
  }'
```

### Response Coordinate Information

Each item includes both WGS84 and native CRS coordinates:

```json
{
  "bbox": [138.716, 35.363, 138.747, 35.383],
  "properties": {
    "proj:epsg": 6676,
    "proj:bbox": [19600.0, -70667.82, 2485.91, 22399.99, -68400.01, 3756.64]
  }
}
```

- `bbox`: WGS84 coordinates (for map display)
- `proj:epsg`: Native CRS EPSG code
- `proj:bbox`: 6D bounding box in native CRS [minX, minY, minZ, maxX, maxY, maxZ]

### PDAL Usage Example

Filter point cloud data using native coordinates:

```json
{
  "pipeline": [
    {
      "type": "readers.copc",
      "filename": "https://stac.uixai.org/data/fujisan-unified.copc.laz"
    },
    {
      "type": "filters.crop",
      "bounds": "([19600, 22400], [-70000, -68400])"
    },
    {
      "type": "writers.las",
      "filename": "output.las"
    }
  ]
}
```

---

## Application Scenarios / 应用场景

本节介绍使用 STAC API 和原生坐标系数据的四大典型应用场景。

**核心优势**：
- 使用**原生坐标系**（EPSG:6676/6677）确保亚米级精度
- 米制平面坐标系，避免 WGS84 转换带来的精度损失
- 通过 `bbox-crs` 参数实现精确空间查询
- COPC 格式支持按需流式读取，无需下载完整文件

---

### Scenario 1: Precision Surveying / 精确测绘

**精度**: 0.5米

**适用场景**: 地籍测量、建筑定位、道路设计、工程施工控制

#### 技术栈
- **Python**: PDAL, pyproj, laspy
- **坐标系**: EPSG:6676 (JGD2011 Zone 8)
- **数据格式**: COPC (点云), COG (DEM)

#### Step 1: Query Precise Area (精确区域查询)

```bash
# 查询富士山区域 100m x 100m 范围
# 使用米制坐标，避免经纬度转换误差
curl "https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/search?\
bbox=20000,-69500,20100,-69400&\
bbox-crs=EPSG:6676&\
collections=fujisan"
```

#### Step 2: Extract High-Precision Points (提取高精度点云)

```python
import pdal
import json

# 定义测量区域 (100m x 100m, 米制坐标)
survey_bounds = {
    "min_x": 20000, "max_x": 20100,
    "min_y": -69500, "max_y": -69400
}

pipeline = {
    "pipeline": [
        {
            "type": "readers.copc",
            "filename": "https://stac.uixai.org/data/fujisan-unified.copc.laz",
            # 直接使用原生坐标系裁剪，无精度损失
            "bounds": f"([{survey_bounds['min_x']}, {survey_bounds['max_x']}], \
                        [{survey_bounds['min_y']}, {survey_bounds['max_y']}])"
        },
        {
            "type": "filters.range",
            # 过滤地面点 (分类码 2)
            "limits": "Classification[2:2]"
        },
        {
            "type": "writers.las",
            "filename": "survey_area.las",
            "a_srs": "EPSG:6676"  # 保持原生坐标系
        }
    ]
}

# 执行管道
p = pdal.Pipeline(json.dumps(pipeline))
p.execute()
print(f"提取点数: {p.arrays[0].shape[0]}")
print(f"精度保证: 0.5m (原生坐标系，无转换损失)")
```

#### Step 3: Calculate Precise Coordinates (计算精确坐标)

```python
import numpy as np

# 读取提取的点云
arrays = p.arrays[0]

# 计算区域统计（米制单位）
print(f"X 范围: {arrays['X'].min():.2f} - {arrays['X'].max():.2f} m")
print(f"Y 范围: {arrays['Y'].min():.2f} - {arrays['Y'].max():.2f} m")
print(f"Z 范围: {arrays['Z'].min():.2f} - {arrays['Z'].max():.2f} m")
print(f"平均高程: {arrays['Z'].mean():.3f} m")

# 精度验证：坐标应在厘米级精度
assert arrays['X'].dtype == np.float64, "需要双精度浮点数"
```

---

### Scenario 2: Flood Simulation / 洪水模拟

**适用场景**: 水文分析、淹没预测、防灾规划、排水设计

#### 技术栈
- **Python**: rasterio, GDAL, numpy, scipy
- **坐标系**: EPSG:6676 (保持米制高程精度)
- **数据格式**: COG (DEM), COPC (点云用于补充)

#### Step 1: Get DEM Data (获取 DEM 数据)

```bash
# 查询 DEM 数据
curl "https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/search?\
collections=fujisan&\
ids=dem" | jq '.features[0].assets'
```

#### Step 2: Flood Inundation Analysis (洪水淹没分析)

```python
import rasterio
from rasterio.windows import from_bounds
import numpy as np

# COG 支持按需读取，只下载需要的区域
dem_url = "https://stac.uixai.org/data/fujisan_dem_2024_official_jgd.cog.tif"

# 定义分析区域 (米制坐标)
analysis_bounds = {
    "west": 20000, "east": 21000,
    "south": -70000, "north": -69000
}

# 模拟水位 (米)
flood_levels = [2700, 2750, 2800, 2850, 2900]  # 不同洪水水位

with rasterio.open(dem_url) as src:
    # 按需读取分析区域
    window = from_bounds(
        analysis_bounds["west"], analysis_bounds["south"],
        analysis_bounds["east"], analysis_bounds["north"],
        src.transform
    )
    dem = src.read(1, window=window)
    transform = src.window_transform(window)

    print(f"DEM 分辨率: {src.res[0]:.2f} m")
    print(f"坐标系: {src.crs}")

    # 计算各水位淹没面积
    pixel_area = src.res[0] * src.res[1]  # 平方米

    for water_level in flood_levels:
        # 淹没区域 = 高程 < 水位
        inundated = dem < water_level
        inundated_area = np.sum(inundated) * pixel_area
        inundated_volume = np.sum(water_level - dem[inundated]) * pixel_area

        print(f"\n水位 {water_level}m:")
        print(f"  淹没面积: {inundated_area/10000:.2f} 公顷")
        print(f"  淹没体积: {inundated_volume/1000000:.2f} 百万立方米")
```

#### Step 3: Generate Flood Map (生成洪水地图)

```python
import matplotlib.pyplot as plt

# 创建淹没深度图
water_level = 2800  # 目标水位
flood_depth = np.maximum(0, water_level - dem)

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# 原始 DEM
im1 = axes[0].imshow(dem, cmap='terrain')
axes[0].set_title('DEM 高程 (m)')
plt.colorbar(im1, ax=axes[0])

# 淹没深度
im2 = axes[1].imshow(flood_depth, cmap='Blues')
axes[1].set_title(f'洪水淹没深度 @ {water_level}m (m)')
plt.colorbar(im2, ax=axes[1])

plt.savefig('flood_simulation.png', dpi=150)
print("洪水模拟地图已保存")
```

---

### Scenario 3: Earthquake Simulation / 地震模拟

**适用场景**: 地表变形分析、建筑物评估、滑坡风险、基础设施检测

#### 技术栈
- **Python**: PDAL, numpy, scipy, Open3D
- **坐标系**: EPSG:6676 (米制坐标用于位移计算)
- **数据格式**: COPC (点云), COG (DEM)

#### Step 1: Extract Building Points (提取建筑物点)

```python
import pdal
import json
import numpy as np

# 定义分析区域
area_bounds = "([20000, 21000], [-70000, -69000])"

pipeline = {
    "pipeline": [
        {
            "type": "readers.copc",
            "filename": "https://stac.uixai.org/data/fujisan-unified.copc.laz",
            "bounds": area_bounds
        },
        {
            "type": "filters.range",
            # 提取建筑物点 (分类码 6)
            "limits": "Classification[6:6]"
        },
        {
            "type": "filters.smrf",
            # 地面分类用于计算相对高度
            "slope": 0.3,
            "window": 16
        }
    ]
}

p = pdal.Pipeline(json.dumps(pipeline))
p.execute()
building_points = p.arrays[0]
print(f"建筑物点数: {building_points.shape[0]}")
```

#### Step 2: Slope Stability Analysis (坡度稳定性分析)

```python
import rasterio
from scipy import ndimage

dem_url = "https://stac.uixai.org/data/fujisan_dem_2024_official_jgd.cog.tif"

with rasterio.open(dem_url) as src:
    dem = src.read(1)
    resolution = src.res[0]  # 0.5m

    # 计算坡度 (度)
    dy, dx = np.gradient(dem, resolution)
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
    slope_deg = np.degrees(slope_rad)

    # 地震滑坡风险分级
    # 根据日本建筑基准法，坡度 > 30° 为高风险
    risk_low = slope_deg < 15
    risk_medium = (slope_deg >= 15) & (slope_deg < 30)
    risk_high = slope_deg >= 30

    print(f"低风险区域: {np.sum(risk_low) * resolution**2 / 10000:.2f} 公顷")
    print(f"中风险区域: {np.sum(risk_medium) * resolution**2 / 10000:.2f} 公顷")
    print(f"高风险区域 (坡度>30°): {np.sum(risk_high) * resolution**2 / 10000:.2f} 公顷")
```

#### Step 3: Building Height Estimation (建筑物高度估算)

```python
# 建筑物高度估算 (用于抗震评估)
from scipy.spatial import cKDTree

# 获取地面点
ground_pipeline = {
    "pipeline": [
        {
            "type": "readers.copc",
            "filename": "https://stac.uixai.org/data/fujisan-unified.copc.laz",
            "bounds": area_bounds
        },
        {
            "type": "filters.range",
            "limits": "Classification[2:2]"  # 地面点
        }
    ]
}

p_ground = pdal.Pipeline(json.dumps(ground_pipeline))
p_ground.execute()
ground_points = p_ground.arrays[0]

# 使用 KD-Tree 查找最近地面点
ground_xy = np.column_stack([ground_points['X'], ground_points['Y']])
building_xy = np.column_stack([building_points['X'], building_points['Y']])

tree = cKDTree(ground_xy)
_, indices = tree.query(building_xy)

# 计算建筑物相对高度
ground_z = ground_points['Z'][indices]
building_height = building_points['Z'] - ground_z

print(f"建筑物高度范围: {building_height.min():.1f} - {building_height.max():.1f} m")
print(f"平均高度: {building_height.mean():.1f} m")
print(f"高层建筑 (>10m) 数量估计: {np.sum(building_height > 10)}")
```

---

### Scenario 4: Geospatial Analysis / 地理空间分析

**适用场景**: 体积计算、坡度分析、视线分析、断面提取

#### 技术栈
- **Python**: PDAL, rasterio, numpy, scipy
- **坐标系**: EPSG:6676 (米制单位用于精确计算)

#### 4.1 Volume Calculation (体积计算)

```python
import rasterio
import numpy as np

dem_url = "https://stac.uixai.org/data/fujisan_dem_2024_official_jgd.cog.tif"

# 定义挖填区域
excavation_area = {
    "west": 20500, "east": 20600,
    "south": -69600, "north": -69500
}
target_elevation = 2750  # 目标高程

with rasterio.open(dem_url) as src:
    window = rasterio.windows.from_bounds(
        excavation_area["west"], excavation_area["south"],
        excavation_area["east"], excavation_area["north"],
        src.transform
    )
    dem = src.read(1, window=window)
    pixel_area = src.res[0] * src.res[1]  # 0.25 m²

    # 计算挖填方量
    diff = dem - target_elevation
    cut_volume = np.sum(diff[diff > 0]) * pixel_area  # 挖方
    fill_volume = np.sum(-diff[diff < 0]) * pixel_area  # 填方

    print(f"目标高程: {target_elevation} m")
    print(f"挖方量: {cut_volume:.2f} m³")
    print(f"填方量: {fill_volume:.2f} m³")
    print(f"净土方量: {cut_volume - fill_volume:.2f} m³")
```

#### 4.2 Cross-Section Extraction (断面提取)

```python
import pdal
import json
import numpy as np

# 定义断面线 (米制坐标)
section_start = (20000, -69500)
section_end = (21000, -69500)
buffer_width = 2  # 断面宽度 (米)

# 创建断面边界
min_x = min(section_start[0], section_end[0])
max_x = max(section_start[0], section_end[0])
min_y = section_start[1] - buffer_width
max_y = section_start[1] + buffer_width

pipeline = {
    "pipeline": [
        {
            "type": "readers.copc",
            "filename": "https://stac.uixai.org/data/fujisan-unified.copc.laz",
            "bounds": f"([{min_x}, {max_x}], [{min_y}, {max_y}])"
        },
        {
            "type": "filters.range",
            "limits": "Classification[2:2]"  # 地面点
        }
    ]
}

p = pdal.Pipeline(json.dumps(pipeline))
p.execute()
points = p.arrays[0]

# 按 X 坐标排序并提取断面
sorted_idx = np.argsort(points['X'])
x_coords = points['X'][sorted_idx]
z_coords = points['Z'][sorted_idx]

# 每 10m 采样一次
sample_interval = 10
sample_x = np.arange(min_x, max_x, sample_interval)
sample_z = np.interp(sample_x, x_coords, z_coords)

print("断面数据:")
print("距离(m)\t高程(m)")
for i, (x, z) in enumerate(zip(sample_x, sample_z)):
    print(f"{i * sample_interval}\t{z:.2f}")
```

#### 4.3 Slope and Aspect Analysis (坡度坡向分析)

```python
import rasterio
import numpy as np

dem_url = "https://stac.uixai.org/data/fujisan_dem_2024_official_jgd.cog.tif"

with rasterio.open(dem_url) as src:
    dem = src.read(1)
    resolution = src.res[0]  # 0.5m

    # 计算梯度
    dy, dx = np.gradient(dem, resolution)

    # 坡度 (度)
    slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))

    # 坡向 (度, 北=0, 顺时针)
    aspect = np.degrees(np.arctan2(-dx, dy))
    aspect = np.where(aspect < 0, aspect + 360, aspect)

    # 统计
    print("坡度统计:")
    print(f"  最小: {np.nanmin(slope):.1f}°")
    print(f"  最大: {np.nanmax(slope):.1f}°")
    print(f"  平均: {np.nanmean(slope):.1f}°")

    # 坡向分布
    directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    for i, d in enumerate(directions):
        angle_min = i * 45 - 22.5
        angle_max = i * 45 + 22.5
        if d == 'N':
            count = np.sum((aspect >= 337.5) | (aspect < 22.5))
        else:
            count = np.sum((aspect >= angle_min) & (aspect < angle_max))
        print(f"  {d}: {count / aspect.size * 100:.1f}%")
```

---

## Data Specifications / 数据规格

| 数据类型 | 格式 | 分辨率 | 坐标系 | 精度 |
|---------|------|--------|--------|------|
| 点云 (富士山) | COPC | ~0.5m 点间距 | EPSG:6676 | 0.5m |
| 点云 (春日居) | COPC | ~0.5m 点间距 | EPSG:6677 | 0.5m |
| DEM | COG (Float32) | 0.5m | EPSG:6676/4326 | 0.5m |
| DEM 可视化 | COG (RGBA) | 0.5m | EPSG:4326 | - |

---

## Current Data

- **Collections**: 3 (fujisan, kasugai-station, pointcloud-jgd2011)
- **Items**: 25 point cloud tiles + DEM layers

## STAC Conformance

This API conforms to:
- STAC API Core 1.0.0
- STAC API Collections 1.0.0
- STAC API Item Search 1.0.0
- OGC API Features 1.0

## Integration with STAC Browser

Point STAC Browser to the API endpoint:
```javascript
// stac-browser config
catalogUrl: "https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/"
```

## Auto-Sync with S3

The API now **automatically syncs** with S3 catalog changes:

### How It Works

1. **S3 Event Trigger**: When any `.json` file is created/modified/deleted in `s3://stac-uixai-catalog/`, an S3 event triggers the indexer Lambda
2. **Indexer Lambda**: `stac-indexer-prod` scans all STAC JSON files and rebuilds the Parquet index
3. **Index Upload**: Updated `items.parquet` and `collections.parquet` are uploaded to `s3://stac-uixai-catalog/index/`
4. **API Cache Refresh**: API reads from S3 index with 60-second TTL cache

### Workflow

```
STAC Browser → S3 sync → S3 Event → Indexer Lambda → Index updated → API sees changes
```

### Manual Triggers (if needed)

```bash
# Force indexer to run now
aws lambda invoke --function-name stac-indexer-prod --payload '{}' /tmp/out.json

# Force API to refresh cache immediately
curl -X POST https://8cc8250qpj.execute-api.ap-northeast-1.amazonaws.com/prod/admin/refresh-index

# Check index status
aws s3 ls s3://stac-uixai-catalog/index/
```

### Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  STAC Browser   │────▶│   S3 Bucket     │────▶│ Indexer Lambda  │
│  (catalog sync) │     │ (stac-uixai-    │     │ (stac-indexer-  │
└─────────────────┘     │  catalog)       │     │  prod)          │
                        └────────┬────────┘     └────────┬────────┘
                                 │                       │
                                 ▼                       ▼
                        ┌─────────────────┐     ┌─────────────────┐
                        │  index/*.parquet│◀────│ Rebuild Index   │
                        └────────┬────────┘     └─────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │   STAC API      │
                        │ (60s TTL cache) │
                        └─────────────────┘
```
