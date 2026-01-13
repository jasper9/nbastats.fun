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
from concurrent.futures import ThreadPoolExecutor, as_completed

# LLM commentary for exciting events (optional)
try:
    from llm_commentary import (
        enhance_message_with_llm,
        get_cached_or_generate,
        refine_message_with_persona,
        should_refine_message
    )
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    def refine_message_with_persona(bot, gist, ctx=None):
        return gist
    def should_refine_message(msg_type):
        return False

# BallDontLie API for live game data (play-by-play, stats)
try:
    import balldontlie_live as bdl
    BDL_AVAILABLE = True
except ImportError:
    BDL_AVAILABLE = False

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

# NBA uses Eastern time for scheduling
EASTERN_TZ = ZoneInfo('America/New_York')


def get_nba_game_date():
    """Get the current date in Eastern time (what NBA uses for game scheduling)."""
    return datetime.now(EASTERN_TZ).strftime('%Y-%m-%d')


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

# History storage for dev-live feed (persists chat messages and score progression)
_dev_live_history = {}  # game_id -> {'messages': [], 'scores': [], 'game_info': {}, 'status': ''}
DEV_LIVE_HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache', 'dev_live_history')

# Odds cache for dev-live games
_dev_live_odds_cache = {}  # game_id -> {'odds': [], 'consensus': {}, 'updated_at': timestamp}
DEV_LIVE_ODDS_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache', 'dev_live_odds.json')
DEV_LIVE_ODDS_CACHE_TTL = 60  # seconds before refreshing odds

# Probability history per game (for charts)
_dev_live_prob_history = {}  # game_id -> [{'home_prob': N, 'away_prob': N, 'home_score': N, 'away_score': N, 'action': N}]

# Player stats tracking per game for milestone detection
# game_id -> player_name -> {'pts': N, 'reb': N, 'ast': N, 'blk': N, 'stl': N, 'team': 'XXX'}
_dev_live_player_stats = {}

# Track which milestones have already been announced per game
# game_id -> set of milestone keys like "LeBron_triple_double", "Curry_30pts"
_dev_live_announced_milestones = {}

# Player season averages cache (player_name -> {'ppg': N, 'rpg': N, 'apg': N, 'bpg': N, 'spg': N})
_player_season_averages = {}
PLAYER_AVERAGES_CACHE_TTL = 3600  # 1 hour cache for season averages


def get_player_season_averages(player_name, team_abbrev=None):
    """
    Get player season averages from BallDontLie API.
    Falls back to hardcoded star player averages if API fails.
    """
    global _player_season_averages

    if player_name in _player_season_averages:
        cached = _player_season_averages[player_name]
        if (datetime.now() - cached.get('cached_at', datetime.min)).total_seconds() < PLAYER_AVERAGES_CACHE_TTL:
            return cached

    # Hardcoded fallback averages for star players (2024-25 season estimates)
    star_averages = {
        'LeBron James': {'ppg': 25.5, 'rpg': 7.5, 'apg': 8.0, 'bpg': 0.5, 'spg': 1.0},
        'Nikola Jokic': {'ppg': 27.0, 'rpg': 12.5, 'apg': 9.5, 'bpg': 0.7, 'spg': 1.3},
        'Luka Doncic': {'ppg': 34.0, 'rpg': 9.0, 'apg': 9.5, 'bpg': 0.5, 'spg': 1.5},
        'Giannis Antetokounmpo': {'ppg': 31.0, 'rpg': 12.0, 'apg': 6.0, 'bpg': 1.0, 'spg': 1.0},
        'Stephen Curry': {'ppg': 23.0, 'rpg': 4.5, 'apg': 5.0, 'bpg': 0.2, 'spg': 0.8},
        'Kevin Durant': {'ppg': 27.0, 'rpg': 6.5, 'apg': 5.0, 'bpg': 1.2, 'spg': 0.8},
        'Jayson Tatum': {'ppg': 27.0, 'rpg': 8.5, 'apg': 5.0, 'bpg': 0.6, 'spg': 1.0},
        'Shai Gilgeous-Alexander': {'ppg': 31.0, 'rpg': 5.5, 'apg': 6.0, 'bpg': 1.0, 'spg': 2.0},
        'Anthony Edwards': {'ppg': 26.0, 'rpg': 5.5, 'apg': 5.0, 'bpg': 0.6, 'spg': 1.3},
        'Joel Embiid': {'ppg': 27.0, 'rpg': 11.0, 'apg': 4.5, 'bpg': 1.7, 'spg': 1.0},
        'Trae Young': {'ppg': 25.0, 'rpg': 3.0, 'apg': 11.0, 'bpg': 0.1, 'spg': 1.0},
        'Ja Morant': {'ppg': 21.0, 'rpg': 5.0, 'apg': 8.0, 'bpg': 0.3, 'spg': 1.0},
        'Tyrese Haliburton': {'ppg': 18.0, 'rpg': 4.0, 'apg': 9.0, 'bpg': 0.5, 'spg': 1.2},
        'Damian Lillard': {'ppg': 25.0, 'rpg': 4.5, 'apg': 7.0, 'bpg': 0.3, 'spg': 1.0},
        'Anthony Davis': {'ppg': 24.0, 'rpg': 12.5, 'apg': 3.5, 'bpg': 2.3, 'spg': 1.2},
        'Domantas Sabonis': {'ppg': 19.0, 'rpg': 14.0, 'apg': 8.0, 'bpg': 0.5, 'spg': 1.0},
        'Victor Wembanyama': {'ppg': 22.0, 'rpg': 10.5, 'apg': 3.5, 'bpg': 3.5, 'spg': 1.0},
        'Karl-Anthony Towns': {'ppg': 25.0, 'rpg': 11.0, 'apg': 3.0, 'bpg': 0.7, 'spg': 0.7},
        'Chet Holmgren': {'ppg': 16.0, 'rpg': 8.0, 'apg': 2.5, 'bpg': 2.5, 'spg': 1.0},
        'Jamal Murray': {'ppg': 21.0, 'rpg': 4.0, 'apg': 6.5, 'bpg': 0.3, 'spg': 1.0},
        'Michael Porter Jr.': {'ppg': 15.0, 'rpg': 7.0, 'apg': 1.5, 'bpg': 0.5, 'spg': 0.8},
        'Russell Westbrook': {'ppg': 11.0, 'rpg': 5.0, 'apg': 4.5, 'bpg': 0.2, 'spg': 0.9},
    }

    # Check for partial name matches
    for known_name, avgs in star_averages.items():
        if player_name in known_name or known_name in player_name:
            result = avgs.copy()
            result['cached_at'] = datetime.now()
            _player_season_averages[player_name] = result
            return result

    # Default averages for unknown players
    default = {'ppg': 10.0, 'rpg': 4.0, 'apg': 2.5, 'bpg': 0.5, 'spg': 0.7, 'cached_at': datetime.now()}
    _player_season_averages[player_name] = default
    return default


def track_player_stats_from_play(game_id, play):
    """
    Track cumulative player stats from a play for milestone detection.
    Updates _dev_live_player_stats with running totals.
    """
    global _dev_live_player_stats

    if game_id not in _dev_live_player_stats:
        _dev_live_player_stats[game_id] = {}

    text = play.get('text', '')
    play_type = play.get('type', '').lower()
    team_obj = play.get('team') or {}
    team = team_obj.get('abbreviation', '')
    is_scoring = play.get('scoring_play', False)
    score_value = play.get('score_value', 0) or 0

    # Extract player name
    from balldontlie_live import extract_player_from_text
    player = extract_player_from_text(text)

    if not player:
        return None

    # Initialize player stats if needed
    if player not in _dev_live_player_stats[game_id]:
        _dev_live_player_stats[game_id][player] = {
            'pts': 0, 'reb': 0, 'ast': 0, 'blk': 0, 'stl': 0, 'team': team
        }

    stats = _dev_live_player_stats[game_id][player]
    stats['team'] = team or stats['team']

    # Update stats based on play type
    if is_scoring:
        stats['pts'] += score_value

    if 'rebound' in play_type:
        stats['reb'] += 1

    if 'assist' in text.lower() or 'ast' in play_type:
        # Look for assisted by pattern
        import re
        assist_match = re.search(r'(?:assist|assisted)\s+by\s+([A-Z][a-z\']+(?:\s+[A-Z][a-z\']+)+)', text, re.IGNORECASE)
        if assist_match:
            assister = assist_match.group(1).strip()
            if assister not in _dev_live_player_stats[game_id]:
                _dev_live_player_stats[game_id][assister] = {
                    'pts': 0, 'reb': 0, 'ast': 0, 'blk': 0, 'stl': 0, 'team': team
                }
            _dev_live_player_stats[game_id][assister]['ast'] += 1

    if 'block' in play_type:
        stats['blk'] += 1

    if 'steal' in play_type:
        stats['stl'] += 1

    return player


def check_stat_milestones(game_id, player, game_info):
    """
    Check if a player has hit any stat milestones.
    Returns list of milestone messages to add.
    """
    global _dev_live_announced_milestones

    if game_id not in _dev_live_player_stats:
        return []

    if player not in _dev_live_player_stats[game_id]:
        return []

    if game_id not in _dev_live_announced_milestones:
        _dev_live_announced_milestones[game_id] = set()

    stats = _dev_live_player_stats[game_id][player]
    announced = _dev_live_announced_milestones[game_id]
    messages = []

    pts = stats.get('pts', 0)
    reb = stats.get('reb', 0)
    ast = stats.get('ast', 0)
    blk = stats.get('blk', 0)
    stl = stats.get('stl', 0)
    team = stats.get('team', '')

    # Get player averages for context
    avgs = get_player_season_averages(player, team)

    # Check triple-double (10+ in 3 categories)
    categories_10 = sum([1 for v in [pts, reb, ast] if v >= 10])
    if categories_10 >= 3:
        milestone_key = f"{player}_triple_double"
        if milestone_key not in announced:
            announced.add(milestone_key)
            season_avg = f"{avgs.get('ppg', 0):.1f}/{avgs.get('rpg', 0):.1f}/{avgs.get('apg', 0):.1f}"
            msg = generate_historian_milestone_message(
                'triple_double', player, team,
                {'pts': pts, 'reb': reb, 'ast': ast, 'season_avg': season_avg},
                game_info
            )
            if msg:
                messages.append(msg)

    # Check double-double (10+ in 2 categories)
    categories_10_dd = sum([1 for v in [pts, reb, ast, blk, stl] if v >= 10])
    if categories_10_dd >= 2 and categories_10 < 3:  # Not if it's a triple-double
        milestone_key = f"{player}_double_double"
        if milestone_key not in announced:
            announced.add(milestone_key)
            # Find the two highest categories
            stat_pairs = [('pts', pts), ('reb', reb), ('ast', ast), ('blk', blk), ('stl', stl)]
            stat_pairs.sort(key=lambda x: x[1], reverse=True)
            stat1_name, stat1_val = stat_pairs[0]
            stat2_name, stat2_val = stat_pairs[1]
            season_avg = f"{avgs.get('ppg', 0):.1f}/{avgs.get('rpg', 0):.1f}/{avgs.get('apg', 0):.1f}"
            msg = generate_historian_milestone_message(
                'double_double', player, team,
                {'stat1_name': stat1_name.upper(), 'stat1_val': stat1_val,
                 'stat2_name': stat2_name.upper(), 'stat2_val': stat2_val,
                 'season_avg': season_avg},
                game_info
            )
            if msg:
                messages.append(msg)

    # Check scoring milestones: 30+, 40+, 50+, 60+
    for threshold in [30, 40, 50, 60]:
        if pts >= threshold:
            milestone_key = f"{player}_{threshold}pts"
            if milestone_key not in announced:
                announced.add(milestone_key)
                ppg = avgs.get('ppg', 0)
                pts_above_avg = pts - ppg if ppg > 0 else pts
                msg = generate_historian_milestone_message(
                    'scoring_milestone', player, team,
                    {'pts': pts, 'milestone': threshold, 'ppg': ppg, 'pts_above_avg': round(pts_above_avg, 1)},
                    game_info
                )
                if msg:
                    messages.append(msg)
                break  # Only announce highest threshold

    # Check blocks milestones: 5+, 10+, 15+, 20+
    for threshold in [5, 10, 15, 20]:
        if blk >= threshold:
            milestone_key = f"{player}_{threshold}blk"
            if milestone_key not in announced:
                announced.add(milestone_key)
                msg = generate_historian_milestone_message(
                    'blocks_milestone', player, team,
                    {'blocks': blk, 'milestone': threshold, 'bpg': avgs.get('bpg', 0)},
                    game_info
                )
                if msg:
                    messages.append(msg)
                break  # Only announce highest threshold

    # Check steals milestones: 5+, 10+, 15+, 20+
    for threshold in [5, 10, 15, 20]:
        if stl >= threshold:
            milestone_key = f"{player}_{threshold}stl"
            if milestone_key not in announced:
                announced.add(milestone_key)
                msg = generate_historian_milestone_message(
                    'steals_milestone', player, team,
                    {'steals': stl, 'milestone': threshold, 'spg': avgs.get('spg', 0)},
                    game_info
                )
                if msg:
                    messages.append(msg)
                break  # Only announce highest threshold

    return messages


def check_big_lead_milestone(game_id, home_score, away_score, home_team, away_team, period, game_info):
    """
    Check for big lead milestones (20+, 25+, 30+).
    Returns a milestone message if threshold crossed.
    """
    global _dev_live_announced_milestones

    if game_id not in _dev_live_announced_milestones:
        _dev_live_announced_milestones[game_id] = set()

    announced = _dev_live_announced_milestones[game_id]
    lead_diff = abs(home_score - away_score)

    if lead_diff < 20:
        return None

    leader = home_team if home_score > away_score else away_team
    opponent = away_team if home_score > away_score else home_team

    # Check thresholds in descending order
    for threshold in [30, 25, 20]:
        if lead_diff >= threshold:
            milestone_key = f"{leader}_{threshold}lead_Q{period}"
            if milestone_key not in announced:
                announced.add(milestone_key)
                msg = generate_historian_milestone_message(
                    'big_lead', leader, opponent,
                    {'lead_amount': lead_diff, 'period': period},
                    game_info
                )
                return msg
            break

    return None


