#!/usr/bin/env python3
"""
Weekly refresh: Slow-changing data that rarely needs updates.
Run via cron: 0 6 * * 0 cd /path/to/nba_fun && ./venv/bin/python refresh_weekly.py

Refreshes:
- Roster
- Contracts
- Salary cap status
"""

import time
from datetime import datetime

from refresh_cache import ensure_cache_dir


def main():
    print("=" * 60)
    print(f"Weekly Cache Refresh - {datetime.now().isoformat()}")
    print("=" * 60)

    ensure_cache_dir()

    from refresh_balldontlie import (
        refresh_roster,
        refresh_contracts,
        refresh_salary_cap_status,
    )

    # Roster changes are rare (trades, signings)
    print("\nRefreshing roster...")
    refresh_roster()
    time.sleep(1)

    # Contracts don't change often
    print("\nRefreshing contracts...")
    refresh_contracts()
    time.sleep(1)

    # Salary cap status
    print("\nRefreshing salary cap status...")
    refresh_salary_cap_status()

    print("\n" + "=" * 60)
    print("Weekly refresh complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
