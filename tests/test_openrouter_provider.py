import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import ai


class FakeOpenAIChatCompletions:
    def __init__(self, return_text="response text"):
        self.return_text = return_text
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.return_text))]
        )


class OpenRouterChatClientTests(unittest.TestCase):
    def test_create_chat_client_openrouter(self):
        with patch.object(ai.settings, "ai_provider", "openrouter"), \
             patch.object(ai.settings, "openrouter_api_key", "test-or-key"), \
             patch.object(ai.settings, "openrouter_base_url", "https://openrouter.ai/api/v1"):
            client = ai.create_chat_client()
            self.assertIsInstance(client, ai._OpenRouterChatClient)


class OpenRouterCompletionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_injects_provider_routing_in_extra_body(self):
        fake_completions = FakeOpenAIChatCompletions("ok")
        fake_raw = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        wrapper = ai._OpenRouterChatClient(fake_raw)

        with patch.object(ai.settings, "openrouter_data_collection", "deny"), \
             patch.object(ai.settings, "openrouter_allow_fallbacks", False), \
             patch.object(ai.settings, "openrouter_provider_order", "Anthropic"):
            response = await wrapper.chat.completions.create(
                model="anthropic/claude-opus-5",
                messages=[{"role": "user", "content": "hi"}],
                max_completion_tokens=100,
            )

        self.assertEqual(response.choices[0].message.content, "ok")
        self.assertEqual(len(fake_completions.calls), 1)
        call_kwargs = fake_completions.calls[0]
        self.assertEqual(call_kwargs["model"], "anthropic/claude-opus-5")
        self.assertEqual(call_kwargs["max_completion_tokens"], 100)
        self.assertEqual(
            call_kwargs["extra_body"]["provider"],
            {
                "data_collection": "deny",
                "allow_fallbacks": False,
                "order": ["Anthropic"],
            },
        )

    async def test_strips_json_fences_when_json_requested(self):
        fake_completions = FakeOpenAIChatCompletions('```json\n{"summary": "done"}\n```')
        fake_raw = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        wrapper = ai._OpenRouterChatClient(fake_raw)

        response = await wrapper.chat.completions.create(
            model="anthropic/claude-opus-5",
            messages=[{"role": "user", "content": "summarize"}],
            response_format={"type": "json_object"},
        )

        self.assertEqual(response.choices[0].message.content, '{"summary": "done"}')

    async def test_preserves_custom_extra_body_and_provider_override(self):
        fake_completions = FakeOpenAIChatCompletions("custom")
        fake_raw = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        wrapper = ai._OpenRouterChatClient(fake_raw)

        await wrapper.chat.completions.create(
            model="anthropic/claude-opus-5",
            messages=[{"role": "user", "content": "hi"}],
            extra_body={"custom_flag": 123, "provider": {"data_collection": "allow"}},
        )

        call_kwargs = fake_completions.calls[0]
        self.assertEqual(call_kwargs["extra_body"]["custom_flag"], 123)
        self.assertEqual(call_kwargs["extra_body"]["provider"], {"data_collection": "allow"})


if __name__ == "__main__":
    unittest.main()
