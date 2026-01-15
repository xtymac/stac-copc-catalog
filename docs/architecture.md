# STAC COPC 点云系统架构说明

> 面向设计师的通俗版本

---

## 一句话概述

**把测量得到的 3D 点云数据，放到网上让任何人用浏览器就能查看。**

---

## 系统做了什么？

```
原始测量数据 → 格式转换 → 生成目录 → 上传云端 → 网页浏览
   (LAS)        (COPC)      (STAC)      (AWS)     (Potree)
```

### 用大白话解释每一步：

| 步骤 | 做什么 | 类比 |
|------|--------|------|
| **格式转换** | 把原始点云压缩成网页能读的格式 | 把 RAW 照片转成 JPG |
| **生成目录** | 给每个文件建立索引卡片 | 图书馆的图书目录 |
| **上传云端** | 放到全球 CDN 加速 | 把文件放到百度网盘 |
| **网页浏览** | 用 3D 查看器展示 | 在线版的 SketchUp |

---

## 核心组件图解

```
┌─────────────────────────────────────────────────────────────┐
│                        用户浏览器                            │
│  ┌─────────────────┐      ┌─────────────────┐              │
│  │   STAC Browser  │      │  Potree Viewer  │              │
│  │   (数据目录)     │ ──→  │   (3D 查看器)   │              │
│  └─────────────────┘      └─────────────────┘              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    AWS CloudFront (CDN)                     │
│                 全球加速，就近访问，速度快                     │
│                   https://stac.uixai.org                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      AWS S3 (存储桶)                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ 点云数据  │  │ STAC目录 │  │  浏览器   │  │  查看器   │   │
│  │ *.copc   │  │ *.json   │  │ /browser │  │ /viewer  │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 两个查看器的区别

### 1. STAC Browser（数据浏览器）
- **网址**: https://stac.uixai.org/browser/
- **用途**: 浏览有哪些数据、查看元信息
- **类比**: 就像 Finder/资源管理器，看文件夹结构

### 2. Potree Viewer（3D 查看器）
- **网址**: https://stac.uixai.org/viewer/
- **用途**: 实际查看 3D 点云、旋转缩放、测量
- **类比**: 就像在线版的 CloudCompare

---

## 文件格式说明

### COPC（Cloud Optimized Point Cloud）
- **是什么**: 专门为网页优化的点云格式
- **优点**:
  - 不用下载整个文件就能预览
  - 自动分层，远看粗略、近看精细
  - 压缩率高，节省带宽

### STAC（SpatioTemporal Asset Catalog）
- **是什么**: 地理数据的标准目录格式
- **优点**:
  - 国际通用标准，兼容 QGIS 等软件
  - 记录坐标系、范围、点数等信息
  - 支持搜索和筛选

---

## 项目文件结构

```
Study STAC/
├── scripts/                 # 自动化脚本
│   ├── 01-prepare-data.py   # LAS → COPC 格式转换
│   ├── 02-generate-stac.py  # 生成 STAC 目录
│   ├── 03-deploy-aws.sh     # 部署到 AWS
│   ├── 05-build-browser.sh  # 构建 STAC Browser
│   └── 06-build-potree.sh   # 构建 Potree 查看器
│
├── local/                   # 本地工作区
│   ├── input/               # 放原始 LAS 文件
│   └── output/              # 转换后的 COPC + 元数据
│
├── catalog/                 # STAC 目录文件
│   ├── catalog.json         # 根目录
│   └── pointcloud-jgd2011/  # 数据集合（目前 21 个点云）
│
├── stac-browser/            # STAC Browser 源码
│   ├── src/                 # 定制化代码
│   └── dist/                # 构建输出
│
├── potree-viewer/           # Potree 查看器（构建输出）
├── potree-src/              # Potree 源码
│
├── docs/                    # 文档目录
│   ├── architecture.md      # 本文件
│   ├── copc-conversion.md   # COPC 转换指南
│   ├── copc-point-cloud-selector.md # Selector 说明
│   ├── API_COORDINATE_SYSTEM.md
│   ├── COG_DEM_GUIDE.md
│   ├── CKAN_INTEGRATION_PATTERN.md
│   └── COST_OPERATIONS.md
│
└── .env                     # 配置文件（域名、密钥等）
```

---

## 工作流程（给设计师看的版本）

### 添加新数据的流程：

```
1. 把 LAS 文件放到 local/input/ 文件夹

