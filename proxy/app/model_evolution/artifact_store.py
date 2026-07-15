"""Artifact store: upload/download model artifacts via MinIO/S3 with local fallback."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ArtifactRef:
  """Reference to a stored model artifact (bucket, key, version, size, URI)."""

  bucket: str
  key: str
  version_id: str | None = None
  size: int = 0
  uri: str = ""


class ArtifactStore:
  """Storage backend for model artifacts — supports MinIO/S3 and local filesystem."""

  def __init__ (
      self, endpoint: str | None = None, access_key: str | None = None, secret_key: str | None = None,
      bucket: str = "rag-artifacts", secure: bool = False, ):
    self.bucket = bucket
    self._client = None
    self._local_mode = True

    if endpoint and access_key and secret_key:
      try:
        import boto3

        self._client = boto3.client ("s3", endpoint_url = f"{'https' if secure else 'http'}://{endpoint}",
            aws_access_key_id = access_key, aws_secret_access_key = secret_key, )
        self.ensure_bucket ()
        self._local_mode = False
      except ImportError:
        pass

    if self._local_mode:
      self._local_path = Path ("data/artifacts") / bucket
      self._local_path.mkdir (parents = True, exist_ok = True)

  def ensure_bucket (self) -> None:
    """Ensure the S3 bucket exists, creating it if necessary."""
    if self._client:
      try:
        self._client.head_bucket (Bucket = self.bucket)
      except Exception:
        self._client.create_bucket (Bucket = self.bucket)

  def upload_model (self, model_name: str, version: str, local_path: str) -> ArtifactRef:
    """Upload a model directory or file to storage.

    Args:
        model_name: Name of the model.
        version: Version string.
        local_path: Local path to the model directory or file.

    Returns:
        ArtifactRef with bucket, key, and URI.
    """
    key = f"models/{model_name}/{version}/"
    if self._client:
      if os.path.isdir (local_path):
        for root, _, files in os.walk (local_path):
          for fname in files:
            fp = os.path.join (root, fname)
            rel = os.path.relpath (fp, local_path)
            self._client.upload_file (fp, self.bucket, key + rel)
      else:
        self._client.upload_file (local_path, self.bucket, key + os.path.basename (local_path))
    else:
      dest = self._local_path / model_name / version
      dest.mkdir (parents = True, exist_ok = True)
      if os.path.isdir (local_path):
        shutil.copytree (local_path, dest, dirs_exist_ok = True)
      else:
        shutil.copy2 (local_path, dest / os.path.basename (local_path))

    return ArtifactRef (bucket = self.bucket, key = key, uri = str (
      self._local_path / model_name / version) if self._local_mode else f"s3://{self.bucket}/{key}", )  # noqa: E501

  def download_model (self, model_name: str, version: str, local_dir: str) -> str:
    """Download a model version to a local directory.

    Args:
        model_name: Name of the model.
        version: Version string.
        local_dir: Local directory to download into.

    Returns:
        Path to the downloaded model directory.
    """
    dest = Path (local_dir) / model_name / version
    dest.mkdir (parents = True, exist_ok = True)
    key = f"models/{model_name}/{version}/"

    if self._client:
      paginator = self._client.get_paginator ("list_objects_v2")
      for page in paginator.paginate (Bucket = self.bucket, Prefix = key):
        for obj in page.get ("Contents", []):
          rel = obj ["Key"] [len (key):]
          if rel:
            target = dest / rel
            target.parent.mkdir (parents = True, exist_ok = True)
            self._client.download_file (self.bucket, obj ["Key"], str (target))
    else:
      src = self._local_path / model_name / version
      if src.exists ():
        shutil.copytree (src, dest, dirs_exist_ok = True)

    return str (dest)

  def list_versions (self, model_name: str) -> list [str]:
    """List all versions of a model in storage."""
    prefix = f"models/{model_name}/"
    versions = set ()
    if self._client:
      paginator = self._client.get_paginator ("list_objects_v2")
      for page in paginator.paginate (Bucket = self.bucket, Prefix = prefix, Delimiter = "/"):
        for cp in page.get ("CommonPrefixes", []):
          v = cp ["Prefix"] [len (prefix):].rstrip ("/")
          if v:
            versions.add (v)
    else:
      model_dir = self._local_path / model_name
      if model_dir.exists ():
        for d in model_dir.iterdir ():
          if d.is_dir ():
            versions.add (d.name)
    return sorted (versions)

  def delete_version (self, model_name: str, version: str) -> None:
    """Delete a specific model version from storage."""
    key = f"models/{model_name}/{version}/"
    if self._client:
      paginator = self._client.get_paginator ("list_objects_v2")
      objects = []
      for page in paginator.paginate (Bucket = self.bucket, Prefix = key):
        objects.extend ([{"Key": o ["Key"]} for o in page.get ("Contents", [])])
      if objects:
        self._client.delete_objects (Bucket = self.bucket, Delete = {"Objects": objects})
    else:
      path = self._local_path / model_name / version
      if path.exists ():
        shutil.rmtree (path)
