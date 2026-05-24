"""
TradeAI — Macro Event Calendar
================================
Hardcoded schedule of high-impact macro events that cause outsized volatility
in crypto markets. Used by the MACRO_FILTER gate in generate_signal() to block
(or advisory-warn) signals near event windows.

Roadmap reference:
  • Top-10 #8 / Phase A item #4 of docs/ENTERPRISE_ROADMAP.md
  • MACRO_FILTER_ENABLED=false by default — advisory mode ships first per roadmap.

Supported events:
  • FOMC rate decisions (8 per year)
  • US CPI releases (monthly, BLS)
  • US NFP / Non-Farm Payrolls (monthly, 1st Friday)

Hard invariants:
  • NO network calls. Event list built at import time from hardcoded data only.
  • Do NOT use retrospectively as a backtest training label — the schedule
    contains future-knowledge relative to each historical bar.
  • is_macro_window() is the sole public interface for the signal gate.

Window semantics:
  • Each event has a UTC announcement timestamp.
  • Returns True when:  event_time - pre_hours <= now_utc <= event_time + post_hours
  • Default pre=2h, post=1h (3-hour total window). FOMC press conferences can
    extend volatility well past 1h — callers may widen post_h via config.

Maintenance:
  • Update _CPI_RELEASES when BLS publishes the next year's schedule (~Oct).
  • Update _FOMC_DECISIONS when the Fed publishes the next year's calendar (~Nov).
  • NFP is computed algorithmically (1st Friday of each month) — update
    _build_nfp_dates() range when extending beyond 2027.
"""
from __future__ import annotations

import calendar
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

_logger = logging.getLogger("event_calendar")

# ── FOMC rate decision dates ──────────────────────────────────────────────────
# Source: federalreserve.gov/monetarypolicy/fomccalendars.htm
# Each tuple is (YYYY-MM-DD of decision day, announcement_hour_utc).
# Announcement: ~14:00 ET = 19:00 UTC (Nov-Mar EST) / 18:00 UTC (Mar-Nov EDT).
_FOMC_DECISIONS: list[tuple[str, int]] = [
    # 2025
    ("2025-01-29", 19), ("2025-03-19", 18), ("2025-05-07", 18),
    ("2025-06-18", 18), ("2025-07-30", 18), ("2025-09-17", 18),
    ("2025-10-29", 18), ("2025-12-10", 19),
    # 2026
    ("2026-01-28", 19), ("2026-03-18", 18), ("2026-04-29", 18),
    ("2026-06-17", 18), ("2026-07-29", 18), ("2026-09-16", 18),
    ("2026-10-28", 18), ("2026-12-16", 19),
    # 2027 (tentative — update when Fed publishes official 2027 calendar ~Nov 2026)
    ("2027-01-27", 19), ("2027-03-17", 18), ("2027-05-05", 18),
    ("2027-06-16", 18), ("2027-07-28", 18), ("2027-09-15", 18),
    ("2027-10-27", 18), ("2027-12-15", 19),
]

# ── US CPI release dates ──────────────────────────────────────────────────────
# Source: bls.gov/schedule/news_release/cpi.htm
# Release: 08:30 ET = 13:30 UTC year-round (BLS uses ET not EDT/EST offset).
# 2027 dates are approximate (BLS publishes official calendar ~Oct of prior year).
_CPI_RELEASES: list[str] = [
    # 2025 — BLS official calendar
    "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10",
    "2025-05-13", "2025-06-11", "2025-07-15", "2025-08-12",
    "2025-09-10", "2025-10-15", "2025-11-12", "2025-12-10",
    # 2026 — BLS official calendar
    "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-15",
    "2026-05-13", "2026-06-10", "2026-07-15", "2026-08-12",
    "2026-09-09", "2026-10-14", "2026-11-11", "2026-12-09",
    # 2027 — approximate (update when BLS publishes)
    "2027-01-13", "2027-02-10", "2027-03-10", "2027-04-14",
    "2027-05-12", "2027-06-09", "2027-07-14", "2027-08-11",
    "2027-09-08", "2027-10-13", "2027-11-10", "2027-12-08",
]
_CPI_HOUR_UTC = 13
_CPI_MINUTE_UTC = 30

# ── NFP (Non-Farm Payrolls) ───────────────────────────────────────────────────
# Released: 1st Friday of each month at 08:30 ET = 13:30 UTC.
# Computed algorithmically — accurate >99% of the time (BLS occasionally shifts
# for federal holidays; hardcode specific exceptions here if needed).
_NFP_HOUR_UTC = 13
_NFP_MINUTE_UTC = 30
_NFP_YEARS = (2025, 2026, 2027)


def _first_friday(year: int, month: int) -> Optional[datetime]:
    """1st Friday of year/month at NFP release time UTC. Returns None if impossible."""
    for week in calendar.monthcalendar(year, month):
        if week[4] != 0:  # column 4 = Friday; 0 means the month doesn't have that day
            return datetime(
                year, month, week[4],
                _NFP_HOUR_UTC, _NFP_MINUTE_UTC,
                tzinfo=timezone.utc,
            )
    return None


def _build_nfp_dates() -> list[datetime]:
    dates: list[datetime] = []
    for year in _NFP_YEARS:
        for month in range(1, 13):
            dt = _first_friday(year, month)
            if dt:
                dates.append(dt)
    return dates


# ── Build master event list (once at module load) ─────────────────────────────
def _build_events() -> list[tuple[str, datetime]]:
    events: list[tuple[str, datetime]] = []

    for date_str, hour_utc in _FOMC_DECISIONS:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=hour_utc, minute=0, second=0, tzinfo=timezone.utc
        )
        events.append((f"FOMC {date_str}", dt))

    for date_str in _CPI_RELEASES:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=_CPI_HOUR_UTC, minute=_CPI_MINUTE_UTC, second=0, tzinfo=timezone.utc
        )
        events.append((f"CPI {date_str}", dt))

    for dt in _build_nfp_dates():
        events.append((f"NFP {dt.strftime('%Y-%m-%d')}", dt))

    events.sort(key=lambda x: x[1])
    return events


_EVENTS: list[tuple[str, datetime]] = _build_events()


# ── Public API ────────────────────────────────────────────────────────────────
def is_macro_window(
    now_utc: datetime,
    pre_hours: float = 2.0,
    post_hours: float = 1.0,
) -> tuple[bool, Optional[str]]:
    """Return (in_window, event_name_or_None).

    True when now_utc is within pre_hours before or post_hours after any event.
    now_utc may be naive (assumed UTC) or timezone-aware.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    pre_delta  = timedelta(hours=pre_hours)
    post_delta = timedelta(hours=post_hours)
    for name, event_dt in _EVENTS:
        if (event_dt - pre_delta) <= now_utc <= (event_dt + post_delta):
            _logger.debug("event_calendar: %s in window of %s", now_utc.isoformat(), name)
            return True, name
    return False, None


def next_event(now_utc: datetime) -> Optional[tuple[str, datetime]]:
    """Return (name, utc_datetime) of the next scheduled event after now_utc."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    for name, event_dt in _EVENTS:
        if event_dt > now_utc:
            return name, event_dt
    return None


def event_count() -> int:
    """Total number of events in the calendar (for test assertions)."""
    return len(_EVENTS)


__all__ = ["is_macro_window", "next_event", "event_count"]
