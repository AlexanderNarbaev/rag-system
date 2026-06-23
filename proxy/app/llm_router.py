# proxy/app/llm_router.py
"""
Маршрутизация запросов к LLM через OpenAI-совместимый API.
Поддерживает потоковую и обычную генерацию, повторные попытки при сбоях.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
from aiohttp import ClientError, ClientTimeout
from app.config import LLM_API_KEY, LLM_ENDPOINT, LLM_MODEL_NAME, MAX_RETRIES, REQUEST_TIMEOUT, RETRY_DELAY

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Исключение при вызове LLM."""

    pass


async def _send_completion_request(
    messages: list[dict[str, str]], temperature: float, max_tokens: int, stream: bool, retry: int = 0
) -> Any:
    """
    Отправляет запрос к LLM API с повторными попытками.
    Возвращает либо объект Response для потокового режима, либо JSON для не-потокового.
    """
    url = f"{LLM_ENDPOINT}/chat/completions"
    headers = {
        "Content-Type": "application/json",
    }
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    payload = {
        "model": LLM_MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }

    timeout = ClientTimeout(total=REQUEST_TIMEOUT)

    for attempt in range(retry + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"LLM API error {response.status}: {error_text}")
                        raise LLMError(f"LLM returned {response.status}: {error_text}")

                    if stream:
                        return response  # возвращаем raw response для стриминга
                    else:
                        data = await response.json()
                        # Проверяем наличие expected полей
                        if "choices" not in data or not data["choices"]:
                            raise LLMError("Invalid response format from LLM")
                        return data
        except (TimeoutError, ClientError, LLMError) as e:
            logger.warning(f"LLM request attempt {attempt + 1}/{retry + 1} failed: {e}")
            if attempt < retry:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))  # экспоненциальная задержка
            else:
                raise LLMError(f"LLM request failed after {retry + 1} attempts: {e}") from e


async def stream_completion(
    messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = 4096
) -> AsyncIterator[dict[str, Any]]:
    """
    Потоковая генерация ответа.
    Возвращает асинхронный генератор, выдающий чанки в формате OpenAI SSE.
    Каждый чанк – dict с полями: id, object, choices, etc.
    """
    response = await _send_completion_request(messages, temperature, max_tokens, stream=True, retry=MAX_RETRIES)

    # Читаем поток построчно
    async for line in response.content:
        line = line.decode("utf-8").strip()
        if not line:
            continue
        if line.startswith("data: "):
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                yield chunk
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse SSE chunk: {data_str}, error: {e}")
                continue


async def non_stream_completion(
    messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = 4096
) -> str:
    """
    Не-потоковая генерация, возвращает полный текст ответа.
    """
    data = await _send_completion_request(messages, temperature, max_tokens, stream=False, retry=MAX_RETRIES)
    try:
        content = data["choices"][0]["message"]["content"]
        return content
    except (KeyError, IndexError) as e:
        logger.error(f"Unexpected LLM response structure: {data}")
        raise LLMError(f"Failed to extract content from LLM response: {e}") from e


# Синхронные обёртки для использования в не-async контекстах (например, в LangGraph узлах)
def non_stream_completion_sync(messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = 4096) -> str:
    """Синхронная обёртка для вызова в обычных функциях."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(non_stream_completion(messages, temperature, max_tokens))
    finally:
        loop.close()


# Пример использования (для самопроверки, требует запущенного LLM сервера)
if __name__ == "__main__":

    async def test():
        messages = [{"role": "user", "content": "Привет, как дела?"}]
        # Не-потоковый тест
        resp = await non_stream_completion(messages)
        print("Non-stream response:", resp)
        # Потоковый тест
        async for chunk in stream_completion(messages):
            print("Chunk:", chunk)

    asyncio.run(test())
