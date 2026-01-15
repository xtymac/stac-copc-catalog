# CKAN Integration Pattern

This document describes how to integrate the static STAC catalog with CKAN for discovery and metadata management.

## Overview

The STAC catalog is standalone and static-first, but can be linked from CKAN as external resources. This provides:

- **STAC**: Efficient point cloud data access (range requests, cloud-native)
- **CKAN**: Data discovery, organization metadata, access control

---

## Integration Options

### Option 1: Link STAC Items as CKAN Resources

Each STAC item can be registered as a CKAN resource with the STAC item URL.

```python
from ckanapi import RemoteCKAN

ckan = RemoteCKAN('https://your-ckan-instance.com', apikey='your-api-key')

# Create/update CKAN dataset
dataset = ckan.action.package_create(
    name='pointcloud-jgd2011',
    title='Point Cloud Collection (JGD2011)',
    notes='LiDAR point cloud data in COPC format',
    owner_org='your-organization',
    extras=[
        {'key': 'stac_catalog_url', 'value': 'https://stac.example.com/catalog.json'},
        {'key': 'stac_collection_id', 'value': 'pointcloud-jgd2011'},
        {'key': 'data_format', 'value': 'COPC'},
    ]
)

# Add STAC collection as resource
ckan.action.resource_create(
    package_id=dataset['id'],
    name='STAC Collection',
    description='STAC Collection metadata (JSON)',
    url='https://stac.example.com/collections/pointcloud-jgd2011/collection.json',
    format='JSON',
    resource_type='stac_collection'
)
```

### Option 2: Sync STAC Items to CKAN Resources

For tighter integration, sync each STAC item as a separate CKAN resource.

```python
import pystac
from ckanapi import RemoteCKAN

def sync_stac_to_ckan(catalog_url: str, ckan_url: str, api_key: str, package_id: str):
    """Sync STAC items to CKAN resources."""

    catalog = pystac.read_file(catalog_url)
    ckan = RemoteCKAN(ckan_url, apikey=api_key)

    for item in catalog.get_items(recursive=True):
        # Get data asset
        data_asset = item.assets.get('data')
        if not data_asset:
            continue

        # Check if resource exists
        existing = ckan.action.resource_search(
            query=f'name:{item.id}'
        )

        resource_data = {
            'package_id': package_id,
            'name': item.id,
            'description': item.properties.get('description', ''),
            'url': data_asset.href,
            'format': 'COPC',
            'mimetype': 'application/vnd.laszip+copc',
            # STAC metadata as extras
            'stac_item_url': item.get_self_href(),
            'pc_count': item.properties.get('pc:count', 0),
            'pc_type': item.properties.get('pc:type', ''),
            'proj_epsg': item.properties.get('proj:epsg', ''),
        }

        if existing['results']:
            # Update existing
            resource_data['id'] = existing['results'][0]['id']
            ckan.action.resource_update(**resource_data)
        else:
            # Create new
            ckan.action.resource_create(**resource_data)
```

### Option 3: CKAN STAC Extension

Use or develop a CKAN extension that understands STAC catalogs.

```python
# Example ckanext-stac configuration
# ckan.ini

ckan.plugins = stac_harvester stac_view

# STAC Harvester configuration
ckanext.stac.catalog_url = https://stac.example.com/catalog.json
ckanext.stac.harvest_interval = 3600  # seconds
ckanext.stac.collection_mapping = {
    "pointcloud-jgd2011": "pointcloud-dataset"
}
```

---

## Metadata Mapping

### STAC to CKAN Field Mapping

| STAC Field | CKAN Field | Notes |
|------------|------------|-------|
| `catalog.id` | `package.name` | URL-safe identifier |
| `catalog.title` | `package.title` | Human-readable title |
| `catalog.description` | `package.notes` | Markdown description |
| `collection.license` | `package.license_id` | License identifier |
| `collection.providers` | `package.author` | First producer |
| `collection.extent.spatial` | `package.spatial` | GeoJSON bbox |
| `item.id` | `resource.name` | Item identifier |
| `item.assets.data.href` | `resource.url` | Data URL |
| `item.properties.pc:count` | `resource.pc_count` | Point count |
| `item.properties.proj:epsg` | `resource.proj_epsg` | CRS code |

### Custom CKAN Schema

For full STAC support, extend CKAN schema:

```python
# ckanext-stac/plugin.py

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

class StacPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IDatasetForm)

    def _modify_package_schema(self, schema):
        schema.update({
            'stac_catalog_url': [
                toolkit.get_validator('ignore_missing'),
                toolkit.get_converter('convert_to_extras')
            ],
            'stac_collection_id': [
                toolkit.get_validator('ignore_missing'),
                toolkit.get_converter('convert_to_extras')
            ],
        })
        return schema

    def create_package_schema(self):
        schema = super().create_package_schema()
        return self._modify_package_schema(schema)

    def update_package_schema(self):
        schema = super().update_package_schema()
        return self._modify_package_schema(schema)
```

