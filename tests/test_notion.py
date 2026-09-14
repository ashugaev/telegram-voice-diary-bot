import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import notion


class NotionHelpersTests(unittest.TestCase):
    def test_extract_page_title_uses_known_or_fallback_title_property(self):
        page = {
            "properties": {
                "Custom title": {
                    "type": "title",
                    "title": [{"plain_text": "Daily page"}],
                }
            }
        }

        self.assertEqual(notion.extract_page_title(page), "Daily page")

    def test_find_database_property_prefers_candidate_then_type_fallback(self):
        properties = {
            "Name": {"type": "rich_text"},
            "Actual title": {"type": "title"},
        }

        self.assertEqual(
            notion._find_database_property(properties, "title", ("Name",)),
            "Actual title",
        )

    def test_combine_tags_uses_configured_tags_property_and_deduplicates(self):
        page = {
            "properties": {
                "Labels": {
                    "multi_select": [
                        {"name": "Daily"},
                        {"name": "work"},
                    ]
                }
            }
        }

        self.assertEqual(
            notion._combine_tags(page, ["work", "health"], "Labels"),
            [{"name": "Daily"}, {"name": "work"}, {"name": "health"}],
        )

    def test_default_entry_date_uses_configured_diary_day(self):
        with patch.object(notion, "diary_today", return_value=date(2026, 6, 21)):
            self.assertEqual(notion._notion_entry_date(), "2026-06-21")
            self.assertEqual(notion._today_label(), "21 июня")


class NotionSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_database_schema_adds_missing_created_and_tags_properties(self):
        http = FakeNotionHttp({
            "Name": {"type": "title"},
        })

        result = await notion.ensure_database_schema(http)

        self.assertEqual(result.title, "Name")
        self.assertEqual(result.created, "Created")
        self.assertEqual(result.tags, "Tags")
        self.assertEqual(result.day, "Day")
        self.assertEqual(result.source, "Source")
        self.assertEqual(result.source_message_url, "Source Message URL")
        self.assertEqual(result.original_text, "Original Text")
        self.assertEqual(len(http.patch_calls), 1)
        self.assertEqual(
            http.patch_calls[0]["json"],
            {
                "properties": {
                    "Created": {"date": {}},
                    "Tags": {"multi_select": {}},
                    "Day": {"select": {}},
                    "Source": {"select": {"options": [{"name": "voice"}, {"name": "text"}]}},
                    "Telegram Chat ID": {"number": {}},
                    "Telegram Message ID": {"number": {}},
                    "Source Message URL": {"url": {}},
                    "Original Text": {"rich_text": {}},
                    "Voice File Unique ID": {"rich_text": {}},
                    "Audio Duration": {"number": {}},
                    "Audio File Size": {"number": {}},
                    "Source Text SHA256": {"rich_text": {}},
                }
            },
        )

    async def test_ensure_database_schema_adds_missing_source_options(self):
        http = FakeNotionHttp({
            "Name": {"type": "title"},
            "Created": {"type": "date"},
            "Tags": {"type": "multi_select"},
            "Day": {"type": "select"},
            "Source": {"type": "select", "select": {"options": [{"name": "voice"}]}},
            "Telegram Chat ID": {"type": "number"},
            "Telegram Message ID": {"type": "number"},
            "Source Message URL": {"type": "url"},
            "Original Text": {"type": "rich_text"},
            "Voice File Unique ID": {"type": "rich_text"},
            "Audio Duration": {"type": "number"},
            "Audio File Size": {"type": "number"},
            "Source Text SHA256": {"type": "rich_text"},
        })

        await notion.ensure_database_schema(http)

        self.assertEqual(len(http.patch_calls), 1)
        source_update = http.patch_calls[0]["json"]["properties"]["Source"]
        option_names = {option["name"] for option in source_update["select"]["options"]}
        self.assertEqual(option_names, {"voice", "text"})

    async def test_ensure_database_schema_leaves_complete_source_untouched(self):
        http = FakeNotionHttp({
            "Name": {"type": "title"},
            "Created": {"type": "date"},
            "Tags": {"type": "multi_select"},
            "Day": {"type": "select"},
            "Source": {
                "type": "select",
                "select": {"options": [{"name": "voice"}, {"name": "text"}]},
            },
            "Telegram Chat ID": {"type": "number"},
            "Telegram Message ID": {"type": "number"},
            "Source Message URL": {"type": "url"},
            "Original Text": {"type": "rich_text"},
            "Voice File Unique ID": {"type": "rich_text"},
            "Audio Duration": {"type": "number"},
            "Audio File Size": {"type": "number"},
            "Source Text SHA256": {"type": "rich_text"},
        })

        await notion.ensure_database_schema(http)

        self.assertEqual(len(http.patch_calls), 0)

    async def test_ensure_database_schema_rejects_wrong_created_type(self):
        http = FakeNotionHttp({
            "Name": {"type": "title"},
            "Created": {"type": "rich_text"},
            "Tags": {"type": "multi_select"},
            "Day": {"type": "select"},
        })

        with self.assertRaisesRegex(RuntimeError, 'property "Created" must be a date'):
            await notion.ensure_database_schema(http)

    async def test_ensure_database_schema_rejects_wrong_day_type(self):
        http = FakeNotionHttp({
            "Name": {"type": "title"},
            "Created": {"type": "date"},
            "Tags": {"type": "multi_select"},
            "Day": {"type": "rich_text"},
        })

        with self.assertRaisesRegex(RuntimeError, 'property "Day" must be a select'):
            await notion.ensure_database_schema(http)

    async def test_save_entry_creates_a_new_page_for_each_entry(self):
        calls = []

        async def fake_create_page(
            entry_title,
            entry_text,
            entry_tags,
            metadata=None,
            entry_date=None,
            allow_duplicate=False,
            original_text=None,
        ):
            calls.append((entry_title, entry_text, entry_tags, metadata, entry_date, allow_duplicate, original_text))
            return notion.SaveResult(page_id="page-1", created=True)

        original_create_page = notion.create_page
        notion.create_page = fake_create_page
        try:
            result = await notion.save_entry(
                "Title",
                "Text",
                ["work"],
                entry_date="2026-06-08",
                allow_duplicate=True,
                original_text="Raw text",
            )
        finally:
            notion.create_page = original_create_page

        self.assertEqual(result, notion.SaveResult(page_id="page-1", created=True))
        self.assertEqual(calls, [("Title", "Text", ["work"], None, "2026-06-08", True, "Raw text")])

    async def test_request_with_retry_retries_transient_notion_errors(self):
        http = FakeRetryHttp([
            FakeResponse({}, is_success=False, status_code=503, text="unavailable"),
            FakeResponse({"ok": True}),
        ])
        sleeps = []

        async def fake_sleep(delay):
            sleeps.append(delay)

        original_sleep = notion.asyncio.sleep
        notion.asyncio.sleep = fake_sleep
        try:
            resp = await notion._request_with_retry(http, "get", "https://notion.test")
        finally:
            notion.asyncio.sleep = original_sleep

        self.assertEqual(resp.json(), {"ok": True})
        self.assertEqual(http.get_calls, 2)
        self.assertEqual(sleeps, [notion.NOTION_RETRY_DELAY])

    async def test_create_page_verifies_created_page_before_returning_success(self):
        http = FakeCreatePageHttp()
        original_client = notion.httpx.AsyncClient
        notion.httpx.AsyncClient = lambda timeout: http
        try:
            result = await notion.create_page(
                "Title",
                "Text",
                ["work"],
                {
                    "source": "voice",
                    "telegram_chat_id": 123,
                    "telegram_message_id": 10,
                    "source_message_url": "tg://openmessage?user_id=123&message_id=10",
                    "voice_file_unique_id": "voice-unique",
                    "audio_duration": 42,
                    "audio_file_size": 1000,
                },
                entry_date="2026-06-08",
                original_text="Raw model text",
            )
        finally:
            notion.httpx.AsyncClient = original_client

        self.assertEqual(result, notion.SaveResult(page_id="page-1", created=True))
        self.assertEqual(http.created_pages, 1)
        self.assertEqual(http.verified_pages, ["page-1"])
        create_payload = http.post_calls[-1]["json"]
        self.assertEqual(create_payload["properties"]["Created"], {"date": {"start": "2026-06-08"}})
        self.assertEqual(create_payload["properties"]["Day"], {"select": {"name": "2026-06-08"}})
        self.assertEqual(
            create_payload["properties"]["Source Message URL"],
            {"url": "tg://openmessage?user_id=123&message_id=10"},
        )
        self.assertEqual(
            create_payload["properties"]["Voice File Unique ID"],
            {"rich_text": [{"text": {"content": "voice-unique"}}]},
        )
        self.assertEqual(
            create_payload["properties"]["Original Text"],
            {"rich_text": [{"text": {"content": "Raw model text"}}]},
        )
        self.assertEqual(create_payload["properties"]["Audio Duration"], {"number": 42})
        self.assertEqual(create_payload["properties"]["Audio File Size"], {"number": 1000})

    async def test_create_page_splits_long_entry_text_into_notion_sized_paragraphs(self):
        http = FakeCreatePageHttp()
        long_text = "x" * (notion.NOTION_TEXT_CHUNK_SIZE + 199)
        original_client = notion.httpx.AsyncClient
        notion.httpx.AsyncClient = lambda timeout: http
        try:
            result = await notion.create_page("Title", long_text, ["work"])
        finally:
            notion.httpx.AsyncClient = original_client

        self.assertEqual(result, notion.SaveResult(page_id="page-1", created=True))
        create_payload = http.post_calls[-1]["json"]
        paragraph_blocks = [
            child for child in create_payload["children"]
            if child["type"] == "paragraph"
        ]
        paragraph_chunks = [
            "".join(item["text"]["content"] for item in block["paragraph"]["rich_text"])
            for block in paragraph_blocks
        ]

        self.assertEqual(len(paragraph_blocks), 2)
        self.assertEqual("".join(paragraph_chunks), long_text)
        self.assertTrue(
            all(len(chunk) <= notion.NOTION_TEXT_CHUNK_SIZE for chunk in paragraph_chunks)
        )

    async def test_create_page_splits_blank_line_paragraphs_into_separate_blocks(self):
        http = FakeCreatePageHttp()
        text = "First thought.\n\nSecond thought.\n\nThird thought."
        original_client = notion.httpx.AsyncClient
        notion.httpx.AsyncClient = lambda timeout: http
        try:
            await notion.create_page("Title", text, ["work"])
        finally:
            notion.httpx.AsyncClient = original_client

        create_payload = http.post_calls[-1]["json"]
        paragraph_texts = [
            "".join(item["text"]["content"] for item in child["paragraph"]["rich_text"])
            for child in create_payload["children"]
            if child["type"] == "paragraph"
        ]

        self.assertEqual(
            paragraph_texts,
            ["First thought.", "Second thought.", "Third thought."],
        )

    async def test_create_page_returns_existing_page_when_metadata_matches_duplicate(self):
        http = FakeCreatePageHttp(duplicate_id="existing-page")
        original_client = notion.httpx.AsyncClient
        notion.httpx.AsyncClient = lambda timeout: http
        try:
            result = await notion.create_page("Title", "Text", ["work"], {
                "source": "text",
                "source_text_hash": "hash-1",
            })
        finally:
            notion.httpx.AsyncClient = original_client

        self.assertEqual(result, notion.SaveResult(page_id="existing-page", created=False))
        self.assertEqual(http.created_pages, 0)
        self.assertEqual(http.verified_pages, ["existing-page"])

    async def test_create_page_skips_duplicate_lookup_when_allowed(self):
        http = FakeCreatePageHttp(duplicate_id="existing-page")
        original_client = notion.httpx.AsyncClient
        notion.httpx.AsyncClient = lambda timeout: http
        try:
            result = await notion.create_page(
                "Title",
                "Text",
                ["work"],
                {
                    "source": "voice",
                    "voice_file_unique_id": "voice-unique",
                },
                allow_duplicate=True,
            )
        finally:
            notion.httpx.AsyncClient = original_client

        self.assertEqual(result, notion.SaveResult(page_id="page-1", created=True))
        self.assertEqual(http.created_pages, 1)
        self.assertEqual(len([call for call in http.post_calls if call["url"].endswith("/query")]), 0)

    async def test_get_today_pages_uses_configured_diary_day(self):
        http = FakeCreatePageHttp()
        original_client = notion.httpx.AsyncClient
        notion.httpx.AsyncClient = lambda timeout: http
        try:
            with patch.object(notion, "diary_today", return_value=date(2026, 6, 21)):
                result = await notion.get_today_pages()
        finally:
            notion.httpx.AsyncClient = original_client

        self.assertEqual(result, [])
        query_payload = http.post_calls[-1]["json"]
        self.assertEqual(
            query_payload["filter"],
            {
                "and": [
                    {"property": "Created", "date": {"on_or_after": "2026-06-21"}},
                    {"property": "Created", "date": {"on_or_before": "2026-06-21"}},
                ]
            },
        )

    async def test_get_week_pages_uses_configured_diary_day_range(self):
        http = FakeCreatePageHttp()
        original_client = notion.httpx.AsyncClient
        notion.httpx.AsyncClient = lambda timeout: http
        try:
            with patch.object(notion, "diary_today", return_value=date(2026, 6, 21)):
                result = await notion.get_week_pages()
        finally:
            notion.httpx.AsyncClient = original_client

        self.assertEqual(result, [])
        query_payload = http.post_calls[-1]["json"]
        self.assertEqual(
            query_payload["filter"],
            {
                "and": [
                    {"property": "Created", "date": {"on_or_after": "2026-06-15"}},
                    {"property": "Created", "date": {"on_or_before": "2026-06-21"}},
                ]
            },
        )

    async def test_get_diary_pages_paginates_and_filters_by_date_and_source(self):
        http = FakeQueryPagesHttp()
        original_client = notion.httpx.AsyncClient
        notion.httpx.AsyncClient = lambda timeout: http
        try:
            result = await notion.get_diary_pages(
                start_date="2026-06-17",
                end_date="2026-06-23",
                source="voice",
            )
        finally:
            notion.httpx.AsyncClient = original_client

        self.assertEqual(result, [{"id": "page-1"}, {"id": "page-2"}])
        self.assertEqual(len(http.post_calls), 2)
        self.assertEqual(
            http.post_calls[0]["json"]["filter"],
            {
                "and": [
                    {"property": "Created", "date": {"on_or_after": "2026-06-17"}},
                    {"property": "Created", "date": {"on_or_before": "2026-06-23"}},
                    {"property": "Source", "select": {"equals": "voice"}},
                ]
            },
        )
        self.assertNotIn("start_cursor", http.post_calls[0]["json"])
        self.assertEqual(http.post_calls[1]["json"]["start_cursor"], "cursor-2")

    async def test_get_page_text_joins_non_empty_text_blocks(self):
        http = FakePageTextHttp([
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "First"}]}},
            {"type": "paragraph", "paragraph": {"rich_text": []}},
            {"type": "heading_3", "heading_3": {"rich_text": [{"plain_text": "Second"}]}},
        ])
        original_client = notion.httpx.AsyncClient
        notion.httpx.AsyncClient = lambda timeout: http
        try:
            text = await notion.get_page_text("page-1")
        finally:
            notion.httpx.AsyncClient = original_client

        self.assertEqual(text, "First\n\nSecond")
        self.assertIn("/blocks/page-1/children", http.get_calls[-1])


