#!/usr/bin/env python3
"""
Refresh data from BALLDONTLIE API.
Fetches: injuries, roster, recent games, Jokic season stats.
Run daily to keep data current.
"""

import hashlib
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


def extract_injury_type(description):
    """Extract injury type from description text."""
    import re
    if not description:
        return None

    desc_lower = description.lower()

    # Common patterns for injury mentions
    patterns = [
        r'for (?:a |an )?(.+?)(?: that | he | she | during | suffered)',
        r'with (?:a |an )?(.+?)(?: that | he | she |,|\.)',
        r'due to (?:a |an )?(.+?)(?: that | he | she |,|\.)',
        r'nursing (?:a |an )?(.+?)(?: that | he | she |,|\.)',
        r'(\w+ (?:strain|sprain|contusion|fracture|tear|injury|soreness|tightness|inflammation))',
        r'(hyperextended \w+ \w+)',
        r'(\w+ \w+ (?:strain|sprain|contusion|fracture|tear|injury|soreness))',
    ]

    for pattern in patterns:
        match = re.search(pattern, desc_lower)
        if match:
            injury = match.group(1).strip()
            # Clean up and title case
            injury = re.sub(r'\s+', ' ', injury)
            # Remove trailing punctuation
            injury = injury.rstrip('.,;:')
            if len(injury) > 3 and len(injury) < 50:
                return injury.title()

    # Fallback: look for body parts with common injury keywords
    body_parts = ['knee', 'ankle', 'foot', 'hamstring', 'calf', 'back', 'shoulder',
                  'wrist', 'hip', 'groin', 'quad', 'thigh', 'elbow', 'hand', 'finger', 'toe']
    for part in body_parts:
        if part in desc_lower:
            # Try to get context around the body part
            match = re.search(rf'(\w+ )?{part}( \w+)?', desc_lower)
            if match:
                return match.group(0).strip().title()

    return None


def extract_game_status(description):
    """Extract game status (probable, questionable, doubtful, out) from description."""
    import re
    if not description:
        return None

    desc_lower = description.lower()

    # NBA standard injury designations
    statuses = ['probable', 'questionable', 'doubtful', 'out', 'available', 'cleared']

    for status in statuses:
        if f'is {status}' in desc_lower or f"'{status}" in desc_lower:
            return status.title()
        # Also check for patterns like "listed as questionable"
        if f'listed as {status}' in desc_lower:
            return status.title()
        if f'upgraded to {status}' in desc_lower:
            return status.title()
        if f'downgraded to {status}' in desc_lower:
            return status.title()

    return None


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
            description = injury.get('description', '')
            injury_type = extract_injury_type(description)

            game_status = extract_game_status(description)

            injuries.append({
                'name': f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                'position': player.get('position', ''),
                'jersey': player.get('jersey_number', ''),
                'status': injury.get('status', ''),
                'return_date': injury.get('return_date', ''),
                'description': description,
                'injury_type': injury_type,
                'game_status': game_status,
            })

        print(f"  Found {len(injuries)} injured players")

        # Compute content hash to detect actual changes
        content_hash = hashlib.md5(
            json.dumps(injuries, sort_keys=True).encode()
        ).hexdigest()

        # Load existing cache to check for changes
        injuries_file = CACHE_DIR / 'injuries.json'
        content_changed_at = None
        if injuries_file.exists():
            try:
                with open(injuries_file, 'r') as f:
                    existing = json.load(f)
                old_hash = existing.get('_content_hash')
                if old_hash == content_hash:
                    # Content unchanged, preserve the old change timestamp
                    content_changed_at = existing.get('_content_changed_at')
                    print("  Content unchanged from previous fetch")
                else:
                    print("  Content has changed!")
            except Exception:
                pass

        # If no previous change time or content changed, use now
        if not content_changed_at:
            content_changed_at = datetime.now().isoformat()

        # Save injuries cache
        injuries_data = {
            'injuries': injuries,
            '_cached_at': datetime.now().isoformat(),
            '_content_changed_at': content_changed_at,
            '_content_hash': content_hash,
        }
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


