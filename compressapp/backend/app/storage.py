import os
import boto3
from botocore.config import Config

# Generic S3-compatible config. Works with Backblaze B2, Cloudflare R2,
# or any S3-compatible provider — just set S3_ENDPOINT_URL accordingly.
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
S3_BUCKET = os.environ.get("S3_BUCKET", "compressapp")
S3_REGION = os.environ.get("S3_REGION", "us-west-004")  # B2 region varies by bucket

_client = None


def get_client():
    global _client
    if _client is None:
        if not (S3_ENDPOINT_URL and S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY):
            raise RuntimeError(
                "Storage credentials missing. Set S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, "
                "S3_SECRET_ACCESS_KEY, S3_BUCKET."
            )
        _client = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT_URL,
            aws_access_key_id=S3_ACCESS_KEY_ID,
            aws_secret_access_key=S3_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name=S3_REGION,
        )
    return _client


def upload_file(local_path: str, key: str) -> None:
    get_client().upload_file(local_path, S3_BUCKET, key)


def presigned_download_url(key: str, expires_in: int = 3600, filename: str | None = None) -> str:
    params = {"Bucket": S3_BUCKET, "Key": key}
    if filename:
        # Tells the browser what to name the downloaded file, without
        # renaming the actual object in storage.
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    return get_client().generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires_in,
    )


def delete_file(key: str) -> None:
    get_client().delete_object(Bucket=S3_BUCKET, Key=key)
