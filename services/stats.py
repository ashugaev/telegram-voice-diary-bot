from dataclasses import dataclass
from datetime import date, datetime, timedelta
import zoneinfo

from config import settings
from services.i18n import normalize_language, t
from services.notion import AUDIO_DURATION_PROPERTY, CREATED_PROPERTY, get_diary_pages


STAT_DAYS = 7
STAT_MONTHS = 6
MONTH_NAMES_RU = {
    1: "январь",
    2: "февраль",
    3: "март",
    4: "апрель",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "август",
    9: "сентябрь",
    10: "октябрь",
    11: "ноябрь",
    12: "декабрь",
}
MONTH_GENITIVE_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}
MONTH_NAMES_EN = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}


@dataclass(frozen=True)
class AudioRecord:
    entry_date: date
    duration_seconds: int


@dataclass(frozen=True)
class AudioBucket:
    label: str
    count: int
    seconds: int


@dataclass(frozen=True)
class PeriodStats:
    entry_count: int
    voice_count: int
    audio_seconds: int
    busiest_day: AudioBucket | None = None


@dataclass(frozen=True)
class AudioStats:
    total: AudioBucket
    week: AudioBucket
    daily: list[AudioBucket]
    monthly: list[AudioBucket]


def _local_today() -> date:
    tz = zoneinfo.ZoneInfo(settings.timezone)
    return datetime.now(tz).date()


def _page_date(page: dict) -> date | None:
    prop = page.get("properties", {}).get(CREATED_PROPERTY, {})
    value = prop.get("date", {}).get("start")
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _page_audio_seconds(page: dict) -> int | None:
    value = page.get("properties", {}).get(AUDIO_DURATION_PROPERTY, {}).get("number")
    if value is None:
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _audio_records(pages: list[dict]) -> list[AudioRecord]:
    records = []
    for page in pages:
        entry_date = _page_date(page)
        seconds = _page_audio_seconds(page)
        if entry_date and seconds:
            records.append(AudioRecord(entry_date=entry_date, duration_seconds=seconds))
    return records


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _is_ru(language: str | None) -> bool:
    return _stats_language(language) == "ru"


def _stats_language(language: str | None) -> str:
    return normalize_language(language) if language else "ru"


def _date_label(value: date, language: str | None = None) -> str:
    if _is_ru(language):
        return f"{value.day} {MONTH_GENITIVE_RU[value.month]}"
    return f"{MONTH_NAMES_EN[value.month]} {value.day}"


def _month_label(value: date, language: str | None = None) -> str:
    if _is_ru(language):
        return f"{MONTH_NAMES_RU[value.month]} {value.year}"
    return f"{MONTH_NAMES_EN[value.month]} {value.year}"


def _bucket(label: str, records: list[AudioRecord]) -> AudioBucket:
    return AudioBucket(
        label=label,
        count=len(records),
        seconds=sum(record.duration_seconds for record in records),
    )


def build_audio_stats_from_pages(pages: list[dict], today: date | None = None, language: str | None = None) -> AudioStats:
    language = _stats_language(language)
    today = today or _local_today()
    records = _audio_records(pages)
    week_start = today - timedelta(days=STAT_DAYS - 1)
    month_start = _add_months(_month_start(today), -(STAT_MONTHS - 1))

    daily = []
    for offset in range(STAT_DAYS):
        current_day = week_start + timedelta(days=offset)
        daily_records = [record for record in records if record.entry_date == current_day]
        daily.append(_bucket(_date_label(current_day, language), daily_records))

    monthly = []
    for offset in range(STAT_MONTHS):
        current_month = _add_months(month_start, offset)
        next_month = _add_months(current_month, 1)
        month_records = [
            record
            for record in records
            if current_month <= record.entry_date < next_month
        ]
        monthly.append(_bucket(_month_label(current_month, language), month_records))

    week_records = [
        record
        for record in records
        if week_start <= record.entry_date <= today
    ]
    return AudioStats(
        total=_bucket(t("stats.all_time", language), records),
        week=_bucket(t("stats.last_7_days", language), week_records),
        daily=daily,
        monthly=monthly,
    )


async def build_audio_stats(today: date | None = None, language: str | None = None) -> AudioStats:
    pages = await get_diary_pages()
    return build_audio_stats_from_pages(pages, today=today, language=language)


def build_period_stats_from_pages(pages: list[dict], language: str | None = None) -> PeriodStats:
    language = _stats_language(language)
    records = _audio_records(pages)
    day_buckets = {}
    for record in records:
        day_buckets.setdefault(record.entry_date, []).append(record)

    busiest_day = None
    if day_buckets:
        buckets = [
            _bucket(_date_label(day, language), day_records)
            for day, day_records in day_buckets.items()
        ]
        busiest_day = max(buckets, key=lambda bucket: (bucket.seconds, bucket.count))

    return PeriodStats(
        entry_count=len(pages),
        voice_count=len(records),
        audio_seconds=sum(record.duration_seconds for record in records),
        busiest_day=busiest_day,
    )


def _rounded_minutes(seconds: int) -> int:
    if seconds <= 0:
        return 0
    return max(1, (seconds + 30) // 60)


def format_duration(seconds: int, language: str | None = None) -> str:
    language = _stats_language(language)
    minutes = _rounded_minutes(seconds)
    if minutes == 0:
        return t("stats.duration.zero", language)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return t("stats.duration.hours_minutes", language, hours=hours, minutes=f"{minutes:02d}")
    if hours:
        return t("stats.duration.hours", language, hours=hours)
    return t("stats.duration.minutes", language, minutes=minutes)


def _audio_label(value: int, language: str | None = None) -> str:
    language = _stats_language(language)
    return t("stats.audio_count", language, count=value)


def _bucket_line(bucket: AudioBucket, language: str | None = None) -> str:
    return f"- {bucket.label}: {format_duration(bucket.seconds, language)} · {_audio_label(bucket.count, language)}"


def format_audio_stats(stats: AudioStats, language: str | None = None) -> str:
    language = _stats_language(language)
    return "\n".join([
        t("stats.audio_header", language),
        "",
        t(
            "stats.total_line",
            language,
            duration=format_duration(stats.total.seconds, language),
            count=_audio_label(stats.total.count, language),
        ),
        t(
            "stats.week_line",
            language,
            duration=format_duration(stats.week.seconds, language),
            count=_audio_label(stats.week.count, language),
        ),
        "",
        t("stats.daily_header", language),
        *[_bucket_line(bucket, language) for bucket in stats.daily],
        "",
        t("stats.monthly_header", language),
        *[_bucket_line(bucket, language) for bucket in stats.monthly],
    ])


def format_daily_stats(stats: PeriodStats, language: str | None = None) -> str:
    language = _stats_language(language)
    return "\n".join([
        t("stats.day_header", language),
        t("stats.entries_line", language, count=stats.entry_count),
        t(
            "stats.audio_line",
            language,
            duration=format_duration(stats.audio_seconds, language),
            count=_audio_label(stats.voice_count, language),
        ),
    ])


def format_weekly_stats(stats: PeriodStats, language: str | None = None) -> str:
    language = _stats_language(language)
    lines = [
        t("stats.week_header", language),
        t("stats.entries_line", language, count=stats.entry_count),
        t(
            "stats.audio_line",
            language,
            duration=format_duration(stats.audio_seconds, language),
            count=_audio_label(stats.voice_count, language),
        ),
    ]
    if stats.busiest_day:
        lines.append(
            t(
                "stats.busiest_day",
                language,
                day=stats.busiest_day.label,
                duration=format_duration(stats.busiest_day.seconds, language),
            )
        )
    return "\n".join(lines)
