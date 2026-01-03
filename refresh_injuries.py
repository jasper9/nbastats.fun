#!/usr/bin/env python3
"""
Refresh data from BALLDONTLIE API.
Fetches: injuries, roster, recent games, Jokic season stats.
Run daily to keep data current.
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
JOKIC_BALLDONTLIE_ID = 246


def get_api_key():
    """Get BALLDONTLIE API key from environment."""
    api_key = os.getenv('BALLDONTLIE_API_KEY')
    if not api_key or api_key == 'your_api_key_here':
        print("  WARNING: BALLDONTLIE_API_KEY not set")
        return None
    return api_key


def refresh_injuries():
    """Fetch latest injury report for Nuggets."""
    print(f"\n[Injuries] {datetime.now().isoformat()}")

    api_key = get_api_key()
    if not api_key:
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


def refresh_roster():
    """Fetch Nuggets roster."""
    print(f"\n[Roster] {datetime.now().isoformat()}")

    api_key = get_api_key()
    if not api_key:
        return None

    try:
        print("  Fetching Nuggets roster...")
        response = requests.get(
            'https://api.balldontlie.io/nba/v1/players/active',
            params={'team_ids[]': NUGGETS_BALLDONTLIE_ID, 'per_page': 25},
            headers={'Authorization': api_key},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        roster = []
        for player in data.get('data', []):
            roster.append({
                'id': player.get('id'),
                'name': f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                'position': player.get('position', ''),
                'jersey': player.get('jersey_number', ''),
                'height': player.get('height', ''),
                'weight': player.get('weight', ''),
                'college': player.get('college', ''),
                'country': player.get('country', ''),
                'draft_year': player.get('draft_year'),
                'draft_round': player.get('draft_round'),
                'draft_number': player.get('draft_number'),
            })

        # Sort by jersey number
        roster.sort(key=lambda x: int(x['jersey']) if x['jersey'] and x['jersey'].isdigit() else 999)

        print(f"  Found {len(roster)} players")

        roster_data = {
            'roster': roster,
            '_cached_at': datetime.now().isoformat(),
        }
        with open(CACHE_DIR / 'roster.json', 'w') as f:
            json.dump(roster_data, f, indent=2)
        print("  Saved roster cache")

        return roster

    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def refresh_recent_games():
    """Fetch recent Nuggets games with detailed scores."""
    print(f"\n[Recent Games] {datetime.now().isoformat()}")

    api_key = get_api_key()
    if not api_key:
        return None

    try:
        print("  Fetching recent games...")
        response = requests.get(
            'https://api.balldontlie.io/nba/v1/games',
            params={
                'team_ids[]': NUGGETS_BALLDONTLIE_ID,
                'seasons[]': 2025,
                'per_page': 15,
            },
            headers={'Authorization': api_key},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        games = []
        for game in data.get('data', []):
            if game.get('status') != 'Final':
                continue

            is_home = game.get('home_team', {}).get('id') == NUGGETS_BALLDONTLIE_ID
            nuggets_score = game.get('home_team_score') if is_home else game.get('visitor_team_score')
            opponent_score = game.get('visitor_team_score') if is_home else game.get('home_team_score')
            opponent = game.get('visitor_team') if is_home else game.get('home_team')

            games.append({
                'id': game.get('id'),
                'date': game.get('date'),
                'opponent': opponent.get('full_name', ''),
                'opponent_abbrev': opponent.get('abbreviation', ''),
                'is_home': is_home,
                'nuggets_score': nuggets_score,
                'opponent_score': opponent_score,
                'result': 'W' if nuggets_score > opponent_score else 'L',
                'home_q1': game.get('home_q1'),
                'home_q2': game.get('home_q2'),
                'home_q3': game.get('home_q3'),
                'home_q4': game.get('home_q4'),
                'home_ot1': game.get('home_ot1'),
                'visitor_q1': game.get('visitor_q1'),
                'visitor_q2': game.get('visitor_q2'),
                'visitor_q3': game.get('visitor_q3'),
                'visitor_q4': game.get('visitor_q4'),
                'visitor_ot1': game.get('visitor_ot1'),
            })

        # Sort by date descending (most recent first)
        games.sort(key=lambda x: x['date'], reverse=True)
        games = games[:10]  # Keep last 10 games

        print(f"  Found {len(games)} completed games")

        games_data = {
            'games': games,
            '_cached_at': datetime.now().isoformat(),
        }
        with open(CACHE_DIR / 'recent_games.json', 'w') as f:
            json.dump(games_data, f, indent=2)
        print("  Saved recent games cache")

        return games

    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def refresh_jokic_stats():
    """Fetch Jokic's current season stats."""
    print(f"\n[Jokic Stats] {datetime.now().isoformat()}")

    api_key = get_api_key()
    if not api_key:
        return None

    try:
        print("  Fetching Jokic season averages...")
        response = requests.get(
            'https://api.balldontlie.io/nba/v1/season_averages',
            params={'season': 2025, 'player_id': JOKIC_BALLDONTLIE_ID},
            headers={'Authorization': api_key},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        stats = data.get('data', [{}])[0] if data.get('data') else {}

        if stats:
            print(f"  Jokic: {stats.get('pts', 0):.1f} PPG, {stats.get('reb', 0):.1f} RPG, {stats.get('ast', 0):.1f} APG")

        stats_data = {
            'stats': stats,
            '_cached_at': datetime.now().isoformat(),
        }
        with open(CACHE_DIR / 'jokic_live.json', 'w') as f:
            json.dump(stats_data, f, indent=2)
        print("  Saved Jokic stats cache")

        return stats

    except Exception as e:
        print(f"  ERROR: {e}")
        return None


if __name__ == '__main__':
    print("=" * 50)
    print("BALLDONTLIE Data Refresh")
    print("=" * 50)
    refresh_injuries()
    refresh_roster()
    refresh_recent_games()
    refresh_jokic_stats()
    print("\n" + "=" * 50)
    print("Done!")
    print("=" * 50)