def refresh_contracts():
    """Fetch contract details for all Nuggets players."""
    print(f"\n[Contracts] {datetime.now().isoformat()}")

    api_key = get_api_key()
    if not api_key:
        return None

    try:
        # First get all current season contracts for the team
        print("  Fetching team contracts...")
        response = requests.get(
            'https://api.balldontlie.io/nba/v1/contracts/teams',
            params={'team_id': NUGGETS_BALLDONTLIE_ID},
            headers={'Authorization': api_key},
            timeout=30
        )
        response.raise_for_status()
        team_data = response.json()

        # Get player IDs from team contracts
        player_ids = set()
        current_salaries = {}
        for contract in team_data.get('data', []):
            pid = contract.get('player_id')
            if pid and contract.get('season') == 2025:
                player_ids.add(pid)
                current_salaries[pid] = {
                    'salary_2025': contract.get('base_salary', 0),
                    'cap_hit': contract.get('cap_hit', 0),
                }

        print(f"  Found {len(player_ids)} players with contracts")

        # Get detailed contract info for each player
        contracts = []
        for pid in player_ids:
            try:
                resp = requests.get(
                    'https://api.balldontlie.io/nba/v1/contracts/players/aggregate',
                    params={'player_id': pid},
                    headers={'Authorization': api_key},
                    timeout=30
                )
                resp.raise_for_status()
                data = resp.json()

                # Find current and upcoming extension contracts
                current_contract = None
                extension_contract = None
                for contract in data.get('data', []):
                    status = contract.get('contract_status', '').upper()
                    if status == 'CURRENT':
                        current_contract = contract
                    elif 'EXTENSION' in status or 'UPCOMING' in status:
                        extension_contract = contract

                if current_contract:
                    player = current_contract.get('player', {})
                    salary_info = current_salaries.get(pid, {})

                    # Calculate effective end year (use extension if exists)
                    effective_end_year = current_contract.get('end_year')
                    effective_fa_year = current_contract.get('free_agent_year')
                    effective_fa_status = current_contract.get('free_agent_status', '')

                    if extension_contract:
                        effective_end_year = extension_contract.get('end_year')
                        effective_fa_year = extension_contract.get('free_agent_year')
                        effective_fa_status = extension_contract.get('free_agent_status', '')

                    # Build extension info if exists
                    extension_info = None
                    if extension_contract:
                        extension_info = {
                            'contract_type': extension_contract.get('contract_type', ''),
                            'start_year': extension_contract.get('start_year'),
                            'end_year': extension_contract.get('end_year'),
                            'contract_years': extension_contract.get('contract_years'),
                            'total_value': extension_contract.get('total_value', 0),
                            'average_salary': extension_contract.get('average_salary', 0),
                            'signed_using': extension_contract.get('signed_using', ''),
                            'contract_notes': extension_contract.get('contract_notes', []),
                        }

                    contracts.append({
                        'player_id': pid,
                        'name': f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                        'jersey': player.get('jersey_number', ''),
                        'position': player.get('position', ''),
                        'contract_type': current_contract.get('contract_type', ''),
                        'start_year': current_contract.get('start_year'),
                        'end_year': current_contract.get('end_year'),
                        'contract_years': current_contract.get('contract_years'),
                        'total_value': current_contract.get('total_value', 0),
                        'average_salary': current_contract.get('average_salary', 0),
                        'current_salary': salary_info.get('salary_2025', 0),
                        'signed_using': current_contract.get('signed_using', ''),
                        'free_agent_year': current_contract.get('free_agent_year'),
                        'free_agent_status': current_contract.get('free_agent_status', ''),
                        'contract_notes': current_contract.get('contract_notes', []),
                        # Effective values considering extensions
                        'effective_end_year': effective_end_year,
                        'effective_fa_year': effective_fa_year,
                        'effective_fa_status': effective_fa_status,
                        'has_extension': extension_contract is not None,
                        'extension': extension_info,
                    })
            except Exception as e:
                print(f"  Error fetching contract for player {pid}: {e}")
                continue

        # Sort by current salary descending
        contracts.sort(key=lambda x: x.get('current_salary', 0), reverse=True)

        print(f"  Retrieved {len(contracts)} contract details")

        contracts_data = {
            'contracts': contracts,
            '_cached_at': datetime.now().isoformat(),
        }
        with open(CACHE_DIR / 'contracts.json', 'w') as f:
            json.dump(contracts_data, f, indent=2)
        print("  Saved contracts cache")

        return contracts

    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def refresh_salary_cap_status():
    """
    Calculate team salary cap status using contract data from API.

    Cap thresholds are hardcoded for 2025-26 season as they don't change mid-season.
    Source: NBA.com official announcement, June 2025
    https://www.nba.com/news/nba-salary-cap-set-2025-26-season
    """
    print(f"\n[Salary Cap Status] {datetime.now().isoformat()}")

    api_key = get_api_key()
    if not api_key:
        return None

    # 2025-26 NBA Salary Cap Thresholds (official, set by NBA)
    # Retrieved: January 2026 from NBA.com
    CAP_THRESHOLDS = {
        'salary_cap': 154_647_000,
        'luxury_tax_line': 187_895_000,
        'first_apron': 195_945_000,
        'second_apron': 207_824_000,
        'minimum_team_salary': 139_182_000,
        'taxpayer_mle': 5_685_000,
        'non_taxpayer_mle': 14_104_000,
        'cap_thresholds_season': '2025-26',
        'cap_thresholds_source': 'NBA.com official announcement',
        'cap_thresholds_retrieved': '2026-01-03',
    }

    try:
        print("  Fetching team contracts for cap calculation...")
        response = requests.get(
            'https://api.balldontlie.io/nba/v1/contracts/teams',
            params={'team_id': NUGGETS_BALLDONTLIE_ID},
            headers={'Authorization': api_key},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        # Calculate totals from 2025 season contracts
        players = []
        total_cap_hit = 0
        total_base_salary = 0

        for contract in data.get('data', []):
            if contract.get('season') == 2025:  # 2025-26 season
                player = contract.get('player', {})
                cap_hit = contract.get('cap_hit', 0) or 0
                base_salary = contract.get('base_salary', 0) or 0

                total_cap_hit += cap_hit
                total_base_salary += base_salary

                players.append({
                    'name': f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                    'jersey': player.get('jersey_number', ''),
                    'position': player.get('position', ''),
                    'cap_hit': cap_hit,
                    'base_salary': base_salary,
                })

        # Sort by cap hit descending
        players.sort(key=lambda x: x['cap_hit'], reverse=True)

        # Calculate status vs each threshold
        cap = CAP_THRESHOLDS['salary_cap']
        tax = CAP_THRESHOLDS['luxury_tax_line']
        apron1 = CAP_THRESHOLDS['first_apron']
        apron2 = CAP_THRESHOLDS['second_apron']

        cap_status = {
            'team_total_cap_hit': total_cap_hit,
            'team_total_base_salary': total_base_salary,
            'roster_count': len(players),
            'players': players,

            # Threshold amounts
            'thresholds': CAP_THRESHOLDS,

            # Status calculations
            'over_cap': total_cap_hit > cap,
            'over_cap_amount': max(0, total_cap_hit - cap),
            'cap_space': max(0, cap - total_cap_hit),

            'over_tax': total_cap_hit > tax,
            'over_tax_amount': max(0, total_cap_hit - tax),
            'tax_space': max(0, tax - total_cap_hit),

            'over_first_apron': total_cap_hit > apron1,
            'first_apron_amount': max(0, total_cap_hit - apron1),
            'first_apron_space': max(0, apron1 - total_cap_hit),

            'over_second_apron': total_cap_hit > apron2,
            'second_apron_amount': max(0, total_cap_hit - apron2),
            'second_apron_space': max(0, apron2 - total_cap_hit),

            '_cached_at': datetime.now().isoformat(),
        }

        print(f"  Team cap hit: ${total_cap_hit:,}")
        print(f"  Over cap: {'Yes' if cap_status['over_cap'] else 'No'} (${cap_status['over_cap_amount']:,})")
        print(f"  Over tax: {'Yes' if cap_status['over_tax'] else 'No'}")
        print(f"  Over first apron: {'Yes' if cap_status['over_first_apron'] else 'No'}")

        with open(CACHE_DIR / 'salary_cap.json', 'w') as f:
            json.dump(cap_status, f, indent=2)
        print("  Saved salary cap status cache")

        return cap_status

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
    refresh_contracts()
    refresh_salary_cap_status()
    print("\n" + "=" * 50)
    print("Done!")
    print("=" * 50)
