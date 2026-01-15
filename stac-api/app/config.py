"""Configuration for STAC API"""
import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Configuration
    api_title: str = "STAC COPC API"
    api_description: str = "Dynamic STAC API for Cloud Optimized Point Clouds"
    api_version: str = "1.0.0"

    # Index paths - can be local or S3
    index_path: str = os.getenv("INDEX_PATH", "./index")

    # S3 Index Configuration (for dynamic updates)
    index_bucket: str = os.getenv("INDEX_BUCKET", "stac-uixai-catalog")
    index_prefix: str = os.getenv("INDEX_PREFIX", "index")
    use_s3_index: bool = os.getenv("USE_S3_INDEX", "false").lower() == "true"
    index_cache_ttl: int = int(os.getenv("INDEX_CACHE_TTL", "60"))  # seconds

    # STAC Configuration
    stac_version: str = "1.1.0"
    default_limit: int = 10
    max_limit: int = 100

    # CORS Configuration
    cors_origins: list[str] = [
        "https://stac.uixai.org",
        "http://localhost:8080",
        "http://localhost:3000",
        "*"  # Allow all for development
    ]

    # Cache Configuration
    cache_max_age: int = 300  # 5 minutes for search results
    data_cache_max_age: int = 604800  # 7 days for data files

    # AWS Configuration (for S3 index access)
    aws_region: str = os.getenv("AWS_REGION", "ap-northeast-1")

    class Config:
        env_prefix = "STAC_"
        case_sensitive = False


settings = Settings()
