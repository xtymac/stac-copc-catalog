# STAC API - GeoParquet Backend

轻量级 STAC API 实现，使用 GeoParquet 作为索引存储。适用于小到中型目录（<10,000 items）。

## 快速开始

### 1. 生成 Parquet 索引

```bash
# 从项目根目录
python scripts/index-to-parquet.py --catalog catalog-combined --output stac-api/index
```

### 2. 本地运行

```bash
cd stac-api
pip install -r requirements.txt
./run-local.sh
```

访问:
- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- 搜索: http://localhost:8000/search

### 3. 部署到 AWS Lambda

```bash
cd stac-api
./deploy.sh prod
```

## API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/` | GET | Landing page (root catalog) |
| `/conformance` | GET | Conformance classes |
| `/collections` | GET | 列出所有 collections |
| `/collections/{id}` | GET | 获取单个 collection |
| `/collections/{id}/items` | GET | 列出 collection 中的 items |
| `/collections/{id}/items/{item_id}` | GET | 获取单个 item |
| `/search` | GET/POST | 搜索 items |
| `/queryables` | GET | 可查询属性 |
| `/health` | GET | 健康检查 |

## 搜索参数

### POST /search

```json
{
  "collections": ["kasugai-station", "fujisan"],
  "bbox": [138.6, 35.6, 138.7, 35.7],
  "datetime": "2024-01-01T00:00:00Z/2024-12-31T23:59:59Z",
  "limit": 10
}
```

### GET /search

```
/search?collections=kasugai-station&bbox=138.6,35.6,138.7,35.7&limit=10
```

## 集成 STAC Browser

部署 API 后，更新 `stac-browser/src/config.js`:

```javascript
module.exports = {
    // 指向 API 端点（而非静态 catalog.json）
    catalogUrl: "https://your-api-gateway-url/prod/",

    // 启用 API 优先模式
    apiCatalogPriority: "api",

    // 其他配置保持不变...
    catalogTitle: "STAC COPC Catalog",
    allowExternalAccess: true,
    // ...
};
```

重新构建 STAC Browser:

```bash
cd stac-browser/src
npm run build
```

## CloudFront 集成

在 CloudFront 中添加 API Gateway 作为新的 origin:

1. **Origin Domain**: `{api-id}.execute-api.{region}.amazonaws.com`
2. **Origin Path**: `/prod`

添加 Cache Behavior:

| Path Pattern | Origin | 缓存策略 |
|--------------|--------|----------|
| `/api/*` | API Gateway | CachingDisabled (或 1 分钟) |
| `/search*` | API Gateway | CachingDisabled |
| `/collections*` | API Gateway | 5 分钟 |
| `*` | S3 (现有) | 保持不变 |

## 目录结构

```
stac-api/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI 应用
│   └── config.py         # 配置
├── index/                 # Parquet 索引文件
│   ├── items.parquet
│   ├── collections.parquet
│   └── catalog_metadata.json
├── Dockerfile            # Lambda 容器镜像
├── requirements.txt
├── template.yaml         # SAM 部署模板
├── run-local.sh          # 本地开发脚本
└── deploy.sh             # AWS 部署脚本
```

## 性能特性

- **首屏优化**: 默认 limit=10，避免大响应
- **稳定排序**: datetime DESC + id ASC 作为 tie-breaker
- **Lambda 保活**: 每 5 分钟预热，减少冷启动
- **缓存**: CloudFront 可缓存 /collections 响应

## 成本估算

| 组件 | 月成本 |
|------|--------|
| Lambda (100K 请求) | ~$0.50 |
| API Gateway | ~$0.35 |
| S3 (Parquet 索引) | ~$0.01 |
| **总计** | **~$1/月** |

## 扩展到 pgstac

当满足以下条件时，考虑升级到 pgstac:
- Items 超过 10,000 个
- 需要复杂 CQL2 查询
- 需要实时目录更新
