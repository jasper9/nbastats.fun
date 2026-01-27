#!/usr/bin/env python3
"""
One-time script to fix game_date in existing dev_live_history files.

The BallDontLie API returns dates in UTC, so late-night Eastern games
may show the wrong date. This script:
1. Loads each game history file
2. Uses the file's modification timestamp in Eastern time as the game date
3. Adds/updates the game_date field in game_info
4. Saves the file back

Run from the project root:
    python fix_history_dates.py

Or specify a different path:
    python fix_history_dates.py /path/to/cache/dev_live_history
"""

import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

EASTERN_TZ = ZoneInfo('America/New_York')


def fix_history_dates(history_dir: str = None):
    """Fix game_date in all history files."""

    if history_dir is None:
        history_dir = os.path.join(os.path.dirname(__file__), 'cache', 'dev_live_history')

    if not os.path.exists(history_dir):
        print(f"History directory not found: {history_dir}")
        return

    fixed_count = 0
    error_count = 0
    skipped_count = 0

    for filename in os.listdir(history_dir):
        if not filename.startswith('game_') or not filename.endswith('.json'):
            continue

        filepath = os.path.join(history_dir, filename)
        game_id = filename.replace('game_', '').replace('.json', '')

        try:
            # Get file modification time and convert to Eastern
            file_mtime = os.path.getmtime(filepath)
            file_dt = datetime.fromtimestamp(file_mtime, tz=timezone.utc)
            eastern_dt = file_dt.astimezone(EASTERN_TZ)
            correct_date = eastern_dt.strftime('%Y-%m-%d')

            # Load the history file
            with open(filepath, 'r') as f:
                history = json.load(f)

            # Get current game_info
            game_info = history.get('game_info', {})
            old_date = game_info.get('game_date')

            # Check if date needs fixing
            if old_date == correct_date:
                print(f"[SKIP] {filename}: date already correct ({correct_date})")
                skipped_count += 1
                continue

            # Update game_info with correct date
            game_info['game_date'] = correct_date
            history['game_info'] = game_info

            # Save back (atomic write)
            temp_path = filepath + '.tmp'
            with open(temp_path, 'w') as f:
                json.dump(history, f)
            os.replace(temp_path, filepath)

            if old_date:
                print(f"[FIXED] {filename}: {old_date} -> {correct_date}")
            else:
                print(f"[ADDED] {filename}: game_date set to {correct_date}")
            fixed_count += 1

        except Exception as e:
            print(f"[ERROR] {filename}: {e}")
            error_count += 1

    print(f"\nSummary: {fixed_count} fixed, {skipped_count} skipped, {error_count} errors")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        history_dir = sys.argv[1]
    else:
        history_dir = None

    fix_history_dates(history_dir)
