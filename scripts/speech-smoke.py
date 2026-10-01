"""Authorized speech-service check. Test credentials isolate other services."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values


async def main() -> None:
    artifacts = Path(os.environ["SPUR_SESSION_ARTIFACTS_DIR"])
    key = os.getenv("OPENAI_API_KEY") or dotenv_values(".env").get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for the authorized speech check")
    output_dir = Path(tempfile.mkdtemp(prefix="speech.", dir=artifacts))
    os.environ.update(
        PYTHON_DOTENV_DISABLED="1",
        OPENAI_API_KEY=key,
        TELEGRAM_TOKEN="test-token",
        NOTION_TOKEN="test-notion-token",
        NOTION_DATABASE_ID="test-notion-db",
        ALLOWED_USER_ID="1",
        AI_PROVIDER="openai",
        BOT_STATE_PATH=str(output_dir / "message_state.json"),
    )
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services.speech import client, synthesize

    try:
        data = await synthesize(os.getenv(
            "SPEECH_SMOKE_TEXT",
            "Your voice mode is ready. Clear thinking, sharp words, and a little mischief.",
        ))
    finally:
        await client.close()
    if not data.startswith(b"OggS") or b"OpusHead" not in data[:512]:
        raise RuntimeError("Speech output is not an Ogg Opus voice message")
    output = output_dir / "sample.ogg"
    output.write_bytes(data)
    print(f"Speech check passed: {output} ({len(data)} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
