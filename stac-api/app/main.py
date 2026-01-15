"""
STAC API - Parquet Backend (No GeoParquet dependency)

A lightweight STAC API implementation using Parquet for index storage.
Uses pyarrow + shapely directly, without geopandas (for Lambda compatibility).

Endpoints:
    GET  /                      - Landing page (root catalog)
    GET  /conformance           - Conformance classes
    GET  /collections           - List collections
    GET  /collections/{id}      - Get collection
    GET  /collections/{id}/items - List items in collection
    GET  /collections/{id}/items/{item_id} - Get item
    POST /search                - Search items (STAC API search)
    GET  /search                - Search items (GET variant)
    GET  /queryables            - Queryable properties
"""

import json
import logging
import time
import io
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

import boto3
import pandas as pd
import pyarrow.parquet as pq
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from shapely.geometry import box, shape
from shapely import wkt
from pyproj import Transformer, CRS as ProjCRS

from .config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# S3 client for reading index from S3
s3_client = None
if settings.use_s3_index:
    s3_client = boto3.client('s3', region_name=settings.aws_region)

# Initialize FastAPI app
app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version=settings.api_version,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global index storage (loaded on startup)
_items_df: Optional[pd.DataFrame] = None
_collections_df: Optional[pd.DataFrame] = None
_catalog_metadata: Optional[Dict] = None
_index_loaded_at: float = 0  # Timestamp of last index load


def load_parquet_from_s3(bucket: str, key: str) -> pd.DataFrame:
    """Load a Parquet file from S3 into a DataFrame."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = response['Body'].read()
        table = pq.read_table(io.BytesIO(data))
        return table.to_pandas()
    except Exception as e:
        logger.warning(f"Failed to load {key} from S3: {e}")
        return pd.DataFrame()


def load_json_from_s3(bucket: str, key: str) -> Optional[Dict]:
    """Load a JSON file from S3."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(response['Body'].read().decode('utf-8'))
    except Exception as e:
        logger.warning(f"Failed to load {key} from S3: {e}")
        return None


def should_reload_index() -> bool:
    """Check if index should be reloaded based on TTL."""
    global _index_loaded_at
    if not settings.use_s3_index:
        return False
    return (time.time() - _index_loaded_at) > settings.index_cache_ttl


# Pydantic models for request/response
class SearchRequest(BaseModel):
    """STAC API Search request body."""
    collections: Optional[List[str]] = None
    ids: Optional[List[str]] = None
    bbox: Optional[List[float]] = Field(None, min_length=4, max_length=6)
    bbox_crs: Optional[str] = Field(None, description="CRS for bbox, e.g., 'EPSG:6676'. Default is EPSG:4326 (WGS84)")
    datetime: Optional[str] = None
    limit: int = Field(default=settings.default_limit, ge=1, le=settings.max_limit)
    sortby: Optional[List[Dict[str, str]]] = None


class Link(BaseModel):
    """STAC Link object."""
    rel: str
    href: str
    type: Optional[str] = None
    title: Optional[str] = None


# Index loading functions
def load_index() -> None:
    """Load Parquet index files from local path or S3."""
    global _items_df, _collections_df, _catalog_metadata, _index_loaded_at

    if settings.use_s3_index:
        # Load from S3
        logger.info(f"Loading index from S3: {settings.index_bucket}/{settings.index_prefix}")

        _items_df = load_parquet_from_s3(
            settings.index_bucket,
            f"{settings.index_prefix}/items.parquet"
        )
        logger.info(f"Loaded {len(_items_df)} items from S3")

        _collections_df = load_parquet_from_s3(
            settings.index_bucket,
            f"{settings.index_prefix}/collections.parquet"
        )
        logger.info(f"Loaded {len(_collections_df)} collections from S3")

        _catalog_metadata = load_json_from_s3(
            settings.index_bucket,
            f"{settings.index_prefix}/catalog_metadata.json"
        )
        if not _catalog_metadata:
            _catalog_metadata = {
                "catalog_id": "stac-catalog",
                "catalog_title": "STAC Catalog",
                "stac_version": settings.stac_version
            }
        logger.info(f"Loaded catalog metadata: {_catalog_metadata.get('catalog_id')}")

        _index_loaded_at = time.time()
    else:
        # Load from local path
        index_path = Path(settings.index_path)

        # Load items
        items_file = index_path / "items.parquet"
        if items_file.exists():
            table = pq.read_table(items_file)
            _items_df = table.to_pandas()
            logger.info(f"Loaded {len(_items_df)} items from index")
        else:
            logger.warning(f"Items index not found: {items_file}")
            _items_df = pd.DataFrame()

        # Load collections
        collections_file = index_path / "collections.parquet"
        if collections_file.exists():
            table = pq.read_table(collections_file)
            _collections_df = table.to_pandas()
            logger.info(f"Loaded {len(_collections_df)} collections from index")
        else:
            logger.warning(f"Collections index not found: {collections_file}")
            _collections_df = pd.DataFrame()

        # Load catalog metadata
        metadata_file = index_path / "catalog_metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                _catalog_metadata = json.load(f)
            logger.info(f"Loaded catalog metadata: {_catalog_metadata.get('catalog_id')}")
        else:
            _catalog_metadata = {
                "catalog_id": "stac-catalog",
                "catalog_title": "STAC Catalog",
                "stac_version": settings.stac_version
            }


