from flask import Flask, render_template
import calendar
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

JOKIC_PLAYER_ID = 203999
CACHE_DIR = Path(__file__).parent / 'cache'

STAT_NAMES = {
    'PTS': 'Points',
    'REB': 'Rebounds',
    'AST': 'Assists',
    'STL': 'Steals',
    'BLK': 'Blocks',
    'FG_PCT': 'Field Goal %',
    'FG3_PCT': 'Three-Point %',
    'FT_PCT': 'Free Throw %',
    'EFF': 'Efficiency',
    'FGM': 'Field Goals Made',
    'FGA': 'Field Goals Attempted',
    'FTM': 'Free Throws Made',
    'FTA': 'Free Throws Attempted',
    'OREB': 'Offensive Rebounds',
    'DREB': 'Defensive Rebounds',
    'MIN': 'Minutes Played'
}

app = Flask(__name__)


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

    # Extract injuries
    injuries = injuries_cache.get('injuries', []) if injuries_cache else []

    # Get cache timestamp for display
    cache_time = career_cache.get('_cached_at', 'Unknown')

    # Current date for calendar highlighting (Mountain Time)
    mountain_tz = ZoneInfo('America/Denver')
    now_date = datetime.now(mountain_tz).strftime('%Y-%m-%d')

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
        injuries=injuries,
        now_date=now_date,
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

    # Mark injured players in roster
    injured_names = {inj['name'] for inj in injuries}
    for player in roster:
        player['is_injured'] = player['name'] in injured_names

    cache_time = roster_cache.get('_cached_at', 'Unknown') if roster_cache else 'Unknown'

    return render_template('more.html',
        roster=roster,
        recent_games=recent_games,
        jokic_stats=jokic_stats,
        injuries=injuries,
        contracts=contracts,
        salary_cap=salary_cap,
        cache_time=cache_time
    )


if __name__ == '__main__':
    app.run(debug=True, port=5001)
