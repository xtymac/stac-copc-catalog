#!/bin/bash
# AWS Deployment Script for STAC COPC Catalog
#
# This script handles:
# - S3 bucket creation and configuration
# - CloudFront distribution with OAC
# - Bucket policy, CORS, and lifecycle rules
# - Syncing catalog and data to S3
#
# Usage:
#   ./03-deploy-aws.sh --create     # Create infrastructure and deploy
#   ./03-deploy-aws.sh --update     # Update content and invalidate cache
#   ./03-deploy-aws.sh --sync-only  # Just sync files (no cache invalidation)
#   ./03-deploy-aws.sh --status     # Show deployment status

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load environment variables
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration (override via environment or .env file)
BUCKET_NAME="${STAC_BUCKET_NAME:-stac-copc-catalog}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
CUSTOM_DOMAIN="${STAC_DOMAIN:-}"
ACM_CERT_ARN="${ACM_CERTIFICATE_ARN:-}"

# Paths
CONFIG_DIR="$PROJECT_ROOT/config/aws"
CATALOG_DIR="$PROJECT_ROOT/catalog"
DATA_DIR="$PROJECT_ROOT/local/output"
BROWSER_DIR="$PROJECT_ROOT/stac-browser/dist"
POTREE_DIR="$PROJECT_ROOT/potree-viewer/dist"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1" >&2; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1" >&2; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1" >&2; }

check_prerequisites() {
    log_step "Checking prerequisites..."

    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI not installed"
        log_info "Install from: https://aws.amazon.com/cli/"
        exit 1
    fi

    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured"
        log_info "Run: aws configure"
        exit 1
    fi

    # Check jq
    if ! command -v jq &> /dev/null; then
        log_error "jq not installed (required for JSON processing)"
        log_info "Install with: brew install jq"
        exit 1
    fi

    # Get account ID
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    log_info "AWS Account: $AWS_ACCOUNT_ID"
    log_info "Region: $AWS_REGION"
    log_info "Bucket: $BUCKET_NAME"

    if [ -n "$CUSTOM_DOMAIN" ]; then
        log_info "Domain: $CUSTOM_DOMAIN"
    fi
}

create_bucket() {
    log_step "Creating S3 bucket: $BUCKET_NAME"

    # Check if bucket exists
    if aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
        log_warn "Bucket already exists"
    else
        # Create bucket
        if [ "$AWS_REGION" = "us-east-1" ]; then
            aws s3api create-bucket --bucket "$BUCKET_NAME"
        else
            aws s3api create-bucket \
                --bucket "$BUCKET_NAME" \
                --region "$AWS_REGION" \
                --create-bucket-configuration LocationConstraint="$AWS_REGION"
        fi
        log_info "Bucket created"
    fi

    # Block all public access (we use CloudFront OAC)
    log_info "Configuring public access block..."
    aws s3api put-public-access-block \
        --bucket "$BUCKET_NAME" \
        --public-access-block-configuration \
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

    # Enable versioning
    log_info "Enabling versioning..."
    aws s3api put-bucket-versioning \
        --bucket "$BUCKET_NAME" \
        --versioning-configuration Status=Enabled
}

configure_cors() {
    log_step "Configuring CORS..."

    aws s3api put-bucket-cors \
        --bucket "$BUCKET_NAME" \
        --cors-configuration file://"$CONFIG_DIR/cors-config.json"

    log_info "CORS configured"
}

configure_lifecycle() {
    log_step "Configuring lifecycle rules..."

    aws s3api put-bucket-lifecycle-configuration \
        --bucket "$BUCKET_NAME" \
        --lifecycle-configuration file://"$CONFIG_DIR/lifecycle-rules.json"

    log_info "Lifecycle rules configured"
}

create_oac() {
    log_step "Creating CloudFront Origin Access Control..."

    OAC_NAME="oac-$BUCKET_NAME"

    # Check if OAC exists
    EXISTING_OAC=$(aws cloudfront list-origin-access-controls \
        --query "OriginAccessControlList.Items[?Name=='$OAC_NAME'].Id" \
        --output text 2>/dev/null || echo "")

    if [ -n "$EXISTING_OAC" ] && [ "$EXISTING_OAC" != "None" ]; then
        log_warn "OAC already exists: $EXISTING_OAC"
        echo "$EXISTING_OAC"
        return
    fi

    # Create OAC
    OAC_RESULT=$(aws cloudfront create-origin-access-control \
        --origin-access-control-config "{
            \"Name\": \"$OAC_NAME\",
            \"Description\": \"OAC for STAC COPC Catalog\",
            \"SigningProtocol\": \"sigv4\",
            \"SigningBehavior\": \"always\",
            \"OriginAccessControlOriginType\": \"s3\"
        }")

    OAC_ID=$(echo "$OAC_RESULT" | jq -r '.OriginAccessControl.Id')
    log_info "Created OAC: $OAC_ID"

    echo "$OAC_ID"
}

