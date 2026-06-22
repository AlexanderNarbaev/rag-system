#!/usr/bin/env python3
# scripts/download_models_offline.py
"""
Скрипт для загрузки всех моделей, необходимых для RAG-системы, в офлайн-режиме.
Запускается на машине с доступом в интернет. Скачанные модели копируются в защищённый контур.
Поддерживает:
- SentenceTransformer (BAAI/bge-m3)
- Cross-encoder (cross-encoder/ms-marco-MiniLM-L-6-v2)
- SLM (например, gemma-2b-it в GGUF или HF)
- spaCy модели (ru_core_news_sm, en_core_web_sm)
- Опционально: LLM (gemma-4-26b-it) для vLLM
"""
import os
import sys
import argparse
from pathlib import Path
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Установка путей для кэша
HF_HOME = os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface"))
SENTENCE_TRANSFORMERS_HOME = os.environ.get("SENTENCE_TRANSFORMERS_HOME", str(Path.home() / ".cache/sentence-transformers"))
SPACY_DATA_DIR = os.environ.get("SPACY_DATA_DIR", str(Path.home() / ".cache/spacy"))

def download_sentence_transformer(model_name: str):
    """Скачивает модель sentence-transformers."""
    from sentence_transformers import SentenceTransformer
    logger.info(f"Downloading sentence-transformers model: {model_name}")
    model = SentenceTransformer(model_name)
    # Сохраняем локально (кэш уже сохранился)
    save_path = Path(SENTENCE_TRANSFORMERS_HOME) / model_name.replace("/", "_")
    model.save(str(save_path))
    logger.info(f"Saved to {save_path}")
    return save_path

def download_cross_encoder(model_name: str):
    """Скачивает кросс-энкодер."""
    from sentence_transformers import CrossEncoder
    logger.info(f"Downloading cross-encoder model: {model_name}")
    model = CrossEncoder(model_name)
    # CrossEncoder не имеет прямого метода save, но модель сохраняется в кэш.
    # Можно скопировать из кэша.
    logger.info(f"Model cached at {HF_HOME}")
    return Path(HF_HOME)

def download_spacy_model(model_name: str):
    """Скачивает spaCy модель."""
    logger.info(f"Downloading spaCy model: {model_name}")
    subprocess.run([sys.executable, "-m", "spacy", "download", model_name], check=True)
    # Определяем путь установки
    result = subprocess.run([sys.executable, "-m", "spacy", "info", model_name, "--path"], capture_output=True, text=True)
    if result.returncode == 0:
        path = result.stdout.strip()
        logger.info(f"spaCy model installed at {path}")
        return Path(path)
    return None

def download_huggingface_model(model_id: str, save_dir: Path):
    """Скачивает любую Hugging Face модель (например, LLM) с помощью transformers."""
    from transformers import AutoModel, AutoTokenizer
    logger.info(f"Downloading HF model: {model_id}")
    model = AutoModel.from_pretrained(model_id, trust_remote_code=True)
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    save_path = save_dir / model_id.replace("/", "_")
    model.save_pretrained(save_path)
    tokenizer.save_pretrained(save_path)
    logger.info(f"Saved to {save_path}")
    return save_path

def download_gguf_model(url: str, output_path: Path):
    """Скачивает GGUF файл модели (например, gemma-4-26b-it-GGUF)."""
    import requests
    logger.info(f"Downloading GGUF model from {url}")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"Saved to {output_path}")
    return output_path

def main():
    parser = argparse.ArgumentParser(description="Download all models for offline RAG system")
    parser.add_argument("--output-dir", type=Path, default=Path("./offline_models"), help="Directory to copy models to (optional, will also keep cache)")
    parser.add_argument("--models", nargs="+", choices=["embedder", "reranker", "spacy_ru", "spacy_en", "slm", "llm_gguf"], default=["embedder", "reranker", "spacy_ru", "spacy_en"], help="Which models to download")
    parser.add_argument("--gguf-url", type=str, default="", help="URL for GGUF LLM (e.g., gemma-4-26b-it)")
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / "cache"
    cache_dir.mkdir(exist_ok=True)

    # Настройка путей кэша, чтобы сохранить всё в output_dir
    os.environ["HF_HOME"] = str(cache_dir / "huggingface")
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(cache_dir / "sentence-transformers")
    os.environ["TRANSFORMERS_CACHE"] = str(cache_dir / "transformers")

    if "embedder" in args.models:
        download_sentence_transformer("BAAI/bge-m3")
    if "reranker" in args.models:
        download_cross_encoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    if "spacy_ru" in args.models:
        download_spacy_model("ru_core_news_sm")
    if "spacy_en" in args.models:
        download_spacy_model("en_core_web_sm")
    if "slm" in args.models:
        # Пример: скачиваем gemma-2b-it (HF)
        download_huggingface_model("google/gemma-2b-it", cache_dir / "hf_models")
    if "llm_gguf" in args.models and args.gguf_url:
        gguf_path = output_dir / "gemma-4-26b-it.Q4_K_M.gguf"
        download_gguf_model(args.gguf_url, gguf_path)

    logger.info(f"All models downloaded to cache directory: {cache_dir}")
    logger.info("Copy the entire 'offline_models' folder to the target environment.")
    logger.info("Then set environment variables: HF_HOME, SENTENCE_TRANSFORMERS_HOME to point to the cache directory.")

if __name__ == "__main__":
    main()