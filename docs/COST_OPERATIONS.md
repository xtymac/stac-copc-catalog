# Cost Estimation and Operations Guide

## Monthly Cost Breakdown

### Target Budget: $20-50/month

This estimate assumes:
- 50-200 GB of COPC data
- Low to moderate traffic (< 1000 requests/day)
- Data accessed primarily from Japan/Asia-Pacific

---

## AWS Cost Components

### 1. S3 Storage

| Storage Class | Price (ap-northeast-1) | 50 GB | 100 GB | 200 GB |
|---------------|------------------------|-------|--------|--------|
| Standard | $0.025/GB/month | $1.25 | $2.50 | $5.00 |
| Standard-IA | $0.0138/GB/month | $0.69 | $1.38 | $2.76 |
| Glacier | $0.005/GB/month | $0.25 | $0.50 | $1.00 |

**With Lifecycle Rules (after 90 days):**
- First 3 months: Standard pricing
- After 3 months: ~45% savings on data storage

### 2. S3 Requests

| Operation | Price | Estimated Monthly |
|-----------|-------|-------------------|
| GET/HEAD | $0.00037/1000 | ~$0.50-2.00 |
| PUT/POST | $0.0047/1000 | ~$0.10-0.50 |
| LIST | $0.0047/1000 | ~$0.05 |

### 3. CloudFront

| Component | Price | Estimated Monthly |
|-----------|-------|-------------------|
| Data Transfer (first 10 TB) | $0.114/GB (Japan) | $5-15 |
| HTTP Requests | $0.0090/10,000 | $0.50-2.00 |
| HTTPS Requests | $0.0120/10,000 | $0.75-3.00 |

### 4. Route 53 (Optional)

| Component | Price |
|-----------|-------|
| Hosted Zone | $0.50/month |
| DNS Queries | $0.40/million |

### 5. ACM Certificate

- **Free** for CloudFront distributions

---

## Cost Scenarios

### Scenario A: Minimal Usage (< 10 GB transfer/month)

| Component | Cost |
|-----------|------|
| S3 Storage (100 GB Standard) | $2.50 |
| S3 Requests | $0.50 |
| CloudFront Transfer (10 GB) | $1.14 |
| CloudFront Requests (50K) | $0.60 |
| **Total** | **~$5/month** |

### Scenario B: Moderate Usage (50 GB transfer/month)

| Component | Cost |
|-----------|------|
| S3 Storage (150 GB, mixed) | $3.00 |
| S3 Requests | $1.50 |
| CloudFront Transfer (50 GB) | $5.70 |
| CloudFront Requests (200K) | $2.40 |
| Route 53 | $0.50 |
| **Total** | **~$13/month** |

### Scenario C: Active Usage (200 GB transfer/month)

| Component | Cost |
|-----------|------|
| S3 Storage (200 GB, lifecycle) | $4.00 |
| S3 Requests | $3.00 |
| CloudFront Transfer (200 GB) | $22.80 |
| CloudFront Requests (500K) | $6.00 |
| Route 53 | $0.50 |
| **Total** | **~$36/month** |

---

## Cost Optimization Strategies

### 1. Storage Optimization

```json
// Lifecycle rules (already configured)
{
  "data/*": "Standard → Standard-IA (90 days)",
  "raw/*": "Standard → IA (30 days) → Glacier (180 days)",
  "logs/*": "Standard → Glacier (30 days) → Delete (365 days)",
  "tmp/*": "Delete (7 days)"
}
```

### 2. CloudFront Caching

| Content Type | TTL | Rationale |
|--------------|-----|-----------|
| `*.copc.laz` | 7 days | Immutable data |
| `*.json` (STAC) | 5 minutes | May be updated |
| `browser/*` | 1 hour | Static assets |

### 3. Compression

- JSON files: gzip enabled (CloudFront)
- COPC files: Already compressed (LAZ)

### 4. Request Reduction

- Enable HTTP/2 multiplexing (CloudFront default)
- Use range requests for COPC files
- Cache STAC Browser assets aggressively

---

## Monitoring and Alerts

### AWS Budget Setup

