#!/usr/bin/env python3
"""
Refresh odds data from multiple providers (runs daily).
Fetches from: the-odds-api.com and BALLDONTLIE.
For full cache refresh, use refresh_cache.py instead.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path(__file__).parent / 'cache'

# Team name mappings for matching between providers
TEAM_NAME_MAP = {
    'Denver Nuggets': 'DEN',
    'Brooklyn Nets': 'BKN',
    'Philadelphia 76ers': 'PHI',
    'Boston Celtics': 'BOS',
    'Atlanta Hawks': 'ATL',
    'Milwaukee Bucks': 'MIL',
    'New Orleans Pelicans': 'NOP',
    'Dallas Mavericks': 'DAL',
    'Washington Wizards': 'WAS',
    'Charlotte Hornets': 'CHA',
    'Los Angeles Lakers': 'LAL',
    'Los Angeles Clippers': 'LAC',
    'Golden State Warriors': 'GSW',
    'Phoenix Suns': 'PHX',
    'Sacramento Kings': 'SAC',
    'Portland Trail Blazers': 'POR',
    'Utah Jazz': 'UTA',
    'Oklahoma City Thunder': 'OKC',
    'Minnesota Timberwolves': 'MIN',
    'San Antonio Spurs': 'SAS',
    'Houston Rockets': 'HOU',
    'Memphis Grizzlies': 'MEM',
    'Miami Heat': 'MIA',
    'Orlando Magic': 'ORL',
    'Indiana Pacers': 'IND',
    'Chicago Bulls': 'CHI',
    'Cleveland Cavaliers': 'CLE',
    'Detroit Pistons': 'DET',
    'Toronto Raptors': 'TOR',
    'New York Knicks': 'NYK',
}


def fetch_theoddsapi_odds():
    """Fetch odds from the-odds-api.com."""
    api_key = os.getenv('ODDS_API_KEY')
    if not api_key or api_key == 'your_api_key_here':
        print("  [the-odds-api] WARNING: ODDS_API_KEY not set")
        return {}

    try:
        print("  [the-odds-api] Fetching odds...")
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
        print(f"  [the-odds-api] API requests remaining: {remaining}")

        # Build odds lookup by teams
        odds_lookup = {}
        for game in odds_games:
            key = (game.get('home_team', ''), game.get('away_team', ''))
            if game.get('bookmakers'):
                book = game['bookmakers'][0]
                odds_data = {
                    'source': 'the-odds-api',
                    'bookmaker': book['title'],
                }
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

        print(f"  [the-odds-api] Found odds for {len(odds_lookup)} games")
        return odds_lookup

    except Exception as e:
        print(f"  [the-odds-api] ERROR: {e}")
        return {}


def fetch_balldontlie_odds(dates):
    """Fetch odds from BALLDONTLIE v2 API."""
    api_key = os.getenv('BALLDONTLIE_API_KEY')
    if not api_key:
        print("  [balldontlie] WARNING: BALLDONTLIE_API_KEY not set")
        return {}

    try:
        print(f"  [balldontlie] Fetching odds for {len(dates)} dates...")

        # Build request with multiple dates
        params = [('dates[]', d) for d in dates] + [('per_page', 100)]
        response = requests.get(
            'https://api.balldontlie.io/v2/odds',
            params=params,
            headers={'Authorization': api_key},
            timeout=30
        )
        response.raise_for_status()
        odds_data = response.json().get('data', [])

        print(f"  [balldontlie] Got {len(odds_data)} odds entries")

        # Get game details to map game_id to teams
        game_ids = set(o['game_id'] for o in odds_data)
        game_teams = {}

        for gid in game_ids:
            try:
                game_resp = requests.get(
                    f'https://api.balldontlie.io/v1/games/{gid}',
                    headers={'Authorization': api_key},
                    timeout=30
                )
                game = game_resp.json().get('data', {})
                home = game.get('home_team', {}).get('full_name', '')
                away = game.get('visitor_team', {}).get('full_name', '')
                home_abbr = game.get('home_team', {}).get('abbreviation', '')
                away_abbr = game.get('visitor_team', {}).get('abbreviation', '')
                game_teams[gid] = {
                    'home': home,
                    'away': away,
                    'home_abbr': home_abbr,
                    'away_abbr': away_abbr,
                }
            except Exception:
                pass

        # Group odds by game
        from collections import defaultdict
        game_odds = defaultdict(list)
        for o in odds_data:
            game_odds[o['game_id']].append(o)

        # Build odds lookup by teams - include ALL vendors with data
        odds_lookup = {}
        for game_id, odds_list in game_odds.items():
            teams = game_teams.get(game_id)
            if not teams:
                continue

            # Determine if Nuggets is home or away
            is_nuggets_home = teams['home_abbr'] == 'DEN'
            is_nuggets_away = teams['away_abbr'] == 'DEN'

            if not (is_nuggets_home or is_nuggets_away):
                continue

            # Collect odds from ALL vendors that have data
            all_vendors = {}
            for o in odds_list:
                if o.get('moneyline_home_odds') is None:
                    continue

                vendor = o.get('vendor', 'unknown')
                vendor_data = {
                    'bookmaker': vendor,
                    'updated_at': o.get('updated_at'),
                }

                if is_nuggets_home:
                    vendor_data['nuggets_ml'] = o.get('moneyline_home_odds')
                    vendor_data['opponent_ml'] = o.get('moneyline_away_odds')
                    if o.get('spread_home_value'):
                        vendor_data['nuggets_spread'] = float(o['spread_home_value'])
                        vendor_data['nuggets_spread_odds'] = o.get('spread_home_odds')
                else:
                    vendor_data['nuggets_ml'] = o.get('moneyline_away_odds')
                    vendor_data['opponent_ml'] = o.get('moneyline_home_odds')
                    if o.get('spread_away_value'):
                        vendor_data['nuggets_spread'] = float(o['spread_away_value'])
                        vendor_data['nuggets_spread_odds'] = o.get('spread_away_odds')

                if o.get('total_value'):
                    vendor_data['total'] = float(o['total_value'])
                    vendor_data['over_odds'] = o.get('total_over_odds')
                    vendor_data['under_odds'] = o.get('total_under_odds')

                all_vendors[vendor] = vendor_data

            if all_vendors:
                key = (teams['home'], teams['away'])
                odds_lookup[key] = {
                    'source': 'balldontlie',
                    'vendors': all_vendors,
                    # For backwards compat, pick best vendor as primary
                    **max(all_vendors.values(), key=lambda v: sum([
                        v.get('nuggets_ml') is not None,
                        v.get('nuggets_spread') is not None,
                        v.get('total') is not None,
                    ]))
                }

        print(f"  [balldontlie] Found Nuggets odds for {len(odds_lookup)} games")
        return odds_lookup

    except Exception as e:
        print(f"  [balldontlie] ERROR: {e}")
        return {}


def refresh_odds():
    """Fetch latest odds from both providers and merge into schedule cache."""
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

    # Get upcoming dates for BALLDONTLIE query
    upcoming_dates = set()
    for game in games:
        if game.get('local_date'):
            upcoming_dates.add(game['local_date'])
    for game in calendar_games:
        if game.get('local_date') and not game.get('is_past'):
            upcoming_dates.add(game['local_date'])

    # Also add next 14 days just in case
    today = datetime.now()
    for i in range(14):
        d = (today + timedelta(days=i)).strftime('%Y-%m-%d')
        upcoming_dates.add(d)

    upcoming_dates = sorted(list(upcoming_dates))[:14]  # Limit to 14 dates

    # Fetch from both providers
    theoddsapi_odds = fetch_theoddsapi_odds()
    balldontlie_odds = fetch_balldontlie_odds(upcoming_dates)

    # Merge odds into games
    theoddsapi_matched = 0
    balldontlie_matched = 0
    for game in games:
        key = (game['home_team'], game['away_team'])

        # Store odds from both providers
        game['odds_providers'] = {}

        if key in theoddsapi_odds:
            game['odds_providers']['theoddsapi'] = theoddsapi_odds[key]
            # Also set as primary for backwards compatibility
            for k, v in theoddsapi_odds[key].items():
                if k not in ['source']:
                    game[k] = v
            theoddsapi_matched += 1

        if key in balldontlie_odds:
            game['odds_providers']['balldontlie'] = balldontlie_odds[key]
            # If no theoddsapi, use balldontlie as primary
            if 'theoddsapi' not in game['odds_providers']:
                for k, v in balldontlie_odds[key].items():
                    if k not in ['source', 'updated_at']:
                        game[k] = v
            balldontlie_matched += 1

    # Also update calendar_games
    for game in calendar_games:
        key = (game['home_team'], game['away_team'])
        game['odds_providers'] = {}

        if key in theoddsapi_odds:
            game['odds_providers']['theoddsapi'] = theoddsapi_odds[key]
            for k, v in theoddsapi_odds[key].items():
                if k not in ['source']:
                    game[k] = v

        if key in balldontlie_odds:
            game['odds_providers']['balldontlie'] = balldontlie_odds[key]
            if 'theoddsapi' not in game['odds_providers']:
                for k, v in balldontlie_odds[key].items():
                    if k not in ['source', 'updated_at']:
                        game[k] = v

    games_with_odds = sum(1 for g in games if g.get('odds_providers'))
    print(f"  Updated {games_with_odds} upcoming games with odds:")
    print(f"    the-odds-api: {theoddsapi_matched} Nuggets games matched")
    print(f"    balldontlie: {balldontlie_matched} Nuggets games matched")

    # Save updated cache
    schedule_data['_odds_updated_at'] = datetime.now().isoformat()
    schedule_data['_odds_providers'] = {
        'theoddsapi': len(theoddsapi_odds),
        'balldontlie': len(balldontlie_odds),
    }
    with open(schedule_file, 'w') as f:
        json.dump(schedule_data, f, indent=2)
    print("  Saved updated schedule cache")

    return games_with_odds


if __name__ == '__main__':
    refresh_odds()
