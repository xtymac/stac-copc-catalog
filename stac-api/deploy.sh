#!/bin/bash
# Deploy STAC API to AWS Lambda
# Supports both SAM CLI and direct Docker + AWS CLI deployment

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STAGE="${1:-prod}"
STACK_NAME="stac-api-${STAGE}"
REGION="${AWS_REGION:-ap-northeast-1}"
ECR_REPO="stac-api"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")

echo "=== STAC API Deployment ==="
echo "Stage: $STAGE"
echo "Stack: $STACK_NAME"
echo "Region: $REGION"
echo ""

# Step 1: Generate index if needed
if [ ! -d "$SCRIPT_DIR/index" ]; then
    echo ">>> Step 1: Generating Parquet index..."
    cd "$PROJECT_DIR"
    source .venv/bin/activate
    python scripts/index-to-parquet.py --catalog catalog-combined --output stac-api/index
else
    echo ">>> Step 1: Index already exists, skipping..."
fi

# Check if SAM is available
if command -v sam &> /dev/null; then
    echo ""
    echo ">>> Using SAM CLI for deployment..."

    # Step 2: Build Docker image
    echo ""
    echo ">>> Step 2: Building Docker image..."
    cd "$SCRIPT_DIR"
    sam build --use-container

    # Step 3: Deploy to AWS
    echo ""
    echo ">>> Step 3: Deploying to AWS..."
    sam deploy \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --capabilities CAPABILITY_IAM \
        --parameter-overrides Stage="$STAGE" \
        --resolve-s3 \
        --resolve-image-repos \
        --no-confirm-changeset \
        --no-fail-on-empty-changeset

    # Step 4: Get outputs
    echo ""
    echo ">>> Step 4: Getting deployment outputs..."
    API_URL=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
        --output text)
else
    echo ""
    echo ">>> SAM CLI not found. Using Docker + AWS CLI..."
    echo ""
    echo "To install SAM CLI:"
    echo "  brew install aws-sam-cli"
    echo ""
    echo "Or deploy manually:"
    echo ""
    echo "1. Build Docker image:"
    echo "   cd $SCRIPT_DIR"
    echo "   docker build -t stac-api:latest ."
    echo ""
    echo "2. Create ECR repository (if not exists):"
    echo "   aws ecr create-repository --repository-name $ECR_REPO --region $REGION"
    echo ""
    echo "3. Push to ECR:"
    echo "   aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
    echo "   docker tag stac-api:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$ECR_REPO:$STAGE"
    echo "   docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$ECR_REPO:$STAGE"
    echo ""
    echo "4. Create Lambda function via AWS Console or CLI"
    echo ""
    exit 1
fi

echo ""
echo "=== Deployment Complete ==="
echo "API URL: $API_URL"
echo ""
echo "Test commands:"
echo "  curl ${API_URL}"
echo "  curl ${API_URL}collections"
echo "  curl ${API_URL}search"
echo ""
echo "To integrate with CloudFront, add origin for:"
echo "  Origin Domain: ${STACK_NAME}.execute-api.${REGION}.amazonaws.com"
echo "  Origin Path: /${STAGE}"