---

## CKAN Resource View for COPC

Create a custom view for displaying point cloud data:

```javascript
// ckanext-stac/public/stac-pointcloud-view.js

ckan.module('stac-pointcloud-view', function($) {
    return {
        initialize: function() {
            const stacItemUrl = this.options.stacItemUrl;
            const container = this.el;

            // Fetch STAC item
            fetch(stacItemUrl)
                .then(response => response.json())
                .then(item => {
                    // Display metadata
                    const html = `
                        <div class="stac-item-info">
                            <h4>${item.id}</h4>
                            <p>Points: ${item.properties['pc:count'].toLocaleString()}</p>
                            <p>CRS: EPSG:${item.properties['proj:epsg']}</p>
                            <p>Format: ${item.properties['pc:encoding']}</p>
                            <a href="${item.assets.data.href}" class="btn btn-primary">
                                Download COPC
                            </a>
                        </div>
                    `;
                    container.html(html);
                });
        }
    };
});
```

---

## Automated Sync Script

```python
#!/usr/bin/env python3
"""
Sync STAC catalog to CKAN.

Usage:
    python sync-stac-to-ckan.py \
        --stac-url https://stac.example.com/catalog.json \
        --ckan-url https://ckan.example.com \
        --api-key your-api-key \
        --organization your-org
"""

import argparse
import logging
from datetime import datetime

import pystac
from ckanapi import RemoteCKAN, NotFound

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def sync_catalog(stac_url: str, ckan_url: str, api_key: str, organization: str):
    """Sync STAC catalog to CKAN."""

    catalog = pystac.read_file(stac_url)
    ckan = RemoteCKAN(ckan_url, apikey=api_key)

    for collection in catalog.get_children():
        if not isinstance(collection, pystac.Collection):
            continue

        logger.info(f"Processing collection: {collection.id}")

        # Create or update CKAN dataset
        package_name = f"stac-{collection.id}"

        try:
            package = ckan.action.package_show(id=package_name)
            action = ckan.action.package_update
        except NotFound:
            package = None
            action = ckan.action.package_create

        # Build package data
        package_data = {
            'name': package_name,
            'title': collection.title or collection.id,
            'notes': collection.description or '',
            'owner_org': organization,
            'license_id': collection.license or 'notspecified',
            'extras': [
                {'key': 'stac_collection_url', 'value': collection.get_self_href()},
                {'key': 'stac_type', 'value': 'collection'},
                {'key': 'last_synced', 'value': datetime.now().isoformat()},
            ]
        }

        if package:
            package_data['id'] = package['id']

        result = action(**package_data)
        package_id = result['id']

        # Sync items as resources
        for item in collection.get_items():
            sync_item(ckan, package_id, item)

        logger.info(f"Synced collection: {collection.id}")


def sync_item(ckan: RemoteCKAN, package_id: str, item: pystac.Item):
    """Sync STAC item as CKAN resource."""

    data_asset = item.assets.get('data')
    if not data_asset:
        return

    resource_name = f"copc-{item.id}"

    # Check existing
    package = ckan.action.package_show(id=package_id)
    existing = None
    for resource in package.get('resources', []):
        if resource['name'] == resource_name:
            existing = resource
            break

    resource_data = {
        'package_id': package_id,
        'name': resource_name,
        'description': item.properties.get('description', f'COPC data for {item.id}'),
        'url': data_asset.href,
        'format': 'COPC',
        'mimetype': 'application/vnd.laszip+copc',
        'stac_item_url': item.get_self_href(),
    }

    if existing:
        resource_data['id'] = existing['id']
        ckan.action.resource_update(**resource_data)
    else:
        ckan.action.resource_create(**resource_data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stac-url', required=True)
    parser.add_argument('--ckan-url', required=True)
    parser.add_argument('--api-key', required=True)
    parser.add_argument('--organization', required=True)
    args = parser.parse_args()

    sync_catalog(args.stac_url, args.ckan_url, args.api_key, args.organization)
```

---

## Best Practices

1. **Keep STAC as source of truth** for point cloud metadata
2. **Use CKAN for discovery** and organizational metadata
3. **Automate sync** with scheduled jobs (cron, Airflow)
4. **Validate URLs** before syncing to CKAN
5. **Monitor sync status** and handle failures gracefully

---

## Related Resources

- [CKAN API Documentation](https://docs.ckan.org/en/latest/api/)
- [ckanapi Python Library](https://github.com/ckan/ckanapi)
- [STAC Specification](https://stacspec.org/)
- [pystac Documentation](https://pystac.readthedocs.io/)
