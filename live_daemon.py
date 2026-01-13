#!/usr/bin/env python3
"""
Live Game Daemon - Automatically captures win probability history for Nuggets games.

This daemon:
1. Checks if there's a Nuggets game today
2. Starts polling 30 minutes before game time
3. Captures snapshots every 30 seconds during live games
4. Updates schedule cache with final scores and balldontlie_id
5. Stops polling after game is final

Run as systemd service for automatic game tracking.
"""

import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

# Setup paths
SCRIPT_DIR = Path(__file__).parent
CACHE_DIR = SCRIPT_DIR / 'cache'
LIVE_HISTORY_DIR = CACHE_DIR / 'live_history'
DEV_LIVE_HISTORY_DIR = CACHE_DIR / 'dev_live_history'

# Load environment
load_dotenv(SCRIPT_DIR / '.env')

# Timezone
MOUNTAIN_TZ = ZoneInfo('America/Denver')

# Polling intervals (seconds)
IDLE_INTERVAL = 60          # Check for games every minute when idle
PREGAME_INTERVAL = 30       # Poll every 30s starting 30 min before game
LIVE_INTERVAL = 30          # Poll every 30s during live game
POSTGAME_WAIT = 300         # Wait 5 min after final before returning to idle

# How early to start polling before game time
PREGAME_START_MINUTES = 30

# Nuggets team ID in BALLDONTLIE API
NUGGETS_ID = 8