@app.on_event("startup")
async def startup_event():
    """Load index on startup."""
    load_index()


# Helper functions
def get_base_url(request: Request) -> str:
    """Get base URL from request."""
    return str(request.base_url).rstrip('/')


def parse_bbox(bbox: List[float]) -> box:
    """Parse bbox to shapely box."""
    if len(bbox) == 4:
        return box(bbox[0], bbox[1], bbox[2], bbox[3])
    elif len(bbox) == 6:
        # 3D bbox - use only 2D for spatial query
        return box(bbox[0], bbox[1], bbox[3], bbox[4])
    raise ValueError("Invalid bbox")


def transform_bbox_to_wgs84(bbox: List[float], source_crs: str) -> List[float]:
    """Transform bbox from source CRS to WGS84 (EPSG:4326).

    Args:
        bbox: Bounding box [minX, minY, maxX, maxY] or [minX, minY, minZ, maxX, maxY, maxZ]
        source_crs: Source CRS string, e.g., 'EPSG:6676'

    Returns:
        Transformed bbox in WGS84
    """
    try:
        transformer = Transformer.from_crs(
            ProjCRS.from_string(source_crs),
            ProjCRS.from_epsg(4326),
            always_xy=True
        )
        if len(bbox) == 4:
            # 2D bbox
            lon1, lat1 = transformer.transform(bbox[0], bbox[1])
            lon2, lat2 = transformer.transform(bbox[2], bbox[3])
            return [min(lon1, lon2), min(lat1, lat2), max(lon1, lon2), max(lat1, lat2)]
        elif len(bbox) == 6:
            # 3D bbox - transform X/Y, keep Z
            lon1, lat1 = transformer.transform(bbox[0], bbox[1])
            lon2, lat2 = transformer.transform(bbox[3], bbox[4])
            return [min(lon1, lon2), min(lat1, lat2), bbox[2], max(lon1, lon2), max(lat1, lat2), bbox[5]]
        raise ValueError("Invalid bbox length")
    except Exception as e:
        logger.error(f"Failed to transform bbox from {source_crs}: {e}")
        raise ValueError(f"Invalid CRS or bbox: {e}")


def get_geometry_from_row(row: pd.Series):
    """Extract shapely geometry from row (stored as WKT or GeoJSON)."""
    if 'geometry_wkt' in row and pd.notna(row.get('geometry_wkt')):
        return wkt.loads(row['geometry_wkt'])
    if 'geometry' in row and pd.notna(row.get('geometry')):
        geom_val = row['geometry']
        if isinstance(geom_val, str):
            # Try WKT first, then GeoJSON
            try:
                return wkt.loads(geom_val)
            except:
                try:
                    return shape(json.loads(geom_val))
                except:
                    pass
    return None


