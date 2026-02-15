"""業務時間判定ユーティリティ

日本の業務時間（平日 8:00-19:00 JST、祝日除く）を判定する。
祝日データは内閣府CSVから取得し、1日1回リフレッシュする。
"""
import csv
import io
import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")
BUSINESS_START = time(8, 0)
BUSINESS_END = time(19, 0)
HOLIDAYS_CSV_URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"

# モジュールレベルキャッシュ
_holidays: set[date] = set()
_last_fetched: date | None = None

# 内閣府CSVダウンロード失敗時のフォールバック (2025-2027)
_FALLBACK_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 1), date(2025, 1, 13), date(2025, 2, 11), date(2025, 2, 23),
    date(2025, 2, 24), date(2025, 3, 20), date(2025, 4, 29), date(2025, 5, 3),
    date(2025, 5, 4), date(2025, 5, 5), date(2025, 5, 6), date(2025, 7, 21),
    date(2025, 8, 11), date(2025, 9, 15), date(2025, 9, 23), date(2025, 10, 13),
    date(2025, 11, 3), date(2025, 11, 23), date(2025, 11, 24),
    # 2026
    date(2026, 1, 1), date(2026, 1, 12), date(2026, 2, 11), date(2026, 2, 23),
    date(2026, 3, 20), date(2026, 4, 29), date(2026, 5, 3), date(2026, 5, 4),
    date(2026, 5, 5), date(2026, 5, 6), date(2026, 7, 20), date(2026, 8, 11),
    date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23), date(2026, 10, 12),
    date(2026, 11, 3), date(2026, 11, 23),
    # 2027
    date(2027, 1, 1), date(2027, 1, 11), date(2027, 2, 11), date(2027, 2, 23),
    date(2027, 3, 21), date(2027, 3, 22), date(2027, 4, 29), date(2027, 5, 3),
    date(2027, 5, 4), date(2027, 5, 5), date(2027, 7, 19), date(2027, 8, 11),
    date(2027, 9, 20), date(2027, 9, 23), date(2027, 10, 11), date(2027, 11, 3),
    date(2027, 11, 23),
}


def _fetch_holidays_from_csv() -> set[date]:
    """内閣府CSVから祝日データを取得"""
    try:
        resp = requests.get(HOLIDAYS_CSV_URL, timeout=15)
        resp.raise_for_status()
        text = resp.content.decode("shift_jis")
        reader = csv.reader(io.StringIO(text))
        holidays = set()
        for row in reader:
            if not row:
                continue
            try:
                d = datetime.strptime(row[0].strip(), "%Y/%m/%d").date()
                holidays.add(d)
            except ValueError:
                continue
        if holidays:
            logger.info(f"Fetched {len(holidays)} holidays from Cabinet Office CSV")
            return holidays
    except Exception as e:
        logger.warning(f"Failed to fetch holidays CSV: {e}")
    return set()


def _get_holidays() -> set[date]:
    """キャッシュ付きで祝日セットを返す（1日1回リフレッシュ）"""
    global _holidays, _last_fetched
    today = datetime.now(JST).date()
    if _last_fetched == today and _holidays:
        return _holidays

    fetched = _fetch_holidays_from_csv()
    if fetched:
        _holidays = fetched
    elif not _holidays:
        _holidays = _FALLBACK_HOLIDAYS.copy()
        logger.warning("Using fallback holiday list")
    _last_fetched = today
    return _holidays


def is_business_hours() -> bool:
    """現在がJST業務時間内（平日8:00-19:00、祝日除く）かどうかを返す"""
    now = datetime.now(JST)
    # 土日チェック
    if now.weekday() >= 5:
        return False
    # 祝日チェック
    if now.date() in _get_holidays():
        return False
    # 時間帯チェック
    return BUSINESS_START <= now.time() < BUSINESS_END


def next_business_day_8am() -> datetime:
    """次の営業日8:00 (JST) を返す。現在が営業日8:00前なら当日8:00を返す。"""
    now = datetime.now(JST)
    holidays = _get_holidays()
    candidate = now.date()

    # 現在が営業日で8:00前ならその日
    if candidate.weekday() < 5 and candidate not in holidays and now.time() < BUSINESS_START:
        return datetime.combine(candidate, BUSINESS_START, tzinfo=JST)

    # 翌日から探す
    candidate += timedelta(days=1)
    for _ in range(30):
        if candidate.weekday() < 5 and candidate not in holidays:
            return datetime.combine(candidate, BUSINESS_START, tzinfo=JST)
        candidate += timedelta(days=1)

    # フォールバック（ありえないが安全のため）
    return datetime.combine(candidate, BUSINESS_START, tzinfo=JST)