def generate_historian_milestone_message(milestone_type, player, team, context, game_info):
    """
    Generate a Historian bot message for a stat milestone using LLM.
    """
    try:
        from llm_commentary import generate_llm_commentary, COMMENTARY_PROMPTS

        # Build LLM context
        llm_context = {
            'player': player,
            'team': team,
            **context
        }

        # Generate LLM commentary
        llm_text = generate_llm_commentary(milestone_type, llm_context)

        if llm_text:
            return {
                'bot': 'historian',
                'text': llm_text,
                'type': 'milestone',
                'team': team if milestone_type != 'big_lead' else context.get('team', ''),
                'timestamp': datetime.now().isoformat(),
            }
        else:
            # Fallback messages without LLM
            fallback_messages = {
                'triple_double': f"📜 {player} records a triple-double with {context.get('pts', 0)} pts, {context.get('reb', 0)} reb, {context.get('ast', 0)} ast!",
                'double_double': f"📜 {player} has a double-double: {context.get('stat1_val', 0)} {context.get('stat1_name', 'PTS')}, {context.get('stat2_val', 0)} {context.get('stat2_name', 'REB')}",
                'scoring_milestone': f"📜 {player} hits {context.get('pts', 0)} points! ({context.get('milestone', 30)}+ game)",
                'blocks_milestone': f"📜 {player} with {context.get('blocks', 0)} blocks tonight! Defensive showcase.",
                'steals_milestone': f"📜 {player} has {context.get('steals', 0)} steals! Picking pockets all night.",
                'big_lead': f"📜 {player} leads by {context.get('lead_amount', 20)} - historically, teams hold this lead ~95% of the time.",
            }
            fallback = fallback_messages.get(milestone_type, f"📜 {player} hits a milestone!")
            return {
                'bot': 'historian',
                'text': fallback,
                'type': 'milestone',
                'team': team if milestone_type != 'big_lead' else '',
                'timestamp': datetime.now().isoformat(),
            }

    except Exception as e:
        print(f"Historian milestone error: {e}")
        return None


def ml_to_prob(ml):
    """Convert moneyline odds to implied probability."""
    if ml is None:
        return None
    try:
        ml = float(ml)
        if ml > 0:
            return 100 / (ml + 100)
        else:
            return abs(ml) / (abs(ml) + 100)
    except (ValueError, ZeroDivisionError):
        return None


def prob_to_ml(prob):
    """Convert implied probability (0-1) to American moneyline odds."""
    if prob is None or prob <= 0 or prob >= 1:
        return None
    try:
        if prob >= 0.5:
            # Favorite: negative moneyline
            return round(-100 * prob / (1 - prob))
        else:
            # Underdog: positive moneyline
            return round(100 * (1 - prob) / prob)
    except (ValueError, ZeroDivisionError):
        return None


def parse_nba_minutes(min_str):
    """Parse NBA API minutes format 'PT14M11.00S' to 'MM:SS' or 'MM' string."""
    if not min_str:
        return '-'
    try:
        # Format: PT{minutes}M{seconds}.00S
        import re
        match = re.match(r'PT(\d+)M([\d.]+)S', min_str)
        if match:
            mins = int(match.group(1))
            secs = int(float(match.group(2)))
            if secs > 0:
                return f"{mins:02d}:{secs:02d}"
            return f"{mins:02d}"
        return '-'
    except Exception:
        return '-'


def get_player_stats_from_nba_boxscore(bs_data, home_team_tricode):
    """
    Extract player stats from NBA API boxscore data.
    Returns dict with 'home' and 'away' lists of player stats.
    This provides more complete data than BallDontLie API.
    """
    result = {'home': [], 'away': []}

    game_data = bs_data.get('game', {})
    home_team = game_data.get('homeTeam', {})
    away_team = game_data.get('awayTeam', {})

    # Process home team
    for player in home_team.get('players', []):
        stats = player.get('statistics', {})
        player_stat = {
            'name': player.get('name', ''),
            'team': home_team.get('teamTricode', ''),
            'min': parse_nba_minutes(stats.get('minutes', '')),
            'pts': stats.get('points', 0),
            'reb': stats.get('reboundsTotal', 0),
            'ast': stats.get('assists', 0),
            'stl': stats.get('steals', 0),
            'blk': stats.get('blocks', 0),
            'fgm': stats.get('fieldGoalsMade', 0),
            'fga': stats.get('fieldGoalsAttempted', 0),
            'fg3m': stats.get('threePointersMade', 0),
            'fg3a': stats.get('threePointersAttempted', 0),
            'ftm': stats.get('freeThrowsMade', 0),
            'fta': stats.get('freeThrowsAttempted', 0),
            'oreb': stats.get('reboundsOffensive', 0),
            'dreb': stats.get('reboundsDefensive', 0),
            'tov': stats.get('turnovers', 0),
            'pf': stats.get('foulsPersonal', 0),
            'plus_minus': stats.get('plusMinusPoints', 0),
            'starter': player.get('starter') == '1' or player.get('starter') == 1,
            'oncourt': player.get('oncourt') == '1' or player.get('oncourt') == 1,
        }
        result['home'].append(player_stat)

    # Process away team
    for player in away_team.get('players', []):
        stats = player.get('statistics', {})
        player_stat = {
            'name': player.get('name', ''),
            'team': away_team.get('teamTricode', ''),
            'min': parse_nba_minutes(stats.get('minutes', '')),
            'pts': stats.get('points', 0),
            'reb': stats.get('reboundsTotal', 0),
            'ast': stats.get('assists', 0),
            'stl': stats.get('steals', 0),
            'blk': stats.get('blocks', 0),
            'fgm': stats.get('fieldGoalsMade', 0),
            'fga': stats.get('fieldGoalsAttempted', 0),
            'fg3m': stats.get('threePointersMade', 0),
            'fg3a': stats.get('threePointersAttempted', 0),
            'ftm': stats.get('freeThrowsMade', 0),
            'fta': stats.get('freeThrowsAttempted', 0),
            'oreb': stats.get('reboundsOffensive', 0),
            'dreb': stats.get('reboundsDefensive', 0),
            'tov': stats.get('turnovers', 0),
            'pf': stats.get('foulsPersonal', 0),
            'plus_minus': stats.get('plusMinusPoints', 0),
            'starter': player.get('starter') == '1' or player.get('starter') == 1,
            'oncourt': player.get('oncourt') == '1' or player.get('oncourt') == 1,
        }
        result['away'].append(player_stat)

    # Sort by points descending within each team
    result['home'].sort(key=lambda x: x['pts'], reverse=True)
    result['away'].sort(key=lambda x: x['pts'], reverse=True)

    return result


def clock_to_elapsed_seconds(clock_str, period):
    """
    Convert game clock (MM:SS remaining) and period to elapsed seconds.
    Q1 12:00 → 0, Q1 0:00 → 720, Q2 12:00 → 720, Q4 0:00 → 2880
    """
    if not clock_str or not period:
        return 0
    try:
        parts = clock_str.split(':')
        if len(parts) == 2:
            mins = int(parts[0])
            secs = int(float(parts[1]))  # Handle "12:00.0" format
        else:
            return (period - 1) * 720  # Default to start of period

        # Time remaining in current quarter
        remaining = mins * 60 + secs
        # Elapsed in current quarter (12 min = 720 sec per quarter)
        quarter_elapsed = 720 - remaining
        # Total elapsed including previous quarters
        total_elapsed = (period - 1) * 720 + quarter_elapsed
        return total_elapsed
    except (ValueError, IndexError):
        return (period - 1) * 720


# Cache for odds data (saves ~1-2 seconds per page load)
_odds_cache = {'data': None, 'date': None, 'updated_at': None}
ODDS_CACHE_TTL = 60  # 60 seconds - odds don't change that often


def fetch_dev_live_odds(game_ids, game_date=None):
    """Fetch odds for multiple games from balldontlie API.
    Returns dict with both game_id and team-pair keys for flexible matching.
    Results are cached for 60 seconds."""
    global _odds_cache

    api_key = os.getenv('BALLDONTLIE_API_KEY')
    if not api_key:
        return {}

    if not game_date:
        game_date = get_nba_game_date()

    # Check cache first
    now = datetime.now()
    if (_odds_cache['data'] is not None and
        _odds_cache['date'] == game_date and
        _odds_cache['updated_at'] and
        (now - _odds_cache['updated_at']).total_seconds() < ODDS_CACHE_TTL):
        return _odds_cache['data']

    try:
        response = requests.get(
            'https://api.balldontlie.io/v2/odds',
            params={'dates[]': game_date, 'per_page': 100},
            headers={'Authorization': api_key},
            timeout=15
        )
        response.raise_for_status()
        all_odds = response.json().get('data', [])

        # Group by game_id
        odds_by_game = {}
        for o in all_odds:
            gid = str(o.get('game_id'))
            if gid not in odds_by_game:
                odds_by_game[gid] = []
            odds_by_game[gid].append(o)

        # Get game details to map to teams (for cross-API matching)
        game_teams = {}
        if odds_by_game:
            try:
                games_resp = requests.get(
                    'https://api.balldontlie.io/v1/games',
                    params={'dates[]': game_date, 'per_page': 100},
                    headers={'Authorization': api_key},
                    timeout=15
                )
                games_resp.raise_for_status()
                for game in games_resp.json().get('data', []):
                    gid = str(game.get('id'))
                    game_teams[gid] = {
                        'home': game.get('home_team', {}).get('abbreviation', ''),
                        'away': game.get('visitor_team', {}).get('abbreviation', ''),
                    }
            except Exception:
                pass

        # Calculate consensus for each game
        result = {}
        for gid, odds_list in odds_by_game.items():
            home_probs = []
            away_probs = []
            vendors = []
            spreads = []
            totals = []
            home_mls = []
            away_mls = []

            for o in odds_list:
                home_ml = o.get('moneyline_home_odds')
                away_ml = o.get('moneyline_away_odds')

                if home_ml is None:
                    continue

                home_prob = ml_to_prob(home_ml)
                away_prob = ml_to_prob(away_ml)

                if home_prob:
                    home_probs.append(home_prob * 100)
                    away_probs.append((away_prob or (1 - home_prob)) * 100)
                    home_mls.append(float(home_ml))
                    away_mls.append(float(away_ml))
                    vendors.append({
                        'name': o.get('vendor', 'Unknown'),
                        'home_ml': home_ml,
                        'away_ml': away_ml,
                        'home_prob': round(home_prob * 100, 1),
                        'spread_home': o.get('spread_home_value'),
                        'total': o.get('total_value'),
                    })
                    if o.get('spread_home_value') is not None:
                        spreads.append(float(o.get('spread_home_value')))
                    if o.get('total_value') is not None:
                        totals.append(float(o.get('total_value')))

            if home_probs:
                # Calculate average probabilities
                avg_home_prob = sum(home_probs) / len(home_probs)
                avg_away_prob = sum(away_probs) / len(away_probs)

                # Convert average probabilities to moneylines (more meaningful than averaging raw MLs)
                consensus_home_ml = prob_to_ml(avg_home_prob / 100)  # prob_to_ml expects 0-1
                consensus_away_ml = prob_to_ml(avg_away_prob / 100)

                odds_data = {
                    'vendors': vendors,
                    'consensus': {
                        'home_prob': round(avg_home_prob, 1),
                        'away_prob': round(avg_away_prob, 1),
                        'vendor_count': len(vendors),
                        'spread': round(sum(spreads) / len(spreads), 1) if spreads else None,
                        'total': round(sum(totals) / len(totals), 1) if totals else None,
                        'home_ml': consensus_home_ml,
                        'away_ml': consensus_away_ml,
                    },
                    'updated_at': datetime.now().isoformat(),
                }

                # Store by balldontlie game_id
                result[gid] = odds_data

                # Also store by team pair for cross-API matching
                teams = game_teams.get(gid)
                if teams:
                    team_key = f"{teams['away']}@{teams['home']}"
                    result[team_key] = odds_data

        # Update cache
        _odds_cache['data'] = result
        _odds_cache['date'] = game_date
        _odds_cache['updated_at'] = now

        return result

    except Exception as e:
        print(f"Error fetching dev-live odds: {e}")
        return {}


def get_cached_odds(game_id, game_date=None):
    """Get odds from cache or fetch fresh."""
    global _dev_live_odds_cache

    now = datetime.now()

    # Check memory cache first
    if game_id in _dev_live_odds_cache:
        cached = _dev_live_odds_cache[game_id]
        cache_time = datetime.fromisoformat(cached.get('updated_at', '2000-01-01'))
        if (now - cache_time).total_seconds() < DEV_LIVE_ODDS_CACHE_TTL:
            return cached

    # Check file cache
    if os.path.exists(DEV_LIVE_ODDS_CACHE_FILE):
        try:
            with open(DEV_LIVE_ODDS_CACHE_FILE, 'r') as f:
                file_cache = json.load(f)
                if game_id in file_cache:
                    cached = file_cache[game_id]
                    cache_time = datetime.fromisoformat(cached.get('updated_at', '2000-01-01'))
                    if (now - cache_time).total_seconds() < DEV_LIVE_ODDS_CACHE_TTL:
                        _dev_live_odds_cache[game_id] = cached
                        return cached
        except Exception:
            pass

    # Fetch fresh odds for all games on this date (more efficient than per-game)
    fresh_odds = fetch_dev_live_odds([game_id], game_date)

    if fresh_odds:
        # Load existing file cache to preserve pre_game_odds
        existing = {}
        try:
            if os.path.exists(DEV_LIVE_ODDS_CACHE_FILE):
                with open(DEV_LIVE_ODDS_CACHE_FILE, 'r') as f:
                    existing = json.load(f)
        except Exception:
            pass

        # For each game, preserve pre_game_odds if it exists
        for gid, odds_data in fresh_odds.items():
            # If pre_game_odds already saved, preserve it
            if gid in existing and 'pre_game_odds' in existing[gid]:
                odds_data['pre_game_odds'] = existing[gid]['pre_game_odds']
            else:
                # First time seeing this game - capture pre_game_odds
                odds_data['pre_game_odds'] = {
                    'consensus': odds_data.get('consensus', {}),
                    'captured_at': datetime.now().isoformat()
                }

        # Update memory cache
        _dev_live_odds_cache.update(fresh_odds)

        # Save to file
        try:
            os.makedirs(os.path.dirname(DEV_LIVE_ODDS_CACHE_FILE), exist_ok=True)
            existing.update(fresh_odds)
            with open(DEV_LIVE_ODDS_CACHE_FILE, 'w') as f:
                json.dump(existing, f)
        except Exception as e:
            print(f"Error saving odds cache: {e}")

    return _dev_live_odds_cache.get(game_id)


def save_prob_snapshot(game_id, home_prob, away_prob, home_score, away_score, action_num):
    """Save probability snapshot for chart history."""
    global _dev_live_prob_history

    if game_id not in _dev_live_prob_history:
        _dev_live_prob_history[game_id] = []

    _dev_live_prob_history[game_id].append({
        'home_prob': home_prob,
        'away_prob': away_prob,
        'home_score': home_score,
        'away_score': away_score,
        'action': action_num,
        'timestamp': datetime.now().isoformat(),
    })