class FakePageTextHttp:
    def __init__(self, blocks):
        self.blocks = blocks
        self.get_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers):
        self.get_calls.append(url)
        return FakeResponse({"results": self.blocks})


class FakeNotionHttp:
    def __init__(self, properties):
        self.properties = properties
        self.patch_calls = []

    async def get(self, url, headers):
        return FakeResponse({"properties": self.properties})

    async def patch(self, url, headers, json):
        self.patch_calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse({})


class FakeRetryHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.get_calls = 0

    async def get(self, url, headers):
        self.get_calls += 1
        return self.responses.pop(0)


class FakeCreatePageHttp:
    def __init__(self, duplicate_id=None):
        self.created_pages = 0
        self.verified_pages = []
        self.duplicate_id = duplicate_id
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers):
        if "/databases/" in url:
            return FakeResponse({
                "properties": {
                    "Name": {"type": "title"},
                    "Created": {"type": "date"},
                    "Tags": {"type": "multi_select"},
                    "Day": {"type": "select"},
                    "Source": {
                        "type": "select",
                        "select": {"options": [{"name": "voice"}, {"name": "text"}]},
                    },
                    "Telegram Chat ID": {"type": "number"},
                    "Telegram Message ID": {"type": "number"},
                    "Source Message URL": {"type": "url"},
                    "Original Text": {"type": "rich_text"},
                    "Voice File Unique ID": {"type": "rich_text"},
                    "Audio Duration": {"type": "number"},
                    "Audio File Size": {"type": "number"},
                    "Source Text SHA256": {"type": "rich_text"},
                }
            })
        page_id = url.rsplit("/", 1)[-1]
        self.verified_pages.append(page_id)
        return FakeResponse({"id": page_id, "archived": False})

    async def post(self, url, headers, json):
        self.post_calls.append({"url": url, "headers": headers, "json": json})
        if url.endswith("/query"):
            results = [{"id": self.duplicate_id}] if self.duplicate_id else []
            return FakeResponse({"results": results})
        self.created_pages += 1
        return FakeResponse({"id": "page-1"})