# Configure logging
def setup_logging():
    """Setup logging to stdout (systemd will capture this)."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout
    )
    return logging.getLogger('live_daemon')

logger = setup_logging()


def ensure_dirs():
    """Ensure cache directories exist."""
    CACHE_DIR.mkdir(exist_ok=True)
    LIVE_HISTORY_DIR.mkdir(exist_ok=True)
    DEV_LIVE_HISTORY_DIR.mkdir(exist_ok=True)


def atomic_write_json(filepath, data, indent=2):
    """
    Write JSON data to a file atomically.
    Writes to a temp file first, then renames to avoid race conditions.
    """
    filepath = Path(filepath)
    # Create temp file in same directory to ensure same filesystem for atomic rename
    fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=indent)
        # Atomic rename (works on same filesystem)
        os.replace(tmp_path, filepath)
    except Exception:
        # Clean up temp file on error
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def load_cache(filename):
    """Load a cache file."""
    cache_file = CACHE_DIR / filename
    if cache_file.exists():
        with open(cache_file, 'r') as f:
            return json.load(f)
    return None


def save_cache(filename, data):
    """Save data to cache file (atomic write)."""
    data['_cached_at'] = datetime.now().isoformat()
    atomic_write_json(CACHE_DIR / filename, data)


def load_live_history(game_id):
    """Load history for a specific game."""
    history_file = LIVE_HISTORY_DIR / f'game_{game_id}.json'
    if history_file.exists():
        with open(history_file, 'r') as f:
            return json.load(f)
    return None


def save_live_history(game_id, data):
    """Save history for a specific game (atomic write)."""
    history_file = LIVE_HISTORY_DIR / f'game_{game_id}.json'
    atomic_write_json(history_file, data)


def save_live_status(is_live, game_data=None):
    """Save current live game status for the web UI.

    This allows the nav bar to show when a game is live.
    """
    status = {
        'is_live': is_live,
        '_updated_at': datetime.now().isoformat()
    }
    if game_data:
        status['game_id'] = game_data.get('game_id')
        status['opponent'] = game_data.get('opponent_name')
        status['nuggets_score'] = game_data.get('nuggets_score')
        status['opponent_score'] = game_data.get('opponent_score')
        status['period'] = game_data.get('period')
        status['time_remaining'] = game_data.get('time_remaining')
    atomic_write_json(CACHE_DIR / 'live_status.json', status)


def ml_to_prob(ml):
    """Convert moneyline to implied probability."""
    if ml is None:
        return None
    if ml < 0:
        return abs(ml) / (abs(ml) + 100)
    else:
        return 100 / (ml + 100)


def get_todays_game(api_key):
    """Check if there's a Nuggets game today (or still in progress from yesterday).

    Queries both today and yesterday to handle:
    - Late-night West Coast games that cross midnight in other timezones
    - Games that started yesterday but are still live
    """
    now = datetime.now(MOUNTAIN_TZ)
    today = now.strftime('%Y-%m-%d')
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')

    try:
        # Query both today and yesterday to catch edge cases
        resp = requests.get(
            'https://api.balldontlie.io/v1/games',
            params={
                'team_ids[]': NUGGETS_ID,
                'dates[]': [yesterday, today],
                'per_page': 10
            },
            headers={'Authorization': api_key},
            timeout=15
        )
        resp.raise_for_status()
        games = resp.json().get('data', [])

        if not games:
            return None

        # Prioritize:
        # 1. Any live game (regardless of date)
        # 2. Today's scheduled game
        # 3. Yesterday's game if it's Final (might still need final processing)
        live_game = None
        todays_game = None
        yesterdays_final = None

        for game in games:
            status = game.get('status', '')
            game_date = game.get('date', '')
            home_score = game.get('home_team_score', 0) or 0
            away_score = game.get('visitor_team_score', 0) or 0

            # Check if game is live
            is_live = (home_score > 0 or away_score > 0) and status != 'Final'

            if is_live:
                live_game = game
                break  # Live game takes priority
            elif game_date == today and status != 'Final':
                todays_game = game
            elif game_date == yesterday and status == 'Final':
                yesterdays_final = game

        # Return in priority order
        if live_game:
            logger.debug(f"Found live game: {live_game.get('id')}")
            return live_game
        elif todays_game:
            logger.debug(f"Found today's scheduled game: {todays_game.get('id')}")
            return todays_game
        elif yesterdays_final:
            # Only return if we might need to do final processing
            logger.debug(f"Found yesterday's final game: {yesterdays_final.get('id')}")
            return yesterdays_final

        return None

    except Exception as e:
        logger.error(f"Error fetching games: {e}")
        return None


def fetch_live_data(api_key, game):
    """Fetch live game data including odds."""
    game_id = game.get('id')
    game_date = game.get('date', '')  # Use the game's actual date from API
    status = game.get('status', '')
    home_team = game.get('home_team', {})
    away_team = game.get('visitor_team', {})

    is_nuggets_home = home_team.get('id') == NUGGETS_ID
    nuggets_team = home_team if is_nuggets_home else away_team
    opponent_team = away_team if is_nuggets_home else home_team

    home_score = game.get('home_team_score', 0) or 0
    away_score = game.get('visitor_team_score', 0) or 0
    nuggets_score = home_score if is_nuggets_home else away_score
    opponent_score = away_score if is_nuggets_home else home_score

    # Determine game state
    if status == 'Final':
        game_state = 'final'
    elif home_score > 0 or away_score > 0:
        game_state = 'live'
    else:
        game_state = 'pregame'

    # Get period/time info
    period = game.get('period', 0)
    time_remaining = game.get('time', '')

    now = datetime.now(MOUNTAIN_TZ)

    # Fetch live odds using the game's actual date
    consensus_prob = None
    vendor_count = 0

    try:
        odds_resp = requests.get(
            'https://api.balldontlie.io/v2/odds',
            params={'dates[]': game_date, 'per_page': 100},
            headers={'Authorization': api_key},
            timeout=15
        )
        odds_resp.raise_for_status()
        all_odds = odds_resp.json().get('data', [])

        # Filter for this game
        game_odds = [o for o in all_odds if o.get('game_id') == game_id]

        # Calculate consensus probability
        probs = []
        for o in game_odds:
            if o.get('moneyline_home_odds') is None:
                continue

            home_ml = o.get('moneyline_home_odds')
            away_ml = o.get('moneyline_away_odds')
            nuggets_ml = home_ml if is_nuggets_home else away_ml

            prob = ml_to_prob(nuggets_ml)
            if prob:
                probs.append(prob * 100)

        if probs:
            consensus_prob = round(sum(probs) / len(probs), 1)
            vendor_count = len(probs)

    except Exception as e:
        logger.warning(f"Error fetching odds: {e}")

    return {
        'game_id': game_id,
        'game_state': game_state,
        'status': status,
        'period': period,
        'time_remaining': time_remaining,
        'nuggets_score': nuggets_score,
        'opponent_score': opponent_score,
        'nuggets_name': nuggets_team.get('full_name', 'Denver Nuggets'),
        'opponent_name': opponent_team.get('full_name', ''),
        'opponent_abbrev': opponent_team.get('abbreviation', ''),
        'is_nuggets_home': is_nuggets_home,
        'home_team': home_team.get('full_name', ''),
        'away_team': away_team.get('full_name', ''),
        'home_score': home_score,
        'away_score': away_score,
        'consensus_prob': consensus_prob,
        'vendor_count': vendor_count,
        'timestamp': now.isoformat(),
        'date': game_date,  # Use the game's actual date from API
    }


def save_snapshot(data):
    """Save a snapshot to the game's history file."""
    game_id = data['game_id']

    # Load or create history
    history = load_live_history(game_id)
    if not history:
        history = {
            'game_id': game_id,
            'balldontlie_id': game_id,  # Add explicit field for easier lookup
            'game_date': data['date'],  # Add explicit field for easier lookup
            'snapshots': [],
            'game_info': {
                'nuggets_name': data['nuggets_name'],
                'opponent_name': data['opponent_name'],
                'is_nuggets_home': data['is_nuggets_home'],
                'date': data['date'],
            },
            'created_at': datetime.now().isoformat(),
        }
        logger.info(f"Created new history for game {game_id}")

    # Create snapshot
    snapshot = {
        'timestamp': data['timestamp'],
        'game_state': data['game_state'],
        'period': data['period'],
        'time_remaining': data['time_remaining'],
        'nuggets_score': data['nuggets_score'],
        'opponent_score': data['opponent_score'],
        'consensus_prob': data['consensus_prob'],
        'vendor_count': data['vendor_count'],
    }

    # Only add if probability changed (avoid duplicates)
    if not history['snapshots'] or history['snapshots'][-1].get('consensus_prob') != snapshot['consensus_prob']:
        history['snapshots'].append(snapshot)
        logger.debug(f"Added snapshot: prob={data['consensus_prob']}%, score={data['nuggets_score']}-{data['opponent_score']}")

    # Update final state
    history['final_state'] = data['game_state']
    history['final_score'] = {
        'nuggets': data['nuggets_score'],
        'opponent': data['opponent_score'],
    }
    history['updated_at'] = datetime.now().isoformat()

    save_live_history(game_id, history)
    return len(history['snapshots'])