create_cloudfront_distribution() {
    local OAC_ID="$1"

    log_step "Creating CloudFront distribution..."

    # Generate unique caller reference
    CALLER_REF="stac-copc-$(date +%s)"

    # Build distribution config
    DIST_CONFIG=$(cat <<EOF
{
    "CallerReference": "$CALLER_REF",
    "Comment": "STAC COPC Catalog - $BUCKET_NAME",
    "Enabled": true,
    "HttpVersion": "http2and3",
    "IsIPV6Enabled": true,
    "PriceClass": "PriceClass_100",
    "DefaultRootObject": "browser/index.html",
    "Origins": {
        "Quantity": 1,
        "Items": [
            {
                "Id": "S3-$BUCKET_NAME",
                "DomainName": "$BUCKET_NAME.s3.$AWS_REGION.amazonaws.com",
                "OriginPath": "",
                "S3OriginConfig": {
                    "OriginAccessIdentity": ""
                },
                "OriginAccessControlId": "$OAC_ID"
            }
        ]
    },
    "DefaultCacheBehavior": {
        "TargetOriginId": "S3-$BUCKET_NAME",
        "ViewerProtocolPolicy": "redirect-to-https",
        "AllowedMethods": {
            "Quantity": 2,
            "Items": ["GET", "HEAD"],
            "CachedMethods": {
                "Quantity": 2,
                "Items": ["GET", "HEAD"]
            }
        },
        "Compress": true,
        "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
        "OriginRequestPolicyId": "88a5eaf4-2fd4-4709-b370-b4c650ea3fcf"
    },
    "CustomErrorResponses": {
        "Quantity": 2,
        "Items": [
            {
                "ErrorCode": 403,
                "ResponsePagePath": "/browser/index.html",
                "ResponseCode": "200",
                "ErrorCachingMinTTL": 300
            },
            {
                "ErrorCode": 404,
                "ResponsePagePath": "/browser/index.html",
                "ResponseCode": "200",
                "ErrorCachingMinTTL": 300
            }
        ]
    }
}
EOF
)

    # Add custom domain and certificate if provided
    if [ -n "$CUSTOM_DOMAIN" ] && [ -n "$ACM_CERT_ARN" ]; then
        DIST_CONFIG=$(echo "$DIST_CONFIG" | jq ". + {
            \"Aliases\": {
                \"Quantity\": 1,
                \"Items\": [\"$CUSTOM_DOMAIN\"]
            },
            \"ViewerCertificate\": {
                \"ACMCertificateArn\": \"$ACM_CERT_ARN\",
                \"SSLSupportMethod\": \"sni-only\",
                \"MinimumProtocolVersion\": \"TLSv1.2_2021\"
            }
        }")
    else
        DIST_CONFIG=$(echo "$DIST_CONFIG" | jq ". + {
            \"ViewerCertificate\": {
                \"CloudFrontDefaultCertificate\": true
            }
        }")
    fi

    # Close JSON
    DIST_CONFIG=$(echo "$DIST_CONFIG" | jq '.')

    # Create distribution
    DIST_RESULT=$(aws cloudfront create-distribution \
        --distribution-config "$DIST_CONFIG")

    DISTRIBUTION_ID=$(echo "$DIST_RESULT" | jq -r '.Distribution.Id')
    DISTRIBUTION_DOMAIN=$(echo "$DIST_RESULT" | jq -r '.Distribution.DomainName')

    log_info "Created distribution: $DISTRIBUTION_ID"
    log_info "Domain: $DISTRIBUTION_DOMAIN"

    # Save distribution info
    echo "$DISTRIBUTION_ID" > "$PROJECT_ROOT/.cloudfront-distribution-id"

    echo "$DISTRIBUTION_ID"
}

get_distribution_id() {
    # Try to get from saved file
    if [ -f "$PROJECT_ROOT/.cloudfront-distribution-id" ]; then
        cat "$PROJECT_ROOT/.cloudfront-distribution-id"
        return
    fi

    # Try to find by bucket name
    aws cloudfront list-distributions \
        --query "DistributionList.Items[?Origins.Items[?contains(DomainName, '$BUCKET_NAME')]].Id" \
        --output text 2>/dev/null | head -n1 || echo ""
}

