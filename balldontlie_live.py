#!/usr/bin/env python3
"""
BallDontLie API module for live game data.
Provides play-by-play, player stats, and game info for the dev-live feed.
"""

import os
import requests
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

# Import LLM commentary for quarter/game summaries
try:
    from llm_commentary import generate_llm_commentary
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False

# API Configuration
API_BASE = 'https://api.balldontlie.io/v1'

# Caching for API responses
_cache = {}  # key -> {'data': ..., 'time': datetime}
GAMES_CACHE_TTL = 30  # 30 seconds for games list
GAME_INFO_CACHE_TTL = 15  # 15 seconds for individual game info
PLAYS_CACHE_TTL = 5  # 5 seconds for play-by-play (needs to be fresh)


def _get_cached(key: str, ttl: int):
    """Get cached value if still valid."""
    if key in _cache:
        age = (datetime.now() - _cache[key]['time']).total_seconds()
        if age < ttl:
            return _cache[key]['data']
    return None


def _set_cache(key: str, data):
    """Store value in cache."""
    _cache[key] = {'data': data, 'time': datetime.now()}


def get_api_key():
    """Get BallDontLie API key from environment."""
    return os.getenv('BALLDONTLIE_API_KEY')


def _make_request(endpoint: str, params: dict = None) -> dict:
    """Make authenticated request to BallDontLie API."""
    api_key = get_api_key()
    if not api_key:
        raise ValueError("BALLDONTLIE_API_KEY not set")

    headers = {'Authorization': api_key}
    url = f"{API_BASE}/{endpoint}"

    response = requests.get(url, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def get_todays_games(date: str = None) -> list:
    """
    Get all games for a specific date. Results are cached for 30 seconds.

    Args:
        date: Date in YYYY-MM-DD format, defaults to today

    Returns:
        List of game objects
    """
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')

    cache_key = f"games_{date}"
    cached = _get_cached(cache_key, GAMES_CACHE_TTL)
    if cached is not None:
        return cached

    data = _make_request('games', {'dates[]': date})
    result = data.get('data', [])
    _set_cache(cache_key, result)
    return result


def get_play_by_play(game_id: int) -> list:
    """
    Get play-by-play data for a game.

    Args:
        game_id: BallDontLie game ID

    Returns:
        List of play objects sorted by order
    """
    data = _make_request('plays', {'game_id': game_id})
    plays = data.get('data', [])
    # Sort by order to ensure chronological
    return sorted(plays, key=lambda p: p.get('order', 0))


def get_player_stats(game_id: int) -> list:
    """
    Get player stats for a game (includes MIN and plus_minus).

    Args:
        game_id: BallDontLie game ID

    Returns:
        List of player stat objects
    """
    data = _make_request('stats', {'game_ids[]': game_id})
    return data.get('data', [])


def get_game_info(game_id: int) -> dict:
    """
    Get game info including teams, scores, status. Results are cached for 15 seconds.

    Args:
        game_id: BallDontLie game ID

    Returns:
        Game info dict
    """
    cache_key = f"game_{game_id}"
    cached = _get_cached(cache_key, GAME_INFO_CACHE_TTL)
    if cached is not None:
        return cached

    data = _make_request(f'games/{game_id}')
    result = data.get('data', {})
    _set_cache(cache_key, result)
    return result


def parse_game_status(game: dict) -> tuple:
    """
    Parse game status into period, clock, and status string.

    Args:
        game: Game object from API

    Returns:
        Tuple of (period: int, clock: str, status: str, is_live: bool)
    """
    status = game.get('status', '')
    period = game.get('period', 0)
    time_str = game.get('time', '')

    # Check various status indicators
    if status == 'Final' or time_str == 'Final':
        return (period, '', 'Final', False)

    # Check if game hasn't started (status is a time like "7:00 PM")
    if 'PM' in status or 'AM' in status:
        return (0, '', status, False)

    # In progress
    if period > 0:
        # time might be like "Q4 5:32" or just "5:32"
        clock = time_str if time_str else ''
        if 'Q' in clock:
            clock = clock.split(' ')[-1]
        return (period, clock, f'Q{period}' if period <= 4 else f'OT{period-4}', True)

    return (0, '', status, False)


def format_player_stats_for_frontend(stats: list, home_team_id: int) -> dict:
    """
    Format player stats for frontend consumption.
    Separates by home/away and includes MIN and plus_minus.

    Args:
        stats: List of player stat objects from API
        home_team_id: ID of home team for grouping

    Returns:
        Dict with 'home' and 'away' lists of player stats
    """
    result = {'home': [], 'away': []}

    for s in stats:
        team = s.get('team', {})
        player = s.get('player', {})

        # Build player stat dict matching frontend expectations
        player_stat = {
            'name': f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
            'team': team.get('abbreviation', ''),
            'min': s.get('min', '-'),
            'pts': s.get('pts', 0),
            'reb': s.get('reb', 0),
            'ast': s.get('ast', 0),
            'stl': s.get('stl', 0),
            'blk': s.get('blk', 0),
            'fgm': s.get('fgm', 0),
            'fga': s.get('fga', 0),
            'fg3m': s.get('fg3m', 0),
            'fg3a': s.get('fg3a', 0),
            'ftm': s.get('ftm', 0),
            'fta': s.get('fta', 0),
            'oreb': s.get('oreb', 0),
            'dreb': s.get('dreb', 0),
            'tov': s.get('turnover', 0),
            'pf': s.get('pf', 0),
            'plus_minus': s.get('plus_minus', 0),
        }

        # Group by team
        if team.get('id') == home_team_id:
            result['home'].append(player_stat)
        else:
            result['away'].append(player_stat)

    # Sort by points descending
    result['home'].sort(key=lambda x: x['pts'], reverse=True)
    result['away'].sort(key=lambda x: x['pts'], reverse=True)

    return result


def convert_play_to_action(play: dict) -> dict:
    """
    Convert BallDontLie play to action format compatible with existing message generation.

    Args:
        play: Play object from BallDontLie API

    Returns:
        Action dict in format expected by generate_chat_message
    """
    team = play.get('team', {})

    # Map BallDontLie play types to action types
    play_type = play.get('type', '').lower()

    # Determine action type category
    action_type = 'unknown'
    if 'shot' in play_type or 'dunk' in play_type or 'layup' in play_type:
        action_type = '2pt' if play.get('score_value') == 2 else '3pt'
    elif 'free throw' in play_type:
        action_type = 'freethrow'
    elif 'rebound' in play_type:
        action_type = 'rebound'
    elif 'turnover' in play_type:
        action_type = 'turnover'
    elif 'steal' in play_type:
        action_type = 'steal'
    elif 'block' in play_type:
        action_type = 'block'
    elif 'foul' in play_type:
        action_type = 'foul'
    elif 'timeout' in play_type:
        action_type = 'timeout'
    elif 'jumpball' in play_type:
        action_type = 'jumpball'
    elif 'period' in play_type:
        action_type = 'period'

    return {
        'actionNumber': play.get('order', 0),
        'period': play.get('period', 1),
        'clock': play.get('clock', ''),
        'scoreHome': play.get('home_score', 0),
        'scoreAway': play.get('away_score', 0),
        'teamTricode': team.get('abbreviation', ''),
        'actionType': action_type,
        'subType': play_type,
        'description': play.get('text', ''),
        'personId': 0,  # Not provided by BallDontLie
        'playerNameI': '',  # Will extract from text
        'isScoring': play.get('scoring_play', False),
        'shotResult': 'Made' if play.get('scoring_play') else 'Missed',
        # Additional BallDontLie specific fields
        '_bdl_type': play.get('type', ''),
        '_bdl_text': play.get('text', ''),
        '_bdl_score_value': play.get('score_value'),
    }


def extract_player_from_text(text: str) -> str:
    """Extract player name from play description text."""
    if not text:
        return ''

    import re

    # Try "Name makes/misses/draws/defensive/offensive" pattern - handles multi-word names
    match = re.match(r'^([A-Z][a-z\']+(?:\s+[A-Z][a-z\']+)+?)(?:\s+(?:Jr\.|Sr\.|II|III|IV))?\s+(?:makes|misses|draws|commits|blocks|steals|with|offensive|defensive|personal|shooting|loose|turnover|rebound)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Try "by Name" pattern
    match = re.search(r'(?:by|from)\s+([A-Z][a-z\']+(?:\s+[A-Z][a-z\']+)+?)(?:\s+(?:Jr\.|Sr\.|II|III|IV))?(?:\s|$|\.|\)|,)', text)
    if match:
        return match.group(1).strip()

    return ''


def generate_messages_from_play(play: dict, game_info: dict, prev_play: dict = None, largest_leads: dict = None, lead_changes: int = 0, is_game_final: bool = False) -> list:
    """
    Generate chat messages from a BallDontLie play.

    Args:
        play: Play object from BallDontLie API
        game_info: Dict with home_team, away_team
        prev_play: Previous play for lead change detection
        largest_leads: Dict tracking largest leads for each team
        lead_changes: Total number of lead changes so far
        is_game_final: Whether the game has ended (for game summary)

    Returns:
        List of message dicts
    """
    play_type = play.get('type', '').lower()
    text = play.get('text', '')
    team_obj = play.get('team') or {}  # Handle None case
    team = team_obj.get('abbreviation', '')
    home_score = play.get('home_score', 0) or 0
    away_score = play.get('away_score', 0) or 0
    period = play.get('period', 1)
    clock = play.get('clock', '')
    is_scoring = play.get('scoring_play', False)
    score_value = play.get('score_value')

    home_team = game_info.get('home_team', 'HOME')
    away_team = game_info.get('away_team', 'AWAY')

    # Extract player name from text
    player = extract_player_from_text(text)

    # Get previous scores for lead change detection
    prev_home = (prev_play.get('home_score', 0) or 0) if prev_play else 0
    prev_away = (prev_play.get('away_score', 0) or 0) if prev_play else 0

    if largest_leads is None:
        largest_leads = {'home': 0, 'away': 0}

    messages = []

    # Scoring plays
    if is_scoring and score_value:
        pts = str(score_value)
        shot_type = play_type.replace(' shot', '').replace(' putback', '').strip()

        msg = f"💥 {player} ({team}) hits the {shot_type.lower()}! {pts} points."
        messages.append({
            'bot': 'play_by_play',
            'text': msg,
            'type': 'score',
            'team': team,
        })

        # HypeMan for dunks and highlight plays
        if 'dunk' in play_type or 'alley oop' in play_type:
            messages.append({
                'bot': 'hype_man',
                'text': f"🔥🔥🔥 POSTER! {player} throws it DOWN!",
                'type': 'hype',
                'team': team,
            })

    # Free throws
    elif 'free throw' in play_type and 'makes' in text.lower():
        msg = f"✓ {player} ({team}) makes the free throw."
        messages.append({
            'bot': 'play_by_play',
            'text': msg,
            'type': 'freethrow',
            'team': team,
        })

    # Blocks - check both play_type AND text (API often has shot type as play_type but block in text)
    elif 'block' in play_type or ('blocks' in text.lower() and not is_scoring):
        # Extract blocker name from text like "Goga Bitadze blocks Zion Williamson's shot"
        blocker = player
        if 'blocks' in text.lower():
            import re
            block_match = re.match(r'^([A-Za-z\s\'\-]+?)\s+blocks', text)
            if block_match:
                blocker = block_match.group(1).strip()
        messages.append({
            'bot': 'play_by_play',
            'text': f"🚫 {blocker} with the REJECTION!",
            'type': 'block',
            'team': team,
        })

    # Steals - check both play_type AND text
    elif 'steal' in play_type or 'steal' in text.lower():
        # Extract stealer name from text
        stealer = player
        if 'steal' in text.lower():
            import re
            steal_match = re.search(r'([A-Za-z\s\'\-]+?)\s+steals?', text)
            if steal_match:
                stealer = steal_match.group(1).strip()
        messages.append({
            'bot': 'play_by_play',
            'text': f"👋 {stealer} ({team}) picks the pocket! Steal!",
            'type': 'steal',
            'team': team,
        })

    # Turnovers
    elif 'turnover' in play_type or 'turnover' in text.lower():
        if 'steal' not in text.lower():  # Don't duplicate with steal
            messages.append({
                'bot': 'play_by_play',
                'text': f"💨 Turnover by {player} ({team})",
                'type': 'turnover',
                'team': team,
            })

    # Missed shots - show when it's a shooting play but not a scoring play
    elif play.get('shooting_play') and not is_scoring and 'blocks' not in text.lower():
        # Extract shot type and distance from text
        shot_desc = play_type.replace(' Shot', '').lower()
        if 'misses' in text.lower():
            messages.append({
                'bot': 'play_by_play',
                'text': f"❌ {player} ({team}) misses the {shot_desc}.",
                'type': 'miss',
                'team': team,
            })

    # Rebounds
    elif 'rebound' in play_type.lower():
        reb_type = 'offensive' if 'offensive' in play_type.lower() else 'defensive'
        emoji = '🔄' if reb_type == 'offensive' else '📥'
        messages.append({
            'bot': 'play_by_play',
            'text': f"{emoji} {player} ({team}) grabs the {reb_type} rebound.",
            'type': 'rebound',
            'team': team,
        })

    # Fouls - show referee calls
    elif 'foul' in play_type:
        # Determine foul type from play_type or text
        foul_type = 'foul'
        if 'personal' in play_type.lower() or 'personal' in text.lower():
            foul_type = 'personal foul'
        elif 'shooting' in play_type.lower() or 'shooting' in text.lower():
            foul_type = 'shooting foul'
        elif 'offensive' in play_type.lower() or 'offensive' in text.lower():
            foul_type = 'offensive foul'
        elif 'technical' in play_type.lower() or 'technical' in text.lower():
            foul_type = 'technical foul'
        elif 'flagrant' in play_type.lower() or 'flagrant' in text.lower():
            foul_type = 'flagrant foul'
        elif 'loose ball' in play_type.lower() or 'loose ball' in text.lower():
            foul_type = 'loose ball foul'
        elif 'away from play' in text.lower():
            foul_type = 'away from play foul'

        # Extract who was fouled if in text
        fouled_player = ''
        if ' on ' in text.lower():
            # "Player commits foul on OtherPlayer"
            parts = text.lower().split(' on ')
            if len(parts) > 1:
                fouled_part = parts[1].split()[0:2]  # Get first two words
                fouled_player = ' '.join(fouled_part).title()

        foul_msg = f"🚨 {foul_type.upper()} called on {player} ({team})"
        if fouled_player:
            foul_msg += f" - fouled {fouled_player}"

        messages.append({
            'bot': 'referee',
            'text': foul_msg,
            'type': 'foul',
            'team': team,
        })

    # Coach's Challenge / Replay Review
    elif 'challenge' in play_type.lower() or 'replay' in play_type.lower() or 'review' in play_type.lower():
        challenge_team = team if team else 'Team'
        if 'overturn' in text.lower() or 'successful' in text.lower():
            messages.append({
                'bot': 'referee',
                'text': f"⚖️ CHALLENGE SUCCESSFUL! {challenge_team}'s challenge overturns the call.",
                'type': 'challenge',
                'team': team,
            })
        elif 'stands' in text.lower() or 'unsuccessful' in text.lower() or 'upheld' in text.lower():
            messages.append({
                'bot': 'referee',
                'text': f"⚖️ CHALLENGE FAILED. The call on the floor stands. {challenge_team} loses a timeout.",
                'type': 'challenge',
                'team': team,
            })
        else:
            messages.append({
                'bot': 'referee',
                'text': f"⚖️ COACH'S CHALLENGE - {challenge_team} is challenging the call. Play under review.",
                'type': 'challenge',
                'team': team,
            })

    # Timeouts
    elif 'timeout' in play_type.lower():
        timeout_type = 'Full' if 'full' in play_type.lower() else '20-second'
        messages.append({
            'bot': 'play_by_play',
            'text': f"⏸️ {team} calls a {timeout_type.lower()} timeout.",
            'type': 'timeout',
            'team': team,
        })

    # Jumpball
    elif 'jumpball' in play_type.lower() or 'jump ball' in play_type.lower():
        messages.append({
            'bot': 'play_by_play',
            'text': f"⬆️ Jump ball! {text}",
            'type': 'jumpball',
        })

    # Period events
    elif 'period' in play_type:
        if 'end' in play_type.lower():
            messages.append({
                'bot': 'play_by_play',
                'text': f"⏱️ End of Q{period}. Score: {away_team} {away_score} - {home_team} {home_score}",
                'type': 'period',
            })
            # LLM-generated quarter summary (longer, analytical)
            lead = home_score - away_score
            leader = home_team if lead > 0 else away_team
            lead_diff = abs(lead) if lead != 0 else 0

            # Determine largest lead info
            largest_home = largest_leads.get('home', 0) if largest_leads else 0
            largest_away = largest_leads.get('away', 0) if largest_leads else 0
            if largest_home > largest_away:
                largest_lead_team = home_team
                largest_lead = largest_home
            elif largest_away > largest_home:
                largest_lead_team = away_team
                largest_lead = largest_away
            else:
                largest_lead_team = 'Neither'
                largest_lead = 0

            # Generate LLM quarter summary
            if LLM_AVAILABLE:
                llm_context = {
                    'home_team': home_team,
                    'away_team': away_team,
                    'period': period,
                    'home_score': home_score,
                    'away_score': away_score,
                    'leader': leader if lead != 0 else 'Tied',
                    'lead_diff': str(lead_diff) if lead_diff > 0 else 'tied',
                    'lead_changes': lead_changes,
                    'largest_lead_team': largest_lead_team,
                    'largest_lead': largest_lead,
                }
                llm_summary = generate_llm_commentary('quarter_summary', llm_context)
                if llm_summary:
                    messages.append({
                        'bot': 'ai_commentator',
                        'text': f"🤖 {llm_summary}",
                        'type': 'ai_summary',
                    })
                else:
                    # Fallback to simple summary if LLM fails
                    messages.append({
                        'bot': 'stats_nerd',
                        'text': f"📊 Quarter {period} complete. {leader} leads by {lead_diff}.",
                        'type': 'summary',
                    })
            else:
                # No LLM available - use simple summary
                messages.append({
                    'bot': 'stats_nerd',
                    'text': f"📊 Quarter {period} complete. {leader} leads by {lead_diff}.",
                    'type': 'summary',
                })
        elif 'start' in play_type.lower():
            messages.append({
                'bot': 'play_by_play',
                'text': f"🏀 Quarter {period} is underway!",
                'type': 'period',
            })

    # Lead change and tie detection (only on scoring plays)
    if is_scoring:
        prev_diff = prev_away - prev_home
        curr_diff = away_score - home_score

        # Lead change
        if prev_diff > 0 and curr_diff < 0:
            messages.append({
                'bot': 'hype_man',
                'text': f"🔄 LEAD CHANGE! {home_team} takes the lead!",
                'type': 'lead_change',
                'team': home_team,
                'is_lead_change': True,
            })
        elif prev_diff < 0 and curr_diff > 0:
            messages.append({
                'bot': 'hype_man',
                'text': f"🔄 LEAD CHANGE! {away_team} takes the lead!",
                'type': 'lead_change',
                'team': away_team,
                'is_lead_change': True,
            })
        # Tie game
        elif curr_diff == 0 and prev_diff != 0:
            messages.append({
                'bot': 'hype_man',
                'text': f"⚖️ TIE GAME! {away_score}-{home_score}",
                'type': 'tie',
            })

        # Largest lead detection
        home_lead = home_score - away_score
        away_lead = away_score - home_score

        if home_lead > 0 and home_lead > largest_leads.get('home', 0):
            if home_lead >= 5:
                messages.append({
                    'bot': 'stats_nerd',
                    'text': f"📈 {home_team} extends to their LARGEST LEAD of the game: +{home_lead}!",
                    'type': 'largest_lead',
                    'team': home_team,
                    'is_largest_lead': True,
                    'lead_amount': home_lead,
                })
            largest_leads['home'] = home_lead

        if away_lead > 0 and away_lead > largest_leads.get('away', 0):
            if away_lead >= 5:
                messages.append({
                    'bot': 'stats_nerd',
                    'text': f"📈 {away_team} extends to their LARGEST LEAD of the game: +{away_lead}!",
                    'type': 'largest_lead',
                    'team': away_team,
                    'is_largest_lead': True,
                    'lead_amount': away_lead,
                })
            largest_leads['away'] = away_lead

    # Game summary (when game is final)
    if is_game_final and LLM_AVAILABLE:
        # Determine winner and margin
        if home_score > away_score:
            winner = home_team
            margin = home_score - away_score
        elif away_score > home_score:
            winner = away_team
            margin = away_score - home_score
        else:
            winner = 'Tie'
            margin = 0

        # Determine largest lead info
        largest_home = largest_leads.get('home', 0) if largest_leads else 0
        largest_away = largest_leads.get('away', 0) if largest_leads else 0
        if largest_home > largest_away:
            largest_lead_team = home_team
            largest_lead = largest_home
        elif largest_away > largest_home:
            largest_lead_team = away_team
            largest_lead = largest_away
        else:
            largest_lead_team = 'Neither'
            largest_lead = 0

        llm_context = {
            'home_team': home_team,
            'away_team': away_team,
            'home_score': home_score,
            'away_score': away_score,
            'winner': winner,
            'margin': margin,
            'lead_changes': lead_changes,
            'largest_lead_team': largest_lead_team,
            'largest_lead': largest_lead,
        }
        llm_summary = generate_llm_commentary('game_summary', llm_context)
        if llm_summary:
            messages.append({
                'bot': 'ai_commentator',
                'text': f"🤖 FINAL RECAP: {llm_summary}",
                'type': 'ai_summary',
                'score': f"{away_team} {away_score} - {home_team} {home_score}",
                'period': period,
                'clock': '',
            })

    # Add metadata to all messages
    for msg in messages:
        msg['score'] = f"{away_team} {away_score} - {home_team} {home_score}"
        msg['period'] = period
        msg['clock'] = clock

    return messages


if __name__ == '__main__':
    # Test the module
    import json

    print("Testing BallDontLie Live module...")

    games = get_todays_games()
    print(f"\nFound {len(games)} games today")

    if games:
        game = games[0]
        game_id = game['id']
        print(f"\nTesting with game {game_id}: {game['visitor_team']['abbreviation']} @ {game['home_team']['abbreviation']}")

        plays = get_play_by_play(game_id)
        print(f"Found {len(plays)} plays")

        stats = get_player_stats(game_id)
        print(f"Found {len(stats)} player stats")

        if stats:
            formatted = format_player_stats_for_frontend(stats, game['home_team']['id'])
            print(f"\nHome team players: {len(formatted['home'])}")
            print(f"Away team players: {len(formatted['away'])}")

            if formatted['home']:
                print(f"\nTop home scorer: {formatted['home'][0]}")
