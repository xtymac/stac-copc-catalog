# STAC API - Lambda Container Image
# Based on AWS Lambda Python 3.11 ARM64 base image

FROM public.ecr.aws/lambda/python:3.11-arm64

# Copy requirements first for caching
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Install Python dependencies
# Use --only-binary for all packages to avoid compilation
# This requires pre-built wheels which are available for ARM64 Linux
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --only-binary :all: -r requirements.txt

# Copy application code and fix permissions
COPY app/ ${LAMBDA_TASK_ROOT}/app/
RUN chmod -R 644 ${LAMBDA_TASK_ROOT}/app/*.py && \
    chmod 755 ${LAMBDA_TASK_ROOT}/app/

# Copy index files and fix permissions
COPY index/ ${LAMBDA_TASK_ROOT}/index/
RUN chmod -R 644 ${LAMBDA_TASK_ROOT}/index/* && \
    chmod 755 ${LAMBDA_TASK_ROOT}/index/

# Set environment variables
ENV INDEX_PATH=${LAMBDA_TASK_ROOT}/index
ENV PYTHONPATH=${LAMBDA_TASK_ROOT}

# Lambda handler
CMD ["app.main.handler"]
