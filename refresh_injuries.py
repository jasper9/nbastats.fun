#!/usr/bin/env python3
"""
Refresh injury report data from BALLDONTLIE API.
Run daily to keep injury info current.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path(__file__).parent / 'cache'
NUGGETS_BALLDONTLIE_ID = 8


def refresh_injuries():
    """Fetch latest injury report for Nuggets."""
    print(f"[Injuries Refresh] {datetime.now().isoformat()}")

    api_key = os.getenv('BALLDONTLIE_API_KEY')
    if not api_key or api_key == 'your_api_key_here':
        print("  WARNING: BALLDONTLIE_API_KEY not set")
        return None

    try:
        print("  Fetching injuries from BALLDONTLIE API...")
        response = requests.get(
            'https://api.balldontlie.io/nba/v1/player_injuries',
            params={'team_ids[]': NUGGETS_BALLDONTLIE_ID},
            headers={'Authorization': api_key},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        injuries = []
        for injury in data.get('data', []):
            player = injury.get('player', {})
            injuries.append({
                'name': f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                'position': player.get('position', ''),
                'jersey': player.get('jersey_number', ''),
                'status': injury.get('status', ''),
                'return_date': injury.get('return_date', ''),
                'description': injury.get('description', ''),
            })

        print(f"  Found {len(injuries)} injured players")

        # Save injuries cache
        injuries_data = {
            'injuries': injuries,
            '_cached_at': datetime.now().isoformat(),
        }
        injuries_file = CACHE_DIR / 'injuries.json'
        with open(injuries_file, 'w') as f:
            json.dump(injuries_data, f, indent=2)
        print("  Saved injuries cache")

        return injuries

    except Exception as e:
        print(f"  ERROR: {e}")
        return None


if __name__ == '__main__':
    refresh_injuries()
