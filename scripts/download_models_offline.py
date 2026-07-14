#!/usr/bin/env python3
# scripts/download_models_offline.py
"""
Скрипт для загрузки всех моделей, необходимых для RAG-системы, в офлайн-режиме.
Запускается на машине с доступом в интернет. Скачанные модели копируются в защищённый контур.

Download script for all models needed by the RAG system in air-gapped environments.
Run on a machine with internet access. Copy downloaded models to the target environment.

Поддерживает / Supports:
- SentenceTransformer (embedding models)
- Cross-encoder (reranker models)
- SLM / Small Language Model (HuggingFace)
- spaCy models (NER, text processing)
- Optional: LLM GGUF files
"""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig (level = logging.INFO, format = "%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger (__name__)

HF_HOME = os.environ.get ("HF_HOME", str (Path.home () / ".cache/huggingface"))
SENTENCE_TRANSFORMERS_HOME = os.environ.get ("SENTENCE_TRANSFORMERS_HOME",
    str (Path.home () / ".cache/sentence-transformers"), )
SPACY_DATA_DIR = os.environ.get ("SPACY_DATA_DIR", str (Path.home () / ".cache/spacy"))


def download_sentence_transformer (model_name: str):
  """Downloads a sentence-transformers model."""
  from sentence_transformers import SentenceTransformer
  
  logger.info (f"Downloading sentence-transformers model: {model_name}")
  model = SentenceTransformer (model_name)
  save_path = Path (SENTENCE_TRANSFORMERS_HOME) / model_name.replace ("/", "_")
  model.save (str (save_path))
  logger.info (f"Saved to {save_path}")
  return save_path


def download_cross_encoder (model_name: str):
  """Downloads a cross-encoder model."""
  from sentence_transformers import CrossEncoder
  
  logger.info (f"Downloading cross-encoder model: {model_name}")
  _ = CrossEncoder (model_name)  # noqa: F841 — triggers download/cache
  logger.info (f"Model cached at {HF_HOME}")
  return Path (HF_HOME)


def download_spacy_model (model_name: str):
  """Downloads a spaCy model."""
  logger.info (f"Downloading spaCy model: {model_name}")
  subprocess.run ([sys.executable, "-m", "spacy", "download", model_name], check = True)
  result = subprocess.run ([sys.executable, "-m", "spacy", "info", model_name, "--path"], capture_output = True,
      text = True, )
  if result.returncode == 0:
    path = result.stdout.strip ()
    logger.info (f"spaCy model installed at {path}")
    return Path (path)
  return None


def download_huggingface_model (model_id: str, save_dir: Path):
  """Downloads any HuggingFace model using transformers."""
  from transformers import AutoModel, AutoTokenizer
  
  logger.info (f"Downloading HF model: {model_id}")
  # trust_remote_code=False: only execute code from trusted HF repos
  model = AutoModel.from_pretrained (model_id, trust_remote_code = False)
  tokenizer = AutoTokenizer.from_pretrained (model_id, trust_remote_code = False)
  save_path = save_dir / model_id.replace ("/", "_")
  model.save_pretrained (save_path)
  tokenizer.save_pretrained (save_path)
  logger.info (f"Saved to {save_path}")
  return save_path


def download_gguf_model (url: str, output_path: Path):
  """Downloads a GGUF model file."""
  import requests
  
  logger.info (f"Downloading GGUF model from {url}")
  response = requests.get (url, stream = True, timeout = 300)
  response.raise_for_status ()
  with open (output_path, "wb") as f:
    for chunk in response.iter_content (chunk_size = 8192):
      f.write (chunk)
  logger.info (f"Saved to {output_path}")
  return output_path


def main ():
  parser = argparse.ArgumentParser (description = "Download all models for offline RAG system")
  parser.add_argument ("--output-dir", type = Path, default = Path ("./offline_models"),
                       help = "Directory to copy models to")
  parser.add_argument ("--models", nargs = "+", choices = ["embedder", "reranker", "spacy", "slm", "llm_gguf"],
      default = ["embedder", "reranker", "spacy"], help = "Which model types to download", )
  parser.add_argument ("--embedder-model", type = str, default = "", help = "Embedding model name (e.g. BAAI/bge-m3)")
  parser.add_argument ("--reranker-model", type = str, default = "",
      help = "Reranker model name (e.g. cross-encoder/ms-marco-MiniLM-L-6-v2)")
  parser.add_argument ("--spacy-model", type = str, default = "", help = "spaCy model name (e.g. ru_core_news_sm)")
  parser.add_argument ("--slm-model", type = str, default = "",
      help = "Small Language Model HF ID (e.g. google/gemma-2b-it)")
  parser.add_argument ("--gguf-url", type = str, default = "", help = "URL for GGUF LLM download")
  parser.add_argument ("--gguf-output", type = str, default = "llm-model.gguf", help = "Output filename for GGUF file")
  args = parser.parse_args ()
  
  output_dir = args.output_dir
  output_dir.mkdir (parents = True, exist_ok = True)
  cache_dir = output_dir / "cache"
  cache_dir.mkdir (exist_ok = True)
  
  os.environ ["HF_HOME"] = str (cache_dir / "huggingface")
  os.environ ["SENTENCE_TRANSFORMERS_HOME"] = str (cache_dir / "sentence-transformers")
  os.environ ["TRANSFORMERS_CACHE"] = str (cache_dir / "transformers")
  
  if "embedder" in args.models:
    model = args.embedder_model or os.getenv ("EMBEDDER_MODEL", "")
    if model:
      download_sentence_transformer (model)
    else:
      logger.warning ("No embedder model specified. Set --embedder-model or EMBEDDER_MODEL env var.")
  if "reranker" in args.models:
    model = args.reranker_model or os.getenv ("RERANKER_MODEL", "")
    if model:
      download_cross_encoder (model)
    else:
      logger.warning ("No reranker model specified. Set --reranker-model or RERANKER_MODEL env var.")
  if "spacy" in args.models:
    model = args.spacy_model or os.getenv ("SPACY_MODEL", "")
    if model:
      download_spacy_model (model)
    else:
      logger.warning ("No spaCy model specified. Set --spacy-model or SPACY_MODEL env var.")
  if "slm" in args.models:
    model = args.slm_model or os.getenv ("SLM_MODEL_NAME", "")
    if model:
      download_huggingface_model (model, cache_dir / "hf_models")
    else:
      logger.warning ("No SLM model specified. Set --slm-model or SLM_MODEL_NAME env var.")
  if "llm_gguf" in args.models and args.gguf_url:
    gguf_path = output_dir / args.gguf_output
    download_gguf_model (args.gguf_url, gguf_path)
  
  logger.info (f"All models downloaded to cache directory: {cache_dir}")
  logger.info ("Copy the entire 'offline_models' folder to the target environment.")
  logger.info ("Then set environment variables: HF_HOME, SENTENCE_TRANSFORMERS_HOME to point to the cache directory.")


if __name__ == "__main__":
  main ()
