# proxy/app/utils.py
"""
Вспомогательные утилиты для RAG-прокси.
- Хеширование строк и объектов
- Оценка количества токенов (tiktoken или приближение)
- Безопасная обрезка текста
- Форматирование метаданных
- Генерация ID запросов
- Работа с датами
"""

import hashlib
import json
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

# Попытка импорта tiktoken для точной токенизации
try:
  import tiktoken
  
  TIKTOKEN_AVAILABLE = True
except ImportError:
  TIKTOKEN_AVAILABLE = False


def compute_hash (data: Any) -> str:
  """
  Вычисляет SHA-256 хеш от любого объекта (сериализуемого в JSON).
  """
  if isinstance (data, str):  # noqa: SIM108
    content = data
  else:
    content = json.dumps (data, sort_keys = True, ensure_ascii = False)
  return hashlib.sha256 (content.encode ("utf-8")).hexdigest ()


def estimate_tokens (text: str, model: str = "gpt-3.5-turbo") -> int:
  """
  Оценивает количество токенов в тексте.
  Использует tiktoken, если доступен, иначе приближённое правило (4 символа ~ 1 токен).
  """
  if not text:
    return 0
  if TIKTOKEN_AVAILABLE:
    try:
      encoding = tiktoken.encoding_for_model (model)
      return len (encoding.encode (text))
    except Exception:
      # fallback
      pass
  # Fallback: длина / 4 (грубо)
  return len (text) // 4


def truncate_by_tokens (text: str, max_tokens: int, model: str = "gpt-3.5-turbo") -> str:
  """
  Обрезает текст до указанного количества токенов.
  """
  if estimate_tokens (text, model) <= max_tokens:
    return text
  # Грубое приближение: обрезаем символы
  max_chars = max_tokens * 4
  if len (text) <= max_chars:
    return text
  return text [:max_chars] + "..." if max_chars > 3 else "..."


def generate_request_id () -> str:
  """
  Генерирует уникальный ID для запроса.
  Формат: rag_<timestamp>_<uuid_short>
  """
  timestamp = int (time.time () * 1000)
  short_uuid = uuid.uuid4 ().hex [:8]
  return f"rag_{timestamp}_{short_uuid}"


def format_metadata (metadata: dict [str, Any]) -> str:
  """
  Форматирует метаданные для включения в контекст.
  """
  if not metadata:
    return ""
  parts = []
  for key, value in metadata.items ():
    if value is not None:
      parts.append (f"{key}: {value}")
  return " | ".join (parts)


def now_iso () -> str:
  """
  Возвращает текущее время в ISO формате.
  """
  return datetime.now (UTC).isoformat ()


def safe_json_loads (s: str, default: Any = None) -> Any:
  """
  Безопасно парсит JSON, возвращает default при ошибке.
  """
  try:
    return json.loads (s)
  except json.JSONDecodeError:
    return default


def extract_issue_keys (text: str) -> list [str]:
  """
  Извлекает Jira-like issue ключи из текста (например, PROJ-123).
  """
  pattern = r"\b[A-Z][A-Z0-9]+-\d+\b"
  return re.findall (pattern, text)


def extract_urls (text: str) -> list [str]:
  """
  Извлекает URL из текста.
  """
  pattern = r'https?://[^\s<>"\']+'
  return re.findall (pattern, text)


def mask_sensitive_data (text: str, secrets: list [str] | None = None) -> str:
  """
  Маскирует чувствительные данные (токены, пароли) в логах.
  По умолчанию маскирует строки, похожие на токены (40+ символов).
  """
  if not text:
    return text
  # Маскировка последовательностей из 40+ алфавитно-цифровых символов (предположительно токены)
  masked = re.sub (r"\b[A-Za-z0-9]{40,}\b", "[REDACTED_TOKEN]", text)
  if secrets:
    for secret in secrets:
      if secret and secret in masked:
        masked = masked.replace (secret, "[REDACTED]")
  return masked


def chunk_list (lst: list [Any], chunk_size: int) -> list [list [Any]]:
  """
  Разбивает список на чанки указанного размера.
  """
  return [lst [i: i + chunk_size] for i in range (0, len (lst), chunk_size)]


def safe_divide (a: float, b: float, default: float = 0.0) -> float:
  """
  Безопасное деление (защита от деления на ноль).
  """
  return a / b if b != 0 else default


if __name__ == "__main__":
  # Примеры использования
  print (f"Hash: {compute_hash ({'key': 'value'})}")
  print (f"Tokens estimate: {estimate_tokens ('Пример текста для оценки токенов.')}")
  print (f"Truncated: {truncate_by_tokens ('Длинный текст ' * 100, 50)}")
  print (f"Request ID: {generate_request_id ()}")
  print (f"Issue keys: {extract_issue_keys ('Связано с PROJ-123 и TEST-456')}")
  print (f"Masked: {mask_sensitive_data ('My token: abcdef1234567890abcdef1234567890abcdef12')}")
