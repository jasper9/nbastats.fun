from flask import Flask, render_template, jsonify, request
import calendar
import json
import math
import os
import re
import requests
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# LLM commentary for exciting events (optional)
try:
    from llm_commentary import enhance_message_with_llm, get_cached_or_generate
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Fallback: manually read .env file
    env_file = Path(__file__).parent / '.env'
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

JOKIC_PLAYER_ID = 203999
CACHE_DIR = Path(__file__).parent / 'cache'
DATA_DIR = Path(__file__).parent / 'data'

# Month name to number mapping for sorting
MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
}


def parse_return_date(date_str):
    """Parse 'Jan 4' format to sortable tuple (month, day)."""
    if not date_str:
        return (99, 99)  # No date sorts last
    match = re.match(r'(\w+)\s+(\d+)', date_str)
    if match:
        month_str, day = match.groups()
        month = MONTH_MAP.get(month_str.lower(), 99)
        return (month, int(day))
    return (99, 99)

STAT_NAMES = {
    'PTS': 'Points Per Game',
    'REB': 'Rebounds Per Game',
    'AST': 'Assists Per Game',
    'STL': 'Steals Per Game',
    'BLK': 'Blocks Per Game',
    'FG_PCT': 'Field Goal %',
    'FG3_PCT': 'Three-Point %',
    'FT_PCT': 'Free Throw %',
    'EFF': 'Efficiency',
    'FGM': 'Field Goals Made Per Game',
    'FGA': 'Field Goals Attempted Per Game',
    'FTM': 'Free Throws Made Per Game',
    'FTA': 'Free Throws Attempted Per Game',
    'OREB': 'Offensive Rebounds Per Game',
    'DREB': 'Defensive Rebounds Per Game',
    'MIN': 'Minutes Per Game'
}

app = Flask(__name__)

# Make GA tracking ID and live status available to all templates
@app.context_processor
def inject_globals():
    # Check if a game is currently live
    live_status = load_cache('live_status.json')
    is_live = False
    if live_status:
        is_live = live_status.get('is_live', False)
        # Also check if status is stale (more than 2 minutes old)
        updated_at = live_status.get('_updated_at')
        if updated_at:
            from datetime import datetime
            try:
                updated_time = datetime.fromisoformat(updated_at)
                age_seconds = (datetime.now() - updated_time).total_seconds()
                if age_seconds > 120:  # Stale after 2 minutes
                    is_live = False
            except Exception:
                pass

    return {
        'ga_tracking_id': os.getenv('GA_TRACKING_ID'),
        'is_game_live': is_live,
        'live_status': live_status
    }


