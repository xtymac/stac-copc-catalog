# COPC Point Cloud Selector 技术说明

本文总结 `potree-viewer/dist/selector.html` 的实现思路，便于快速理解组件依赖、数据流与可用接口。

## 主要功能
- 在网页上列出 STAC Catalog 中的点云 Collection，让用户选择数据集。
- 通过 OpenLayers 在地图上绘制矩形，生成 WGS84 的 bbox。
- 根据选择的数据集和 bbox，生成 Potree 视图链接以及 Python/JS/PDAL 代码示例。
- 一键跳转到 Potree 3D Viewer，可选全量数据或裁剪区域。

## 用到的组件
- **OpenLayers 8.2**：底图（OSM、Esri 影像）、绘制交互（`ol.interaction.Draw` createBox）、坐标投影转换（Web Mercator ↔ WGS84）、矢量图层展示 Collection 边界与用户绘制框。
- **STAC Catalog**：从 `https://stac.uixai.org/catalog.json` 获取子 Collection，再拉取每个 Collection 的 item 以获得 COPC 资产 URL。
- **Potree Viewer（CDN 部署）**：`https://stac.uixai.org/potree/index.html`，负责 COPC 渲染，接受查询参数 `files` 和 `bbox`。
- **原生浏览器能力**：`fetch` 读取 STAC JSON，`navigator.clipboard` 复制代码片段，vanilla JS 负责 UI 状态管理。

## 架构与流程
1. **配置**：`CONFIG.catalogUrl` 指向 STAC Catalog，`CONFIG.potreeUrl` 指向 Potree Viewer。
2. **加载数据集**：页面加载时 `loadCatalog()`：
   - 取 catalog 中 `rel=child` 的链接；逐个请求 Collection。
   - 找到 Collection 的 `rel=item`，再请求 item JSON，提取 `assets.data.href` 作为 `copcUrl`。
   - 收集 `id/title/description/bbox/pc:count/copcUrl` 放入内存数组，渲染左侧列表。
3. **选择数据集**：点击后保存 `selectedCollection`，用 Collection bbox 自动缩放视图，并在地图上画出蓝色虚线框。
4. **绘制 bbox**：点击 “Start Drawing Rectangle” 启动 `ol.interaction.Draw`（类型 Circle+createBox），绘制结束后：
   - 将 Web Mercator extent 转回 WGS84，得到 `[minLng, minLat, maxLng, maxLat]`。
   - 显示 bbox 文本，激活“打开 3D/查看全量”按钮，并展示 API 片段。
5. **生成 API 片段**：`generateApiCode()` 按当前 tab 输出：
   - **Viewer URL**：`<potreeUrl>?files=<COPC_URL>&bbox=minLng,minLat,maxLng,maxLat`
   - **Python**：基于 `copc` 库的 `Copc.open(...).read(bounds=bbox)`
   - **JavaScript**：基于 `copc.js` 的 `Copc.create(...).create_view({bounds})`
   - **PDAL**：`readers.copc` + `writers.las` 管线 JSON
6. **打开 3D**：
   - “Open Selected Area in 3D”：新窗口打开 `potreeUrl`，附带 `files` 与 `bbox`。
   - “View Full Dataset”：仅携带 `files`，加载全量 COPC。

## API 与参数
- **Potree Viewer URL**：`https://stac.uixai.org/potree/index.html?files=<COPC_URL>[,&bbox=minLng,minLat,maxLng,maxLat]`
  - `files` 支持逗号分隔多个 COPC URL。
  - `bbox` 为 WGS84，经纬度顺序 `[west, south, east, north]`，可选；不传则加载全量。
- **STAC**：Catalog → child Collection → item → `assets.data.href`（COPC）。
- **代码示例**：页面内置 Python/JS/PDAL 片段，可直接复制；仅需替换 `copcUrl` 与 `bbox` 即可复用。

## 关键文件
- 交互与逻辑：`potree-viewer/dist/selector.html`
- Potree 自定义 viewer（被 selector 生成的链接调用）：`potree-viewer/custom/index.html`
