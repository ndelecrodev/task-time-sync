"""Reads and writes the workbook on Backblaze B2 (S3-compatible storage)."""

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from sop_pipeline.config.settings import settings
from sop_pipeline.errors.exceptions import StorageError


class StorageClient:
    """Transfers the spreadsheet between the local disk and the B2 bucket.

    B2 exposes an S3-compatible API, so the standard ``boto3`` S3 client works as
    long as it is pointed at the bucket's own endpoint.
    """

    def __init__(self) -> None:
        """Build the S3 client from the configured B2 credentials."""
        self.bucket_name = settings.B2_BUCKET_NAME
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.B2_ENDPOINT_URL,
            aws_access_key_id=settings.B2_KEY_ID,
            aws_secret_access_key=settings.B2_APPLICATION_KEY,
        )

    def download_file(self, local_destination: str, cloud_name: str) -> None:
        """Download an object from the bucket to a local path.

        Args:
            local_destination: Path the object is written to.
            cloud_name: Object key inside the bucket.

        Raises:
            StorageError: If the download fails.
        """
        try:
            self.client.download_file(self.bucket_name, cloud_name, local_destination)
        except (BotoCoreError, ClientError, OSError) as error:
            raise StorageError(f"Failed to download {cloud_name}: {error}") from error

    def upload_file(self, local_source: str, cloud_name: str) -> None:
        """Upload a local file to the bucket, overwriting the existing object.

        Args:
            local_source: Path of the file to upload.
            cloud_name: Object key inside the bucket.

        Raises:
            StorageError: If the upload fails.
        """
        try:
            self.client.upload_file(local_source, self.bucket_name, cloud_name)
        except (BotoCoreError, ClientError, OSError) as error:
            raise StorageError(f"Failed to upload {cloud_name}: {error}") from error

    def delete_file(self, cloud_name: str) -> None:
        """Delete an object from the bucket.

        Args:
            cloud_name: Object key inside the bucket.

        Raises:
            StorageError: If the deletion fails.
        """
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=cloud_name)
        except (BotoCoreError, ClientError) as error:
            raise StorageError(f"Failed to delete {cloud_name}: {error}") from error
