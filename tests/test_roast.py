import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import memory, roast


def _chat_response(text, finish_reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason=finish_reason,
            )
        ]
    )


class FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeOpenAI:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=FakeCompletions(response))


def _items(*texts):
    """Stored memory as the bot holds it: text plus the id the model addresses."""
    return [memory.MemoryItem(str(index), text) for index, text in enumerate(texts, 1)]


def _ops(*ops):
    return json.dumps({"ops": list(ops)})


class RoastServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_roast_uses_configured_model_high_reasoning_and_chain(self):
        fake = FakeOpenAI(_chat_response("Roast ready."))
        chain = [{"role": "user", "content": "got nothing done today"}]

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast.settings, "roast_language", ""), \
                patch.object(roast, "client", fake):
            result = await roast.roast(chain)

        self.assertEqual(result, roast.RoastReply("Roast ready.", None))
        kwargs = fake.chat.completions.calls[0]
        self.assertEqual(kwargs["model"], roast.settings.openai_roast_model)
        self.assertEqual(kwargs["max_completion_tokens"], roast.ROAST_MAX_COMPLETION_TOKENS)
        self.assertEqual(kwargs["reasoning_effort"], roast.ROAST_REASONING_EFFORT)
        # System persona is prepended, then the diary chain follows verbatim.
        self.assertEqual(kwargs["messages"][0]["role"], "system")
        self.assertEqual(
            kwargs["messages"][0]["content"],
            f"{roast.DEFAULT_SYSTEM_PROMPT}\n\n{roast.RULES_PROTOCOL_PROMPT}",
        )
        self.assertEqual(kwargs["messages"][1:], chain)

    async def test_roast_honors_env_system_prompt_override(self):
        fake = FakeOpenAI(_chat_response("ok"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast.settings, "roast_language", ""), \
                patch.object(roast.settings, "roast_system_prompt", "Custom persona"), \
                patch.object(roast, "client", fake):
            await roast.roast([{"role": "user", "content": "x"}])

        self.assertTrue(
            fake.chat.completions.calls[0]["messages"][0]["content"].startswith("Custom persona")
        )

    async def test_roast_appends_response_language_directive(self):
        fake = FakeOpenAI(_chat_response("ok"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast.settings, "roast_language", "English"), \
                patch.object(roast, "client", fake):
            await roast.roast([{"role": "user", "content": "x"}])

        system = fake.chat.completions.calls[0]["messages"][0]["content"]
        self.assertTrue(system.startswith(roast.DEFAULT_SYSTEM_PROMPT))
        self.assertIn("English", system)

    async def test_roast_runtime_language_overrides_env_fallback(self):
        fake = FakeOpenAI(_chat_response("ok"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast.settings, "roast_language", "Russian"), \
                patch.object(roast, "client", fake):
            await roast.roast([{"role": "user", "content": "x"}], language="en")

        system = fake.chat.completions.calls[0]["messages"][0]["content"]
        self.assertTrue(system.startswith(roast.DEFAULT_SYSTEM_PROMPTS["en"]))
        self.assertIn("English", system)
        self.assertIn("Always write the visible answer", system)

    async def test_roast_uses_russian_prompt_for_runtime_russian(self):
        fake = FakeOpenAI(_chat_response("ok"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast.settings, "roast_language", "English"), \
                patch.object(roast, "client", fake):
            await roast.roast([{"role": "user", "content": "x"}], language="ru")

        system = fake.chat.completions.calls[0]["messages"][0]["content"]
        self.assertTrue(system.startswith(roast.DEFAULT_SYSTEM_PROMPTS["ru"]))
        self.assertIn("Всегда пиши ответ", system)

    async def test_roast_trims_long_chain_to_limit_and_keeps_latest(self):
        fake = FakeOpenAI(_chat_response("ok"))
        chain = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(roast.MAX_CONVERSATION_MESSAGES + 11)
        ]

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            await roast.roast(chain)

        sent = fake.chat.completions.calls[0]["messages"]
        # System prompt plus at most MAX_CONVERSATION_MESSAGES diary turns.
        self.assertLessEqual(len(sent) - 1, roast.MAX_CONVERSATION_MESSAGES)
        self.assertEqual(sent[-1], chain[-1])

    async def test_roast_raises_when_response_is_empty(self):
        fake = FakeOpenAI(_chat_response(""))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            with self.assertRaisesRegex(RuntimeError, "empty response"):
                await roast.roast([{"role": "user", "content": "x"}])

    async def test_roast_raises_when_not_configured(self):
        with patch.object(roast.settings, "ai_api_key", ""):
            with self.assertRaisesRegex(RuntimeError, "API key is not configured"):
                await roast.roast([{"role": "user", "content": "x"}])

    async def test_roast_injects_profile_points_into_system_prompt(self):
        fake = FakeOpenAI(_chat_response("ok"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast.settings, "roast_language", ""), \
                patch.object(roast, "client", fake):
            await roast.roast(
                [{"role": "user", "content": "x"}],
                points=_items("likes hiking", "avoids conflict"),
            )

        system = fake.chat.completions.calls[0]["messages"][0]["content"]
        self.assertTrue(system.startswith(roast.DEFAULT_SYSTEM_PROMPT))
        self.assertIn("- likes hiking", system)
        self.assertIn("- avoids conflict", system)

    async def test_roast_puts_behavior_rules_last_and_above_the_persona(self):
        fake = FakeOpenAI(_chat_response("ok"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast.settings, "roast_language", ""), \
                patch.object(roast, "client", fake):
            await roast.roast(
                [{"role": "user", "content": "x"}],
                points=_items("likes hiking"),
                rules=_items("не задавай вопросов", "меньше мата"),
            )

        system = fake.chat.completions.calls[0]["messages"][0]["content"]
        self.assertIn(roast.RULES_HEADER, system)
        # Rules carry their ids: the model edits them from inside its own reply.
        self.assertIn("[1] не задавай вопросов", system)
        self.assertIn("[2] меньше мата", system)
        # Rules outrank the persona and the profile, so they come after both.
        self.assertGreater(system.index(roast.RULES_HEADER), system.index("- likes hiking"))

    async def test_roast_always_carries_the_rules_protocol(self):
        # With an empty list too — that is how the first rule ever gets recorded.
        fake = FakeOpenAI(_chat_response("ok"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            await roast.roast([{"role": "user", "content": "x"}], rules=[])

        system = fake.chat.completions.calls[0]["messages"][0]["content"]
        self.assertIn(roast.RULES_MARKER, system)
        self.assertNotIn(roast.RULES_HEADER, system)

    async def test_roast_returns_the_attached_rule_ops_without_the_block(self):
        ops = [{"action": "create", "text": "не задавай вопросов"}]
        fake = FakeOpenAI(_chat_response(f"Разъёб.\n{roast.RULES_MARKER}{_ops(*ops)}"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            reply = await roast.roast([{"role": "user", "content": "x"}])

        self.assertEqual(reply, roast.RoastReply("Разъёб.", ops))

    async def test_roast_raises_when_only_a_rules_block_comes_back(self):
        fake = FakeOpenAI(_chat_response(f"{roast.RULES_MARKER}{_ops({'action': 'create', 'text': 'x'})}"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            with self.assertRaisesRegex(RuntimeError, "empty response"):
                await roast.roast([{"role": "user", "content": "x"}])

    async def test_extract_profile_points_applies_ops_and_shows_ids_to_the_model(self):
        long_point = "x" * (roast.MAX_PROFILE_POINT_LENGTH + 20)
        raw = _ops(
            {"action": "create", "text": "  likes   hiking  "},
            {"action": "create", "text": "likes hiking"},
            {"action": "create", "text": ""},
            {"action": "create", "text": long_point},
        )
        fake = FakeOpenAI(_chat_response(raw))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            points = await roast.extract_profile_points("entry text", _items("known fact"))

        # Whitespace collapsed, repeats and empties dropped, long facts never truncated.
        self.assertEqual(memory.texts(points), ["known fact", "likes hiking", long_point])

        kwargs = fake.chat.completions.calls[0]
        self.assertEqual(kwargs["model"], roast.settings.openai_profile_model)
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        # The model sees each known fact with its id, so it can address one.
        self.assertIn('"id": "1"', kwargs["messages"][1]["content"])
        self.assertIn("known fact", kwargs["messages"][1]["content"])

    async def test_extract_profile_points_does_not_cap_count(self):
        count = roast.MAX_PROFILE_POINTS + 5
        raw = _ops(*({"action": "create", "text": f"fact {i}"} for i in range(count)))
        fake = FakeOpenAI(_chat_response(raw))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            points = await roast.extract_profile_points("entry", [])

        self.assertEqual(len(points), count)  # count is guided at the prompt level, never capped mechanically

    async def test_extract_profile_points_passes_focus_to_the_model(self):
        fake = FakeOpenAI(_chat_response(_ops({"action": "create", "text": "fact"})))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            await roast.extract_profile_points("entry", _items("known"), focus="work and health", language="en")

        kwargs = fake.chat.completions.calls[0]
        system, user = kwargs["messages"]
        self.assertTrue(system["content"].startswith(roast.PROFILE_EXTRACTION_PROMPTS["en"]))
        self.assertIn(roast.PROFILE_FOCUS_INSTRUCTIONS["en"], system["content"])
        self.assertIn("work and health", user["content"])
        self.assertIn('"focus"', user["content"])

    async def test_extract_profile_points_omits_focus_when_absent(self):
        fake = FakeOpenAI(_chat_response(_ops({"action": "create", "text": "fact"})))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            await roast.extract_profile_points("entry", _items("known"))

        kwargs = fake.chat.completions.calls[0]
        self.assertEqual(kwargs["messages"][0]["content"], roast.PROFILE_EXTRACTION_PROMPT)
        self.assertNotIn('"focus"', kwargs["messages"][1]["content"])

    async def test_extract_profile_points_uses_runtime_russian_prompt(self):
        fake = FakeOpenAI(_chat_response(_ops({"action": "create", "text": "fact"})))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            await roast.extract_profile_points("entry", _items("known"), language="ru")

        system = fake.chat.completions.calls[0]["messages"][0]["content"]
        self.assertEqual(system, roast.PROFILE_EXTRACTION_PROMPTS["ru"])

    async def test_extract_profile_points_uses_budget_and_pinned_reasoning_effort(self):
        fake = FakeOpenAI(_chat_response(_ops({"action": "create", "text": "fact"})))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            await roast.extract_profile_points("entry", [])

        kwargs = fake.chat.completions.calls[0]
        self.assertEqual(kwargs["max_completion_tokens"], roast.PROFILE_MAX_COMPLETION_TOKENS)
        self.assertEqual(kwargs["reasoning_effort"], roast.PROFILE_REASONING_EFFORT)

    def test_profile_budget_covers_the_worst_case_note(self):
        # A pass only ever reports its own operations, never the profile, so the
        # ceiling tracks one dense note rather than the accumulated list. Russian
        # facts run ~32 tokens each, and reasoning tokens share the same ceiling.
        worst_case_output = roast.MAX_PROFILE_OPS_PER_NOTE * 32
        self.assertGreater(roast.PROFILE_MAX_COMPLETION_TOKENS, worst_case_output * 2)

    async def test_extract_profile_points_keeps_existing_profile_when_truncated(self):
        # A truncated completion has no content. Accumulated knowledge must
        # survive it: return what we already knew instead of raising.
        fake = FakeOpenAI(_chat_response("", finish_reason="length"))
        existing = _items("known fact", "other fact")

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            points = await roast.extract_profile_points("entry", existing)

        self.assertEqual(points, existing)

    async def test_extract_profile_points_keeps_existing_profile_on_partial_json(self):
        # Running out of budget mid-object yields unparseable JSON, not an empty
        # string — the same no-op path has to cover it.
        fake = FakeOpenAI(_chat_response('{"ops": [{"action": "cre', finish_reason="length"))
        existing = _items("known fact")

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            points = await roast.extract_profile_points("entry", existing)

        self.assertEqual(points, existing)

    async def test_extract_profile_points_returns_empty_when_truncated_with_no_history(self):
        fake = FakeOpenAI(_chat_response("", finish_reason="length"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            self.assertEqual(await roast.extract_profile_points("entry", []), [])

    async def test_extract_profile_points_applies_a_mixed_batch_of_ops(self):
        raw = _ops(
            {"action": "create", "text": "newly durable trait"},
            {"action": "delete", "id": "3"},
            {"action": "modify", "id": "2", "text": "sharpened fact"},
        )
        fake = FakeOpenAI(_chat_response(raw))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            points = await roast.extract_profile_points(
                "entry", _items("keep me", "vague fact", "stale fact")
            )

        # Untouched facts keep their position and id, a modify rewrites in place,
        # a delete drops out, and a create lands at the end with a fresh id.
        self.assertEqual(
            points,
            [
                memory.MemoryItem("1", "keep me"),
                memory.MemoryItem("2", "sharpened fact"),
                memory.MemoryItem("4", "newly durable trait"),
            ],
        )

    async def test_extract_profile_points_keeps_profile_on_empty_ops(self):
        # The common case: nothing durable in this entry. Costs a handful of
        # output tokens no matter how large the profile has grown.
        fake = FakeOpenAI(_chat_response(_ops()))
        existing = _items(*(f"fact {i}" for i in range(80)))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            points = await roast.extract_profile_points("entry", existing)

        self.assertEqual(points, existing)

    async def test_extract_profile_points_survives_a_non_object_response(self):
        fake = FakeOpenAI(_chat_response(json.dumps(["not", "an", "ops", "block"])))
        existing = _items("known")

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            self.assertEqual(await roast.extract_profile_points("entry", existing), existing)


class RulesBlockTests(unittest.TestCase):
    def test_no_marker_means_no_change(self):
        # The steady-state answer: nothing to save, nothing to strip.
        self.assertEqual(roast.split_rules_update("  Just a roast.  "), ("Just a roast.", None))

    def test_marker_is_stripped_and_the_ops_parsed(self):
        ops = [{"action": "create", "text": "будь короче"}]
        text, parsed = roast.split_rules_update(f"Roast text.\n\n{roast.RULES_MARKER}{_ops(*ops)}")
        self.assertEqual(text, "Roast text.")
        self.assertEqual(parsed, ops)

    def test_fenced_block_is_stripped_from_both_sides(self):
        block = _ops({"action": "delete", "id": "2"})
        answer = f"Roast text.\n\n```\n{roast.RULES_MARKER}{block}\n```"
        text, parsed = roast.split_rules_update(answer)
        self.assertEqual(text, "Roast text.")
        self.assertEqual(parsed, [{"action": "delete", "id": "2"}])

    def test_unparseable_block_is_dropped_and_never_shown(self):
        text, parsed = roast.split_rules_update(f'Roast text.\n{roast.RULES_MARKER}{{"ops": [{{"act')
        self.assertEqual(text, "Roast text.")
        self.assertIsNone(parsed)

    def test_block_without_ops_is_dropped(self):
        for block in ('["not", "a", "block"]', '{"add": ["будь короче"]}', '{"ops": []}',
                      '{"ops": "not a list"}'):
            with self.subTest(block=block):
                text, parsed = roast.split_rules_update(f"Roast text.\n{roast.RULES_MARKER}{block}")
                self.assertEqual(text, "Roast text.")
                self.assertIsNone(parsed)

    def test_first_marker_cuts_the_text_and_trailing_output_is_ignored(self):
        answer = (
            f'Roast text.\n{roast.RULES_MARKER}{_ops({"action": "create", "text": "первое"})}'
            f'\n{roast.RULES_MARKER}{_ops({"action": "create", "text": "второе"})}'
        )
        text, parsed = roast.split_rules_update(answer)
        self.assertEqual(text, "Roast text.")
        self.assertEqual(parsed, [{"action": "create", "text": "первое"}])
        self.assertNotIn(roast.RULES_MARKER, text)


class ConfigTests(unittest.TestCase):
    def test_is_configured_reflects_api_key(self):
        with patch.object(roast.settings, "ai_api_key", "key"):
            self.assertTrue(roast.is_configured())
        with patch.object(roast.settings, "ai_api_key", ""):
            self.assertFalse(roast.is_configured())


if __name__ == "__main__":
    unittest.main()
