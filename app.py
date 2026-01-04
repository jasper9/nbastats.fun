from flask import Flask, render_template, jsonify, request
import calendar
import json
import math
import os
import re
import requests
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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

# Make GA tracking ID available to all templates
@app.context_processor
def inject_ga():
    return {'ga_tracking_id': os.getenv('GA_TRACKING_ID')}


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

    # Extract schedule
    upcoming_games = schedule_cache.get('games', []) if schedule_cache else []
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

    return render_template('jokic.html',
        career_totals=career_totals,
        jokic_ranks=jokic_ranks,
        records_watch=records_watch,
        triple_doubles=triple_doubles,
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

    return render_template('more.html',
        roster=roster,
        recent_games=recent_games,
        jokic_stats=jokic_stats,
        injuries=injuries,
        contracts=contracts,
        salary_cap=salary_cap,
        current_year=current_year,
        cache_time=cache_time
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


@app.route('/live/<game_id>')
def live_history(game_id):
    """View historical live data for a specific game."""
    history = load_live_history(game_id)
    if not history:
        return "Game history not found", 404
    return render_template('live_history.html', history=history)


if __name__ == '__main__':
    app.run(debug=True, port=5001)
