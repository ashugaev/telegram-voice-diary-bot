import os
import zoneinfo
from dotenv import load_dotenv

load_dotenv()

def _optional_env(name: str, default: str) -> str:
    return os.getenv(name) or default


def _optional_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def _required_int(name: str) -> int:
    value = _required_env(name)
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _ai_provider() -> str:
    value = (os.getenv("AI_PROVIDER") or "openai").strip().lower() or "openai"
    if value not in {"openai", "anthropic"}:
        raise RuntimeError("AI_PROVIDER must be either 'openai' or 'anthropic'")
    return value


def _anthropic_api_key(provider: str) -> str:
    value = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if provider == "anthropic" and not value:
        raise RuntimeError("ANTHROPIC_API_KEY is required when AI_PROVIDER=anthropic")
    return value


def _diary_day_start_hour() -> int:
    name = "DIARY_DAY_START_HOUR"
    value = os.getenv(name, "0").strip() or "0"
    try:
        hour = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer from 0 to 23") from exc
    if hour < 0 or hour > 23:
        raise RuntimeError(f"{name} must be an integer from 0 to 23")
    return hour


def _timezone() -> str:
    value = os.getenv("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
    try:
        zoneinfo.ZoneInfo(value)
    except zoneinfo.ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"TIMEZONE must be a valid IANA timezone: {value}") from exc
    return value


class _Settings:
    telegram_token: str = _required_env("TELEGRAM_TOKEN")
    # AI provider for chat tasks (formatter, summary, roast, profile). Whisper
    # transcription always stays on OpenAI, so OPENAI_API_KEY is required either way.
    ai_provider: str = _ai_provider()
    openai_api_key: str = _required_env("OPENAI_API_KEY")
    anthropic_api_key: str = _anthropic_api_key(ai_provider)
    openai_transcription_model: str = _optional_env("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
    openai_formatter_model: str = _optional_env("OPENAI_FORMATTER_MODEL", "gpt-6-astra")
    openai_summary_model: str = _optional_env("OPENAI_SUMMARY_MODEL", openai_formatter_model)
    openai_profile_model: str = _optional_env("OPENAI_PROFILE_MODEL", openai_summary_model)
    openai_roast_model: str = _optional_env("OPENAI_ROAST_MODEL", "gpt-6-astra")
    anthropic_formatter_model: str = _optional_env("ANTHROPIC_FORMATTER_MODEL", "claude-opus-5")
    anthropic_summary_model: str = _optional_env("ANTHROPIC_SUMMARY_MODEL", anthropic_formatter_model)
    anthropic_profile_model: str = _optional_env("ANTHROPIC_PROFILE_MODEL", anthropic_summary_model)
    anthropic_roast_model: str = _optional_env("ANTHROPIC_ROAST_MODEL", "claude-opus-5")
    # Provider-neutral models the chat services actually use, resolved from the
    # active provider so switching AI_PROVIDER needs no code changes.
    formatter_model: str = anthropic_formatter_model if ai_provider == "anthropic" else openai_formatter_model
    summary_model: str = anthropic_summary_model if ai_provider == "anthropic" else openai_summary_model
    profile_model: str = anthropic_profile_model if ai_provider == "anthropic" else openai_profile_model
    roast_model: str = anthropic_roast_model if ai_provider == "anthropic" else openai_roast_model
    ai_api_key: str = anthropic_api_key if ai_provider == "anthropic" else openai_api_key
    notion_token: str = _required_env("NOTION_TOKEN")
    notion_database_id: str = _required_env("NOTION_DATABASE_ID")
    allowed_user_id: int = _required_int("ALLOWED_USER_ID")
    timezone: str = _timezone()
    diary_day_start_hour: int = _diary_day_start_hour()
    silent_notifications: bool = _optional_bool("SILENT_NOTIFICATIONS", True)
    roast_language: str = _optional_env("ROAST_LANGUAGE", "Russian").strip()
    roast_system_prompt: str = os.getenv("ROAST_SYSTEM_PROMPT", "").strip()


settings = _Settings()
