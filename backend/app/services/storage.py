from __future__ import annotations

import contextlib
import mimetypes
from pathlib import Path

import boto3

from app.config import get_settings


class ObjectStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._local_dir = Path(self.settings.local_artifact_dir)
        self._local_dir.mkdir(parents=True, exist_ok=True)
        self._object_store_client = None
        if all(
            [
                self.settings.object_store_endpoint_url,
                self.settings.object_store_access_key_id,
                self.settings.object_store_secret_access_key,
            ]
        ):
            self._object_store_client = boto3.client(
                "s3",
                endpoint_url=self.settings.object_store_endpoint_url,
                aws_access_key_id=self.settings.object_store_access_key_id,
                aws_secret_access_key=self.settings.object_store_secret_access_key,
                region_name=self.settings.object_store_region,
            )

    def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> str:
        if self._object_store_client:
            self._object_store_client.put_object(
                Bucket=self.settings.object_store_bucket,
                Key=key,
                Body=content,
                ContentType=content_type or mimetypes.guess_type(key)[0] or "application/octet-stream",
            )
            return key

        path = self._local_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return key

    def get_bytes(self, key: str) -> bytes:
        if self._object_store_client:
            response = self._object_store_client.get_object(Bucket=self.settings.object_store_bucket, Key=key)
            return response["Body"].read()
        return (self._local_dir / key).read_bytes()

    def close(self) -> None:
        if self._object_store_client is not None:
            with contextlib.suppress(Exception):
                self._object_store_client._endpoint.http_session.close()
            self._object_store_client = None

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

    def guess_content_type(self, key: str) -> str:
        return mimetypes.guess_type(key)[0] or "application/octet-stream"