update_bucket_policy() {
    local DISTRIBUTION_ID="$1"

    log_step "Updating bucket policy for OAC..."

    # Substitute variables in policy template
    POLICY=$(cat "$CONFIG_DIR/bucket-policy.json" | \
        sed "s/\${BUCKET_NAME}/$BUCKET_NAME/g" | \
        sed "s/\${AWS_ACCOUNT_ID}/$AWS_ACCOUNT_ID/g" | \
        sed "s/\${DISTRIBUTION_ID}/$DISTRIBUTION_ID/g")

    # Temporarily disable public access block for policy update
    aws s3api put-public-access-block \
        --bucket "$BUCKET_NAME" \
        --public-access-block-configuration \
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=false,RestrictPublicBuckets=false"

    # Apply policy
    aws s3api put-bucket-policy \
        --bucket "$BUCKET_NAME" \
        --policy "$POLICY"

    log_info "Bucket policy updated"
}

sync_catalog() {
    log_step "Syncing STAC catalog to S3..."

    if [ ! -d "$CATALOG_DIR" ]; then
        log_warn "Catalog directory not found: $CATALOG_DIR"
        log_warn "Run: python scripts/02-generate-stac.py first"
        return 1
    fi

    # Sync JSON files with appropriate content type
    aws s3 sync "$CATALOG_DIR" "s3://$BUCKET_NAME/" \
        --exclude "*" \
        --include "*.json" \
        --content-type "application/json" \
        --cache-control "max-age=300"

    log_info "Catalog synced"
}

sync_data() {
    log_step "Syncing COPC data to S3..."

    if [ ! -d "$DATA_DIR" ]; then
        log_warn "Data directory not found: $DATA_DIR"
        return 1
    fi

    # Check for COPC files
    COPC_COUNT=$(find "$DATA_DIR" -name "*.copc.laz" 2>/dev/null | wc -l | tr -d ' ')

    if [ "$COPC_COUNT" -eq 0 ]; then
        log_warn "No COPC files found in: $DATA_DIR"
        return 1
    fi

    log_info "Found $COPC_COUNT COPC files to sync"

    # Sync COPC files
    aws s3 sync "$DATA_DIR" "s3://$BUCKET_NAME/data/" \
        --exclude "*" \
        --include "*.copc.laz" \
        --content-type "application/vnd.laszip+copc" \
        --cache-control "max-age=604800"

    # Sync metadata files
    aws s3 sync "$DATA_DIR" "s3://$BUCKET_NAME/data/" \
        --exclude "*" \
        --include "*.metadata.json" \
        --content-type "application/json" \
        --cache-control "max-age=3600"

    log_info "Data synced"
}

sync_browser() {
    log_step "Syncing STAC Browser..."

    if [ ! -d "$BROWSER_DIR" ]; then
        log_warn "STAC Browser not built: $BROWSER_DIR"
        log_warn "Run: ./scripts/05-build-browser.sh first"
        return 1
    fi

    aws s3 sync "$BROWSER_DIR" "s3://$BUCKET_NAME/browser/" \
        --cache-control "max-age=3600"

    log_info "Browser synced"
}

sync_potree() {
    log_step "Syncing Potree viewer..."

    if [ ! -d "$POTREE_DIR" ]; then
        log_warn "Potree not built: $POTREE_DIR"
        log_warn "Run: ./scripts/06-build-potree.sh first"
        return 1
    fi

    # Sync all Potree files
    aws s3 sync "$POTREE_DIR" "s3://$BUCKET_NAME/potree/" \
        --cache-control "max-age=86400"

    # Set shorter cache for index.html
    if [ -f "$POTREE_DIR/index.html" ]; then
        aws s3 cp "$POTREE_DIR/index.html" "s3://$BUCKET_NAME/potree/index.html" \
            --content-type "text/html" \
            --cache-control "max-age=300" \
            --metadata-directive REPLACE
    fi

    log_info "Potree synced"
}

invalidate_cache() {
    local DISTRIBUTION_ID="$1"

    if [ -z "$DISTRIBUTION_ID" ]; then
        log_warn "No distribution ID provided, skipping cache invalidation"
        return
    fi

    log_step "Invalidating CloudFront cache..."

    aws cloudfront create-invalidation \
        --distribution-id "$DISTRIBUTION_ID" \
        --paths "/*.json" "/collections/*" "/browser/*" "/potree*" \
        --output text

    log_info "Cache invalidation initiated"
}

