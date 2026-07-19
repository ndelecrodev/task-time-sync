from config.settings import settings
import boto3

class StorageClient:
    
    def __init__(self) -> None:

        self.bucket_name = settings.B2_BUCKET_NAME
        self.client = boto3.client(
                    "s3",
                    endpoint_url=settings.B2_ENDPOINT_URL,
                    aws_access_key_id=settings.B2_KEY_ID,
                    aws_secret_access_key=settings.B2_APPLICATION_KEY,
            )

    def download_file(self, destino_local: str, name_cloud: str) -> None:
        self.client.download_file(self.bucket_name, name_cloud, destino_local)
    
    def upload_file(self, origem_local: str, name_cloud: str) -> None:
        self.client.upload_file(origem_local, self.bucket_name, name_cloud)
    
    def delete_file(self, name_cloud: str) -> None:
        self.client.delete_object(Bucket=self.bucket_name, Key=name_cloud)