def load_cache(filename):
    """Load data from a cache file."""
    cache_file = CACHE_DIR / filename
    if cache_file.exists():
        try:
            with open(cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
    return None


def save_cache(filename, data):
    """Save data to a cache file."""
    cache_file = CACHE_DIR / filename
    try:
        with open(cache_file, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving {filename}: {e}")
        return False


def update_schedule_with_final_score(game_date, home_team, away_team, home_score, away_score, is_nuggets_home, balldontlie_id=None):
    """Update schedule cache with final game score."""
    schedule = load_cache('nuggets_schedule.json')
    if not schedule:
        return False

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
                if balldontlie_id:
                    game['balldontlie_id'] = balldontlie_id
                updated = True

    if updated:
        save_cache('nuggets_schedule.json', schedule)
        print(f"Updated schedule with final: {away_team} @ {home_team} - {away_score}-{home_score}")

    return updated


def update_recent_games_with_final(game_date, opponent_name, opponent_abbrev, is_nuggets_home, nuggets_score, opponent_score, balldontlie_id):
    """Update recent games cache with final game score."""
    recent_games_cache = load_cache('recent_games.json')
    if not recent_games_cache:
        recent_games_cache = {'games': []}

    games = recent_games_cache.get('games', [])

    # Check if game already exists
    for game in games:
        if game.get('id') == balldontlie_id:
            return False  # Already exists

    result = 'W' if nuggets_score > opponent_score else 'L'

    new_game = {
        'id': balldontlie_id,
        'date': game_date,
        'opponent': opponent_name,
        'opponent_abbrev': opponent_abbrev,
        'is_home': is_nuggets_home,
        'nuggets_score': nuggets_score,
        'opponent_score': opponent_score,
        'result': result,
        'home_q1': None,
        'home_q2': None,
        'home_q3': None,
        'home_q4': None,
        'home_ot1': None,
        'visitor_q1': None,
        'visitor_q2': None,
        'visitor_q3': None,
        'visitor_q4': None,
        'visitor_ot1': None
    }

    # Insert at beginning (most recent first)
    games.insert(0, new_game)

    # Keep only last 10 games
    games = games[:10]

    recent_games_cache['games'] = games
    recent_games_cache['_cached_at'] = datetime.now().isoformat()

    if save_cache('recent_games.json', recent_games_cache):
        print(f"Updated recent games with: {opponent_name} - {nuggets_score}-{opponent_score}")
        return True
    return False


def load_data(filename):
    """Load data from a static data file."""
    data_file = DATA_DIR / filename
    if data_file.exists():
        try:
            with open(data_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
    return None


@app.template_filter('rank_class')
def rank_class_filter(val):
    """Return CSS class based on ranking value"""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ''
    val = int(val)
    if val == 1:
        return 'rank-1'
    elif val == 2:
        return 'rank-2'
    elif val == 3:
        return 'rank-3'
    elif val <= 5:
        return 'rank-top5'
    elif val <= 10:
        return 'rank-top10'
    return ''


@app.template_filter('safe_rank')
def safe_rank_filter(val):
    """Display rank value safely, handling NaN"""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return '-'
    return int(val)


@app.template_filter('mountain_time')
def mountain_time_filter(iso_timestamp):
    """Convert ISO timestamp to Mountain time display"""
    if not iso_timestamp or iso_timestamp == 'Unknown':
        return 'Unknown'
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        mountain_tz = ZoneInfo('America/Denver')
        dt_mountain = dt.replace(tzinfo=ZoneInfo('UTC')).astimezone(mountain_tz)
        # If the original timestamp was local (no timezone), treat it as local
        if dt.tzinfo is None:
            dt_mountain = dt.astimezone(mountain_tz)
        return dt_mountain.strftime('%Y-%m-%d %I:%M %p MT')
    except Exception:
        return iso_timestamp[:10] if len(iso_timestamp) >= 10 else iso_timestamp


@app.template_filter('game_time')
def game_time_filter(iso_timestamp):
    """Convert ISO timestamp to game time display (e.g., Thu Dec 26, 8:30 PM)"""
    if not iso_timestamp:
        return 'TBD'
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
        mountain_tz = ZoneInfo('America/Denver')
        dt_mountain = dt.astimezone(mountain_tz)
        return dt_mountain.strftime('%a %b %d, %I:%M %p')
    except Exception:
        return iso_timestamp


@app.template_filter('format_odds')
def format_odds_filter(odds):
    """Format American odds with + for positive"""
    if odds is None:
        return '-'
    if odds > 0:
        return f'+{odds}'
    return str(odds)


@app.template_filter('format_spread')
def format_spread_filter(spread):
    """Format point spread with + for positive"""
    if spread is None:
        return '-'
    if spread > 0:
        return f'+{spread}'
    return str(spread)


@app.template_filter('calendar_weekday')
def calendar_weekday_filter(date_tuple):
    """Get weekday for first day of month (Sunday=0)"""
    year, month, day = date_tuple
    # Python's weekday: Monday=0, Sunday=6
    # We want: Sunday=0, Monday=1, etc.
    weekday = calendar.weekday(year, month, day)
    return (weekday + 1) % 7


@app.template_filter('days_in_month')
def days_in_month_filter(year_month_tuple):
    """Get number of days in a month"""
    year, month = year_month_tuple
    return calendar.monthrange(year, month)[1]


def get_live_history_game_ids():
    """Get set of game IDs that have live history data."""
    history_dir = CACHE_DIR / 'live_history'
    if not history_dir.exists():
        return set()
    game_ids = set()
    for f in history_dir.glob('game_*.json'):
        # Extract game ID from filename like "game_18447310.json"
        game_id = f.stem.replace('game_', '')
        game_ids.add(game_id)
    return game_ids


@app.route('/')
def index():
    # Load all data from cache
    career_cache = load_cache('jokic_career.json')
    standings_cache = load_cache('standings.json')
    records_cache = load_cache('alltime_records.json')
    triple_doubles_cache = load_cache('triple_doubles.json')
    schedule_cache = load_cache('nuggets_schedule.json')
    injuries_cache = load_cache('injuries.json')

    # Check if cache exists
    if not career_cache:
        return """
        <h1>Cache not found!</h1>
        <p>Run <code>python refresh_cache.py</code> to generate the cache.</p>
        """, 500

    # Extract career data
    regular_season = career_cache.get('regular_season', [])
    career_totals = career_cache.get('career_totals', [{}])[0]
    playoffs = career_cache.get('playoffs', [])
    playoff_totals = career_cache.get('playoff_totals', [{}])[0]
    season_rankings = career_cache.get('season_rankings', [])

    # Extract standings
    east_standings = standings_cache.get('east', []) if standings_cache else []
    west_standings = standings_cache.get('west', []) if standings_cache else []

    # Extract all-time records (sorted by rank in numerical order)
    records_watch = records_cache.get('records', []) if records_cache else []
    records_watch = sorted(records_watch, key=lambda x: x.get('rank', 999))

    # Extract triple-doubles
    triple_doubles = None
    if triple_doubles_cache:
        players = triple_doubles_cache.get('players', [])
        jokic_data = triple_doubles_cache.get('jokic', {})
        triple_doubles = {
            'total': jokic_data.get('total', 0),
            'rank': jokic_data.get('rank', 0),
            'season_breakdown': jokic_data.get('season_breakdown', []),
            'current_season': jokic_data.get('recent_games', []),
            'all_time_leaders': players[:10],
            'to_next': jokic_data.get('to_next', 0),
            'next_player': jokic_data.get('next_player'),
            'to_record': jokic_data.get('to_record', 0),
            'updated_at': triple_doubles_cache.get('_cached_at', 'Unknown'),
        }

    # Extract schedule - filter out past games from upcoming
    all_games = schedule_cache.get('games', []) if schedule_cache else []
    upcoming_games = [g for g in all_games if not g.get('is_past')]
    calendar_games = schedule_cache.get('calendar_games', []) if schedule_cache else []

    # Load special events for games
    special_events_data = load_data('special_events.json')
    special_events = special_events_data.get('events', {}) if special_events_data else {}

    # Load jersey schedule
    jersey_data = load_data('jersey_schedule.json')
    jersey_schedule = jersey_data.get('schedule', {}) if jersey_data else {}

    # Extract injuries and sort by return date
    injuries = injuries_cache.get('injuries', []) if injuries_cache else []
    injuries = sorted(injuries, key=lambda x: parse_return_date(x.get('return_date', '')))
    injuries_updated = injuries_cache.get('_content_changed_at') if injuries_cache else None

    # Get cache timestamp for display
    cache_time = career_cache.get('_cached_at', 'Unknown')

    # Current date for calendar highlighting (Mountain Time)
    mountain_tz = ZoneInfo('America/Denver')
    now_date = datetime.now(mountain_tz).strftime('%Y-%m-%d')

    # Get game IDs with live history data
    live_history_ids = get_live_history_game_ids()

    return render_template('index.html',
        regular_season=regular_season,
        career_totals=career_totals,
        playoffs=playoffs,
        playoff_totals=playoff_totals,
        season_rankings=season_rankings,
        east_standings=east_standings,
        west_standings=west_standings,
        records_watch=records_watch,
        triple_doubles=triple_doubles,
        upcoming_games=upcoming_games,
        calendar_games=calendar_games,
        special_events=special_events,
        jersey_schedule=jersey_schedule,
        injuries=injuries,
        injuries_updated=injuries_updated,
        now_date=now_date,
        live_history_ids=live_history_ids,
        cache_time=cache_time
    )


@app.route('/jokic')
def jokic():
    """Dedicated Jokić stats page."""
    career_cache = load_cache('jokic_career.json')
    records_cache = load_cache('alltime_records.json')
    triple_doubles_cache = load_cache('triple_doubles.json')
    leaders_cache = load_cache('league_leaders.json')
    jokic_live_cache = load_cache('jokic_live.json')

    if not career_cache:
        return """
        <h1>Cache not found!</h1>
        <p>Run <code>python refresh_cache.py</code> to generate the cache.</p>
        """, 500

    career_totals = career_cache.get('career_totals', [{}])[0]

    # Get Jokic's current season per-game ranks from league leaders
    jokic_ranks = leaders_cache.get('jokic_ranks', {}) if leaders_cache else {}

    # Extract all-time records
    records_watch = records_cache.get('records', []) if records_cache else []
    records_watch = sorted(records_watch, key=lambda x: x.get('rank', 999))

    # Extract triple-doubles
    triple_doubles = None
    if triple_doubles_cache:
        players = triple_doubles_cache.get('players', [])
        jokic_data = triple_doubles_cache.get('jokic', {})
        triple_doubles = {
            'total': jokic_data.get('total', 0),
            'rank': jokic_data.get('rank', 0),
            'season_breakdown': jokic_data.get('season_breakdown', []),
            'current_season': jokic_data.get('recent_games', []),
            'all_time_leaders': players[:10],
            'to_next': jokic_data.get('to_next', 0),
            'next_player': jokic_data.get('next_player'),
            'to_record': jokic_data.get('to_record', 0),
            'updated_at': triple_doubles_cache.get('_cached_at', 'Unknown'),
        }

    cache_time = career_cache.get('_cached_at', 'Unknown')

    # Get current season stats
    jokic_stats = jokic_live_cache.get('stats', {}) if jokic_live_cache else {}

    return render_template('jokic.html',
        career_totals=career_totals,
        jokic_ranks=jokic_ranks,
        records_watch=records_watch,
        triple_doubles=triple_doubles,
        jokic_stats=jokic_stats,
        cache_time=cache_time
    )


@app.route('/leaders/<stat>')
def leaders(stat):
    """Show league leaders for a specific stat (from cache)"""
    stat = stat.upper()
    if stat not in STAT_NAMES:
        return "Invalid stat category", 404

    # Load from cache
    leaders_cache = load_cache('league_leaders.json')

    if not leaders_cache:
        return """
        <h1>Cache not found!</h1>
        <p>Run <code>python refresh_cache.py</code> to generate the cache.</p>
        """, 500

    all_leaders = leaders_cache.get('leaders', {})
    top_players = all_leaders.get(stat, [])

    if not top_players:
        return f"No data for {stat}", 404

    return render_template('leaders.html',
        stat=stat,
        stat_name=STAT_NAMES[stat],
        players=top_players,
        jokic_id=JOKIC_PLAYER_ID,
        cache_time=leaders_cache.get('_cached_at', 'Unknown')
    )


@app.route('/more')
def more():
    """Additional stats and info page."""
    roster_cache = load_cache('roster.json')
    games_cache = load_cache('recent_games.json')
    jokic_cache = load_cache('jokic_live.json')
    injuries_cache = load_cache('injuries.json')
    contracts_cache = load_cache('contracts.json')
    salary_cap_cache = load_cache('salary_cap.json')

    roster = roster_cache.get('roster', []) if roster_cache else []
    recent_games = games_cache.get('games', []) if games_cache else []
    jokic_stats = jokic_cache.get('stats', {}) if jokic_cache else {}
    injuries = injuries_cache.get('injuries', []) if injuries_cache else []
    contracts = contracts_cache.get('contracts', []) if contracts_cache else []
    salary_cap = salary_cap_cache if salary_cap_cache else {}

    # Mark injured players in roster and add contract info
    injured_names = {inj['name'] for inj in injuries}
    contract_lookup = {c['name']: c for c in contracts}
    for player in roster:
        player['is_injured'] = player['name'] in injured_names
        # Add contract expiration info
        contract = contract_lookup.get(player['name'])
        if contract:
            player['contract_end'] = contract.get('effective_end_year') or contract.get('end_year')
            player['has_extension'] = contract.get('has_extension', False)
            player['free_agent_year'] = contract.get('effective_fa_year') or contract.get('free_agent_year')
            player['free_agent_status'] = contract.get('effective_fa_status') or contract.get('free_agent_status', 'UFA')

    cache_time = roster_cache.get('_cached_at', 'Unknown') if roster_cache else 'Unknown'

    # Current year for contract status display
    current_year = datetime.now().year

    # Get game IDs with live history data
    live_history_ids = get_live_history_game_ids()

    return render_template('more.html',
        roster=roster,
        recent_games=recent_games,
        jokic_stats=jokic_stats,
        injuries=injuries,
        contracts=contracts,
        salary_cap=salary_cap,
        current_year=current_year,
        cache_time=cache_time,
        live_history_ids=live_history_ids
    )


@app.route('/live')
def live():
    """Live game tracking page with win probability from betting odds."""
    return render_template('live.html')


# Cache for live data (refreshes every 20 seconds)
_live_cache = {'data': None, 'timestamp': None}
LIVE_CACHE_TTL = 20  # seconds


def get_cached_live_data():
    """Return cached live data if fresh, otherwise None."""
    if _live_cache['data'] and _live_cache['timestamp']:
        age = (datetime.now() - _live_cache['timestamp']).total_seconds()
        if age < LIVE_CACHE_TTL:
            return _live_cache['data']
    return None


def set_live_cache(data):
    """Store data in live cache."""
    _live_cache['data'] = data
    _live_cache['timestamp'] = datetime.now()


@app.route('/api/live')
def api_live():
    """API endpoint for live game data - polls BALLDONTLIE for current odds and score."""
    # Check cache first for fast response
    cached = get_cached_live_data()
    if cached:
        return jsonify(cached)

    api_key = os.getenv('BALLDONTLIE_API_KEY')
    if not api_key:
        return jsonify({'error': 'API key not configured'}), 500

    NUGGETS_ID = 8
    mountain_tz = ZoneInfo('America/Denver')
    now = datetime.now(mountain_tz)
    today = now.strftime('%Y-%m-%d')

    try:
        # Get today's Nuggets game
        games_resp = requests.get(
            'https://api.balldontlie.io/v1/games',
            params={'team_ids[]': NUGGETS_ID, 'dates[]': today, 'per_page': 10},
            headers={'Authorization': api_key},
            timeout=15
        )
        games_resp.raise_for_status()
        games = games_resp.json().get('data', [])

        if not games:
            return jsonify({'error': 'No Nuggets game today', 'date': today})

        game = games[0]
        game_id = game.get('id')
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
            # Update schedule cache with final score
            update_schedule_with_final_score(
                today,
                home_team.get('full_name'),
                away_team.get('full_name'),
                home_score,
                away_score,
                is_nuggets_home,
                game_id  # Pass BALLDONTLIE game ID for history linking
            )
            # Update recent games cache
            update_recent_games_with_final(
                today,
                opponent_team.get('full_name'),
                opponent_team.get('abbreviation'),
                is_nuggets_home,
                nuggets_score,
                opponent_score,
                game_id
            )
        elif home_score > 0 or away_score > 0:
            game_state = 'live'
        else:
            game_state = 'pregame'

        # Get period/time info
        period = game.get('period', 0)
        time_remaining = game.get('time', '')

        # Fetch live odds from BALLDONTLIE v2
        odds_resp = requests.get(
            'https://api.balldontlie.io/v2/odds',
            params={'dates[]': today, 'per_page': 100},
            headers={'Authorization': api_key},
            timeout=15
        )
        odds_resp.raise_for_status()
        all_odds = odds_resp.json().get('data', [])

        # Filter for this game
        game_odds = [o for o in all_odds if o.get('game_id') == game_id]

        # Process odds by vendor
        vendors = []
        for o in game_odds:
            if o.get('moneyline_home_odds') is None:
                continue

            vendor = o.get('vendor', 'unknown')
            home_ml = o.get('moneyline_home_odds')
            away_ml = o.get('moneyline_away_odds')

            # Convert to Nuggets perspective
            nuggets_ml = home_ml if is_nuggets_home else away_ml
            opponent_ml = away_ml if is_nuggets_home else home_ml

            # Convert moneyline to implied probability
            def ml_to_prob(ml):
                if ml is None:
                    return None
                if ml < 0:
                    return abs(ml) / (abs(ml) + 100)
                else:
                    return 100 / (ml + 100)

            nuggets_prob = ml_to_prob(nuggets_ml)

            vendors.append({
                'name': vendor,
                'nuggets_ml': nuggets_ml,
                'opponent_ml': opponent_ml,
                'nuggets_prob': round(nuggets_prob * 100, 1) if nuggets_prob else None,
                'spread': o.get('spread_home_value') if is_nuggets_home else o.get('spread_away_value'),
                'total': o.get('total_value'),
                'updated_at': o.get('updated_at'),
            })

        # Calculate consensus probability (average of all vendors)
        probs = [v['nuggets_prob'] for v in vendors if v['nuggets_prob'] is not None]
        consensus_prob = round(sum(probs) / len(probs), 1) if probs else None

        # Sort vendors by name for consistent display
        vendors.sort(key=lambda x: x['name'])

        # Build response data
        response_data = {
            'game_id': game_id,
            'game_state': game_state,
            'status': status,
            'period': period,
            'time_remaining': time_remaining,
            'nuggets': {
                'name': nuggets_team.get('full_name', 'Denver Nuggets'),
                'abbrev': nuggets_team.get('abbreviation', 'DEN'),
                'score': nuggets_score,
                'is_home': is_nuggets_home,
            },
            'opponent': {
                'name': opponent_team.get('full_name', ''),
                'abbrev': opponent_team.get('abbreviation', ''),
                'score': opponent_score,
            },
            'odds': {
                'vendors': vendors,
                'consensus_prob': consensus_prob,
                'vendor_count': len(vendors),
            },
            'timestamp': now.isoformat(),
        }

        # Cache for fast subsequent requests
        set_live_cache(response_data)

        return jsonify(response_data)

    except requests.RequestException as e:
        return jsonify({'error': f'API request failed: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500


# Live history storage
LIVE_HISTORY_DIR = CACHE_DIR / 'live_history'


def ensure_live_history_dir():
    LIVE_HISTORY_DIR.mkdir(exist_ok=True)


def load_live_history(game_id):
    """Load history for a specific game."""
    ensure_live_history_dir()
    history_file = LIVE_HISTORY_DIR / f'game_{game_id}.json'
    if history_file.exists():
        with open(history_file, 'r') as f:
            return json.load(f)
    return None


def save_live_history(game_id, data):
    """Save history for a specific game."""
    ensure_live_history_dir()
    history_file = LIVE_HISTORY_DIR / f'game_{game_id}.json'
    with open(history_file, 'w') as f:
        json.dump(data, f, indent=2)


@app.route('/api/live/snapshot', methods=['POST'])
def api_live_snapshot():
    """Save a probability snapshot for a game."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        game_id = data.get('game_id')
        if not game_id:
            return jsonify({'error': 'No game_id provided'}), 400

        # Load existing history or create new
        history = load_live_history(game_id)
        if not history:
            history = {
                'game_id': game_id,
                'snapshots': [],
                'game_info': {
                    'nuggets_name': data.get('nuggets_name', 'Denver Nuggets'),
                    'opponent_name': data.get('opponent_name', ''),
                    'is_nuggets_home': data.get('is_nuggets_home', False),
                    'date': data.get('date', ''),
                },
                'created_at': datetime.now().isoformat(),
            }

        # Add new snapshot
        snapshot = {
            'timestamp': data.get('timestamp'),
            'game_state': data.get('game_state'),
            'period': data.get('period'),
            'time_remaining': data.get('time_remaining'),
            'nuggets_score': data.get('nuggets_score'),
            'opponent_score': data.get('opponent_score'),
            'consensus_prob': data.get('consensus_prob'),
            'vendor_count': data.get('vendor_count'),
        }

        # Only add if different from last snapshot (avoid duplicates)
        if not history['snapshots'] or history['snapshots'][-1].get('consensus_prob') != snapshot['consensus_prob']:
            history['snapshots'].append(snapshot)

        # Update final state info
        history['final_state'] = data.get('game_state')
        history['final_score'] = {
            'nuggets': data.get('nuggets_score'),
            'opponent': data.get('opponent_score'),
        }
        history['updated_at'] = datetime.now().isoformat()

        save_live_history(game_id, history)

        return jsonify({'success': True, 'snapshot_count': len(history['snapshots'])})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/live/history')
def api_live_history_list():
    """List all saved game histories."""
    ensure_live_history_dir()
    histories = []
    for f in LIVE_HISTORY_DIR.glob('game_*.json'):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                histories.append({
                    'game_id': data.get('game_id'),
                    'date': data.get('game_info', {}).get('date'),
                    'opponent': data.get('game_info', {}).get('opponent_name'),
                    'final_state': data.get('final_state'),
                    'final_score': data.get('final_score'),
                    'snapshot_count': len(data.get('snapshots', [])),
                })
        except Exception:
            continue
    # Sort by date descending
    histories.sort(key=lambda x: x.get('date', ''), reverse=True)
    return jsonify({'histories': histories})


@app.route('/api/live/history/<game_id>')
def api_live_history_game(game_id):
    """Get history data for a specific game as JSON."""
    history = load_live_history(game_id)
    if not history:
        return jsonify({'error': 'Game history not found'}), 404
    return jsonify(history)


@app.route('/live/<game_id>')
def live_history(game_id):
    """View historical live data for a specific game."""
    history = load_live_history(game_id)
    if not history:
        return "Game history not found", 404
    return render_template('live_history.html', history=history)


# ========== DEV LIVE CHAT FEED ==========
# Track last seen action for incremental updates
_dev_live_last_action = {'action_number': 0}

# Track viewers per game (game_id -> {client_id: last_seen_timestamp})
_dev_live_viewers = {}
VIEWER_TIMEOUT = 15  # seconds before a viewer is considered gone

# Track lead changes per game
_dev_live_lead_changes = {}  # game_id -> {'count': N, 'last_leader': 'TEAM'}

# Track largest leads per game
_dev_live_largest_leads = {}  # game_id -> {'home': N, 'away': N}

# Bot personality definitions
BOT_PERSONALITIES = {
    'play_by_play': {
        'name': 'PlayByPlay',
        'emoji': '🏀',
        'color': '#ffffff',
        'triggers': ['2pt', '3pt', 'freethrow', 'block', 'steal'],
    },
    'stats_nerd': {
        'name': 'StatsNerd',
        'emoji': '📊',
        'color': '#22d3ee',  # cyan
        'triggers': ['milestone', 'streak', 'stat'],
    },
    'odds_shark': {
        'name': 'OddsShark',
        'emoji': '🎰',
        'color': '#34d399',  # green
        'triggers': ['odds', 'spread', 'probability'],
    },
    'hype_man': {
        'name': 'HypeMan',
        'emoji': '🔥',
        'color': '#f97316',  # orange
        'triggers': ['dunk', 'and1', 'buzzer', 'run'],
    },
    'historian': {
        'name': 'Historian',
        'emoji': '📜',
        'color': '#a855f7',  # purple
        'triggers': ['record', 'history', 'first'],
    },
    'ai_commentator': {
        'name': 'AI',
        'emoji': '🤖',
        'color': '#60a5fa',  # blue
        'triggers': ['llm', 'ai'],
    },
}


def generate_chat_message(action, game_info, prev_action=None, largest_leads=None):
    """Convert a play-by-play action into a chat message with personality."""
    action_type = action.get('actionType', '')
    sub_type = action.get('subType', '')
    desc = action.get('description', '')
    player = action.get('playerNameI', '')
    team = action.get('teamTricode', '')
    score_home = action.get('scoreHome', '0')
    score_away = action.get('scoreAway', '0')
    period = action.get('period', 1)
    clock = action.get('clock', '')

    # Get previous scores for lead change detection
    prev_home = int(prev_action.get('scoreHome', '0') or 0) if prev_action else 0
    prev_away = int(prev_action.get('scoreAway', '0') or 0) if prev_action else 0
    curr_home = int(score_home or 0)
    curr_away = int(score_away or 0)

    # Track largest leads
    if largest_leads is None:
        largest_leads = {'home': 0, 'away': 0}

    # Parse clock (format: PT04M23.50S)
    clock_display = ''
    if clock and clock.startswith('PT'):
        try:
            import re
            match = re.match(r'PT(\d+)M([\d.]+)S', clock)
            if match:
                mins, secs = match.groups()
                clock_display = f"{mins}:{float(secs):05.2f}"[:5]
        except:
            pass

    home_team = game_info.get('home_team', 'HOME')
    away_team = game_info.get('away_team', 'AWAY')

    messages = []

    # Scoring plays - PlayByPlay bot
    if action_type in ['2pt', '3pt'] and 'MISS' not in desc:
        pts = '3' if action_type == '3pt' else '2'
        shot_type = sub_type or 'shot'

        msg = f"💥 {player} ({team}) hits the {shot_type.lower()}! {pts} points."
        messages.append({
            'bot': 'play_by_play',
            'text': msg,
            'type': 'score',
            'team': team,
        })

        # HypeMan for dunks and highlight plays
        if 'dunk' in shot_type.lower() or 'alley' in desc.lower():
            messages.append({
                'bot': 'hype_man',
                'text': f"🔥🔥🔥 POSTER! {player} throws it DOWN!",
                'type': 'hype',
                'team': team,
            })

    # Made free throws
    elif action_type == 'freethrow' and 'MISS' not in desc:
        msg = f"✓ {player} ({team}) makes the free throw."
        messages.append({
            'bot': 'play_by_play',
            'text': msg,
            'type': 'freethrow',
            'team': team,
        })

    # Blocks - exciting defensive play
    elif action_type == 'block':
        messages.append({
            'bot': 'play_by_play',
            'text': f"🚫 {player} ({team}) with the REJECTION!",
            'type': 'block',
            'team': team,
        })

    # Steals
    elif action_type == 'steal':
        messages.append({
            'bot': 'play_by_play',
            'text': f"👋 {player} ({team}) picks the pocket! Steal!",
            'type': 'steal',
            'team': team,
        })

    # Turnovers - when important
    elif action_type == 'turnover':
        if 'steal' not in desc.lower():  # Don't duplicate with steal
            messages.append({
                'bot': 'play_by_play',
                'text': f"💨 Turnover by {player} ({team})",
                'type': 'turnover',
                'team': team,
            })

    # Period start/end
    elif action_type == 'period':
        if sub_type == 'end':
            messages.append({
                'bot': 'play_by_play',
                'text': f"⏱️ End of Q{period}. Score: {away_team} {score_away} - {home_team} {score_home}",
                'type': 'period',
            })
            # StatsNerd quarter summary
            lead = int(score_home) - int(score_away)
            leader = home_team if lead > 0 else away_team
            messages.append({
                'bot': 'stats_nerd',
                'text': f"📊 Quarter {period} complete. {leader} leads by {abs(lead)}.",
                'type': 'summary',
            })
        elif sub_type == 'start':
            messages.append({
                'bot': 'play_by_play',
                'text': f"🏀 Quarter {period} is underway!",
                'type': 'period',
            })

    # Detect lead changes (only on scoring plays)
    if action_type in ['2pt', '3pt', 'freethrow'] and 'MISS' not in desc:
        # Determine previous and current leaders
        prev_diff = prev_away - prev_home  # positive = away leading
        curr_diff = curr_away - curr_home

        # Lead change: one team was ahead, now the other is
        if prev_diff > 0 and curr_diff < 0:
            # Away was leading, now home leads
            messages.append({
                'bot': 'hype_man',
                'text': f"🔄 LEAD CHANGE! {home_team} takes the lead!",
                'type': 'lead_change',
                'team': home_team,
                'is_lead_change': True,
            })
        elif prev_diff < 0 and curr_diff > 0:
            # Home was leading, now away leads
            messages.append({
                'bot': 'hype_man',
                'text': f"🔄 LEAD CHANGE! {away_team} takes the lead!",
                'type': 'lead_change',
                'team': away_team,
                'is_lead_change': True,
            })
        # Tie game detection
        elif curr_diff == 0 and prev_diff != 0:
            messages.append({
                'bot': 'hype_man',
                'text': f"⚖️ TIE GAME! {curr_away}-{curr_home}",
                'type': 'tie',
            })

        # Largest lead detection
        home_lead = curr_home - curr_away
        away_lead = curr_away - curr_home

        if home_lead > 0 and home_lead > largest_leads.get('home', 0):
            # New largest lead for home team
            if home_lead >= 5:  # Only announce if lead is 5+
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
            # New largest lead for away team
            if away_lead >= 5:  # Only announce if lead is 5+
                messages.append({
                    'bot': 'stats_nerd',
                    'text': f"📈 {away_team} extends to their LARGEST LEAD of the game: +{away_lead}!",
                    'type': 'largest_lead',
                    'team': away_team,
                    'is_largest_lead': True,
                    'lead_amount': away_lead,
                })
            largest_leads['away'] = away_lead

    # Add score context and timestamp to all messages
    for msg in messages:
        msg['score'] = f"{away_team} {score_away} - {home_team} {score_home}"
        msg['clock'] = clock_display
        msg['period'] = period
        msg['timestamp'] = datetime.now().isoformat()
        msg['action_number'] = action.get('actionNumber', 0)

    return messages


@app.route('/dev-live')
def dev_live():
    """Development live chat feed page."""
    return render_template('dev_live.html')


@app.route('/api/dev-live/games')
def api_dev_live_games():
    """Get current live NBA games."""
    try:
        from nba_api.live.nba.endpoints import scoreboard
        sb = scoreboard.ScoreBoard()
        games_data = sb.get_dict()['scoreboard']['games']

        games = []
        for g in games_data:
            games.append({
                'game_id': g['gameId'],
                'home_team': g['homeTeam']['teamTricode'],
                'away_team': g['awayTeam']['teamTricode'],
                'home_team_name': g['homeTeam']['teamName'],
                'away_team_name': g['awayTeam']['teamName'],
                'status': g['gameStatusText'],
                'home_score': g['homeTeam'].get('score', 0),
                'away_score': g['awayTeam'].get('score', 0),
            })

        return jsonify({'games': games})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dev-live/feed/<game_id>')
def api_dev_live_feed(game_id):
    """Get live chat feed for a specific game."""
    try:
        from nba_api.live.nba.endpoints import playbyplay, scoreboard
        import uuid

        # Get last seen action number and client ID from query params
        last_action = int(request.args.get('last_action', 0))
        client_id = request.args.get('client_id', str(uuid.uuid4()))

        # Track viewer heartbeat
        now = datetime.now()
        if game_id not in _dev_live_viewers:
            _dev_live_viewers[game_id] = {}
        _dev_live_viewers[game_id][client_id] = now

        # Clean up stale viewers
        cutoff = now - timedelta(seconds=VIEWER_TIMEOUT)
        _dev_live_viewers[game_id] = {
            cid: ts for cid, ts in _dev_live_viewers[game_id].items()
            if ts > cutoff
        }
        viewer_count = len(_dev_live_viewers[game_id])

        # Get game info from scoreboard (play-by-play doesn't include team names)
        sb = scoreboard.ScoreBoard()
        games_data = sb.get_dict()['scoreboard']['games']
        game_match = next((g for g in games_data if g['gameId'] == game_id), None)

        home_team = 'HOME'
        away_team = 'AWAY'
        if game_match:
            home_team = game_match['homeTeam']['teamTricode']
            away_team = game_match['awayTeam']['teamTricode']

        # Get play-by-play
        pbp = playbyplay.PlayByPlay(game_id)
        data = pbp.get_dict()

        game = data.get('game', {})
        actions = game.get('actions', [])

        game_info = {
            'home_team': home_team,
            'away_team': away_team,
            'game_id': game_id,
        }

        # Initialize lead change tracking for this game
        if game_id not in _dev_live_lead_changes:
            _dev_live_lead_changes[game_id] = {'count': 0, 'last_leader': None}

        # Initialize largest lead tracking for this game
        if game_id not in _dev_live_largest_leads:
            _dev_live_largest_leads[game_id] = {'home': 0, 'away': 0}

        # Filter to new actions only
        new_actions = [a for a in actions if a.get('actionNumber', 0) > last_action]

        # Generate chat messages with lead change detection
        all_messages = []
        lead_changes_in_batch = 0

        # Get the action just before the new ones for lead change detection
        prev_action = None
        if last_action > 0:
            prev_actions = [a for a in actions if a.get('actionNumber', 0) == last_action]
            if prev_actions:
                prev_action = prev_actions[0]

        # Calculate largest leads from history if this is a fresh load
        if last_action == 0 and len(actions) > 0:
            for a in actions:
                h = int(a.get('scoreHome', 0) or 0)
                aw = int(a.get('scoreAway', 0) or 0)
                if h > aw:
                    _dev_live_largest_leads[game_id]['home'] = max(_dev_live_largest_leads[game_id]['home'], h - aw)
                elif aw > h:
                    _dev_live_largest_leads[game_id]['away'] = max(_dev_live_largest_leads[game_id]['away'], aw - h)

        for i, action in enumerate(new_actions):
            # Use previous action for comparison (either from before batch or previous in batch)
            compare_action = prev_action if i == 0 else new_actions[i - 1]
            messages = generate_chat_message(action, game_info, compare_action, _dev_live_largest_leads[game_id])

            # Count lead changes
            for msg in messages:
                if msg.get('is_lead_change'):
                    lead_changes_in_batch += 1
                    _dev_live_lead_changes[game_id]['count'] += 1

            # Try to add LLM commentary for exciting events
            if LLM_AVAILABLE:
                for msg in messages:
                    # Only enhance lead changes, largest leads, dunks, ties, quarter summaries
                    if msg.get('is_lead_change') or msg.get('is_largest_lead') or \
                       msg.get('type') == 'tie' or \
                       (msg.get('type') == 'hype' and 'POSTER' in msg.get('text', '')) or \
                       (msg.get('type') == 'summary' and 'Quarter' in msg.get('text', '')):
                        try:
                            llm_text = enhance_message_with_llm(msg, game_info)
                            if llm_text:
                                ai_msg = {
                                    'bot': 'ai_commentator',
                                    'text': llm_text,
                                    'type': 'ai_commentary',
                                    'score': msg.get('score'),
                                    'clock': msg.get('clock'),
                                    'period': msg.get('period'),
                                    'timestamp': datetime.now().isoformat(),
                                    'action_number': msg.get('action_number'),
                                }
                                messages.append(ai_msg)
                        except Exception as e:
                            print(f"LLM enhancement error: {e}")

            all_messages.extend(messages)

        # Count total lead changes from all actions if this is a fresh load
        if last_action == 0 and len(actions) > 1:
            lead_change_count = 0
            for i in range(1, len(actions)):
                prev = actions[i - 1]
                curr = actions[i]
                prev_home = int(prev.get('scoreHome', 0) or 0)
                prev_away = int(prev.get('scoreAway', 0) or 0)
                curr_home = int(curr.get('scoreHome', 0) or 0)
                curr_away = int(curr.get('scoreAway', 0) or 0)
                prev_diff = prev_away - prev_home
                curr_diff = curr_away - curr_home
                # Lead change: sign changed and neither is zero (tie doesn't count as lead)
                if (prev_diff > 0 and curr_diff < 0) or (prev_diff < 0 and curr_diff > 0):
                    lead_change_count += 1
            _dev_live_lead_changes[game_id]['count'] = lead_change_count

        # Get current score from latest action
        latest_score = {'home': 0, 'away': 0}
        if actions:
            last = actions[-1]
            latest_score['home'] = int(last.get('scoreHome', 0) or 0)
            latest_score['away'] = int(last.get('scoreAway', 0) or 0)

        # Get the highest action number we've seen
        max_action = max([a.get('actionNumber', 0) for a in actions]) if actions else 0

        return jsonify({
            'messages': all_messages,
            'last_action': max_action,
            'game_info': game_info,
            'score': latest_score,
            'total_actions': len(actions),
            'viewer_count': viewer_count,
            'client_id': client_id,
            'lead_changes': _dev_live_lead_changes[game_id]['count'],
        })

    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5001)