show_status() {
    log_step "Deployment Status"
    echo ""

    # Bucket
    if aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
        log_info "S3 Bucket: $BUCKET_NAME (exists)"

        # Count objects
        OBJ_COUNT=$(aws s3 ls "s3://$BUCKET_NAME/" --recursive --summarize 2>/dev/null | grep "Total Objects:" | awk '{print $3}' || echo "0")
        log_info "  Objects: $OBJ_COUNT"
    else
        log_warn "S3 Bucket: $BUCKET_NAME (not found)"
    fi

    # CloudFront
    DIST_ID=$(get_distribution_id)
    if [ -n "$DIST_ID" ] && [ "$DIST_ID" != "None" ]; then
        DIST_INFO=$(aws cloudfront get-distribution --id "$DIST_ID" 2>/dev/null || echo "{}")
        DIST_DOMAIN=$(echo "$DIST_INFO" | jq -r '.Distribution.DomainName // "unknown"')
        DIST_STATUS=$(echo "$DIST_INFO" | jq -r '.Distribution.Status // "unknown"')

        log_info "CloudFront: $DIST_ID"
        log_info "  Domain: $DIST_DOMAIN"
        log_info "  Status: $DIST_STATUS"

        if [ -n "$CUSTOM_DOMAIN" ]; then
            log_info "  Custom Domain: $CUSTOM_DOMAIN"
        fi
    else
        log_warn "CloudFront: Not configured"
    fi

    echo ""
    log_info "URLs:"
    if [ -n "$DIST_DOMAIN" ] && [ "$DIST_DOMAIN" != "unknown" ]; then
        log_info "  Catalog: https://$DIST_DOMAIN/catalog.json"
        log_info "  Browser: https://$DIST_DOMAIN/browser/"
    fi
    if [ -n "$CUSTOM_DOMAIN" ]; then
        log_info "  Custom:  https://$CUSTOM_DOMAIN/"
    fi
}

print_usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  --create      Create S3 bucket, CloudFront distribution, and deploy"
    echo "  --update      Sync content and invalidate CloudFront cache"
    echo "  --sync-only   Just sync files to S3 (no cache invalidation)"
    echo "  --status      Show deployment status"
    echo "  --help        Show this help message"
    echo ""
    echo "Environment variables (or .env file):"
    echo "  STAC_BUCKET_NAME        S3 bucket name (default: stac-copc-catalog)"
    echo "  AWS_REGION              AWS region (default: ap-northeast-1)"
    echo "  STAC_DOMAIN             Custom domain (optional)"
    echo "  ACM_CERTIFICATE_ARN     ACM certificate ARN (required for custom domain)"
}

# Main
ACTION="${1:-}"

case "$ACTION" in
    --create)
        check_prerequisites
        create_bucket
        configure_cors
        configure_lifecycle
        OAC_ID=$(create_oac)
        DIST_ID=$(create_cloudfront_distribution "$OAC_ID")
        update_bucket_policy "$DIST_ID"

        # Wait for distribution to deploy
        log_info "Waiting for CloudFront distribution to deploy (this may take 5-10 minutes)..."
        aws cloudfront wait distribution-deployed --id "$DIST_ID" &
        WAIT_PID=$!

        # While waiting, sync content
        sync_catalog || true
        sync_data || true
        sync_browser || true
        sync_potree || true

        # Wait for distribution
        wait $WAIT_PID 2>/dev/null || true

        echo ""
        log_info "============================================"
        log_info "DEPLOYMENT COMPLETE"
        log_info "============================================"
        show_status
        ;;

    --update)
        check_prerequisites
        sync_catalog || true
        sync_data || true
        sync_browser || true
        sync_potree || true

        DIST_ID=$(get_distribution_id)
        if [ -n "$DIST_ID" ]; then
            invalidate_cache "$DIST_ID"
        fi

        log_info "Update complete"
        ;;

    --sync-only)
        check_prerequisites
        sync_catalog || true
        sync_data || true
        sync_browser || true
        sync_potree || true
        log_info "Sync complete"
        ;;

    --status)
        check_prerequisites
        show_status
        ;;

    --help|-h|"")
        print_usage
        ;;

    *)
        log_error "Unknown command: $ACTION"
        print_usage
        exit 1
        ;;
esac