class FakeQueryPagesHttp:
    def __init__(self):
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers):
        return FakeResponse({
            "properties": {
                "Name": {"type": "title"},
                "Created": {"type": "date"},
                "Tags": {"type": "multi_select"},
                "Day": {"type": "select"},
                "Source": {
                    "type": "select",
                    "select": {"options": [{"name": "voice"}, {"name": "text"}]},
                },
                "Telegram Chat ID": {"type": "number"},
                "Telegram Message ID": {"type": "number"},
                "Source Message URL": {"type": "url"},
                "Original Text": {"type": "rich_text"},
                "Voice File Unique ID": {"type": "rich_text"},
                "Audio Duration": {"type": "number"},
                "Audio File Size": {"type": "number"},
                "Source Text SHA256": {"type": "rich_text"},
            }
        })

    async def post(self, url, headers, json):
        self.post_calls.append({"url": url, "headers": headers, "json": json})
        if len(self.post_calls) == 1:
            return FakeResponse({
                "results": [{"id": "page-1"}],
                "has_more": True,
                "next_cursor": "cursor-2",
            })
        return FakeResponse({
            "results": [{"id": "page-2"}],
            "has_more": False,
            "next_cursor": None,
        })


class FakeResponse:
    def __init__(self, payload, is_success=True, status_code=200, text=""):
        self.payload = payload
        self.is_success = is_success
        self.status_code = status_code
        self.text = text

    def json(self):
        return self.payload
