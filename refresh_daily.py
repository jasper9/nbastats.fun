#!/usr/bin/env python3
"""
Daily refresh: Stats and schedule data that changes daily.
Run via cron: 0 6 * * * cd /path/to/nba_fun && ./venv/bin/python refresh_daily.py

Refreshes:
- Jokic career stats
- All-time records
- Triple-double data
- League leaders
- Nuggets schedule and odds
- Injuries
- Jokic season stats
"""

import time
from datetime import datetime

from refresh_cache import (
    ensure_cache_dir,
    refresh_jokic_career_stats,
    refresh_alltime_records,
    refresh_triple_doubles,
    refresh_league_leaders,
    refresh_nuggets_schedule,
)


def main():
    print("=" * 60)
    print(f"Daily Cache Refresh - {datetime.now().isoformat()}")
    print("=" * 60)

    ensure_cache_dir()

    # Jokic career stats
    refresh_jokic_career_stats()
    time.sleep(1)

    # All-time records
    refresh_alltime_records()
    time.sleep(1)

    # Triple-doubles
    refresh_triple_doubles()
    time.sleep(1)

    # League leaders
    refresh_league_leaders()
    time.sleep(1)

    # Nuggets schedule (preserves balldontlie_id)
    refresh_nuggets_schedule()
    time.sleep(1)

    # Odds data
    print("\nRefreshing odds data...")
    from refresh_odds import refresh_odds
    refresh_odds()
    time.sleep(1)

    # Injuries
    print("\nRefreshing injuries...")
    from refresh_balldontlie import refresh_injuries, refresh_jokic_stats
    refresh_injuries()
    time.sleep(1)

    # Jokic season stats
    print("\nRefreshing Jokic stats...")
    refresh_jokic_stats()

    print("\n" + "=" * 60)
    print("Daily refresh complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
