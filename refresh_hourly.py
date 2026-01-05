#!/usr/bin/env python3
"""
Hourly refresh: Fast-changing data that needs frequent updates.
Run via cron: 0 * * * * cd /path/to/nba_fun && ./venv/bin/python refresh_hourly.py

Refreshes:
- Team standings
- Recent games
"""

import time
from datetime import datetime

from refresh_cache import ensure_cache_dir, refresh_team_standings


def main():
    print("=" * 60)
    print(f"Hourly Cache Refresh - {datetime.now().isoformat()}")
    print("=" * 60)

    ensure_cache_dir()

    # Team standings change after every game
    refresh_team_standings()
    time.sleep(1)

    # Recent games - captures new completed games
    from refresh_balldontlie import refresh_recent_games
    refresh_recent_games()

    print("\n" + "=" * 60)
    print("Hourly refresh complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