def save_dev_live_history(game_id):
    """Save game history to JSON file."""
    if game_id not in _dev_live_history:
        return

    os.makedirs(DEV_LIVE_HISTORY_DIR, exist_ok=True)
    filepath = os.path.join(DEV_LIVE_HISTORY_DIR, f'game_{game_id}.json')

    # Atomic write
    temp_path = filepath + '.tmp'
    try:
        with open(temp_path, 'w') as f:
            json.dump(_dev_live_history[game_id], f)
        os.rename(temp_path, filepath)
    except Exception as e:
        print(f"Error saving dev-live history: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)

def load_dev_live_history(game_id):
    """Load game history from JSON file if it exists."""
    filepath = os.path.join(DEV_LIVE_HISTORY_DIR, f'game_{game_id}.json')
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading dev-live history: {e}")
    return None

# Team ID mapping for balldontlie API
TEAM_IDS = {
    'ATL': 1, 'BOS': 2, 'BKN': 3, 'CHA': 4, 'CHI': 5, 'CLE': 6, 'DAL': 7, 'DEN': 8,
    'DET': 9, 'GSW': 10, 'HOU': 11, 'IND': 12, 'LAC': 13, 'LAL': 14, 'MEM': 15, 'MIA': 16,
    'MIL': 17, 'MIN': 18, 'NOP': 19, 'NYK': 20, 'OKC': 21, 'ORL': 22, 'PHI': 23, 'PHX': 24,
    'POR': 25, 'SAC': 26, 'SAS': 27, 'TOR': 28, 'UTA': 29, 'WAS': 30,
}

# Star players by team - used for pre-game previews
TEAM_STARS = {
    'ATL': ['Trae Young', 'Dejounte Murray'],
    'BOS': ['Jayson Tatum', 'Jaylen Brown', 'Derrick White'],
    'BKN': ['Mikal Bridges', 'Cameron Johnson'],
    'CHA': ['LaMelo Ball', 'Brandon Miller'],
    'CHI': ['Zach LaVine', 'DeMar DeRozan', 'Coby White'],
    'CLE': ['Donovan Mitchell', 'Darius Garland', 'Evan Mobley', 'Jarrett Allen'],
    'DAL': ['Luka Dončić', 'Kyrie Irving'],
    'DEN': ['Nikola Jokić', 'Jamal Murray', 'Michael Porter Jr.', 'Aaron Gordon'],
    'DET': ['Cade Cunningham', 'Jaden Ivey'],
    'GSW': ['Stephen Curry', 'Draymond Green', 'Jonathan Kuminga'],
    'HOU': ['Jalen Green', 'Alperen Şengün', 'Jabari Smith Jr.'],
    'IND': ['Tyrese Haliburton', 'Pascal Siakam', 'Myles Turner'],
    'LAC': ['Kawhi Leonard', 'Paul George', 'James Harden'],
    'LAL': ['LeBron James', 'Anthony Davis', 'Austin Reaves'],
    'MEM': ['Ja Morant', 'Desmond Bane', 'Jaren Jackson Jr.'],
    'MIA': ['Jimmy Butler', 'Bam Adebayo', 'Tyler Herro'],
    'MIL': ['Giannis Antetokounmpo', 'Damian Lillard', 'Khris Middleton'],
    'MIN': ['Anthony Edwards', 'Karl-Anthony Towns', 'Rudy Gobert'],
    'NOP': ['Zion Williamson', 'Brandon Ingram', 'CJ McCollum'],
    'NYK': ['Jalen Brunson', 'Julius Randle', 'OG Anunoby'],
    'OKC': ['Shai Gilgeous-Alexander', 'Chet Holmgren', 'Jalen Williams'],
    'ORL': ['Paolo Banchero', 'Franz Wagner', 'Jalen Suggs'],
    'PHI': ['Joel Embiid', 'Tyrese Maxey'],
    'PHX': ['Kevin Durant', 'Devin Booker', 'Bradley Beal'],
    'POR': ['Anfernee Simons', 'Scoot Henderson', 'Jerami Grant'],
    'SAC': ['De\'Aaron Fox', 'Domantas Sabonis', 'Keegan Murray'],
    'SAS': ['Victor Wembanyama', 'Devin Vassell'],
    'TOR': ['Scottie Barnes', 'RJ Barrett', 'Immanuel Quickley'],
    'UTA': ['Lauri Markkanen', 'Collin Sexton', 'Walker Kessler'],
    'WAS': ['Kyle Kuzma', 'Jordan Poole', 'Tyus Jones'],
}

# Notable NBA rivalries with brief descriptions
TEAM_RIVALRIES = {
    # Classic rivalries
    ('BOS', 'LAL'): "The NBA's greatest rivalry - 12 Finals meetings, 22 championships combined",
    ('LAL', 'BOS'): "The NBA's greatest rivalry - 12 Finals meetings, 22 championships combined",
    ('NYK', 'BKN'): "Battle of New York - city bragging rights on the line",
    ('BKN', 'NYK'): "Battle of New York - city bragging rights on the line",
    ('LAL', 'LAC'): "Battle of LA - Staples Center roommates turned rivals",
    ('LAC', 'LAL'): "Battle of LA - Staples Center roommates turned rivals",
    ('CHI', 'DET'): "Bad Boys era rivalry - physical, intense basketball",
    ('DET', 'CHI'): "Bad Boys era rivalry - physical, intense basketball",
    ('MIA', 'BOS'): "Eastern Conference foes with playoff history",
    ('BOS', 'MIA'): "Eastern Conference foes with playoff history",
    ('GSW', 'CLE'): "Four straight Finals meetings (2015-2018)",
    ('CLE', 'GSW'): "Four straight Finals meetings (2015-2018)",
    ('PHX', 'SAS'): "2000s playoff battles - Nash vs Duncan era",
    ('SAS', 'PHX'): "2000s playoff battles - Nash vs Duncan era",
    ('DEN', 'LAL'): "Western Conference rivals with playoff history",
    ('LAL', 'DEN'): "Western Conference rivals with playoff history",
    ('DEN', 'MIN'): "Northwest Division rivals - young star showdown",
    ('MIN', 'DEN'): "Northwest Division rivals - young star showdown",
    ('PHI', 'BOS'): "Historic Atlantic Division rivalry",
    ('BOS', 'PHI'): "Historic Atlantic Division rivalry",
    ('DAL', 'HOU'): "Texas rivalry - Lone Star State bragging rights",
    ('HOU', 'DAL'): "Texas rivalry - Lone Star State bragging rights",
    ('DAL', 'SAS'): "Texas rivalry - decades of playoff battles",
    ('SAS', 'DAL'): "Texas rivalry - decades of playoff battles",
    ('OKC', 'GSW'): "Durant's departure added fuel to this rivalry",
    ('GSW', 'OKC'): "Durant's departure added fuel to this rivalry",
    ('MIL', 'DEN'): "Recent playoff foes - Jokic vs Giannis MVP showdown",
    ('DEN', 'MIL'): "Recent playoff foes - Jokic vs Giannis MVP showdown",
    ('MIL', 'MIA'): "Playoff rivals - Butler's bubble dominance still stings",
    ('MIA', 'MIL'): "Playoff rivals - Butler's bubble dominance still stings",
}

# Team abbreviation to full name mapping
TEAM_ABBREV_TO_CITY = {
    'ATL': 'Atlanta', 'BOS': 'Boston', 'BKN': 'Brooklyn', 'CHA': 'Charlotte',
    'CHI': 'Chicago', 'CLE': 'Cleveland', 'DAL': 'Dallas', 'DEN': 'Denver',
    'DET': 'Detroit', 'GSW': 'Golden State', 'HOU': 'Houston', 'IND': 'Indiana',
    'LAC': 'LA Clippers', 'LAL': 'LA Lakers', 'MEM': 'Memphis', 'MIA': 'Miami',
    'MIL': 'Milwaukee', 'MIN': 'Minnesota', 'NOP': 'New Orleans', 'NYK': 'New York',
    'OKC': 'Oklahoma City', 'ORL': 'Orlando', 'PHI': 'Philadelphia', 'PHX': 'Phoenix',
    'POR': 'Portland', 'SAC': 'Sacramento', 'SAS': 'San Antonio', 'TOR': 'Toronto',
    'UTA': 'Utah', 'WAS': 'Washington',
}


def get_team_standings_info(team_abbrev):
    """Get standings info for a team including record, streak, and rank."""
    standings_cache = load_cache('standings.json')
    if not standings_cache:
        return None

    # Search both conferences
    for conf in ['east', 'west']:
        for team in standings_cache.get(conf, []):
            # Match by city name (standings uses city, not abbrev)
            city = TEAM_ABBREV_TO_CITY.get(team_abbrev, '')
            if team.get('TeamCity', '').lower() == city.lower():
                return {
                    'wins': team.get('WINS', 0),
                    'losses': team.get('LOSSES', 0),
                    'win_pct': team.get('WinPCT', 0),
                    'streak': team.get('strCurrentStreak', ''),
                    'rank': team.get('PlayoffRank', 0),
                    'conference': conf.upper(),
                    'games_back': team.get('ConferenceGamesBack', 0),
                    'l10': team.get('L10', ''),
                }
    return None


def generate_standings_context(home_team, away_team):
    """Generate interesting standings context between two teams."""
    home_info = get_team_standings_info(home_team)
    away_info = get_team_standings_info(away_team)

    if not home_info or not away_info:
        return None

    messages = []

    # Same conference matchup - check standings battle
    if home_info['conference'] == away_info['conference']:
        rank_diff = abs(home_info['rank'] - away_info['rank'])

        if rank_diff <= 2:
            # Close in standings
            if home_info['rank'] < away_info['rank']:
                leader, trailer = home_team, away_team
                leader_rank, trailer_rank = home_info['rank'], away_info['rank']
            else:
                leader, trailer = away_team, home_team
                leader_rank, trailer_rank = away_info['rank'], home_info['rank']

            if leader_rank <= 6:
                messages.append(f"Standings battle! {leader} (#{leader_rank}) vs {trailer} (#{trailer_rank}) in the {home_info['conference']}")
            elif leader_rank <= 10:
                messages.append(f"Play-in implications! {leader} (#{leader_rank}) vs {trailer} (#{trailer_rank}) fighting for position")

    # Check if teams have similar records
    record_diff = abs(home_info['wins'] - away_info['wins'])
    if record_diff <= 3 and home_info['wins'] >= 15:
        home_record = f"{home_info['wins']}-{home_info['losses']}"
        away_record = f"{away_info['wins']}-{away_info['losses']}"
        if not messages:  # Only add if we don't have a standings message
            messages.append(f"Evenly matched! {home_team} ({home_record}) vs {away_team} ({away_record})")

    return messages[0] if messages else None


# Cache for team injuries (refreshes every 30 minutes)
_team_injuries_cache = {}  # team_abbrev -> {injuries: [], updated_at: datetime}
TEAM_INJURIES_CACHE_TTL = 1800  # 30 minutes

# Cache for team rosters (refreshes every hour)
_team_roster_cache = {}  # team_abbrev -> {players: set(), updated_at: datetime}
TEAM_ROSTER_CACHE_TTL = 3600  # 1 hour

# Cache for games list (short TTL for navigation speed)
_games_list_cache = {'data': None, 'updated_at': None}
GAMES_LIST_CACHE_TTL = 30  # 30 seconds - fresh enough for UI, fast for switching

# Cache for game info by ID (speeds up feed loading)
_game_info_cache = {}  # game_id -> {data: {}, updated_at: datetime}
GAME_INFO_CACHE_TTL = 15  # 15 seconds for live game freshness


def normalize_name(name):
    """Normalize player name for comparison (remove accents, lowercase)."""
    import unicodedata
    # Normalize unicode characters (remove accents)
    normalized = unicodedata.normalize('NFD', name)
    # Remove combining characters (accents)
    ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return ascii_name.lower().strip()


def fetch_team_roster(team_abbrev):
    """Fetch current ACTIVE roster for a team from balldontlie API."""
    global _team_roster_cache

    now = datetime.now()

    # Check cache first
    if team_abbrev in _team_roster_cache:
        cached = _team_roster_cache[team_abbrev]
        age = (now - cached['updated_at']).total_seconds()
        if age < TEAM_ROSTER_CACHE_TTL:
            return cached['players']

    api_key = os.getenv('BALLDONTLIE_API_KEY')
    if not api_key:
        return set()

    team_id = TEAM_IDS.get(team_abbrev)
    if not team_id:
        return set()

    try:
        # Use /players/active endpoint to get only current active players
        response = requests.get(
            'https://api.balldontlie.io/v1/players/active',
            params={'team_ids[]': team_id, 'per_page': 50},
            headers={'Authorization': api_key},
            timeout=15
        )
        response.raise_for_status()
        data = response.json()

        # Store both original and normalized names for matching
        players = {}  # normalized_name -> original_name
        for player in data.get('data', []):
            full_name = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
            if full_name:
                normalized = normalize_name(full_name)
                players[normalized] = full_name

        # Cache the result
        _team_roster_cache[team_abbrev] = {
            'players': players,
            'updated_at': now,
        }

        return players
    except Exception as e:
        print(f"Error fetching roster for {team_abbrev}: {e}")
        return {}


def get_verified_stars(team_abbrev):
    """Get star players that are verified to be on the current roster."""
    stars = TEAM_STARS.get(team_abbrev, [])
    if not stars:
        return []

    # Fetch current roster (returns dict of normalized_name -> original_name)
    roster = fetch_team_roster(team_abbrev)
    if not roster:
        # If we can't get roster, don't show any stars (fail safe)
        return []

    # Only return stars that are on the current roster
    # Use normalized name matching to handle accents
    verified = []
    roster_normalized = set(roster.keys())
    for star in stars:
        star_normalized = normalize_name(star)
        if star_normalized in roster_normalized:
            # Use the roster's version of the name (API-provided)
            verified.append(roster[star_normalized])

    return verified


def fetch_team_injuries(team_abbrev):
    """Fetch injuries for a specific team from balldontlie API."""
    global _team_injuries_cache

    now = datetime.now()

    # Check cache first
    if team_abbrev in _team_injuries_cache:
        cached = _team_injuries_cache[team_abbrev]
        age = (now - cached['updated_at']).total_seconds()
        if age < TEAM_INJURIES_CACHE_TTL:
            return cached['injuries']

    api_key = os.getenv('BALLDONTLIE_API_KEY')
    if not api_key:
        return []

    team_id = TEAM_IDS.get(team_abbrev)
    if not team_id:
        return []

    try:
        response = requests.get(
            'https://api.balldontlie.io/nba/v1/player_injuries',
            params={'team_ids[]': team_id},
            headers={'Authorization': api_key},
            timeout=15
        )
        response.raise_for_status()
        data = response.json()

        injuries = []
        for injury in data.get('data', []):
            player = injury.get('player', {})
            description = injury.get('description', '')

            # Try to extract injury type from description
            # Look for common patterns like "knee", "ankle", "hamstring", etc.
            injury_type = ''
            desc_lower = description.lower()
            # Common injury keywords to look for
            injury_keywords = [
                'knee', 'ankle', 'hamstring', 'calf', 'quad', 'hip', 'back',
                'shoulder', 'wrist', 'thumb', 'finger', 'toe', 'foot',
                'groin', 'concussion', 'illness', 'rest', 'load management',
                'achilles', 'elbow', 'neck', 'rib', 'abdominal', 'oblique'
            ]
            for keyword in injury_keywords:
                if keyword in desc_lower:
                    injury_type = keyword.title()
                    break

            injuries.append({
                'name': f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                'status': injury.get('status', 'Out'),
                'return_date': injury.get('return_date', ''),
                'injury_type': injury_type,
            })

        # Cache the result
        _team_injuries_cache[team_abbrev] = {
            'injuries': injuries,
            'updated_at': now,
        }

        return injuries

    except Exception as e:
        print(f"Error fetching injuries for {team_abbrev}: {e}")
        return []


def generate_countdown_message(time_until_game, home_team, away_team):
    """Generate a countdown message based on time until game starts.

    Args:
        time_until_game: Minutes until game start (can be negative if past start time)
        home_team: Home team abbreviation
        away_team: Away team abbreviation

    Returns:
        A message dict or None if no countdown message should be shown
    """
    pregame_score = f"{away_team} 0 - {home_team} 0"

    # Define countdown milestones (in minutes) with messages
    if time_until_game <= 0:
        # Game should be starting any moment
        return {
            'bot': 'hype_man',
            'text': "🚨 GAME TIME! Tipoff is imminent!",
            'type': 'countdown',
            'timestamp': datetime.now().isoformat(),
            'action_number': -80,
            'score': pregame_score,
        }
    elif time_until_game <= 1:
        return {
            'bot': 'hype_man',
            'text': "⏱️ Less than a minute until tipoff!",
            'type': 'countdown',
            'timestamp': datetime.now().isoformat(),
            'action_number': -81,
            'score': pregame_score,
        }
    elif time_until_game <= 2:
        return {
            'bot': 'play_by_play',
            'text': "⏱️ 2 minutes until tipoff. Players taking the court...",
            'type': 'countdown',
            'timestamp': datetime.now().isoformat(),
            'action_number': -82,
            'score': pregame_score,
        }
    elif time_until_game <= 5:
        return {
            'bot': 'hype_man',
            'text': "🔥 5 minutes until tipoff! Get ready!",
            'type': 'countdown',
            'timestamp': datetime.now().isoformat(),
            'action_number': -83,
            'score': pregame_score,
        }
    elif time_until_game <= 10:
        return {
            'bot': 'play_by_play',
            'text': "⏱️ 10 minutes until tipoff. Warm-ups wrapping up.",
            'type': 'countdown',
            'timestamp': datetime.now().isoformat(),
            'action_number': -84,
            'score': pregame_score,
        }
    elif time_until_game <= 15:
        return {
            'bot': 'play_by_play',
            'text': "⏱️ 15 minutes until tipoff. Teams finishing warm-ups.",
            'type': 'countdown',
            'timestamp': datetime.now().isoformat(),
            'action_number': -85,
            'score': pregame_score,
        }
    elif time_until_game <= 30:
        return {
            'bot': 'play_by_play',
            'text': "⏱️ 30 minutes until tipoff. Teams warming up on the court.",
            'type': 'countdown',
            'timestamp': datetime.now().isoformat(),
            'action_number': -86,
            'score': pregame_score,
        }
    elif time_until_game <= 60:
        return {
            'bot': 'play_by_play',
            'text': "⏱️ About an hour until tipoff.",
            'type': 'countdown',
            'timestamp': datetime.now().isoformat(),
            'action_number': -87,
            'score': pregame_score,
        }

    # No countdown message for games more than an hour away
    return None


def generate_pregame_preview(home_team, away_team, home_team_name='', away_team_name='', odds=None, show_hype=True):
    """Generate pre-game preview messages with injuries and star players.

    Args:
        show_hype: If True, include HypeMan messages. Set to False for games not starting soon.
    """
    messages = []

    # Fetch injuries and rosters in parallel to speed up pregame load
    # This reduces 4+ sequential API calls to 2 parallel batches
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit all fetch tasks
        futures = {
            executor.submit(fetch_team_injuries, home_team): 'home_injuries',
            executor.submit(fetch_team_injuries, away_team): 'away_injuries',
            executor.submit(get_verified_stars, home_team): 'home_stars',
            executor.submit(get_verified_stars, away_team): 'away_stars',
        }

        results = {}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                print(f"Error fetching {key}: {e}")
                results[key] = []

    home_injuries = results.get('home_injuries', [])
    away_injuries = results.get('away_injuries', [])
    home_stars = results.get('home_stars', [])
    away_stars = results.get('away_stars', [])

    # Filter out injured stars
    injured_names = set()
    for inj in home_injuries + away_injuries:
        injured_names.add(inj['name'])

    home_injured_stars = [s for s in home_stars if s in injured_names]
    away_injured_stars = [s for s in away_stars if s in injured_names]

    home_available_stars = [s for s in home_stars if s not in injured_names]
    away_available_stars = [s for s in away_stars if s not in injured_names]

    # Use full team names if available, otherwise use abbreviations
    home_display = home_team_name or home_team
    away_display = away_team_name or away_team

    # Common score text for pregame messages (shows 0-0)
    pregame_score = f"{away_team} 0 - {home_team} 0"

    # Generate welcome message
    messages.append({
        'bot': 'play_by_play',
        'text': f"🏀 Welcome to {away_display} @ {home_display}! The game is about to begin.",
        'type': 'pregame',
        'timestamp': datetime.now().isoformat(),
        'action_number': -100,
        'score': pregame_score,
    })

    # Get standings info for context
    home_standings = get_team_standings_info(home_team)
    away_standings = get_team_standings_info(away_team)

    # Generate team streaks and records message
    streak_parts = []
    if away_standings and away_standings.get('streak'):
        streak = away_standings['streak']
        record = f"{away_standings['wins']}-{away_standings['losses']}"
        streak_parts.append(f"{away_team} ({record}, {streak})")
    if home_standings and home_standings.get('streak'):
        streak = home_standings['streak']
        record = f"{home_standings['wins']}-{home_standings['losses']}"
        streak_parts.append(f"{home_team} ({record}, {streak})")

    if streak_parts:
        messages.append({
            'bot': 'stats_nerd',
            'text': f"📈 Current form: {' vs '.join(streak_parts)}",
            'type': 'pregame',
            'timestamp': datetime.now().isoformat(),
            'action_number': -99,
            'score': pregame_score,
        })

    # Check for rivalry
    rivalry_key = (away_team, home_team)
    rivalry_info = TEAM_RIVALRIES.get(rivalry_key)
    if rivalry_info:
        messages.append({
            'bot': 'historian',
            'text': f"📜 Rivalry alert! {rivalry_info}",
            'type': 'pregame',
            'timestamp': datetime.now().isoformat(),
            'action_number': -98,
            'score': pregame_score,
        })

    # Check for standings battle
    standings_context = generate_standings_context(home_team, away_team)
    if standings_context:
        messages.append({
            'bot': 'stats_nerd',
            'text': f"🏆 {standings_context}",
            'type': 'pregame',
            'timestamp': datetime.now().isoformat(),
            'action_number': -97,
            'score': pregame_score,
        })

    # Generate star players preview
    stars_text_parts = []
    if away_available_stars:
        stars_text_parts.append(f"{away_team}: {', '.join(away_available_stars[:2])}")
    if home_available_stars:
        stars_text_parts.append(f"{home_team}: {', '.join(home_available_stars[:2])}")

    if stars_text_parts:
        messages.append({
            'bot': 'stats_nerd',
            'text': f"⭐ Key players to watch: {' vs '.join(stars_text_parts)}",
            'type': 'pregame',
            'timestamp': datetime.now().isoformat(),
            'action_number': -96,
            'score': pregame_score,
        })

    # Generate injury report - group by status level with bullet points
    if away_injuries or home_injuries:
        # Group injuries by status level
        def format_injury_report(injuries, team_abbrev):
            """Format injuries grouped by status with bullet points."""
            # Group by status
            by_status = {}
            for inj in injuries:
                status = inj.get('status', 'Out')
                if status not in by_status:
                    by_status[status] = []
                # Format: "Player (Injury)" or just "Player" if no injury type
                injury_type = inj.get('injury_type', '')
                name = inj['name']
                if injury_type:
                    by_status[status].append(f"{name} ({injury_type})")
                else:
                    by_status[status].append(name)

            # Build formatted text with bullet points
            # Order: Out first, then Doubtful, Questionable, Day-To-Day, Probable
            status_order = ['Out', 'Doubtful', 'Questionable', 'Day-To-Day', 'Probable']
            lines = [f"📋 {team_abbrev} injury report:"]
            for status in status_order:
                if status in by_status:
                    players = ', '.join(by_status[status])
                    lines.append(f"• {status}: {players}")
            # Add any other statuses not in our order
            for status in by_status:
                if status not in status_order:
                    players = ', '.join(by_status[status])
                    lines.append(f"• {status}: {players}")

            return '\n'.join(lines)

        # Create separate messages for each team's injuries
        if away_injuries:
            messages.append({
                'bot': 'stats_nerd',
                'text': format_injury_report(away_injuries, away_team),
                'type': 'injury_report',
                'timestamp': datetime.now().isoformat(),
                'action_number': -98,
                'score': pregame_score,
            })

        if home_injuries:
            messages.append({
                'bot': 'stats_nerd',
                'text': format_injury_report(home_injuries, home_team),
                'type': 'injury_report',
                'timestamp': datetime.now().isoformat(),
                'action_number': -97,
                'score': pregame_score,
            })
    elif False:  # Keep structure but disable old fallback
        # No star injuries but some players out
        total_injuries = 0
        messages.append({
            'bot': 'stats_nerd',
            'text': f"📋 Injury report: {total_injuries} players listed as out/questionable between both teams.",
            'type': 'injury_report',
            'timestamp': datetime.now().isoformat(),
            'action_number': -98,
            'score': pregame_score,
        })
    else:
        messages.append({
            'bot': 'stats_nerd',
            'text': "📋 Both teams appear to be healthy - no major injuries reported!",
            'type': 'injury_report',
            'timestamp': datetime.now().isoformat(),
            'action_number': -98,
            'score': pregame_score,
        })

    # Add odds preview if available
    if odds and odds.get('consensus'):
        consensus = odds['consensus']
        spread = consensus.get('spread')
        total = consensus.get('total')
        home_prob = consensus.get('home_prob')
        away_prob = consensus.get('away_prob')

        odds_parts = []
        if spread is not None:
            spread_str = f"+{spread}" if spread > 0 else str(spread)
            odds_parts.append(f"{home_team} {spread_str}")
        if total is not None:
            odds_parts.append(f"O/U {total}")
        if home_prob and away_prob:
            if home_prob > away_prob:
                odds_parts.append(f"{home_team} {home_prob:.0f}% favorite")
            else:
                odds_parts.append(f"{away_team} {away_prob:.0f}% favorite")

        if odds_parts:
            messages.append({
                'bot': 'stats_nerd',
                'text': f"📊 Line: {' | '.join(odds_parts)} (consensus from {consensus.get('vendor_count', '?')} books)",
                'type': 'odds_preview',
                'timestamp': datetime.now().isoformat(),
                'action_number': -97,
                'score': pregame_score,
            })

    # Add hype message only if game is starting soon
    if show_hype:
        matchup_descriptions = []
        if 'Nikola Jokić' in (home_available_stars + away_available_stars):
            matchup_descriptions.append("the MVP in the building")
        if 'LeBron James' in (home_available_stars + away_available_stars):
            matchup_descriptions.append("the King is playing")
        if 'Stephen Curry' in (home_available_stars + away_available_stars):
            matchup_descriptions.append("Chef Curry cooking")
        if 'Giannis Antetokounmpo' in (home_available_stars + away_available_stars):
            matchup_descriptions.append("the Greek Freak unleashed")

        if matchup_descriptions:
            messages.append({
                'bot': 'hype_man',
                'text': f"🔥 Get ready! {matchup_descriptions[0].capitalize()}! Let's GO!",
                'type': 'hype',
                'timestamp': datetime.now().isoformat(),
                'action_number': -96,
                'score': pregame_score,
            })
        else:
            messages.append({
                'bot': 'hype_man',
                'text': "🔥 Let's get this game started! Time for some basketball!",
                'type': 'hype',
                'timestamp': datetime.now().isoformat(),
                'action_number': -96,
                'score': pregame_score,
            })

    return messages


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

# Track player stats per game for StatsNerd milestone detection
_player_game_stats = {}  # {game_id: {player_id: {name, team, pts, reb, ast, stl, blk, fgm, fga, ftm, fta, 3pm}}}


def reset_player_stats(game_id):
    """Reset player stats for a game (used when starting fresh tracking)."""
    _player_game_stats[game_id] = {}


def get_player_stats(game_id, player_id):
    """Get or initialize player stats for a game."""
    if game_id not in _player_game_stats:
        _player_game_stats[game_id] = {}
    if player_id not in _player_game_stats[game_id]:
        _player_game_stats[game_id][player_id] = {
            'name': '', 'team': '',
            'pts': 0, 'reb': 0, 'ast': 0, 'stl': 0, 'blk': 0,
            'fgm': 0, 'fga': 0, 'ftm': 0, 'fta': 0,
            '3pm': 0, '3pa': 0,  # 3-point made/attempted
            'oreb': 0, 'dreb': 0,  # Offensive/defensive rebounds
            'tov': 0, 'pf': 0,  # Turnovers, personal fouls
            'announced_dd': False, 'announced_td': False,
            'announced_pts_20': False, 'announced_pts_30': False, 'announced_pts_40': False,
        }
    return _player_game_stats[game_id][player_id]


def check_player_milestones(game_id, player_id, player_name, team):
    """Check if player hit any milestones and return StatsNerd messages."""
    stats = get_player_stats(game_id, player_id)
    messages = []

    pts, reb, ast, stl, blk = stats['pts'], stats['reb'], stats['ast'], stats['stl'], stats['blk']

    # Count categories with 10+
    double_cats = []
    if pts >= 10:
        double_cats.append(('points', pts))
    if reb >= 10:
        double_cats.append(('rebounds', reb))
    if ast >= 10:
        double_cats.append(('assists', ast))
    if stl >= 10:
        double_cats.append(('steals', stl))
    if blk >= 10:
        double_cats.append(('blocks', blk))

    # Triple-double detection
    if len(double_cats) >= 3 and not stats['announced_td']:
        cats_str = ', '.join(f"{c[1]} {c[0]}" for c in double_cats[:3])
        messages.append({
            'bot': 'stats_nerd',
            'text': f"🎯🎯🎯 TRIPLE-DOUBLE! {player_name} ({team}) has {cats_str}!",
            'type': 'triple_double',
            'team': team,
            'is_milestone': True,
        })
        # Historian provides context for triple-doubles
        messages.append({
            'bot': 'historian',
            'text': f"📜 Triple-doubles are special - only about 120-150 happen per NBA season. {player_name} joins elite company tonight!",
            'type': 'historical_context',
            'team': team,
        })
        stats['announced_td'] = True
        stats['announced_dd'] = True  # Don't also announce DD

    # Double-double detection
    elif len(double_cats) >= 2 and not stats['announced_dd']:
        cats_str = ' and '.join(f"{c[1]} {c[0]}" for c in double_cats[:2])
        messages.append({
            'bot': 'stats_nerd',
            'text': f"🎯🎯 DOUBLE-DOUBLE! {player_name} ({team}) has {cats_str}!",
            'type': 'double_double',
            'team': team,
            'is_milestone': True,
        })
        # Historian provides context for double-doubles
        messages.append({
            'bot': 'historian',
            'text': f"📜 Double-doubles show all-around excellence - about 15-20 happen across the league each night.",
            'type': 'historical_context',
            'team': team,
        })
        stats['announced_dd'] = True

    # Near triple-double (has DD and 1 away from TD)
    elif len(double_cats) == 2 and not stats['announced_td']:
        near_cats = []
        if pts == 9:
            near_cats.append('points')
        if reb == 9:
            near_cats.append('rebounds')
        if ast == 9:
            near_cats.append('assists')
        if stl == 9:
            near_cats.append('steals')
        if blk == 9:
            near_cats.append('blocks')
        if near_cats:
            messages.append({
                'bot': 'stats_nerd',
                'text': f"👀 {player_name} is 1 {near_cats[0][:-1]} away from a TRIPLE-DOUBLE!",
                'type': 'near_triple_double',
                'team': team,
            })

    # Near double-double (has 1 cat at 10+ and another at 9)
    elif len(double_cats) == 1 and not stats['announced_dd']:
        cat_at_10 = double_cats[0][0]
        near_cats = []
        if pts == 9 and cat_at_10 != 'points':
            near_cats.append('points')
        if reb == 9 and cat_at_10 != 'rebounds':
            near_cats.append('rebounds')
        if ast == 9 and cat_at_10 != 'assists':
            near_cats.append('assists')
        if near_cats:
            messages.append({
                'bot': 'stats_nerd',
                'text': f"👀 {player_name} has {double_cats[0][1]} {cat_at_10} and 9 {near_cats[0]} - 1 away from a double-double!",
                'type': 'near_double_double',
                'team': team,
            })

    # High scoring milestones
    if pts >= 40 and not stats['announced_pts_40']:
        messages.append({
            'bot': 'stats_nerd',
            'text': f"🔥 {player_name} is ON FIRE with {pts} POINTS! Scoring explosion!",
            'type': 'high_scorer',
            'team': team,
        })
        # Historian provides context for 40+ point games
        messages.append({
            'bot': 'historian',
            'text': f"📜 40-point games are rare - only about 150 occur each NBA season. {player_name} is having a historic night!",
            'type': 'historical_context',
            'team': team,
        })
        stats['announced_pts_40'] = True
        stats['announced_pts_30'] = True
        stats['announced_pts_20'] = True
    elif pts >= 30 and not stats['announced_pts_30']:
        messages.append({
            'bot': 'stats_nerd',
            'text': f"🔥 {player_name} is cooking! {pts} points and counting!",
            'type': 'high_scorer',
            'team': team,
        })
        # Historian provides context for 30+ point games
        messages.append({
            'bot': 'historian',
            'text': f"📜 30-point performances are elite - {player_name} joins an average of just 3-4 players per night reaching this mark.",
            'type': 'historical_context',
            'team': team,
        })
        stats['announced_pts_30'] = True
        stats['announced_pts_20'] = True
    elif pts >= 20 and not stats['announced_pts_20']:
        messages.append({
            'bot': 'stats_nerd',
            'text': f"📊 {player_name} ({team}) now has {pts} points tonight.",
            'type': 'scoring_update',
            'team': team,
        })
        stats['announced_pts_20'] = True

    # Rare defensive stats (5+ blocks or steals)
    if blk == 5:
        messages.append({
            'bot': 'stats_nerd',
            'text': f"🚫 {player_name} with {blk} BLOCKS! Protecting the rim!",
            'type': 'defensive_milestone',
            'team': team,
        })
        # Historian context for 5+ blocks
        messages.append({
            'bot': 'historian',
            'text': f"📜 5+ blocks in a game is elite rim protection - only happens about 1-2 times per night across the league.",
            'type': 'historical_context',
            'team': team,
        })
    if stl == 5:
        messages.append({
            'bot': 'stats_nerd',
            'text': f"👋 {player_name} with {stl} STEALS! Picking pockets all night!",
            'type': 'defensive_milestone',
            'team': team,
        })
        # Historian context for 5+ steals
        messages.append({
            'bot': 'historian',
            'text': f"📜 5+ steals is rare - averaging just one such game per night league-wide. {player_name} is disrupting everything!",
            'type': 'historical_context',
            'team': team,
        })

    return messages


def update_player_stats(game_id, action):
    """Update player stats based on an action and return any milestone messages."""
    action_type = action.get('actionType', '')
    player_id = action.get('personId')
    player_name = action.get('playerNameI', '')
    team = action.get('teamTricode', '')
    desc = action.get('description', '')

    if not player_id:
        return []

    stats = get_player_stats(game_id, player_id)
    stats['name'] = player_name
    stats['team'] = team

    messages = []

    # Update stats based on action type
    if action_type == '2pt':
        stats['fga'] += 1
        if 'MISS' not in desc:
            stats['fgm'] += 1
            stats['pts'] += 2
            messages = check_player_milestones(game_id, player_id, player_name, team)

    elif action_type == '3pt':
        stats['fga'] += 1
        stats['3pa'] += 1  # Track 3-point attempts
        if 'MISS' not in desc:
            stats['fgm'] += 1
            stats['3pm'] += 1
            stats['pts'] += 3
            messages = check_player_milestones(game_id, player_id, player_name, team)

    elif action_type == 'freethrow':
        stats['fta'] += 1
        if 'MISS' not in desc:
            stats['ftm'] += 1
            stats['pts'] += 1
            messages = check_player_milestones(game_id, player_id, player_name, team)

    elif action_type == 'rebound':
        stats['reb'] += 1
        # Check for offensive vs defensive rebound
        sub_type = action.get('subType', '').lower()
        if 'offensive' in sub_type or 'off' in desc.lower():
            stats['oreb'] += 1
        else:
            stats['dreb'] += 1
        messages = check_player_milestones(game_id, player_id, player_name, team)

    elif action_type == 'steal':
        stats['stl'] += 1
        messages = check_player_milestones(game_id, player_id, player_name, team)

    elif action_type == 'block':
        stats['blk'] += 1
        messages = check_player_milestones(game_id, player_id, player_name, team)

    elif action_type == 'turnover':
        stats['tov'] += 1

    elif action_type == 'foul':
        stats['pf'] += 1

    # Check for assists on made shots
    assist_player_id = action.get('assistPersonId')
    if assist_player_id and action_type in ['2pt', '3pt'] and 'MISS' not in desc:
        assist_name = action.get('assistPlayerNameInitial', '')
        assist_stats = get_player_stats(game_id, assist_player_id)
        assist_stats['name'] = assist_name
        assist_stats['team'] = team
        assist_stats['ast'] += 1
        assist_messages = check_player_milestones(game_id, assist_player_id, assist_name, team)
        messages.extend(assist_messages)

    return messages


def generate_chat_message(action, game_info, prev_action=None, largest_leads=None, player_stats_tracker=None):
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

        # HypeMan for dunks and highlight plays - LLM refined!
        if 'dunk' in shot_type.lower() or 'alley' in desc.lower():
            dunk_gist = f"{player} just threw down a massive dunk! Absolutely posterized!"
            dunk_context = {'player': player, 'team': team, 'shot_type': shot_type}
            messages.append({
                'bot': 'hype_man',
                'text': refine_message_with_persona('hype_man', dunk_gist, dunk_context),
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

    # Blocks - exciting defensive play with LLM refinement
    elif action_type == 'block':
        block_gist = f"{player} from {team} just blocked a shot! Great defensive play!"
        block_context = {'player': player, 'team': team}
        messages.append({
            'bot': 'play_by_play',
            'text': refine_message_with_persona('play_by_play', block_gist, block_context),
            'type': 'block',
            'team': team,
        })

    # Steals with LLM refinement
    elif action_type == 'steal':
        steal_gist = f"{player} from {team} got a steal! Picked the pocket!"
        steal_context = {'player': player, 'team': team}
        messages.append({
            'bot': 'play_by_play',
            'text': refine_message_with_persona('play_by_play', steal_gist, steal_context),
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

    # Technical fouls and ejections - BIG reactions with LLM refinement!
    elif action_type == 'foul':
        desc_lower = desc.lower()
        sub_lower = sub_type.lower() if sub_type else ''
        event_context = {'player': player, 'team': team}

        # Check for ejection first (most dramatic)
        if 'ejected' in desc_lower or 'ejection' in desc_lower:
            # Play-by-play announcement
            pbp_gist = f"{player} from {team} has been ejected from the game"
            messages.append({
                'bot': 'play_by_play',
                'text': refine_message_with_persona('play_by_play', pbp_gist, event_context),
                'type': 'ejection',
                'team': team,
            })
            # HypeMan goes WILD
            hype_gist = f"{player} just got ejected! This is absolutely crazy! They're gone!"
            messages.append({
                'bot': 'hype_man',
                'text': refine_message_with_persona('hype_man', hype_gist, event_context),
                'type': 'ejection_hype',
                'team': team,
            })
            # Historical context
            hist_gist = f"{player} getting ejected - they have a reputation for passionate play and confrontations"
            messages.append({
                'bot': 'historian',
                'text': refine_message_with_persona('historian', hist_gist, event_context),
                'type': 'history',
            })

        # Flagrant foul (very dramatic)
        elif 'flagrant' in desc_lower or 'flagrant' in sub_lower:
            flagrant_type = '2' if '2' in desc_lower else '1'
            event_context['flagrant_type'] = flagrant_type

            pbp_gist = f"Flagrant {flagrant_type} foul called on {player} from {team}"
            messages.append({
                'bot': 'play_by_play',
                'text': refine_message_with_persona('play_by_play', pbp_gist, event_context),
                'type': 'flagrant',
                'team': team,
            })
            hype_gist = f"Flagrant foul on {player}! This is getting heated and intense out there!"
            messages.append({
                'bot': 'hype_man',
                'text': refine_message_with_persona('hype_man', hype_gist, event_context),
                'type': 'flagrant_hype',
                'team': team,
            })

        # Technical foul (dramatic)
        elif 'technical' in desc_lower or 'technical' in sub_lower:
            pbp_gist = f"Technical foul called on {player} from {team}"
            messages.append({
                'bot': 'play_by_play',
                'text': refine_message_with_persona('play_by_play', pbp_gist, event_context),
                'type': 'technical',
                'team': team,
            })
            hype_gist = f"{player} just got a technical foul! They are NOT happy with the refs!"
            messages.append({
                'bot': 'hype_man',
                'text': refine_message_with_persona('hype_man', hype_gist, event_context),
                'type': 'technical_hype',
                'team': team,
            })
            # Stats context for technicals
            stats_gist = f"{player} picked up a technical - tracking their foul count this season"
            messages.append({
                'bot': 'stats_nerd',
                'text': refine_message_with_persona('stats_nerd', stats_gist, event_context),
                'type': 'tech_stats',
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
            lead_gist = f"{home_team} just took the lead! Lead change in this game!"
            lead_context = {'team': home_team, 'opponent': away_team, 'score': f"{curr_away}-{curr_home}"}
            messages.append({
                'bot': 'hype_man',
                'text': refine_message_with_persona('hype_man', lead_gist, lead_context),
                'type': 'lead_change',
                'team': home_team,
                'is_lead_change': True,
            })
        elif prev_diff < 0 and curr_diff > 0:
            # Home was leading, now away leads
            lead_gist = f"{away_team} just took the lead! Lead change in this game!"
            lead_context = {'team': away_team, 'opponent': home_team, 'score': f"{curr_away}-{curr_home}"}
            messages.append({
                'bot': 'hype_man',
                'text': refine_message_with_persona('hype_man', lead_gist, lead_context),
                'type': 'lead_change',
                'team': away_team,
                'is_lead_change': True,
            })
        # Tie game detection
        elif curr_diff == 0 and prev_diff != 0:
            tie_gist = f"It's a tie game now at {curr_away}-{curr_home}! This is intense!"
            tie_context = {'score': f"{curr_away}-{curr_home}"}
            messages.append({
                'bot': 'hype_man',
                'text': refine_message_with_persona('hype_man', tie_gist, tie_context),
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
                # Historian provides context for blowout leads
                if home_lead >= 25 and largest_leads.get('home', 0) < 25:
                    messages.append({
                        'bot': 'historian',
                        'text': f"📜 A 25+ point lead is historically insurmountable - teams win 99%+ of games when leading by this much.",
                        'type': 'historical_context',
                        'team': home_team,
                    })
                elif home_lead >= 20 and largest_leads.get('home', 0) < 20:
                    messages.append({
                        'bot': 'historian',
                        'text': f"📜 20-point leads in the NBA are dominant - historically held in about 15% of games.",
                        'type': 'historical_context',
                        'team': home_team,
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
                # Historian provides context for blowout leads
                if away_lead >= 25 and largest_leads.get('away', 0) < 25:
                    messages.append({
                        'bot': 'historian',
                        'text': f"📜 A 25+ point lead is historically insurmountable - teams win 99%+ of games when leading by this much.",
                        'type': 'historical_context',
                        'team': away_team,
                    })
                elif away_lead >= 20 and largest_leads.get('away', 0) < 20:
                    messages.append({
                        'bot': 'historian',
                        'text': f"📜 20-point leads in the NBA are dominant - historically held in about 15% of games.",
                        'type': 'historical_context',
                        'team': away_team,
                    })
            largest_leads['away'] = away_lead

    # Track player stats and check for milestones (StatsNerd individual player commentary)
    game_id = game_info.get('game_id', '')
    if game_id:
        player_milestone_msgs = update_player_stats(game_id, action)
        messages.extend(player_milestone_msgs)

    # Add score context and timestamp to all messages
    for msg in messages:
        msg['score'] = f"{away_team} {score_away} - {home_team} {score_home}"
        msg['clock'] = clock_display
        msg['period'] = period
        msg['timestamp'] = datetime.now().isoformat()
        msg['action_number'] = action.get('actionNumber', 0)

    return messages


@app.route('/beta-live')
def beta_live():
    """Beta live chat feed page."""
    return render_template('beta_live.html')


@app.route('/beta-live/archive')
def beta_live_archive():
    """Archive of past games with saved history."""
    return render_template('beta_live_archive.html')


@app.route('/api/beta-live/prewarm')
def api_beta_live_prewarm():
    """Pre-warm caches for all today's games (injuries, rosters).
    Call this on page load to speed up game switching."""
    try:
        if not BDL_AVAILABLE:
            return jsonify({'status': 'skipped', 'reason': 'BDL not available'})

        # Get today's games to know which teams need pre-warming
        game_date = get_nba_game_date()
        games_data = bdl.get_todays_games(game_date)

        # Collect unique teams
        teams = set()
        for g in games_data:
            teams.add(g.get('home_team', {}).get('abbreviation', ''))
            teams.add(g.get('visitor_team', {}).get('abbreviation', ''))
        teams.discard('')  # Remove empty strings

        # Pre-fetch injuries and rosters in parallel for all teams
        warmed = 0
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for team in teams:
                futures.append(executor.submit(fetch_team_injuries, team))
                futures.append(executor.submit(fetch_team_roster, team))

            for future in as_completed(futures):
                try:
                    future.result()
                    warmed += 1
                except Exception:
                    pass

        return jsonify({
            'status': 'ok',
            'teams_warmed': len(teams),
            'cache_items': warmed,
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})


@app.route('/api/beta-live/games')
def api_beta_live_games():
    """Get current live NBA games and games with saved history using BallDontLie API."""
    try:
        if not BDL_AVAILABLE:
            return jsonify({'error': 'BallDontLie API module not available'}), 500

        # Check if we should only return today's games (for main page performance)
        today_only = request.args.get('today_only', 'false').lower() == 'true'

        # Get today's games from BallDontLie (use Eastern time - NBA's schedule timezone)
        game_date = get_nba_game_date()
        games_data = bdl.get_todays_games(game_date)

        # Pre-fetch odds for all games (single API call)
        all_odds = fetch_dev_live_odds([], game_date)

        # Merge pre_game_odds from file cache (captured once, never changes)
        # This preserves the opening line before any in-game movement
        if all_odds:
            file_cache = {}
            try:
                if os.path.exists(DEV_LIVE_ODDS_CACHE_FILE):
                    with open(DEV_LIVE_ODDS_CACHE_FILE, 'r') as f:
                        file_cache = json.load(f)
            except Exception:
                pass

            # For each game's odds, preserve or capture pre_game_odds
            for key, odds_data in all_odds.items():
                if key in file_cache and 'pre_game_odds' in file_cache[key]:
                    # Use preserved pre_game_odds from file cache
                    odds_data['pre_game_odds'] = file_cache[key]['pre_game_odds']
                elif 'pre_game_odds' not in odds_data:
                    # First time seeing this game - capture pre_game_odds
                    odds_data['pre_game_odds'] = {
                        'consensus': odds_data.get('consensus', {}),
                        'captured_at': datetime.now().isoformat()
                    }
                    # Save to file cache for persistence
                    file_cache[key] = odds_data
                    try:
                        os.makedirs(os.path.dirname(DEV_LIVE_ODDS_CACHE_FILE), exist_ok=True)
                        with open(DEV_LIVE_ODDS_CACHE_FILE, 'w') as f:
                            json.dump(file_cache, f)
                    except Exception:
                        pass

        games = []
        seen_game_ids = set()

        for g in games_data:
            game_id = str(g['id'])  # BallDontLie uses numeric IDs
            seen_game_ids.add(game_id)

            # Check if history exists for this game
            has_history = os.path.exists(os.path.join(DEV_LIVE_HISTORY_DIR, f'game_{game_id}.json'))

            home_team = g.get('home_team', {})
            away_team = g.get('visitor_team', {})

            # Get odds for this game - match by team pair since IDs differ between APIs
            team_key = f"{away_team.get('abbreviation', '')}@{home_team.get('abbreviation', '')}"
            game_odds = all_odds.get(team_key, {})

            # Parse game status from BallDontLie format
            status = g.get('status', '')
            period = g.get('period', 0)
            time_str = g.get('time', '')  # Can be "7:21" or "Q4 7:21" or empty

            # Build status text similar to NBA API format
            if status == 'Final':
                status_text = 'Final'
            elif period > 0:
                # Game in progress - time_str might already include quarter
                if time_str:
                    # If time_str already has "Q" prefix, use it as-is
                    if time_str.startswith('Q') or time_str.startswith('OT'):
                        status_text = time_str
                    else:
                        # Add quarter prefix
                        quarter = f"Q{period}" if period <= 4 else f"OT{period-4}"
                        status_text = f"{quarter} {time_str}"
                else:
                    status_text = f"Q{period}" if period <= 4 else f"OT{period-4}"
            else:
                # Scheduled game - status might be time like "7:00 PM" or ISO timestamp
                status_text = status

            game_data = {
                'game_id': game_id,
                'home_team': home_team.get('abbreviation', ''),
                'away_team': away_team.get('abbreviation', ''),
                'home_team_name': home_team.get('name', ''),
                'away_team_name': away_team.get('name', ''),
                'home_team_city': home_team.get('city', ''),
                'away_team_city': away_team.get('city', ''),
                'status': status_text,
                'game_time_utc': None,  # BallDontLie doesn't provide UTC time directly
                'home_score': g.get('home_team_score', 0) or 0,
                'away_score': g.get('visitor_team_score', 0) or 0,
                'has_history': has_history,
                'bdl_id': g['id'],  # Keep original BallDontLie ID for API calls
                'game_date': g.get('date', game_date),  # Date from API or fallback to today
            }

            # Add odds if available
            if game_odds:
                consensus = game_odds.get('consensus', {})
                game_data['odds'] = {
                    'consensus': {
                        'home_prob': consensus.get('home_prob'),
                        'away_prob': consensus.get('away_prob'),
                        'vendor_count': consensus.get('vendor_count', 0),
                        'spread': consensus.get('spread'),
                        'total': consensus.get('total'),
                        'home_ml': consensus.get('home_ml'),
                        'away_ml': consensus.get('away_ml'),
                    }
                }
                # Add pre_game_odds (captured once, never changes)
                pre_game = game_odds.get('pre_game_odds', {})
                if pre_game:
                    game_data['pre_game_odds'] = pre_game.get('consensus', consensus)

            games.append(game_data)

        # Track seen team matchups to avoid duplicates from old NBA API history
        seen_matchups = set()
        for g in games:
            # Create matchup key: "away@home" with scores to identify same game
            matchup = f"{g['away_team']}@{g['home_team']}"
            seen_matchups.add(matchup)

        # Also include saved historical games not in today's scoreboard
        # Skip if today_only mode or if we already have this matchup from BallDontLie
        if not today_only and os.path.exists(DEV_LIVE_HISTORY_DIR):
            for filename in os.listdir(DEV_LIVE_HISTORY_DIR):
                if filename.startswith('game_') and filename.endswith('.json'):
                    game_id = filename.replace('game_', '').replace('.json', '')
                    if game_id not in seen_game_ids:
                        try:
                            history = load_dev_live_history(game_id)
                            if history:
                                game_info = history.get('game_info', {})
                                away = game_info.get('away_team', 'AWAY')
                                home = game_info.get('home_team', 'HOME')
                                matchup = f"{away}@{home}"

                                # Skip if we already have this matchup from BallDontLie
                                if matchup in seen_matchups:
                                    continue

                                final_score = history.get('final_score', {'home': 0, 'away': 0})
                                # Get date from file modification time
                                file_path = os.path.join(DEV_LIVE_HISTORY_DIR, filename)
                                file_mtime = os.path.getmtime(file_path)
                                file_date = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d')
                                games.append({
                                    'game_id': game_id,
                                    'home_team': home,
                                    'away_team': away,
                                    'home_team_name': '',
                                    'away_team_name': '',
                                    'status': 'Final (Saved)',
                                    'home_score': final_score.get('home', 0),
                                    'away_score': final_score.get('away', 0),
                                    'has_history': True,
                                    'game_date': file_date,
                                })
                                seen_matchups.add(matchup)
                        except Exception:
                            pass

        return jsonify({'games': games})
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@app.route('/api/beta-live/feed/<game_id>')
def api_beta_live_feed(game_id):
    """Get live chat feed for a specific game using BallDontLie API."""
    try:
        import uuid

        if not BDL_AVAILABLE:
            return jsonify({'error': 'BallDontLie API module not available'}), 500

        # Convert game_id to int for BallDontLie API
        bdl_game_id = int(game_id)

        # Get last seen action number and client ID from query params
        last_action = int(request.args.get('last_action', 0))
        client_id = request.args.get('client_id', str(uuid.uuid4()))
        # recent_only: only load recent plays for faster initial load (default true for fresh loads)
        recent_only = request.args.get('recent_only', 'true').lower() == 'true'

        # Check for saved history first (for completed games AND live games on first load)
        saved_history = load_dev_live_history(game_id)
        saved_status = saved_history.get('status', '') if saved_history else ''

        # For Final games: use saved history directly
        # For live games on first load (last_action == 0): use saved messages to avoid regeneration
        use_saved_history = saved_history and (saved_status == 'Final' or (saved_status and last_action == 0))

        if use_saved_history and saved_status == 'Final':
            # Check if we need to enrich with starter info (for games saved before starter feature)
            player_stats = saved_history.get('player_stats', {'home': [], 'away': []})
            needs_starter_info = (
                player_stats.get('home') and
                len(player_stats['home']) > 0 and
                'starter' not in player_stats['home'][0]
            )

            if needs_starter_info:
                # Try to add starter info from NBA API (only works for today's games)
                try:
                    from nba_api.live.nba.endpoints import scoreboard, boxscore
                    game_info = saved_history.get('game_info', {})
                    home_team = game_info.get('home_team', '')
                    away_team = game_info.get('away_team', '')

                    sb = scoreboard.ScoreBoard()
                    nba_games = sb.get_dict()['scoreboard']['games']

                    nba_game_id = None
                    for ng in nba_games:
                        if (ng['homeTeam']['teamTricode'] == home_team and
                            ng['awayTeam']['teamTricode'] == away_team):
                            nba_game_id = ng['gameId']
                            break

                    if nba_game_id:
                        bs = boxscore.BoxScore(nba_game_id)
                        bs_data = bs.get_dict()
                        starters = set()
                        for team_key in ['homeTeam', 'awayTeam']:
                            team_data = bs_data.get('game', {}).get(team_key, {})
                            for player in team_data.get('players', []):
                                if player.get('starter') == '1' or player.get('starter') == 1:
                                    starters.add(player.get('name', '').strip())

                        for team in ['home', 'away']:
                            for p in player_stats.get(team, []):
                                p['starter'] = p.get('name', '') in starters

                        # Update saved history with starter info
                        saved_history['player_stats'] = player_stats
                        _dev_live_history[game_id] = saved_history
                        save_dev_live_history(game_id)
                        print(f"Enriched saved history for game {game_id} with starter info")
                except Exception as e:
                    print(f"Could not enrich starter info for saved game: {e}")

            # Return saved history for completed games
            if last_action == 0:
                # Fresh load - return all messages
                return jsonify({
                    'messages': saved_history.get('messages', []),
                    'last_action': saved_history.get('last_action', 0),
                    'game_info': saved_history.get('game_info', {}),
                    'score': saved_history.get('final_score', {'home': 0, 'away': 0}),
                    'scores': saved_history.get('scores', []),  # For chart reconstruction
                    'total_actions': saved_history.get('total_actions', 0),
                    'viewer_count': 0,
                    'client_id': client_id,
                    'lead_changes': saved_history.get('lead_changes', 0),
                    'status': 'Final',
                    'is_historical': True,
                    'player_stats': saved_history.get('player_stats', {'home': [], 'away': []}),
                })
            else:
                # Incremental request on completed game - no new messages
                return jsonify({
                    'messages': [],
                    'last_action': saved_history.get('last_action', 0),
                    'game_info': saved_history.get('game_info', {}),
                    'score': saved_history.get('final_score', {'home': 0, 'away': 0}),
                    'total_actions': saved_history.get('total_actions', 0),
                    'viewer_count': 0,
                    'client_id': client_id,
                    'lead_changes': saved_history.get('lead_changes', 0),
                    'status': 'Final',
                    'is_historical': True,
                    'player_stats': saved_history.get('player_stats', {'home': [], 'away': []}),
                })

        # For live games with saved history on first load: return saved messages + fresh game status + fresh scores
        if use_saved_history and saved_status != 'Final':
            # Get fresh game info from API for current status/score
            game_data = bdl.get_game_info(bdl_game_id)
            period, clock, status_text, is_live = bdl.parse_game_status(game_data)

            home_score = game_data.get('home_team_score', 0) or 0
            away_score = game_data.get('visitor_team_score', 0) or 0

            # If game is now Final, we should regenerate to get final messages
            if status_text == 'Final':
                # Don't use saved history - fall through to regenerate
                pass
            else:
                # Rebuild scores from fresh play-by-play (scores change during game, messages don't)
                fresh_plays = bdl.get_play_by_play(bdl_game_id)
                fresh_scores = []
                for p in fresh_plays:
                    h = int(p.get('home_score', 0) or 0)
                    aw = int(p.get('away_score', 0) or 0)
                    if h > 0 or aw > 0:
                        if not fresh_scores or fresh_scores[-1]['home'] != h or fresh_scores[-1]['away'] != aw:
                            p_clock = p.get('clock', '')
                            p_period = p.get('period', 1)
                            fresh_scores.append({
                                'home': h,
                                'away': aw,
                                'action': p.get('order', 0),
                                'period': p_period,
                                'clock': p_clock,
                                'elapsed': clock_to_elapsed_seconds(p_clock, p_period)
                            })

                # Return saved messages with fresh status and fresh scores
                print(f"Using saved history for live game {game_id}: {len(saved_history.get('messages', []))} messages, {len(fresh_scores)} scores")
                return jsonify({
                    'messages': saved_history.get('messages', []),
                    'last_action': saved_history.get('last_action', 0),
                    'game_info': saved_history.get('game_info', {}),
                    'score': {'home': home_score, 'away': away_score},
                    'scores': fresh_scores,  # Use fresh scores, not cached
                    'total_actions': saved_history.get('total_actions', 0),
                    'viewer_count': 0,
                    'client_id': client_id,
                    'lead_changes': saved_history.get('lead_changes', 0),
                    'status': status_text,
                    'period': period,
                    'game_clock': clock,
                    'is_historical': False,
                    'is_cached': True,  # Indicate this is from cache
                    'player_stats': saved_history.get('player_stats', {'home': [], 'away': []}),
                })

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

        # Get game info from BallDontLie API
        game_data = bdl.get_game_info(bdl_game_id)

        home_team_obj = game_data.get('home_team', {})
        away_team_obj = game_data.get('visitor_team', {})

        home_team = home_team_obj.get('abbreviation', 'HOME')
        away_team = away_team_obj.get('abbreviation', 'AWAY')
        home_team_id = home_team_obj.get('id', 0)

        # Parse game status from BallDontLie
        period, clock, status_text, is_live = bdl.parse_game_status(game_data)
        game_status = status_text
        current_period = period
        game_clock = clock

        home_score = game_data.get('home_team_score', 0) or 0
        away_score = game_data.get('visitor_team_score', 0) or 0

        # BallDontLie doesn't provide timeouts, bonus, or quarter scores
        # Supplement with NBA API scoreboard for these fields (ONLY for live games - skip for pregame)
        home_timeouts = 0
        away_timeouts = 0
        home_in_bonus = False
        away_in_bonus = False
        home_periods = []
        away_periods = []

        # Only fetch NBA API data for LIVE games (not pregame) - saves ~1 second
        is_pregame_check = not is_live and game_status != 'Final' and home_score == 0 and away_score == 0
        if not is_pregame_check and is_live:
            try:
                from nba_api.live.nba.endpoints import scoreboard
                sb = scoreboard.ScoreBoard()
                nba_games = sb.get_dict()['scoreboard']['games']

                # Match by team abbreviations (IDs differ between APIs)
                for ng in nba_games:
                    if (ng['homeTeam']['teamTricode'] == home_team and
                        ng['awayTeam']['teamTricode'] == away_team):
                        # Found matching game - extract timeout/bonus/quarter data
                        home_timeouts = ng['homeTeam'].get('timeoutsRemaining', 0)
                        away_timeouts = ng['awayTeam'].get('timeoutsRemaining', 0)
                        home_in_bonus = ng['homeTeam'].get('inBonus', '0') == '1'
                        away_in_bonus = ng['awayTeam'].get('inBonus', '0') == '1'
                        home_periods = ng['homeTeam'].get('periods', [])
                        away_periods = ng['awayTeam'].get('periods', [])

                        # Also get more accurate game clock from NBA API
                        raw_clock = ng.get('gameClock', '')
                        if raw_clock and raw_clock.startswith('PT'):
                            try:
                                match = re.match(r'PT(\d+)M([\d.]+)S', raw_clock)
                                if match:
                                    mins = int(match.group(1))
                                    secs = int(float(match.group(2)))
                                    game_clock = f"{mins}:{secs:02d}"
                            except:
                                pass
                        break
            except Exception as e:
                # NBA API failed - continue with BallDontLie data only
                print(f"NBA API scoreboard supplement failed: {e}")

        # Get full team names for pregame display
        home_team_name = home_team_obj.get('full_name', '')
        away_team_name = away_team_obj.get('full_name', '')

        game_info = {
            'home_team': home_team,
            'away_team': away_team,
            'game_id': game_id,
        }

        # For games that haven't started yet, return pregame preview
        is_pregame = not is_live and game_status != 'Final' and home_score == 0 and away_score == 0
        if is_pregame:
            pregame_messages = []

            # Calculate time until game (used for both countdown and hype messages)
            time_until_game = None
            try:
                import re
                from datetime import timezone as tz

                now_utc = datetime.now(tz.utc)

                # Try ISO format first (e.g., "2026-01-11T20:00:00Z")
                iso_match = re.match(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z?', game_status)
                if iso_match:
                    year = int(iso_match.group(1))
                    month = int(iso_match.group(2))
                    day = int(iso_match.group(3))
                    hour = int(iso_match.group(4))
                    minute = int(iso_match.group(5))
                    game_time_utc = datetime(year, month, day, hour, minute, tzinfo=tz.utc)
                    time_until_game = (game_time_utc - now_utc).total_seconds() / 60
                else:
                    # Try human-readable format (e.g., "7:00 PM ET")
                    time_match = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', game_status)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2))
                        ampm = time_match.group(3)

                        # Convert to 24-hour (assume ET, convert to local)
                        if ampm == 'PM' and hour != 12:
                            hour += 12
                        elif ampm == 'AM' and hour == 12:
                            hour = 0

                        # Create game datetime (assume today, ET timezone)
                        # ET is UTC-5 (or UTC-4 during DST)
                        et_offset = timedelta(hours=-5)  # EST
                        game_time_et = datetime(now_utc.year, now_utc.month, now_utc.day,
                                                hour, minute, tzinfo=tz(et_offset))
                        time_until_game = (game_time_et - now_utc).total_seconds() / 60
            except Exception as e:
                print(f"Error parsing game time: {e}")

            # Only show pregame preview on fresh load (not polling updates)
            if last_action == 0:
                # Get odds for pregame preview
                game_date = get_nba_game_date()
                team_key = f"{away_team}@{home_team}"
                game_odds = get_cached_odds(team_key, game_date)

                # Show hype messages only if game is within 30 minutes
                show_hype = time_until_game is not None and time_until_game <= 30

                pregame_messages = generate_pregame_preview(
                    home_team, away_team,
                    home_team_name, away_team_name,
                    game_odds,
                    show_hype=show_hype
                )

            # Always add countdown message if within range (updates on each poll)
            if time_until_game is not None:
                countdown_msg = generate_countdown_message(time_until_game, home_team, away_team)
                if countdown_msg:
                    pregame_messages.append(countdown_msg)

            # Calculate scheduled game time as UTC timestamp for client countdown
            scheduled_time_utc = None
            if time_until_game is not None:
                # time_until_game is in minutes, convert to future timestamp
                from datetime import timezone as tz
                scheduled_time_utc = int((datetime.now(tz.utc) + timedelta(minutes=time_until_game)).timestamp() * 1000)

            return jsonify({
                'messages': pregame_messages,
                'last_action': -95,  # Negative to indicate pregame messages
                'game_info': game_info,
                'score': {'home': 0, 'away': 0},
                'scores': [],
                'total_actions': 0,
                'viewer_count': viewer_count,
                'client_id': client_id,
                'lead_changes': 0,
                'status': game_status,
                'is_historical': False,
                'is_pregame': True,
                'scheduled_time_utc': scheduled_time_utc,
            })

        # Get play-by-play from BallDontLie (only for games that have started or finished)
        plays = bdl.get_play_by_play(bdl_game_id)

        # For completed games without saved history, generate and save immediately (no LLM)
        # This avoids expensive LLM calls on page load for historical games
        if game_status == 'Final' and not saved_history and plays:
            print(f"Generating history for completed game {game_id} (no LLM)...")
            full_messages = []
            full_scores = []
            prev_play = None
            largest_leads_regen = {'home': 0, 'away': 0}
            lead_change_count = 0

            for i, play in enumerate(plays):
                # Track largest leads
                h = int(play.get('home_score', 0) or 0)
                aw = int(play.get('away_score', 0) or 0)
                if h > aw:
                    largest_leads_regen['home'] = max(largest_leads_regen['home'], h - aw)
                elif aw > h:
                    largest_leads_regen['away'] = max(largest_leads_regen['away'], aw - h)

                # Count lead changes
                if prev_play:
                    prev_h = int(prev_play.get('home_score', 0) or 0)
                    prev_aw = int(prev_play.get('away_score', 0) or 0)
                    prev_diff = prev_aw - prev_h
                    curr_diff = aw - h
                    if (prev_diff > 0 and curr_diff < 0) or (prev_diff < 0 and curr_diff > 0):
                        lead_change_count += 1

                # Generate messages using BallDontLie module (skip LLM for faster loading)
                compare_play = prev_play if i > 0 else None
                # Check if this is the last play (for game summary)
                is_last_play = (i == len(plays) - 1)
                msgs = bdl.generate_messages_from_play(
                    play, game_info, compare_play, largest_leads_regen,
                    lead_changes=lead_change_count,
                    is_game_final=is_last_play,
                    skip_llm=True  # Skip LLM for historical regeneration
                )
                for msg in msgs:
                    msg['action_number'] = play.get('order', 0)
                full_messages.extend(msgs)

                # Track score at each action (include period for quarter markers)
                if h > 0 or aw > 0:
                    clock = play.get('clock', '')
                    period = play.get('period', 1)
                    full_scores.append({
                        'home': h,
                        'away': aw,
                        'action': play.get('order', 0),
                        'period': period,
                        'clock': clock,
                        'elapsed': clock_to_elapsed_seconds(clock, period)
                    })

                prev_play = play

            # Deduplicate scores
            deduped_scores = []
            if full_scores:
                deduped_scores = [full_scores[0]]
                for s in full_scores[1:]:
                    if s['home'] != deduped_scores[-1]['home'] or s['away'] != deduped_scores[-1]['away']:
                        deduped_scores.append(s)

            # Get final score
            final_score = {'home': home_score, 'away': away_score}

            max_action = max([p.get('order', 0) for p in plays]) if plays else 0

            # Get player stats from NBA API (more complete than BallDontLie)
            player_stats_by_team = {'home': [], 'away': []}
            try:
                from nba_api.live.nba.endpoints import scoreboard, boxscore
                sb = scoreboard.ScoreBoard()
                nba_games = sb.get_dict()['scoreboard']['games']

                nba_game_id = None
                for ng in nba_games:
                    if (ng['homeTeam']['teamTricode'] == home_team and
                        ng['awayTeam']['teamTricode'] == away_team):
                        nba_game_id = ng['gameId']
                        break

                if nba_game_id:
                    bs = boxscore.BoxScore(nba_game_id)
                    bs_data = bs.get_dict()
                    player_stats_by_team = get_player_stats_from_nba_boxscore(bs_data, home_team)
            except Exception as e:
                print(f"NBA API boxscore for stats (regen) failed: {e}")
                # Fall back to BallDontLie if NBA API fails
                player_stats_raw = bdl.get_player_stats(bdl_game_id)
                player_stats_by_team = bdl.format_player_stats_for_frontend(player_stats_raw, home_team_id)

            # Save to history
            history_data = {
                'messages': full_messages,
                'scores': deduped_scores,
                'game_info': game_info,
                'status': 'Final',
                'last_action': max_action,
                'lead_changes': lead_change_count,
                'final_score': final_score,
                'total_actions': len(plays),
                'player_stats': player_stats_by_team,
            }
            _dev_live_history[game_id] = history_data
            save_dev_live_history(game_id)
            print(f"Saved history: {len(full_messages)} messages, {len(deduped_scores)} scores")

            # Return the generated history
            return jsonify({
                'messages': full_messages,
                'last_action': max_action,
                'game_info': game_info,
                'score': final_score,
                'scores': deduped_scores,
                'total_actions': len(plays),
                'viewer_count': 0,
                'client_id': client_id,
                'lead_changes': lead_change_count,
                'status': 'Final',
                'is_historical': True,
                'player_stats': player_stats_by_team,
            })

        # Initialize lead change tracking for this game
        # Track if we need to recalculate from full history (server restart scenario)
        needs_lead_change_calc = game_id not in _dev_live_lead_changes
        if needs_lead_change_calc:
            _dev_live_lead_changes[game_id] = {'count': 0, 'last_leader': None}

        # Initialize largest lead tracking for this game
        # IMPORTANT: If this is a new game for the server (not in tracking dict),
        # we need to calculate largest leads from ALL plays, even if client has last_action > 0
        # This handles server restarts where globals are cleared but client state persists
        needs_full_history_calc = game_id not in _dev_live_largest_leads
        if needs_full_history_calc:
            _dev_live_largest_leads[game_id] = {'home': 0, 'away': 0}

        # Filter to new plays only (BallDontLie uses 'order' instead of 'actionNumber')
        new_plays = [p for p in plays if p.get('order', 0) > last_action]

        # For fresh loads with recent_only, filter to recent plays only (for faster loading)
        # Still need full plays for lead change count and scores (handled separately)
        has_more_history = False
        history_cutoff_action = 0
        if last_action == 0 and recent_only and len(new_plays) > 0:
            # Filter to current period and previous period only
            # This gives ~5-10 minutes of action
            min_period = max(1, current_period - 1)
            recent_plays = [p for p in new_plays if p.get('period', 1) >= min_period]

            # If we filtered out some plays, track that there's more history
            if len(recent_plays) < len(new_plays):
                has_more_history = True
                # Find the cutoff action (first action we're showing)
                if recent_plays:
                    history_cutoff_action = min(p.get('order', 0) for p in recent_plays)
                # Use filtered plays for message generation
                new_plays_for_messages = recent_plays
            else:
                new_plays_for_messages = new_plays
        else:
            new_plays_for_messages = new_plays

        # Generate chat messages with lead change detection
        all_messages = []
        lead_changes_in_batch = 0

        # Get the play just before the new ones for lead change detection
        prev_play = None
        if last_action > 0:
            prev_plays = [p for p in plays if p.get('order', 0) == last_action]
            if prev_plays:
                prev_play = prev_plays[0]

        # Calculate largest leads and player stats from history if this is a fresh load
        # OR if server was restarted (needs_full_history_calc) even if client has last_action > 0
        if (last_action == 0 or needs_full_history_calc) and len(plays) > 0:
            for p in plays:
                h = int(p.get('home_score', 0) or 0)
                aw = int(p.get('away_score', 0) or 0)
                if h > aw:
                    _dev_live_largest_leads[game_id]['home'] = max(_dev_live_largest_leads[game_id]['home'], h - aw)
                elif aw > h:
                    _dev_live_largest_leads[game_id]['away'] = max(_dev_live_largest_leads[game_id]['away'], aw - h)
                # Track player stats from historical plays for milestone detection
                track_player_stats_from_play(game_id, p)

        # For fresh loads of games that just started, prepend pregame messages
        # This ensures viewers joining early see the matchup preview
        pregame_msgs_to_add = []
        if last_action == 0 and current_period == 1 and len(plays) < 50:
            # Game just started - add pregame preview
            game_date = get_nba_game_date()
            team_key = f"{away_team}@{home_team}"
            game_odds = get_cached_odds(team_key, game_date)

            pregame_msgs_to_add = generate_pregame_preview(
                home_team, away_team,
                home_team_name, away_team_name,
                game_odds,
                show_hype=True  # Game just started, always show hype
            )

        for i, play in enumerate(new_plays_for_messages):
            # Use previous play for comparison (either from before batch or previous in batch)
            compare_play = prev_play if i == 0 else new_plays_for_messages[i - 1]
            # Get current lead changes count for LLM context
            current_lead_changes = _dev_live_lead_changes.get(game_id, {}).get('count', 0)
            messages = bdl.generate_messages_from_play(
                play, game_info, compare_play, _dev_live_largest_leads[game_id],
                lead_changes=current_lead_changes,
                is_game_final=False  # Live games are not final
            )

            # Add action_number to each message
            for msg in messages:
                msg['action_number'] = play.get('order', 0)

            # Count lead changes
            for msg in messages:
                if msg.get('is_lead_change'):
                    lead_changes_in_batch += 1
                    _dev_live_lead_changes[game_id]['count'] += 1

            # Try to add LLM commentary for exciting events
            # Only call LLM when there are actual viewers to save API costs
            if LLM_AVAILABLE and viewer_count > 0:
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

            # === HISTORIAN BOT: Stat Milestone Detection ===
            # Track player stats from this play and check for milestones
            if viewer_count > 0:  # Only when viewers are watching
                try:
                    # Track stats from the play
                    tracked_player = track_player_stats_from_play(game_id, play)

                    if tracked_player:
                        # Check for individual stat milestones (triple-double, 30+ pts, etc.)
                        milestone_msgs = check_stat_milestones(game_id, tracked_player, game_info)
                        for milestone_msg in milestone_msgs:
                            milestone_msg['action_number'] = play.get('order', 0)
                            milestone_msg['score'] = f"{away_team} {play.get('away_score', 0)} - {home_team} {play.get('home_score', 0)}"
                            milestone_msg['clock'] = play.get('clock', '')
                            milestone_msg['period'] = play.get('period', 1)
                            messages.append(milestone_msg)

                    # Check for big lead milestones (20+, 25+, 30+ point leads)
                    h_score = int(play.get('home_score', 0) or 0)
                    a_score = int(play.get('away_score', 0) or 0)
                    if abs(h_score - a_score) >= 20:
                        big_lead_msg = check_big_lead_milestone(
                            game_id, h_score, a_score,
                            home_team, away_team,
                            play.get('period', 1), game_info
                        )
                        if big_lead_msg:
                            big_lead_msg['action_number'] = play.get('order', 0)
                            big_lead_msg['score'] = f"{away_team} {a_score} - {home_team} {h_score}"
                            big_lead_msg['clock'] = play.get('clock', '')
                            big_lead_msg['period'] = play.get('period', 1)
                            messages.append(big_lead_msg)
                except Exception as e:
                    print(f"Milestone detection error: {e}")

            all_messages.extend(messages)

        # Prepend pregame messages for early game loads
        if pregame_msgs_to_add:
            all_messages = pregame_msgs_to_add + all_messages

        # Count total lead changes from all plays if this is a fresh load
        # OR if server was restarted (needs_lead_change_calc) even if client has last_action > 0
        if (last_action == 0 or needs_lead_change_calc) and len(plays) > 1:
            lead_change_count = 0
            for i in range(1, len(plays)):
                prev = plays[i - 1]
                curr = plays[i]
                prev_home = int(prev.get('home_score', 0) or 0)
                prev_away = int(prev.get('away_score', 0) or 0)
                curr_home = int(curr.get('home_score', 0) or 0)
                curr_away = int(curr.get('away_score', 0) or 0)
                prev_diff = prev_away - prev_home
                curr_diff = curr_away - curr_home
                # Lead change: sign changed and neither is zero (tie doesn't count as lead)
                if (prev_diff > 0 and curr_diff < 0) or (prev_diff < 0 and curr_diff > 0):
                    lead_change_count += 1
            _dev_live_lead_changes[game_id]['count'] = lead_change_count

        # Get current score from latest play or game data
        latest_score = {'home': home_score, 'away': away_score}
        if plays:
            last_play = plays[-1]
            latest_score['home'] = int(last_play.get('home_score', 0) or 0) or home_score
            latest_score['away'] = int(last_play.get('away_score', 0) or 0) or away_score

        # Get the highest action number we've seen
        max_action = max([p.get('order', 0) for p in plays]) if plays else 0

        # === HISTORY STORAGE ===
        # Initialize history for this game if not exists
        if game_id not in _dev_live_history:
            _dev_live_history[game_id] = {
                'messages': [],
                'scores': [],
                'game_info': game_info,
                'status': '',
                'last_action': 0,
                'lead_changes': 0,
                'final_score': {'home': 0, 'away': 0},
                'total_actions': 0,
                'saved_action_numbers': set(),  # Track which actions we've stored
            }

        history = _dev_live_history[game_id]

        # Ensure saved_action_numbers exists (not in file-loaded history since sets aren't JSON-serializable)
        if 'saved_action_numbers' not in history:
            # Rebuild from existing messages
            history['saved_action_numbers'] = set()
            for msg in history.get('messages', []):
                action_num = msg.get('action_number', 0)
                msg_key = f"{action_num}_{msg.get('bot', '')}_{msg.get('type', '')}"
                history['saved_action_numbers'].add(msg_key)

        # Add new messages to history
        # Use message text + action_number as unique key since multiple messages per action
        for msg in all_messages:
            action_num = msg.get('action_number', 0)
            msg_key = f"{action_num}_{msg.get('bot', '')}_{msg.get('type', '')}"
            if msg_key not in history['saved_action_numbers']:
                history['saved_action_numbers'].add(msg_key)
                history['messages'].append(msg)

        # Track score progression for charts (include period and clock for game time x-axis)
        play_period = plays[-1].get('period', 1) if plays else current_period
        play_clock = plays[-1].get('clock', game_clock) if plays else game_clock
        if latest_score['home'] > 0 or latest_score['away'] > 0:
            # Only add if score changed from last recorded score
            if not history['scores'] or \
               history['scores'][-1]['home'] != latest_score['home'] or \
               history['scores'][-1]['away'] != latest_score['away']:
                history['scores'].append({
                    'home': latest_score['home'],
                    'away': latest_score['away'],
                    'action': max_action,
                    'period': play_period,
                    'clock': play_clock,
                    'elapsed': clock_to_elapsed_seconds(play_clock, play_period),
                })

        # Update history metadata
        history['game_info'] = game_info
        history['last_action'] = max_action
        history['lead_changes'] = _dev_live_lead_changes[game_id]['count']
        history['final_score'] = latest_score
        history['total_actions'] = len(plays)

        # Check if game just ended - save history (check BEFORE updating status)
        prev_status = history.get('status', '')
        if game_status == 'Final' and prev_status != 'Final':
            history['status'] = 'Final'

            # If we don't have any messages accumulated (e.g., game was already Final when first tracked),
            # regenerate ALL messages from all plays before saving
            if not history['messages'] and plays:
                print(f"Regenerating messages for completed game {game_id}...")
                full_messages = []
                full_scores = []
                prev_p = None
                largest_leads_regen = {'home': 0, 'away': 0}
                lead_change_count_regen = 0

                for i, p in enumerate(plays):
                    # Track largest leads
                    h = int(p.get('home_score', 0) or 0)
                    aw = int(p.get('away_score', 0) or 0)
                    if h > aw:
                        largest_leads_regen['home'] = max(largest_leads_regen['home'], h - aw)
                    elif aw > h:
                        largest_leads_regen['away'] = max(largest_leads_regen['away'], aw - h)

                    # Count lead changes
                    if prev_p:
                        prev_h = int(prev_p.get('home_score', 0) or 0)
                        prev_aw = int(prev_p.get('away_score', 0) or 0)
                        prev_diff = prev_aw - prev_h
                        curr_diff = aw - h
                        if (prev_diff > 0 and curr_diff < 0) or (prev_diff < 0 and curr_diff > 0):
                            lead_change_count_regen += 1

                    # Generate messages using BallDontLie module (skip LLM for faster loading)
                    compare_p = prev_p if i > 0 else None
                    # Check if this is the last play (for game summary)
                    is_last_play = (i == len(plays) - 1)
                    msgs = bdl.generate_messages_from_play(
                        p, game_info, compare_p, largest_leads_regen,
                        lead_changes=lead_change_count_regen,
                        is_game_final=is_last_play,
                        skip_llm=True  # Skip LLM for historical regeneration
                    )

                    for msg in msgs:
                        msg['action_number'] = p.get('order', 0)
                    full_messages.extend(msgs)

                    # Track score at each play (include period for quarter markers)
                    if h > 0 or aw > 0:
                        clock = p.get('clock', '')
                        period = p.get('period', 1)
                        full_scores.append({
                            'home': h,
                            'away': aw,
                            'action': p.get('order', 0),
                            'period': period,
                            'clock': clock,
                            'elapsed': clock_to_elapsed_seconds(clock, period)
                        })

                    prev_p = p

                history['messages'] = full_messages
                history['lead_changes'] = lead_change_count_regen
                # Deduplicate scores (only keep significant changes)
                if full_scores:
                    deduped_scores = [full_scores[0]]
                    for s in full_scores[1:]:
                        if s['home'] != deduped_scores[-1]['home'] or s['away'] != deduped_scores[-1]['away']:
                            deduped_scores.append(s)
                    history['scores'] = deduped_scores
                print(f"Regenerated {len(history['messages'])} messages and {len(history['scores'])} score points")

            # Get player stats from NBA API (more complete than BallDontLie) before saving
            try:
                from nba_api.live.nba.endpoints import boxscore
                nba_game_id = None
                for ng in nba_games:
                    if (ng['homeTeam']['teamTricode'] == home_team and
                        ng['awayTeam']['teamTricode'] == away_team):
                        nba_game_id = ng['gameId']
                        break

                if nba_game_id:
                    bs = boxscore.BoxScore(nba_game_id)
                    bs_data = bs.get_dict()
                    history['player_stats'] = get_player_stats_from_nba_boxscore(bs_data, home_team)
                else:
                    # Fall back to BallDontLie if NBA game not found
                    player_stats_raw = bdl.get_player_stats(bdl_game_id)
                    history['player_stats'] = bdl.format_player_stats_for_frontend(player_stats_raw, home_team_id)
            except Exception as e:
                print(f"NBA API boxscore for stats (save) failed: {e}")
                # Fall back to BallDontLie if NBA API fails
                player_stats_raw = bdl.get_player_stats(bdl_game_id)
                history['player_stats'] = bdl.format_player_stats_for_frontend(player_stats_raw, home_team_id)

            # Convert set to list for JSON serialization before saving
            history_to_save = {k: v for k, v in history.items() if k != 'saved_action_numbers'}
            _dev_live_history[game_id] = history_to_save
            save_dev_live_history(game_id)
            print(f"Saved dev-live history for game {game_id}")
        else:
            history['status'] = game_status

        # Get player stats from NBA API (more complete than BallDontLie)
        player_stats_by_team = {'home': [], 'away': []}
        try:
            from nba_api.live.nba.endpoints import boxscore

            # Find matching NBA game ID by checking today's games
            nba_game_id = None
            for ng in nba_games:
                if (ng['homeTeam']['teamTricode'] == home_team and
                    ng['awayTeam']['teamTricode'] == away_team):
                    nba_game_id = ng['gameId']
                    break

            if nba_game_id:
                bs = boxscore.BoxScore(nba_game_id)
                bs_data = bs.get_dict()
                player_stats_by_team = get_player_stats_from_nba_boxscore(bs_data, home_team)
            else:
                # Fall back to BallDontLie if NBA game not found
                player_stats_raw = bdl.get_player_stats(bdl_game_id)
                player_stats_by_team = bdl.format_player_stats_for_frontend(player_stats_raw, home_team_id)
        except Exception as e:
            print(f"NBA API boxscore for stats failed: {e}")
            # Fall back to BallDontLie if NBA API fails
            player_stats_raw = bdl.get_player_stats(bdl_game_id)
            player_stats_by_team = bdl.format_player_stats_for_frontend(player_stats_raw, home_team_id)

        # Build response
        response_data = {
            'messages': all_messages,
            'last_action': max_action,
            'game_info': game_info,
            'score': latest_score,
            'total_actions': len(plays),
            'viewer_count': viewer_count,
            'client_id': client_id,
            'lead_changes': _dev_live_lead_changes[game_id]['count'],
            'status': game_status,
            'period': current_period,  # Current quarter for chart quarter markers
            'player_stats': player_stats_by_team,
            # Game clock, timeouts, and bonus info
            'game_clock': game_clock,
            'home_timeouts': home_timeouts,
            'away_timeouts': away_timeouts,
            'home_in_bonus': home_in_bonus,
            'away_in_bonus': away_in_bonus,
            # Quarter-by-quarter scores
            'home_periods': home_periods,
            'away_periods': away_periods,
            # History loading optimization
            'has_more_history': has_more_history,
            'history_cutoff_action': history_cutoff_action,
        }

        # Include score history on first load for chart reconstruction
        if last_action == 0 and plays:
            # Build full score history from all plays (not just accumulated)
            full_scores = []
            for p in plays:
                h = int(p.get('home_score', 0) or 0)
                aw = int(p.get('away_score', 0) or 0)
                if h > 0 or aw > 0:
                    # Only add if score changed
                    if not full_scores or full_scores[-1]['home'] != h or full_scores[-1]['away'] != aw:
                        clock = p.get('clock', '')
                        period = p.get('period', 1)
                        full_scores.append({
                            'home': h,
                            'away': aw,
                            'action': p.get('order', 0),
                            'period': period,
                            'clock': clock,
                            'elapsed': clock_to_elapsed_seconds(clock, period)
                        })
            if full_scores:
                response_data['scores'] = full_scores
                response_data['is_first_load'] = True

            # Save history for live games on first load (so subsequent loads are fast)
            if game_status != 'Final':
                history_to_save = {
                    'messages': all_messages,
                    'scores': full_scores,
                    'game_info': game_info,
                    'status': game_status,
                    'last_action': max_action,
                    'lead_changes': _dev_live_lead_changes.get(game_id, {}).get('count', 0),
                    'final_score': latest_score,
                    'total_actions': len(plays),
                    'player_stats': player_stats_by_team,
                }
                _dev_live_history[game_id] = history_to_save
                save_dev_live_history(game_id)
                print(f"Saved live game history for {game_id}: {len(all_messages)} messages")

        return jsonify(response_data)

    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5001)