def parse_datetime_filter(dt_str: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """Parse datetime filter string.

    Formats:
        - Single datetime: "2024-01-01T00:00:00Z"
        - Range: "2024-01-01T00:00:00Z/2024-12-31T23:59:59Z"
        - Open start: "../2024-12-31T23:59:59Z"
        - Open end: "2024-01-01T00:00:00Z/.."
    """
    if "/" in dt_str:
        start, end = dt_str.split("/", 1)
        start_dt = None if start in ("", "..") else pd.to_datetime(start, utc=True)
        end_dt = None if end in ("", "..") else pd.to_datetime(end, utc=True)
        return start_dt, end_dt
    else:
        dt = pd.to_datetime(dt_str, utc=True)
        return dt, dt


def filter_items(
    df: pd.DataFrame,
    collections: Optional[List[str]] = None,
    ids: Optional[List[str]] = None,
    bbox: Optional[List[float]] = None,
    bbox_crs: Optional[str] = None,
    datetime_filter: Optional[str] = None,
    limit: int = 10
) -> pd.DataFrame:
    """Filter items based on search parameters.

    Args:
        df: DataFrame with items
        collections: Filter by collection IDs
        ids: Filter by item IDs
        bbox: Bounding box [minX, minY, maxX, maxY]
        bbox_crs: CRS for bbox (e.g., 'EPSG:6676'). Default is WGS84
        datetime_filter: Datetime filter string
        limit: Maximum items to return
    """
    if df.empty:
        return df

    result = df.copy()

    # Filter by collection
    if collections:
        result = result[result['collection'].isin(collections)]

    # Filter by IDs
    if ids:
        result = result[result['id'].isin(ids)]

    # Filter by bbox
    if bbox and len(result) > 0:
        # Transform bbox to WGS84 if a different CRS is specified
        if bbox_crs and bbox_crs.upper() not in ("EPSG:4326", "CRS84"):
            bbox = transform_bbox_to_wgs84(bbox, bbox_crs)
        bbox_geom = parse_bbox(bbox)

        def intersects_bbox(row):
            geom = get_geometry_from_row(row)
            if geom:
                return geom.intersects(bbox_geom)
            # If no geometry, check bbox field
            if 'bbox' in row and pd.notna(row.get('bbox')):
                item_bbox = row['bbox']
                if isinstance(item_bbox, str):
                    item_bbox = json.loads(item_bbox)
                if isinstance(item_bbox, list) and len(item_bbox) >= 4:
                    item_box = box(item_bbox[0], item_bbox[1], item_bbox[2], item_bbox[3])
                    return item_box.intersects(bbox_geom)
            return True  # Include if no geometry info

        result = result[result.apply(intersects_bbox, axis=1)]

    # Filter by datetime
    if datetime_filter and 'datetime' in result.columns:
        start_dt, end_dt = parse_datetime_filter(datetime_filter)
        if start_dt:
            result = result[result['datetime'] >= start_dt]
        if end_dt:
            result = result[result['datetime'] <= end_dt]

    # Apply limit
    result = result.head(limit)

    return result


def row_to_item(row: pd.Series) -> Dict[str, Any]:
    """Convert a DataFrame row to STAC Item."""
    # If we have stored full JSON, use it
    if 'item_json' in row and pd.notna(row['item_json']):
        return json.loads(row['item_json'])

    # Otherwise, reconstruct from flattened fields
    geometry = None
    geom = get_geometry_from_row(row)
    if geom:
        geometry = json.loads(geom.__geo_interface__ if hasattr(geom, '__geo_interface__') else json.dumps(geom))

    # Parse bbox
    bbox_val = row.get('bbox')
    if isinstance(bbox_val, str):
        bbox_val = json.loads(bbox_val)

    item = {
        "type": "Feature",
        "stac_version": row.get('stac_version', settings.stac_version),
        "id": row['id'],
        "geometry": geometry,
        "bbox": bbox_val,
        "properties": {
            "datetime": row['datetime'].isoformat() if pd.notna(row.get('datetime')) else None,
            "title": row.get('title'),
        },
        "links": json.loads(row['links']) if pd.notna(row.get('links')) else [],
        "assets": json.loads(row['assets']) if pd.notna(row.get('assets')) else {},
        "collection": row.get('collection')
    }

    # Add point cloud properties
    if pd.notna(row.get('pc_count')):
        item['properties']['pc:count'] = row['pc_count']
    if pd.notna(row.get('pc_type')):
        item['properties']['pc:type'] = row['pc_type']
    if pd.notna(row.get('pc_encoding')):
        item['properties']['pc:encoding'] = row['pc_encoding']

    # Add projection properties
    if pd.notna(row.get('proj_epsg')):
        item['properties']['proj:epsg'] = row['proj_epsg']
    if pd.notna(row.get('proj_bbox')):
        item['properties']['proj:bbox'] = row['proj_bbox']

    return item


def row_to_collection(row: pd.Series) -> Dict[str, Any]:
    """Convert a DataFrame row to STAC Collection."""
    # If we have stored full JSON, use it
    if 'collection_json' in row and pd.notna(row['collection_json']):
        return json.loads(row['collection_json'])

    # Parse bbox
    bbox_val = row.get('bbox')
    if isinstance(bbox_val, str):
        bbox_val = json.loads(bbox_val)

    # Otherwise, reconstruct
    collection = {
        "type": "Collection",
        "stac_version": row.get('stac_version', settings.stac_version),
        "id": row['id'],
        "title": row.get('title'),
        "description": row.get('description', ''),
        "license": row.get('license', 'proprietary'),
        "extent": {
            "spatial": {"bbox": [bbox_val] if bbox_val else []},
            "temporal": {"interval": [[row.get('start_datetime'), row.get('end_datetime')]]}
        },
        "links": json.loads(row['links']) if pd.notna(row.get('links')) else [],
    }

    if pd.notna(row.get('summaries')):
        collection['summaries'] = json.loads(row['summaries'])

    if pd.notna(row.get('providers')):
        collection['providers'] = json.loads(row['providers'])

    if pd.notna(row.get('stac_extensions')):
        collection['stac_extensions'] = row['stac_extensions']

    return collection


# API Endpoints

@app.get("/", response_class=JSONResponse)
async def root(request: Request):
    """Landing page / Root catalog."""
    base_url = get_base_url(request)

    return {
        "type": "Catalog",
        "id": _catalog_metadata.get('catalog_id', 'stac-catalog'),
        "stac_version": settings.stac_version,
        "title": _catalog_metadata.get('catalog_title', 'STAC Catalog'),
        "description": _catalog_metadata.get('catalog_description', 'STAC API'),
        "conformsTo": [
            "https://api.stacspec.org/v1.0.0/core",
            "https://api.stacspec.org/v1.0.0/collections",
            "https://api.stacspec.org/v1.0.0/item-search",
            "https://api.stacspec.org/v1.0.0/ogcapi-features"
        ],
        "links": [
            {"rel": "self", "href": f"{base_url}/", "type": "application/json"},
            {"rel": "root", "href": f"{base_url}/", "type": "application/json"},
            {"rel": "conformance", "href": f"{base_url}/conformance", "type": "application/json"},
            {"rel": "data", "href": f"{base_url}/collections", "type": "application/json"},
            {"rel": "search", "href": f"{base_url}/search", "type": "application/geo+json", "method": "GET"},
            {"rel": "search", "href": f"{base_url}/search", "type": "application/geo+json", "method": "POST"},
            {"rel": "queryables", "href": f"{base_url}/queryables", "type": "application/schema+json"},
        ]
    }


@app.get("/conformance", response_class=JSONResponse)
async def conformance():
    """Conformance classes."""
    return {
        "conformsTo": [
            "https://api.stacspec.org/v1.0.0/core",
            "https://api.stacspec.org/v1.0.0/collections",
            "https://api.stacspec.org/v1.0.0/item-search",
            "https://api.stacspec.org/v1.0.0/ogcapi-features",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"
        ]
    }


@app.get("/collections", response_class=JSONResponse)
async def list_collections(request: Request):
    """List all collections."""
    base_url = get_base_url(request)

    collections = []
    for _, row in _collections_df.iterrows():
        collection = row_to_collection(row)
        # Add API links
        collection['links'] = [
            {"rel": "self", "href": f"{base_url}/collections/{collection['id']}", "type": "application/json"},
            {"rel": "parent", "href": f"{base_url}/", "type": "application/json"},
            {"rel": "root", "href": f"{base_url}/", "type": "application/json"},
            {"rel": "items", "href": f"{base_url}/collections/{collection['id']}/items", "type": "application/geo+json"},
        ]
        collections.append(collection)

    return {
        "collections": collections,
        "links": [
            {"rel": "self", "href": f"{base_url}/collections", "type": "application/json"},
            {"rel": "root", "href": f"{base_url}/", "type": "application/json"}
        ]
    }


@app.get("/collections/{collection_id}", response_class=JSONResponse)
async def get_collection(collection_id: str, request: Request):
    """Get a single collection."""
    base_url = get_base_url(request)

    matches = _collections_df[_collections_df['id'] == collection_id]
    if matches.empty:
        raise HTTPException(status_code=404, detail=f"Collection not found: {collection_id}")

    collection = row_to_collection(matches.iloc[0])
    collection['links'] = [
        {"rel": "self", "href": f"{base_url}/collections/{collection_id}", "type": "application/json"},
        {"rel": "parent", "href": f"{base_url}/", "type": "application/json"},
        {"rel": "root", "href": f"{base_url}/", "type": "application/json"},
        {"rel": "items", "href": f"{base_url}/collections/{collection_id}/items", "type": "application/geo+json"},
    ]

    return collection


@app.get("/collections/{collection_id}/items", response_class=JSONResponse)
async def list_items(
    collection_id: str,
    request: Request,
    limit: int = Query(default=settings.default_limit, ge=1, le=settings.max_limit),
    bbox: Optional[str] = Query(default=None, description="Bounding box: minx,miny,maxx,maxy"),
    bbox_crs: Optional[str] = Query(default=None, alias="bbox-crs", description="CRS for bbox (e.g., 'EPSG:6676'). Default is WGS84")
):
    """List items in a collection."""
    base_url = get_base_url(request)

    # Check collection exists
    if collection_id not in _collections_df['id'].values:
        raise HTTPException(status_code=404, detail=f"Collection not found: {collection_id}")

    # Parse bbox if provided
    bbox_list = None
    if bbox:
        bbox_list = [float(x) for x in bbox.split(',')]

    # Filter items
    filtered = filter_items(
        _items_df,
        collections=[collection_id],
        bbox=bbox_list,
        bbox_crs=bbox_crs,
        limit=limit
    )

    # Convert to STAC items
    features = [row_to_item(row) for _, row in filtered.iterrows()]

    # Add API links to each item
    for feature in features:
        feature['links'] = [
            {"rel": "self", "href": f"{base_url}/collections/{collection_id}/items/{feature['id']}", "type": "application/geo+json"},
            {"rel": "parent", "href": f"{base_url}/collections/{collection_id}", "type": "application/json"},
            {"rel": "collection", "href": f"{base_url}/collections/{collection_id}", "type": "application/json"},
            {"rel": "root", "href": f"{base_url}/", "type": "application/json"},
        ]

    return {
        "type": "FeatureCollection",
        "features": features,
        "numberMatched": len(_items_df[_items_df['collection'] == collection_id]),
        "numberReturned": len(features),
        "links": [
            {"rel": "self", "href": f"{base_url}/collections/{collection_id}/items", "type": "application/geo+json"},
            {"rel": "parent", "href": f"{base_url}/collections/{collection_id}", "type": "application/json"},
            {"rel": "root", "href": f"{base_url}/", "type": "application/json"},
        ]
    }


@app.get("/collections/{collection_id}/items/{item_id}", response_class=JSONResponse)
async def get_item(collection_id: str, item_id: str, request: Request):
    """Get a single item."""
    base_url = get_base_url(request)

    # Find item
    matches = _items_df[
        (_items_df['id'] == item_id) &
        (_items_df['collection'] == collection_id)
    ]

    if matches.empty:
        raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")

    item = row_to_item(matches.iloc[0])
    item['links'] = [
        {"rel": "self", "href": f"{base_url}/collections/{collection_id}/items/{item_id}", "type": "application/geo+json"},
        {"rel": "parent", "href": f"{base_url}/collections/{collection_id}", "type": "application/json"},
        {"rel": "collection", "href": f"{base_url}/collections/{collection_id}", "type": "application/json"},
        {"rel": "root", "href": f"{base_url}/", "type": "application/json"},
    ]

    return item


@app.post("/search", response_class=JSONResponse)
async def search_post(search: SearchRequest, request: Request):
    """Search items (POST)."""
    base_url = get_base_url(request)

    # Filter items
    filtered = filter_items(
        _items_df,
        collections=search.collections,
        ids=search.ids,
        bbox=search.bbox,
        bbox_crs=search.bbox_crs,
        datetime_filter=search.datetime,
        limit=search.limit
    )

    # Convert to STAC items
    features = [row_to_item(row) for _, row in filtered.iterrows()]

    # Add API links
    for feature in features:
        collection_id = feature.get('collection', 'unknown')
        feature['links'] = [
            {"rel": "self", "href": f"{base_url}/collections/{collection_id}/items/{feature['id']}", "type": "application/geo+json"},
            {"rel": "collection", "href": f"{base_url}/collections/{collection_id}", "type": "application/json"},
            {"rel": "root", "href": f"{base_url}/", "type": "application/json"},
        ]

    return {
        "type": "FeatureCollection",
        "features": features,
        "numberMatched": len(_items_df),  # Total without filters
        "numberReturned": len(features),
        "links": [
            {"rel": "self", "href": f"{base_url}/search", "type": "application/geo+json"},
            {"rel": "root", "href": f"{base_url}/", "type": "application/json"},
        ]
    }


@app.get("/search", response_class=JSONResponse)
async def search_get(
    request: Request,
    collections: Optional[str] = Query(default=None, description="Comma-separated collection IDs"),
    ids: Optional[str] = Query(default=None, description="Comma-separated item IDs"),
    bbox: Optional[str] = Query(default=None, description="Bounding box: minx,miny,maxx,maxy"),
    bbox_crs: Optional[str] = Query(default=None, alias="bbox-crs", description="CRS for bbox (e.g., 'EPSG:6676'). Default is WGS84"),
    datetime: Optional[str] = Query(default=None, description="Datetime filter"),
    limit: int = Query(default=settings.default_limit, ge=1, le=settings.max_limit)
):
    """Search items (GET)."""
    # Convert to SearchRequest
    search = SearchRequest(
        collections=collections.split(',') if collections else None,
        ids=ids.split(',') if ids else None,
        bbox=[float(x) for x in bbox.split(',')] if bbox else None,
        bbox_crs=bbox_crs,
        datetime=datetime,
        limit=limit
    )

    return await search_post(search, request)


@app.get("/queryables", response_class=JSONResponse)
async def queryables(request: Request):
    """Get queryable properties."""
    base_url = get_base_url(request)

    return {
        "$schema": "https://json-schema.org/draft/2019-09/schema",
        "$id": f"{base_url}/queryables",
        "type": "object",
        "title": "Queryables",
        "description": "Queryable properties for STAC API search. Supports bbox-crs parameter for coordinate system transformation.",
        "properties": {
            "id": {
                "title": "Item ID",
                "type": "string"
            },
            "collection": {
                "title": "Collection ID",
                "type": "string"
            },
            "datetime": {
                "title": "Datetime",
                "type": "string",
                "format": "date-time"
            },
            "bbox": {
                "title": "Bounding Box",
                "description": "Bounding box filter. Use bbox-crs parameter to specify coordinate system.",
                "type": "array",
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 6
            },
            "bbox-crs": {
                "title": "Bounding Box CRS",
                "description": "Coordinate Reference System for bbox parameter. Default is EPSG:4326 (WGS84).",
                "type": "string",
                "enum": ["EPSG:4326", "EPSG:6676", "EPSG:6677"],
                "default": "EPSG:4326"
            },
            "pc:count": {
                "title": "Point Count",
                "type": "integer"
            },
            "pc:type": {
                "title": "Point Cloud Type",
                "type": "string"
            },
            "proj:epsg": {
                "title": "EPSG Code",
                "description": "Native coordinate system EPSG code of the data",
                "type": "integer"
            }
        },
        "additionalProperties": {
            "crs": {
                "title": "Supported CRS",
                "description": "Coordinate Reference Systems supported for bbox queries",
                "default": ["EPSG:4326", "EPSG:6676", "EPSG:6677"],
                "note": "EPSG:4326 = WGS84, EPSG:6676 = JGD2011 Zone 8 (Mt. Fuji), EPSG:6677 = JGD2011 Zone 9 (Kasugai)"
            }
        }
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    # Check if index should be reloaded
    if should_reload_index():
        logger.info("Index TTL expired, reloading from S3...")
        load_index()

    return {
        "status": "healthy",
        "items_loaded": len(_items_df) if _items_df is not None else 0,
        "collections_loaded": len(_collections_df) if _collections_df is not None else 0,
        "use_s3_index": settings.use_s3_index,
        "index_loaded_at": _index_loaded_at if settings.use_s3_index else None
    }


@app.post("/admin/refresh-index")
async def refresh_index():
    """Manually refresh the index from S3."""
    if not settings.use_s3_index:
        raise HTTPException(status_code=400, detail="S3 index not enabled")

    load_index()
    return {
        "status": "refreshed",
        "items_loaded": len(_items_df) if _items_df is not None else 0,
        "collections_loaded": len(_collections_df) if _collections_df is not None else 0,
        "loaded_at": _index_loaded_at
    }


# Lambda handler for AWS deployment
try:
    from mangum import Mangum

    # Create Mangum handler with stage path stripping
    # api_gateway_base_path strips the stage name from the path
    _mangum_handler = Mangum(app, api_gateway_base_path="/prod")

    def handler(event, context):
        # Handle keep-warm events (API Gateway v1 format)
        if "httpMethod" in event and "version" not in event:
            return {"statusCode": 200, "body": '{"status": "warm"}'}

        return _mangum_handler(event, context)
except ImportError:
    handler = None  # Not running on Lambda