def update_schedule_with_final(data):
    """Update schedule cache with final game score and balldontlie_id."""
    schedule = load_cache('nuggets_schedule.json')
    if not schedule:
        logger.warning("No schedule cache found")
        return False

    game_date = data['date']
    home_team = data['home_team']
    away_team = data['away_team']
    home_score = data['home_score']
    away_score = data['away_score']
    is_nuggets_home = data['is_nuggets_home']
    game_id = data['game_id']

    nuggets_score = home_score if is_nuggets_home else away_score
    opponent_score = away_score if is_nuggets_home else home_score
    result = 'W' if nuggets_score > opponent_score else 'L'

    updated = False

    # Update both games and calendar_games lists
    for games_list in [schedule.get('games', []), schedule.get('calendar_games', [])]:
        for game in games_list:
            if (game.get('local_date') == game_date and
                game.get('home_team') == home_team and
                game.get('away_team') == away_team):
                game['is_past'] = True
                game['game_status'] = 3
                game['home_score'] = home_score
                game['away_score'] = away_score
                game['result'] = result
                game['balldontlie_id'] = game_id
                updated = True

    if updated:
        save_cache('nuggets_schedule.json', schedule)
        logger.info(f"Updated schedule: {away_team} @ {home_team} - {away_score}-{home_score} ({result})")

    return updated


