import gettext
from functools import lru_cache
from pathlib import Path

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "ru")

LANGUAGE_NAMES = {
    "en": "English",
    "ru": "Русский",
}

AI_LANGUAGE_NAMES = {
    "en": "English",
    "ru": "Russian",
}

_DOMAIN = "bot"
_LOCALE_DIR = Path(__file__).with_name("locale")


def normalize_language(language: str | None) -> str:
    if not language:
        return DEFAULT_LANGUAGE
    language = language.lower().split("-", 1)[0]
    return language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def ai_language(language: str | None) -> str:
    return AI_LANGUAGE_NAMES[normalize_language(language)]


@lru_cache(maxsize=len(SUPPORTED_LANGUAGES))
def _translation(language: str) -> gettext.NullTranslations:
    return gettext.translation(
        _DOMAIN,
        localedir=_LOCALE_DIR,
        languages=[normalize_language(language)],
        fallback=True,
    )


def t(key: str, language: str | None = None, **kwargs) -> str:
    text = _translation(normalize_language(language)).gettext(key)
    if text == key and normalize_language(language) != DEFAULT_LANGUAGE:
        text = _translation(DEFAULT_LANGUAGE).gettext(key)
    return text.format(**kwargs) if kwargs else text
