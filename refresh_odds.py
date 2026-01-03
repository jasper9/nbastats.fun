#!/usr/bin/env python3
"""
Refresh just the odds data (runs daily).
For full cache refresh, use refresh_cache.py instead.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path(__file__).parent / 'cache'


def refresh_odds():
    """Fetch latest odds and merge into existing schedule cache."""
    print(f"[Odds Refresh] {datetime.now().isoformat()}")

    # Load existing schedule cache
    schedule_file = CACHE_DIR / 'nuggets_schedule.json'
    if not schedule_file.exists():
        print("  ERROR: No schedule cache found. Run refresh_cache.py first.")
        return None

    with open(schedule_file, 'r') as f:
        schedule_data = json.load(f)

    games = schedule_data.get('games', [])
    calendar_games = schedule_data.get('calendar_games', [])

    if not games and not calendar_games:
        print("  No games in cache to update.")
        return None

    # Fetch odds
    api_key = os.getenv('ODDS_API_KEY')
    if not api_key or api_key == 'your_api_key_here':
        print("  WARNING: ODDS_API_KEY not set")
        return None

    try:
        print("  Fetching odds from API...")
        response = requests.get(
            'https://api.the-odds-api.com/v4/sports/basketball_nba/odds',
            params={
                'apiKey': api_key,
                'regions': 'us',
                'markets': 'h2h,spreads,totals',
                'oddsFormat': 'american',
            },
            timeout=30
        )
        response.raise_for_status()
        odds_games = response.json()

        remaining = response.headers.get('x-requests-remaining', 'unknown')
        print(f"  API requests remaining: {remaining}")

        # Build odds lookup by teams
        odds_lookup = {}
        for game in odds_games:
            key = (game.get('home_team', ''), game.get('away_team', ''))
            if game.get('bookmakers'):
                book = game['bookmakers'][0]
                odds_data = {'bookmaker': book['title']}
                for market in book.get('markets', []):
                    if market['key'] == 'h2h':
                        for outcome in market['outcomes']:
                            if outcome['name'] == 'Denver Nuggets':
                                odds_data['nuggets_ml'] = outcome['price']
                            else:
                                odds_data['opponent_ml'] = outcome['price']
                    elif market['key'] == 'spreads':
                        for outcome in market['outcomes']:
                            if outcome['name'] == 'Denver Nuggets':
                                odds_data['nuggets_spread'] = outcome['point']
                                odds_data['nuggets_spread_odds'] = outcome['price']
                    elif market['key'] == 'totals':
                        for outcome in market['outcomes']:
                            if outcome['name'] == 'Over':
                                odds_data['total'] = outcome['point']
                                odds_data['over_odds'] = outcome['price']
                            elif outcome['name'] == 'Under':
                                odds_data['under_odds'] = outcome['price']
                odds_lookup[key] = odds_data

        # Merge odds into games
        odds_found = 0
        for game in games:
            key = (game['home_team'], game['away_team'])
            if key in odds_lookup:
                game.update(odds_lookup[key])
                odds_found += 1

        # Also update calendar_games
        for game in calendar_games:
            key = (game['home_team'], game['away_team'])
            if key in odds_lookup:
                game.update(odds_lookup[key])

        print(f"  Updated odds for {odds_found} upcoming games")

        # Save updated cache
        schedule_data['_odds_updated_at'] = datetime.now().isoformat()
        with open(schedule_file, 'w') as f:
            json.dump(schedule_data, f, indent=2)
        print("  Saved updated schedule cache")

        return odds_found

    except Exception as e:
        print(f"  ERROR: {e}")
        return None


if __name__ == '__main__':
    refresh_odds()