def get_nba_starters(game_date):
    """Get starter info from NBA API for the Nuggets game on given date."""
    try:
        from nba_api.stats.endpoints import LeagueGameFinder, BoxScoreTraditionalV3

        # Find Nuggets game on this date
        lgf = LeagueGameFinder(
            team_id_nullable=1610612743,  # Nuggets NBA team ID
            date_from_nullable=game_date.strftime('%m/%d/%Y'),
            date_to_nullable=game_date.strftime('%m/%d/%Y'),
            season_type_nullable='Regular Season'
        )
        games = lgf.get_dict()

        nba_game_id = None
        for rs in games.get('resultSets', []):
            if rs.get('name') == 'LeagueGameFinderResults':
                rows = rs.get('rowSet', [])
                if rows:
                    headers = rs.get('headers', [])
                    game_dict = dict(zip(headers, rows[0]))
                    nba_game_id = game_dict.get('GAME_ID')
                    break

        if not nba_game_id:
            logger.warning(f"Could not find NBA game ID for {game_date}")
            return {}

        # Get box score with starter info
        bs = BoxScoreTraditionalV3(game_id=nba_game_id)
        data = bs.get_dict()
        box = data.get('boxScoreTraditional', {})

        # Find Nuggets team (could be home or away)
        starters = {}
        for team_key in ['homeTeam', 'awayTeam']:
            team = box.get(team_key, {})
            if team.get('teamId') == 1610612743:  # Nuggets
                for p in team.get('players', []):
                    name = f"{p.get('firstName', '')} {p.get('familyName', '')}"
                    # Position is only filled for starters
                    starters[name] = bool(p.get('position'))
                break

        logger.info(f"Found {sum(starters.values())} starters from NBA API")
        return starters

    except Exception as e:
        logger.error(f"Error getting starters from NBA API: {e}")
        return {}


def fetch_player_stats(api_key, game_id, game_date=None):
    """Fetch player box score stats for a completed game."""
    try:
        # Get starter info from NBA API if we have the date
        starters = {}
        if game_date:
            starters = get_nba_starters(game_date)

        resp = requests.get(
            'https://api.balldontlie.io/v1/stats',
            params={'game_ids[]': game_id, 'per_page': 100},
            headers={'Authorization': api_key},
            timeout=15
        )
        resp.raise_for_status()
        all_stats = resp.json().get('data', [])

        # Filter for Nuggets players (team_id 8)
        nuggets_stats = [s for s in all_stats if s.get('team', {}).get('id') == NUGGETS_ID]

        # Sort by minutes played (descending)
        def parse_mins(m):
            if not m:
                return 0
            try:
                return int(str(m).split(':')[0]) if ':' in str(m) else int(m)
            except:
                return 0

        # Filter out DNP (0 or no minutes) and sort by minutes
        nuggets_stats = [s for s in nuggets_stats if parse_mins(s.get('min')) > 0]
        nuggets_stats.sort(key=lambda x: -parse_mins(x.get('min')))

        # Extract relevant stats for each player
        player_stats = []
        for s in nuggets_stats:
            player = s.get('player', {})
            name = f"{player.get('first_name', '')} {player.get('last_name', '')}"
            # Use NBA API starter info if available, otherwise unknown
            is_starter = starters.get(name, None)
            player_stats.append({
                'name': name,
                'jersey': player.get('jersey_number', ''),
                'position': player.get('position', ''),
                'starter': is_starter,
                'min': s.get('min', '0'),
                'pts': s.get('pts', 0),
                'reb': s.get('reb', 0),
                'ast': s.get('ast', 0),
                'stl': s.get('stl', 0),
                'blk': s.get('blk', 0),
                'fgm': s.get('fgm', 0),
                'fga': s.get('fga', 0),
                'fg_pct': s.get('fg_pct', 0),
                'fg3m': s.get('fg3m', 0),
                'fg3a': s.get('fg3a', 0),
                'fg3_pct': s.get('fg3_pct', 0),
                'ftm': s.get('ftm', 0),
                'fta': s.get('fta', 0),
                'ft_pct': s.get('ft_pct', 0),
                'oreb': s.get('oreb', 0),
                'dreb': s.get('dreb', 0),
                'tov': s.get('turnover', 0),
                'pf': s.get('pf', 0),
                'plus_minus': s.get('plus_minus', 0),
            })

        logger.info(f"Fetched stats for {len(player_stats)} Nuggets players")
        return player_stats

    except Exception as e:
        logger.error(f"Error fetching player stats: {e}")
        return []


