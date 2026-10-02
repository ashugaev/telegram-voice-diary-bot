import re

from openai import AsyncOpenAI

from config import settings

client = AsyncOpenAI(api_key=settings.openai_api_key)
MAX_INPUT_BYTES = 1800
VOICE_INSTRUCTIONS = (
    "Use the language of the input. Speak naturally with a warm, pleasant, confident voice. "
    "Use expressive conversational pacing, clear diction, and subtle playful irony. "
    "Read the supplied text faithfully, including slang, without additions. "
    "Avoid shouting, theatrical delivery, and a robotic tone."
)


def split_speech(text: str) -> list[str]:
    """Bound UTF-8 bytes below the API token and character limits."""
    chunks = []
    remaining = text.strip()
    while len(remaining.encode("utf-8")) > MAX_INPUT_BYTES:
        prefix = remaining.encode("utf-8")[:MAX_INPUT_BYTES].decode("utf-8", errors="ignore")
        split_at = prefix.rfind("\n\n")
        if split_at <= 0:
            ends = list(re.finditer(r"[.!?]\s+", prefix))
            split_at = ends[-1].end() if ends else prefix.rfind(" ")
        if split_at <= 0:
            split_at = len(prefix)
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def synthesize(text: str, *, response_format: str = "opus") -> bytes:
    response = await client.audio.speech.create(
        model=settings.openai_tts_model,
        voice=settings.openai_tts_voice,
        input=text,
        instructions=VOICE_INSTRUCTIONS,
        response_format=response_format,
    )
    return response.content