2. 运行转换脚本
   $ python scripts/01-prepare-data.py

3. 生成目录
   $ python scripts/02-generate-stac.py

4. 上传到云端
   $ ./scripts/03-deploy-aws.sh --update

5. 完成！访问网址查看
   https://stac.uixai.org/viewer/
```

---

## 在线访问地址

| 地址 | 用途 |
|------|------|
| https://stac.uixai.org/ | 主页（STAC Browser） |
| https://stac.uixai.org/browser/ | STAC 数据浏览器 |
| https://stac.uixai.org/viewer/ | Potree 3D 查看器 |
| https://stac.uixai.org/catalog.json | 原始目录文件（JSON） |

---

## 如何预览点云？

### 方式 1：从 STAC Browser 进入（推荐）

1. 打开 https://stac.uixai.org/
2. 点击 **pointcloud-jgd2011** 进入数据集
3. 选择任意一个点云文件（如 08LF6238）
4. 点击 **"View in Potree"** 按钮

```
首页 → 数据集 → 单个文件 → View in Potree
```

### 方式 2：直接 URL 访问

#### 查看单个点云：
```
https://stac.uixai.org/viewer/index.html?file=08LF6238.copc.laz
```

#### 同时查看多个点云：
```
https://stac.uixai.org/viewer/index.html?file=08LF6238.copc.laz,08LF6239.copc.laz
```

#### 查看整个数据集（所有 21 个点云）：
```
https://stac.uixai.org/viewer/index.html?collection=pointcloud-jgd2011
```

### 方式 3：在 STAC Browser 中一键查看全部

1. 打开 https://stac.uixai.org/browser/
2. 点击 **pointcloud-jgd2011** 进入数据集
3. 点击右上角 **"View All in Potree"** 链接

### URL 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `file=` | 单个或多个文件（逗号分隔） | `file=08LF6238.copc.laz` |
| `collection=` | 加载整个数据集 | `collection=pointcloud-jgd2011` |

### 当前可用的点云文件（21 个）

```
08LF6238, 08LF6239, 08LF6248, 08LF6249,
08LF6258, 08LF6259, 08LF6268, 08LF6269,
08LF6330, 08LF6331, 08LF6332,
08LF6340, 08LF6341, 08LF6342,
08LF6350, 08LF6351, 08LF6352,
08LF6360, 08LF6361, 08LF6362,
08LE3771
```

---

## 技术栈一览

| 层级 | 技术 | 作用 |
|------|------|------|
| **前端查看器** | Potree + Three.js | 3D 渲染 |
| **数据目录** | STAC Browser | 浏览元数据 |
| **数据格式** | COPC (LAZ) | 点云存储 |
| **元数据** | STAC 1.1 | 标准目录 |
| **CDN** | CloudFront | 全球加速 |
| **存储** | AWS S3 | 文件存储 |
| **转换工具** | PDAL | 格式转换 |

---

## 费用估算

| 项目 | 月费用 |
|------|--------|
| S3 存储 (100GB) | ~$2-3 |
| CloudFront 流量 | ~$5-15 |
| 总计 | **~$10-20/月** |

---

## 常见问题

### Q: 为什么不直接用原始 LAS 文件？
A: LAS 文件太大，无法在网页流式加载。COPC 格式支持按需加载，只下载当前视角需要的部分。

### Q: 点云颜色不一致怎么办？
A: 这是因为不同瓦片采集时的光照条件不同。可以在查看器中选择按"高度"或"强度"着色来避免这个问题。

### Q: 支持哪些坐标系？
A: 主要使用日本 JGD2011 坐标系（EPSG:6677），也支持 WGS84。

### Q: 数据安全吗？
A: 所有访问都通过 HTTPS 加密，S3 存储桶设为私有，只能通过 CloudFront 访问。

---

## 架构优势总结

1. **无需安装** - 浏览器直接访问
2. **全球加速** - CloudFront CDN
3. **标准格式** - STAC + COPC 国际通用
4. **成本低** - 每月 $10-20
5. **可扩展** - 轻松添加新数据