```bash
# Create budget alert at $50/month
aws budgets create-budget \
    --account-id $AWS_ACCOUNT_ID \
    --budget '{
        "BudgetName": "STAC-COPC-Monthly",
        "BudgetLimit": {
            "Amount": "50",
            "Unit": "USD"
        },
        "TimeUnit": "MONTHLY",
        "BudgetType": "COST"
    }' \
    --notifications-with-subscribers '[{
        "Notification": {
            "NotificationType": "ACTUAL",
            "ComparisonOperator": "GREATER_THAN",
            "Threshold": 80
        },
        "Subscribers": [{
            "SubscriptionType": "EMAIL",
            "Address": "your-email@example.com"
        }]
    }]'
```

### CloudWatch Metrics to Monitor

1. **S3 Metrics:**
   - `BucketSizeBytes` - Total storage
   - `NumberOfObjects` - Object count
   - `AllRequests` - Request volume

2. **CloudFront Metrics:**
   - `Requests` - Total requests
   - `BytesDownloaded` - Data transfer
   - `4xxErrorRate` - Client errors
   - `5xxErrorRate` - Server errors

---

## Operations Runbook

### Adding New Data

```bash
# 1. Place new LAS/LAZ files in local/input/
cp new-data/*.laz local/input/

# 2. Convert to COPC
python scripts/01-prepare-data.py \
    --input-dir ./local/input \
    --output-dir ./local/output

# 3. Regenerate STAC catalog
python scripts/02-generate-stac.py \
    --data-dir ./local/output \
    --catalog-dir ./catalog \
    --base-url https://your-domain.com

# 4. Validate
python scripts/04-validate.py --catalog-dir ./catalog

# 5. Deploy
./scripts/03-deploy-aws.sh --update
```

### Updating STAC Browser

```bash
# Update version in .env
echo "STAC_BROWSER_VERSION=3.3.0" >> .env

# Rebuild
./scripts/05-build-browser.sh

# Deploy
./scripts/03-deploy-aws.sh --update
```

### Checking Deployment Status

```bash
./scripts/03-deploy-aws.sh --status
```

### Invalidating Cache

```bash
# Get distribution ID
DIST_ID=$(cat .cloudfront-distribution-id)

# Invalidate specific paths
aws cloudfront create-invalidation \
    --distribution-id $DIST_ID \
    --paths "/catalog.json" "/collections/*"

# Invalidate everything
aws cloudfront create-invalidation \
    --distribution-id $DIST_ID \
    --paths "/*"
```

---

## Backup Strategy

### What to Backup

1. **Source data** (`raw/*`): Original LAS/LAZ files
2. **STAC catalog** (`catalog/`): Version controlled in git
3. **Configuration** (`.env`, `config/`): Version controlled

### Backup Script

```bash
#!/bin/bash
# Backup source data to Glacier

aws s3 sync ./local/input s3://$BUCKET_NAME/raw/ \
    --storage-class GLACIER

# The catalog is in git, so just push
git add catalog/
git commit -m "Catalog backup $(date +%Y-%m-%d)"
git push
```

---

## Disaster Recovery

### S3 Versioning

Versioning is enabled by default. To restore a previous version:

```bash
# List versions
aws s3api list-object-versions \
    --bucket $BUCKET_NAME \
    --prefix catalog.json

# Restore specific version
aws s3api copy-object \
    --bucket $BUCKET_NAME \
    --copy-source "$BUCKET_NAME/catalog.json?versionId=VERSION_ID" \
    --key catalog.json
```

### Full Redeploy

```bash
# From a fresh checkout
git clone <repo-url>
cd Study\ STAC

# Install dependencies
./scripts/install-deps.sh

# Rebuild catalog from source data
python scripts/01-prepare-data.py --input-dir ./backup/input --output-dir ./local/output
python scripts/02-generate-stac.py --data-dir ./local/output --catalog-dir ./catalog

# Deploy
./scripts/03-deploy-aws.sh --create
```

---

## Monthly Maintenance Checklist

- [ ] Review AWS Cost Explorer for unexpected charges
- [ ] Check CloudFront cache hit ratio (target: > 80%)
- [ ] Verify S3 lifecycle transitions are working
- [ ] Review access logs for unusual patterns
- [ ] Update STAC Browser if new version available
- [ ] Test catalog validation
- [ ] Verify PDAL compatibility with sample item
