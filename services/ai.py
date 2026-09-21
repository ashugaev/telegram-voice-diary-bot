"""AI chat provider selection.

`create_chat_client()` returns an async client that exposes the small slice of
the OpenAI SDK the chat services rely on: `client.chat.completions.create(...)`
returning an object with `.choices[0].message.content`.

- For OpenAI (`AI_PROVIDER=openai`, the default) it returns the native
  `openai.AsyncOpenAI` client, so behavior is identical to before this module
  existed.
- For Anthropic (`AI_PROVIDER=anthropic`) it returns a thin shim that translates
  the same call shape onto the Anthropic Messages API and adapts the response
  back into an OpenAI-compatible object.
- For OpenRouter (`AI_PROVIDER=openrouter`) it returns an OpenAI-compatible client
  configured with OpenRouter's base URL and zero-data-retention provider routing.

Audio transcription (Whisper) has no Anthropic or OpenRouter equivalent and always stays on
OpenAI, regardless of the selected provider.
"""

import logging
from types import SimpleNamespace

import openai

from config import settings

logger = logging.getLogger(__name__)

# Appended to the system prompt when JSON output is requested, so Anthropic
# returns a bare JSON object rather than prose or a fenced code block.
_JSON_DIRECTIVE = "Верни СТРОГО валидный JSON-объект, без markdown, пояснений и текста вокруг."


def create_chat_client():
    """Return an async chat client with a `.chat.completions.create(...)` API."""
    if settings.ai_provider == "openrouter":
        raw_client = openai.AsyncOpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            default_headers={
                "HTTP-Referer": "https://github.com/shugaev/diary-bot",
                "X-Title": "diary-bot",
            },
        )
        return _OpenRouterChatClient(raw_client)
    if settings.ai_provider == "anthropic":
        import anthropic

        return _AnthropicChatClient(anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key))
    return openai.AsyncOpenAI(api_key=settings.openai_api_key)


def _extract_text(response) -> str:
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def _strip_json_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = stripped[3:]
    if stripped[:4].lower() == "json":
        stripped = stripped[4:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()


class _AnthropicChatClient:
    """Adapts Anthropic's Messages API to the OpenAI chat-completions surface."""

    def __init__(self, client):
        self.chat = SimpleNamespace(completions=_AnthropicCompletions(client))


class _AnthropicCompletions:
    def __init__(self, client):
        self._client = client

    async def create(
        self,
        *,
        model,
        messages,
        max_completion_tokens=1024,
        response_format=None,
        **_ignored,  # e.g. reasoning_effort: handled natively by Anthropic models.
    ):
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        chat_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") != "system"
        ]
        system = "\n\n".join(part for part in system_parts if part)

        wants_json = isinstance(response_format, dict) and response_format.get("type") == "json_object"
        if wants_json:
            system = f"{system}\n\n{_JSON_DIRECTIVE}" if system else _JSON_DIRECTIVE

        kwargs = {
            "model": model,
            "max_tokens": max_completion_tokens,
            "messages": chat_messages,
        }
        if system:
            kwargs["system"] = system

        response = await self._client.messages.create(**kwargs)
        text = _extract_text(response)
        if wants_json:
            text = _strip_json_fences(text)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class _OpenRouterChatClient:
    """Adapts OpenAI client for OpenRouter with provider routing and output cleanup."""

    def __init__(self, client):
        self.chat = SimpleNamespace(completions=_OpenRouterCompletions(client))


class _OpenRouterCompletions:
    def __init__(self, client):
        self._client = client

    async def create(self, **kwargs):
        provider_cfg = {
            "data_collection": settings.openrouter_data_collection,
            "allow_fallbacks": settings.openrouter_allow_fallbacks,
        }
        if settings.openrouter_provider_order:
            order = [p.strip() for p in settings.openrouter_provider_order.split(",") if p.strip()]
            if order:
                provider_cfg["order"] = order

        extra_body = dict(kwargs.get("extra_body") or {})
        if "provider" not in extra_body:
            extra_body["provider"] = provider_cfg
        kwargs["extra_body"] = extra_body

        response = await self._client.chat.completions.create(**kwargs)
        wants_json = isinstance(kwargs.get("response_format"), dict) and kwargs["response_format"].get("type") == "json_object"
        if wants_json and getattr(response, "choices", None):
            first_choice = response.choices[0]
            msg = getattr(first_choice, "message", None)
            if msg and getattr(msg, "content", None):
                msg.content = _strip_json_fences(msg.content)
        return response