def update_recent_games(data):
    """Update recent games cache with final game."""
    recent = load_cache('recent_games.json')
    if not recent:
        recent = {'games': []}

    games = recent.get('games', [])
    game_id = data['game_id']

    # Check if already exists
    for game in games:
        if game.get('id') == game_id:
            return False

    nuggets_score = data['nuggets_score']
    opponent_score = data['opponent_score']
    result = 'W' if nuggets_score > opponent_score else 'L'

    new_game = {
        'id': game_id,
        'date': data['date'],
        'opponent': data['opponent_name'],
        'opponent_abbreviation': data['opponent_abbrev'],
        'home_game': data['is_nuggets_home'],
        'nuggets_score': nuggets_score,
        'opponent_score': opponent_score,
        'result': result,
    }

    games.insert(0, new_game)
    games = games[:10]  # Keep only 10
    recent['games'] = games

    save_cache('recent_games.json', recent)
    logger.info(f"Added to recent games: {result} vs {data['opponent_name']} ({nuggets_score}-{opponent_score})")
    return True


def get_game_start_time(game):
    """Parse game start time from API response.

    BALLDONTLIE returns status like "7:00 PM ET" or "10:30 PM PT" for scheduled games.
    We need to parse the timezone from the string and use the game's date field.
    """
    status = game.get('status', '')
    game_date = game.get('date', '')  # API returns game date as YYYY-MM-DD

    # If it's a time string, parse it
    if ('PM' in status or 'AM' in status) and game_date:
        try:
            # Map timezone abbreviations to ZoneInfo names
            tz_map = {
                'ET': 'America/New_York',
                'CT': 'America/Chicago',
                'MT': 'America/Denver',
                'PT': 'America/Los_Angeles',
            }

            # Extract timezone from status string
            game_tz = None
            time_str = status
            for tz_abbrev, tz_name in tz_map.items():
                if tz_abbrev in status:
                    game_tz = ZoneInfo(tz_name)
                    time_str = status.replace(f' {tz_abbrev}', '').strip()
                    break

            if not game_tz:
                # Default to Eastern if no timezone found
                game_tz = ZoneInfo('America/New_York')
                logger.warning(f"No timezone found in '{status}', defaulting to ET")

            # Parse using the game's actual date from the API
            game_time = datetime.strptime(f"{game_date} {time_str}", '%Y-%m-%d %I:%M %p')
            game_time = game_time.replace(tzinfo=game_tz)

            return game_time

        except Exception as e:
            logger.warning(f"Could not parse game time '{status}' for date {game_date}: {e}")

    return None


# ============================================================================
# DEV-LIVE CACHE WARMING
# ============================================================================

def get_all_live_games(api_key):
    """Get all NBA games that are currently live or recently started."""
    try:
        # Use Eastern timezone for NBA game dates
        eastern = ZoneInfo('America/New_York')
        today = datetime.now(eastern).strftime('%Y-%m-%d')

        resp = requests.get(
            'https://api.balldontlie.io/v1/games',
            params={'dates[]': today, 'per_page': 50},
            headers={'Authorization': api_key},
            timeout=15
        )
        resp.raise_for_status()
        games = resp.json().get('data', [])

        live_games = []
        for game in games:
            status = game.get('status', '')
            home_score = game.get('home_team_score', 0) or 0
            away_score = game.get('visitor_team_score', 0) or 0

            # Game is live if it has scores but isn't final
            is_live = (home_score > 0 or away_score > 0) and status != 'Final'

            if is_live:
                live_games.append(game)

        return live_games
    except Exception as e:
        logger.error(f"Error fetching all games: {e}")
        return []


