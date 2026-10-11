import json
from collections.abc import Iterator

import httpx

from app.core.config import settings


def stream_chat(messages: list[dict[str, str]]) -> Iterator[str]:
    """Stream completion text deltas from the OpenAI-compatible chat endpoint."""
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
        "stream": True,
    }
    timeout = httpx.Timeout(10, read=300)
    with httpx.Client(base_url=settings.llm_base_url, timeout=timeout) as client:
        with client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                choices = json.loads(data).get("choices") or []
                delta = choices[0].get("delta", {}).get("content") if choices else None
                if delta:
                    yield delta