def warm_dev_live_cache(api_key, game):
    """
    Warm the dev-live cache for a game by fetching play-by-play and building scores.
    This ensures the cache file has complete history from game start.
    """
    game_id = game.get('id')
    cache_file = DEV_LIVE_HISTORY_DIR / f'game_{game_id}.json'

    try:
        # Fetch play-by-play from BallDontLie
        resp = requests.get(
            f'https://api.balldontlie.io/v1/play_by_play',
            params={'game_ids[]': game_id, 'per_page': 1000},
            headers={'Authorization': api_key},
            timeout=30
        )
        resp.raise_for_status()
        plays = resp.json().get('data', [])

        if not plays:
            return False

        # Build scores array from all plays
        scores = []
        for p in plays:
            h = int(p.get('home_score', 0) or 0)
            aw = int(p.get('away_score', 0) or 0)
            if h > 0 or aw > 0:
                if not scores or scores[-1]['home'] != h or scores[-1]['away'] != aw:
                    clock = p.get('clock', '')
                    period = p.get('period', 1)
                    # Calculate elapsed time
                    elapsed = 0
                    if clock and period:
                        try:
                            if ':' in clock:
                                parts = clock.split(':')
                                mins = int(parts[0])
                                secs = int(float(parts[1]))
                            else:
                                mins = 0
                                secs = int(float(clock))
                            remaining = mins * 60 + secs
                            quarter_elapsed = 720 - remaining
                            elapsed = (period - 1) * 720 + quarter_elapsed
                        except:
                            elapsed = (period - 1) * 720

                    scores.append({
                        'home': h,
                        'away': aw,
                        'action': p.get('order', 0),
                        'period': period,
                        'clock': clock,
                        'elapsed': elapsed
                    })

        # Get game info
        home_team = game.get('home_team', {})
        away_team = game.get('visitor_team', {})
        home_score = game.get('home_team_score', 0) or 0
        away_score = game.get('visitor_team_score', 0) or 0

        game_info = {
            'home_team': home_team.get('abbreviation', ''),
            'away_team': away_team.get('abbreviation', ''),
            'game_id': str(game_id),
        }

        # Load existing cache or create new
        existing = None
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    existing = json.load(f)
            except:
                pass

        # Preserve existing messages if any, but always update scores
        cache_data = {
            'messages': existing.get('messages', []) if existing else [],
            'scores': scores,  # Always use fresh complete scores
            'game_info': game_info,
            'status': game.get('status', ''),
            'last_action': plays[-1].get('order', 0) if plays else 0,
            'lead_changes': existing.get('lead_changes', 0) if existing else 0,
            'final_score': {'home': home_score, 'away': away_score},
            'total_actions': len(plays),
            'daemon_updated': datetime.now().isoformat(),
        }

        atomic_write_json(cache_file, cache_data)
        logger.debug(f"Warmed dev-live cache for game {game_id}: {len(scores)} score points")
        return True

    except Exception as e:
        logger.error(f"Error warming dev-live cache for game {game_id}: {e}")
        return False


def warm_all_dev_live_caches(api_key):
    """Warm dev-live caches for all currently live games."""
    live_games = get_all_live_games(api_key)

    if not live_games:
        return 0

    warmed = 0
    for game in live_games:
        if warm_dev_live_cache(api_key, game):
            warmed += 1

    if warmed > 0:
        logger.info(f"Warmed dev-live cache for {warmed}/{len(live_games)} live games")

    return warmed


def run_daemon():
    """Main daemon loop."""
    api_key = os.getenv('BALLDONTLIE_API_KEY')
    if not api_key:
        logger.error("BALLDONTLIE_API_KEY not set in environment")
        sys.exit(1)

    ensure_dirs()
    save_live_status(False)  # Initialize status as not live
    logger.info("Live daemon started")
    logger.info(f"Cache directory: {CACHE_DIR}")

    current_game_id = None
    game_finished = False
    postgame_time = None

    while True:
        try:
            now = datetime.now(MOUNTAIN_TZ)

            # If we just finished a game, wait before checking for new games
            if game_finished and postgame_time:
                if now < postgame_time:
                    time.sleep(LIVE_INTERVAL)
                    continue
                else:
                    game_finished = False
                    postgame_time = None
                    current_game_id = None
                    logger.info("Post-game wait complete, returning to idle")

            # Check for today's game
            game = get_todays_game(api_key)

            if not game:
                logger.debug("No Nuggets game today")
                # Still warm dev-live caches for any other live NBA games
                warm_all_dev_live_caches(api_key)
                time.sleep(IDLE_INTERVAL)
                continue

            game_id = game.get('id')
            status = game.get('status', '')

            # Check if game is final
            if status == 'Final':
                if current_game_id == game_id and not game_finished:
                    # Game just ended - do final processing
                    logger.info("Game ended - doing final processing")
                    data = fetch_live_data(api_key, game)
                    save_snapshot(data)
                    update_schedule_with_final(data)
                    update_recent_games(data)

                    # Fetch and save player stats
                    game_date_str = game.get('date', '')
                    game_date_obj = datetime.strptime(game_date_str, '%Y-%m-%d').date() if game_date_str else None
                    player_stats = fetch_player_stats(api_key, game_id, game_date_obj)
                    if player_stats:
                        history = load_live_history(game_id)
                        if history:
                            history['player_stats'] = player_stats
                            save_live_history(game_id, history)
                            logger.info(f"Saved player stats for {len(player_stats)} players")

                    game_finished = True
                    postgame_time = now + timedelta(seconds=POSTGAME_WAIT)
                    save_live_status(False)  # Clear live status
                    logger.info(f"Final: DEN {data['nuggets_score']} - {data['opponent_name']} {data['opponent_score']}")
                    logger.info(f"Total snapshots: {len(load_live_history(game_id).get('snapshots', []))}")

                time.sleep(IDLE_INTERVAL)
                continue

            # Check if game is live
            home_score = game.get('home_team_score', 0) or 0
            away_score = game.get('visitor_team_score', 0) or 0

            if home_score > 0 or away_score > 0:
                # Game is live - poll frequently
                current_game_id = game_id
                data = fetch_live_data(api_key, game)
                snapshot_count = save_snapshot(data)
                save_live_status(True, data)  # Update live status for nav

                logger.info(f"Q{data['period']} {data['time_remaining']} | "
                           f"DEN {data['nuggets_score']} - {data['opponent_name']} {data['opponent_score']} | "
                           f"Prob: {data['consensus_prob']}% | Snapshots: {snapshot_count}")

                # Warm dev-live caches for all live NBA games
                warm_all_dev_live_caches(api_key)

                time.sleep(LIVE_INTERVAL)
                continue

            # Game is scheduled - check if we should start pregame polling
            game_time = get_game_start_time(game)
            if game_time:
                time_until_game = (game_time - now).total_seconds() / 60  # minutes

                if time_until_game <= PREGAME_START_MINUTES:
                    # Start pregame polling
                    current_game_id = game_id
                    data = fetch_live_data(api_key, game)
                    save_snapshot(data)

                    logger.info(f"Pregame polling started - {int(time_until_game)} min until tip | "
                               f"Prob: {data['consensus_prob']}%")

                    time.sleep(PREGAME_INTERVAL)
                    continue
                else:
                    logger.debug(f"Game in {int(time_until_game)} min - waiting")

            # Idle - check less frequently
            time.sleep(IDLE_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Daemon stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            time.sleep(IDLE_INTERVAL)


if __name__ == '__main__':
    run_daemon()
