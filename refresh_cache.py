#!/usr/bin/env python3
"""
Refresh all cached data for the NBA stats app.
Run this manually or set up a cron job (e.g., daily at 6am):
    0 6 * * * cd /path/to/nba_fun && ./venv/bin/python refresh_cache.py
"""

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

MOUNTAIN_TZ = ZoneInfo('America/Denver')

load_dotenv()

CACHE_DIR = Path(__file__).parent / 'cache'
JOKIC_PLAYER_ID = 203999


def ensure_cache_dir():
    CACHE_DIR.mkdir(exist_ok=True)


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


def save_cache(filename, data):
    """Save data to a cache file with timestamp (atomic write)."""
    data['_cached_at'] = datetime.now().isoformat()
    atomic_write_json(CACHE_DIR / filename, data)
    print(f"  Saved {filename}")


def refresh_jokic_career_stats():
    """Cache Jokic's career statistics."""
    print("\n[Jokic Career] Fetching career stats...")
    from nba_api.stats.endpoints import playercareerstats

    career = playercareerstats.PlayerCareerStats(player_id=JOKIC_PLAYER_ID, timeout=60)

    data = {
        'regular_season': career.season_totals_regular_season.get_data_frame().to_dict('records'),
        'career_totals': career.career_totals_regular_season.get_data_frame().to_dict('records'),
        'playoffs': career.season_totals_post_season.get_data_frame().to_dict('records'),
        'playoff_totals': career.career_totals_post_season.get_data_frame().to_dict('records'),
        'season_rankings': career.season_rankings_regular_season.get_data_frame().to_dict('records'),
    }

    save_cache('jokic_career.json', data)
    return data


def refresh_team_standings():
    """Cache current team standings."""
    print("\n[Standings] Fetching team standings...")
    from nba_api.stats.endpoints import leaguestandings

    standings = leaguestandings.LeagueStandings(season='2025-26', timeout=60)
    df = standings.standings.get_data_frame()

    cols = ['TeamCity', 'TeamName', 'TeamID', 'Conference', 'PlayoffRank',
            'WINS', 'LOSSES', 'WinPCT', 'HOME', 'ROAD', 'L10',
            'strCurrentStreak', 'PointsPG', 'OppPointsPG', 'DiffPointsPG',
            'ConferenceGamesBack']

    df = df[cols].copy()

    data = {
        'east': df[df['Conference'] == 'East'].sort_values('PlayoffRank').to_dict('records'),
        'west': df[df['Conference'] == 'West'].sort_values('PlayoffRank').to_dict('records'),
    }

    save_cache('standings.json', data)
    return data


def refresh_alltime_records():
    """Cache all-time records watch data."""
    print("\n[All-Time Records] Fetching all-time records...")
    from nba_api.stats.endpoints import alltimeleadersgrids

    try:
        leaders = alltimeleadersgrids.AllTimeLeadersGrids(
            per_mode_simple='Totals',
            topx=200,
            timeout=120
        )
    except Exception as e:
        print(f"  Error fetching all-time leaders: {e}")
        return None

    stats_to_check = [
        ('Points', 'pts_leaders', 'PTS'),
        ('Rebounds', 'reb_leaders', 'REB'),
        ('Assists', 'ast_leaders', 'AST'),
        ('Steals', 'stl_leaders', 'STL'),
        ('Blocks', 'blk_leaders', 'BLK'),
        ('Field Goals Made', 'fgm_leaders', 'FGM'),
        ('Def Rebounds', 'dreb_leaders', 'DREB'),
        ('3-Pointers Made', 'fg3_m_leaders', 'FG3M'),
    ]

    results = []

    for stat_name, attr_name, col_name in stats_to_check:
        try:
            df = getattr(leaders, attr_name).get_data_frame()
            jokic_row = df[df['PLAYER_ID'] == JOKIC_PLAYER_ID]

            if not jokic_row.empty:
                rank = int(jokic_row.iloc[0][f'{col_name}_RANK'])
                value = int(jokic_row.iloc[0][col_name])

                ahead = df[df[f'{col_name}_RANK'] < rank].sort_values(
                    f'{col_name}_RANK', ascending=False
                ).head(3)

                ahead_list = []
                for _, row in ahead.iterrows():
                    gap = int(row[col_name]) - value
                    ahead_list.append({
                        'name': row['PLAYER_NAME'],
                        'rank': int(row[f'{col_name}_RANK']),
                        'value': int(row[col_name]),
                        'gap': gap,
                        'active': row['IS_ACTIVE_FLAG'] == 'Y'
                    })

                # Get 3 players behind Jokic
                behind = df[df[f'{col_name}_RANK'] > rank].sort_values(
                    f'{col_name}_RANK', ascending=True
                ).head(3)

                behind_list = []
                for _, row in behind.iterrows():
                    gap = value - int(row[col_name])
                    behind_list.append({
                        'name': row['PLAYER_NAME'],
                        'rank': int(row[f'{col_name}_RANK']),
                        'value': int(row[col_name]),
                        'gap': gap,
                        'active': row['IS_ACTIVE_FLAG'] == 'Y'
                    })

                results.append({
                    'stat': stat_name,
                    'col': col_name,
                    'rank': rank,
                    'value': value,
                    'ahead': ahead_list,
                    'behind': behind_list
                })
        except Exception as e:
            print(f"  Error processing {stat_name}: {e}")
            continue

    # Sort by smallest gap
    results.sort(key=lambda x: x['ahead'][0]['gap'] if x['ahead'] else 9999)

    save_cache('alltime_records.json', {'records': results})
    return results


def get_triple_doubles_baseline():
    """Get or create baseline triple-double data (historical + past seasons).

    This only needs to be refreshed once at the start of each new season.
    Run with: python -c "from refresh_cache import refresh_triple_doubles_baseline; refresh_triple_doubles_baseline()"
    """
    baseline_file = CACHE_DIR / 'triple_doubles_baseline.json'
    if baseline_file.exists():
        with open(baseline_file, 'r') as f:
            return json.load(f)
    return None


def refresh_triple_doubles_baseline():
    """Rebuild the baseline cache (all seasons BEFORE current season).

    Run this once at the start of each new season to update historical totals.
    """
    print("\n[BASELINE] Fetching all historical triple-double data...")
    from nba_api.stats.endpoints import playergamelogs

    CURRENT_SEASON_YEAR = 2025  # Update this each season

    # Active players with their first NBA season year
    ACTIVE_PLAYERS = [
        (201566, 'Russell Westbrook', 2008),
        (203999, 'Nikola Jokić', 2015),
        (2544, 'LeBron James', 2003),
        (201935, 'James Harden', 2009),
        (1629029, 'Luka Dončić', 2018),
    ]

    # Historical players (stats never change)
    HISTORICAL_PLAYERS = [
        {'player_id': 0, 'name': 'Oscar Robertson', 'total': 181, 'active': False, 'season_breakdown': []},
        {'player_id': 0, 'name': 'Magic Johnson', 'total': 138, 'active': False, 'season_breakdown': []},
        {'player_id': 0, 'name': 'Jason Kidd', 'total': 107, 'active': False, 'season_breakdown': []},
        {'player_id': 0, 'name': 'Wilt Chamberlain', 'total': 78, 'active': False, 'season_breakdown': []},
        {'player_id': 0, 'name': 'Larry Bird', 'total': 59, 'active': False, 'season_breakdown': []},
        {'player_id': 0, 'name': 'Fat Lever', 'total': 43, 'active': False, 'season_breakdown': []},
    ]

    baseline = {'active': {}, 'historical': HISTORICAL_PLAYERS}

    for player_id, name, first_season in ACTIVE_PLAYERS:
        print(f"  Fetching {name} (all seasons before {CURRENT_SEASON_YEAR}-{str(CURRENT_SEASON_YEAR+1)[-2:]})...", end=" ", flush=True)
        total_td = 0
        season_breakdown = []

        for year in range(first_season, CURRENT_SEASON_YEAR):  # Up to but NOT including current season
            season = f"{year}-{str(year+1)[-2:]}"
            try:
                logs = playergamelogs.PlayerGameLogs(
                    player_id_nullable=player_id,
                    season_nullable=season,
                    season_type_nullable='Regular Season',
                    timeout=60
                )
                df = logs.player_game_logs.get_data_frame()

                if df.empty:
                    continue

                td_count = int(df['TD3'].sum()) if 'TD3' in df.columns else 0
                if td_count > 0:
                    total_td += td_count
                    season_breakdown.append({'season': season, 'count': td_count})

                time.sleep(0.4)
            except Exception as e:
                print(f"Error {season}: {e}")
                continue

        print(f"{total_td} triple-doubles")
        baseline['active'][str(player_id)] = {
            'player_id': player_id,
            'name': name,
            'baseline_total': total_td,
            'season_breakdown': season_breakdown,
        }

    # Save baseline
    ensure_cache_dir()
    baseline['_created_at'] = datetime.now().isoformat()
    baseline['_current_season'] = f"{CURRENT_SEASON_YEAR}-{str(CURRENT_SEASON_YEAR+1)[-2:]}"
    atomic_write_json(CACHE_DIR / 'triple_doubles_baseline.json', baseline)
    print(f"  Saved triple_doubles_baseline.json")
    return baseline


def refresh_triple_doubles():
    """Cache triple-double data - only fetches CURRENT SEASON for active players."""
    print("\n[Triple-Doubles] Fetching triple-double data (current season only)...")
    from nba_api.stats.endpoints import playergamelogs

    CURRENT_SEASON = "2025-26"
    CURRENT_SEASON_YEAR = 2025

    # Load baseline data
    baseline = get_triple_doubles_baseline()
    if not baseline:
        print("  WARNING: No baseline found. Run refresh_triple_doubles_baseline() first.")
        print("  Falling back to full refresh...")
        return refresh_triple_doubles_baseline()

    ACTIVE_PLAYERS = [
        (201566, 'Russell Westbrook'),
        (203999, 'Nikola Jokić'),
        (2544, 'LeBron James'),
        (201935, 'James Harden'),
        (1629029, 'Luka Dončić'),
    ]

    results = []

    for player_id, name in ACTIVE_PLAYERS:
        print(f"  Fetching {name} ({CURRENT_SEASON})...", end=" ", flush=True)

        # Get baseline data for this player
        player_baseline = baseline['active'].get(str(player_id), {})
        baseline_total = player_baseline.get('baseline_total', 0)
        baseline_breakdown = player_baseline.get('season_breakdown', [])

        current_season_td = 0
        recent_games = []

        try:
            logs = playergamelogs.PlayerGameLogs(
                player_id_nullable=player_id,
                season_nullable=CURRENT_SEASON,
                season_type_nullable='Regular Season',
                timeout=60
            )
            df = logs.player_game_logs.get_data_frame()

            if not df.empty and 'TD3' in df.columns:
                current_season_td = int(df['TD3'].sum())

                # Recent games for Jokic
                if player_id == JOKIC_PLAYER_ID:
                    td_games = df[df['TD3'] == 1]
                    for _, game in td_games.head(10).iterrows():
                        recent_games.append({
                            'date': str(game['GAME_DATE'])[:10],
                            'matchup': game['MATCHUP'],
                            'pts': int(game['PTS']),
                            'reb': int(game['REB']),
                            'ast': int(game['AST'])
                        })

            time.sleep(0.4)
        except Exception as e:
            print(f"Error: {e}")

        total_td = baseline_total + current_season_td
        print(f"{total_td} ({baseline_total} + {current_season_td} this season)")

        # Combine baseline breakdown with current season
        season_breakdown = list(baseline_breakdown)
        if current_season_td > 0:
            season_breakdown.append({'season': CURRENT_SEASON, 'count': current_season_td})

        results.append({
            'player_id': player_id,
            'name': name,
            'total': total_td,
            'active': True,
            'season_breakdown': season_breakdown,
            'recent_games': recent_games
        })

    # Add historical players from baseline
    for hist in baseline.get('historical', []):
        results.append(hist)

    # Sort and rank
    results.sort(key=lambda x: x['total'], reverse=True)
    for i, player in enumerate(results):
        player['rank'] = i + 1

    # Jokic-specific data
    jokic = next((p for p in results if p.get('player_id') == JOKIC_PLAYER_ID), None)
    jokic_data = {}
    if jokic:
        ahead = [p for p in results if p['total'] > jokic['total']]
        if ahead:
            next_player = ahead[-1]
            jokic_data = {
                'total': jokic['total'],
                'rank': jokic['rank'],
                'season_breakdown': jokic.get('season_breakdown', []),
                'recent_games': jokic.get('recent_games', []),
                'to_next': next_player['total'] - jokic['total'],
                'next_player': next_player['name'],
                'to_record': results[0]['total'] - jokic['total'] + 1,
            }

    save_cache('triple_doubles.json', {'players': results, 'jokic': jokic_data})
    return results


def refresh_league_leaders():
    """Cache league leaders for all stat categories (per-game averages)."""
    print("\n[League Leaders] Fetching league leaders...")
    from nba_api.stats.endpoints import leagueleaders

    JOKIC_PLAYER_ID = 203999
    STAT_CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', 'FG_PCT', 'FG3_PCT',
                       'FT_PCT', 'EFF', 'FGM', 'FGA', 'FTM', 'FTA', 'OREB', 'DREB', 'MIN']
    # Percentage stats only work with Totals mode, not PerGame
    PCT_STATS = {'FG_PCT', 'FG3_PCT', 'FT_PCT'}

    all_leaders = {}
    jokic_ranks = {}  # Track Jokic's rank in each category

    for stat in STAT_CATEGORIES:
        try:
            # Use Totals mode for percentage stats, PerGame for everything else
            per_mode = 'Totals' if stat in PCT_STATS else 'PerGame'
            print(f"  Fetching {stat} ({per_mode})...", end=" ", flush=True)
            leaders = leagueleaders.LeagueLeaders(
                season='2025-26',
                stat_category_abbreviation=stat,
                per_mode48=per_mode,
                timeout=60
            )
            df = leaders.league_leaders.get_data_frame()
            all_leaders[stat] = df.head(50).to_dict('records')

            # Find Jokic's rank and value in this category
            jokic_row = df[df['PLAYER_ID'] == JOKIC_PLAYER_ID]
            if not jokic_row.empty:
                rank = int(jokic_row.iloc[0]['RANK'])
                value = float(jokic_row.iloc[0][stat]) if stat in jokic_row.columns else None
                jokic_ranks[stat] = {'rank': rank, 'value': value}

            print("OK")
            time.sleep(0.5)
        except Exception as e:
            print(f"Error: {e}")
            continue

    save_cache('league_leaders.json', {'leaders': all_leaders, 'jokic_ranks': jokic_ranks})
    return all_leaders


def refresh_nuggets_schedule():
    """Fetch upcoming Nuggets games with betting odds."""
    print("\n[Schedule] Fetching Nuggets schedule...")

    NUGGETS_TEAM_ID = 1610612743
    nuggets_games = []

    # Load existing schedule to preserve balldontlie_id mappings
    existing_schedule = {}
    existing_calendar = {}
    schedule_file = CACHE_DIR / 'nuggets_schedule.json'
    if schedule_file.exists():
        with open(schedule_file, 'r') as f:
            existing_data = json.load(f)
            # Build lookup by NBA game ID and by local_date
            for game in existing_data.get('games', []):
                if game.get('id'):
                    existing_schedule[game['id']] = game
                if game.get('local_date'):
                    existing_calendar[game['local_date']] = game
            for game in existing_data.get('calendar_games', []):
                if game.get('id'):
                    existing_schedule[game['id']] = game
                if game.get('local_date'):
                    existing_calendar[game['local_date']] = game

    # Also check live_history files for balldontlie_id mappings
    live_history_dir = CACHE_DIR / 'live_history'
    history_mappings = {}  # local_date -> balldontlie_id
    if live_history_dir.exists():
        for history_file in live_history_dir.glob('game_*.json'):
            try:
                with open(history_file, 'r') as f:
                    history_data = json.load(f)
                    # game_id is the balldontlie_id, date is in game_info
                    game_date = history_data.get('game_info', {}).get('date')
                    game_id = history_data.get('game_id')
                    if game_date and game_id:
                        history_mappings[game_date] = game_id
            except Exception:
                pass

    # Load standings for team records
    standings_cache = None
    standings_file = CACHE_DIR / 'standings.json'
    if standings_file.exists():
        with open(standings_file, 'r') as f:
            standings_cache = json.load(f)

    # Build team records lookup
    team_records = {}
    if standings_cache:
        for conf in ['east', 'west']:
            for team in standings_cache.get(conf, []):
                full_name = f"{team['TeamCity']} {team['TeamName']}"
                team_records[full_name] = {
                    'wins': team['WINS'],
                    'losses': team['LOSSES'],
                }

    # Step 1: Fetch NBA schedule
    try:
        print("  Fetching NBA schedule...")
        schedule_resp = requests.get(
            'https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json',
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=30
        )
        schedule_resp.raise_for_status()
        schedule_data = schedule_resp.json()

        now = datetime.now()

        # Full season calendar - NBA season runs Oct to Apr/May
        # For 2025-26 season: Oct 2025 to June 2026 (including playoffs)
        if now.month >= 10:  # Oct-Dec: current season started
            calendar_start = datetime(now.year, 10, 1)
            calendar_end = datetime(now.year + 1, 7, 1)  # Through June
        else:  # Jan-Sep: current season started last year
            calendar_start = datetime(now.year - 1, 10, 1)
            calendar_end = datetime(now.year, 7, 1)  # Through June

        all_nuggets_games = []

        # Find all Nuggets games in the season
        for game_date in schedule_data.get('leagueSchedule', {}).get('gameDates', []):
            for game in game_date.get('games', []):
                home_id = game.get('homeTeam', {}).get('teamId')
                away_id = game.get('awayTeam', {}).get('teamId')

                if home_id == NUGGETS_TEAM_ID or away_id == NUGGETS_TEAM_ID:
                    game_time_str = game.get('gameDateTimeUTC', '')
                    if game_time_str:
                        try:
                            game_time = datetime.fromisoformat(game_time_str.replace('Z', '+00:00'))
                            game_time_naive = game_time.replace(tzinfo=None)

                            # Check if game is in our season range
                            if calendar_start <= game_time_naive < calendar_end:
                                home_team = game.get('homeTeam', {})
                                away_team = game.get('awayTeam', {})
                                home_name = f"{home_team.get('teamCity', '')} {home_team.get('teamName', '')}".strip()
                                away_name = f"{away_team.get('teamCity', '')} {away_team.get('teamName', '')}".strip()

                                # Get game result if completed
                                home_score = game.get('homeTeam', {}).get('score')
                                away_score = game.get('awayTeam', {}).get('score')
                                game_status = game.get('gameStatus', 1)  # 1=scheduled, 2=in progress, 3=final

                                # Convert to Mountain Time for calendar display
                                game_time_mt = game_time.astimezone(MOUNTAIN_TZ)
                                local_date = game_time_mt.strftime('%Y-%m-%d')

                                game_data = {
                                    'id': game.get('gameId'),
                                    'commence_time': game_time_str,
                                    'local_date': local_date,  # Mountain Time date for calendar
                                    'home_team': home_name,
                                    'away_team': away_name,
                                    'is_home': home_id == NUGGETS_TEAM_ID,
                                    'home_record': team_records.get(home_name, {}),
                                    'away_record': team_records.get(away_name, {}),
                                    'is_past': game_time_naive < now,
                                    'game_status': game_status,
                                }

                                # Add scores for completed games
                                if game_status == 3 and home_score is not None:
                                    game_data['home_score'] = home_score
                                    game_data['away_score'] = away_score
                                    nuggets_score = home_score if home_id == NUGGETS_TEAM_ID else away_score
                                    opponent_score = away_score if home_id == NUGGETS_TEAM_ID else home_score
                                    game_data['result'] = 'W' if nuggets_score > opponent_score else 'L'

                                # Preserve balldontlie_id from existing schedule or history files
                                game_id = game.get('gameId')
                                existing = existing_schedule.get(game_id) or existing_calendar.get(local_date)
                                if existing and existing.get('balldontlie_id'):
                                    game_data['balldontlie_id'] = existing['balldontlie_id']
                                elif local_date in history_mappings:
                                    game_data['balldontlie_id'] = history_mappings[local_date]

                                all_nuggets_games.append(game_data)
                        except ValueError:
                            continue

        # Sort by game time
        all_nuggets_games.sort(key=lambda x: x['commence_time'])

        # Separate upcoming and all games
        nuggets_games = [g for g in all_nuggets_games if not g.get('is_past')][:10]

        print(f"  Found {len(nuggets_games)} upcoming games, {len(all_nuggets_games)} total in calendar range")

    except Exception as e:
        print(f"  Error fetching NBA schedule: {e}")
        return None

    # Note: Odds are fetched separately by refresh_odds.py (daily)
    # to conserve API quota (500 requests/month)

    save_cache('nuggets_schedule.json', {
        'games': nuggets_games,
        'calendar_games': all_nuggets_games,
    })
    return nuggets_games


def main():
    """
    Full cache refresh - runs hourly, daily, and weekly refreshes.

    For scheduled refreshes, use the individual scripts:
    - refresh_hourly.py: standings, recent games (run every hour)
    - refresh_daily.py: stats, schedule, odds, injuries (run daily)
    - refresh_weekly.py: roster, contracts, salary cap (run weekly)
    """
    print("=" * 60)
    print(f"FULL Cache Refresh - {datetime.now().isoformat()}")
    print("=" * 60)

    ensure_cache_dir()

    # === HOURLY DATA ===
    print("\n" + "-" * 40)
    print("HOURLY DATA")
    print("-" * 40)

    refresh_team_standings()
    time.sleep(1)

    from refresh_balldontlie import (
        refresh_injuries,
        refresh_roster,
        refresh_recent_games,
        refresh_jokic_stats,
        refresh_contracts,
        refresh_salary_cap_status,
    )

    refresh_recent_games()
    time.sleep(1)

    # === DAILY DATA ===
    print("\n" + "-" * 40)
    print("DAILY DATA")
    print("-" * 40)

    refresh_jokic_career_stats()
    time.sleep(1)

    refresh_alltime_records()
    time.sleep(1)

    refresh_triple_doubles()
    time.sleep(1)

    refresh_league_leaders()
    time.sleep(1)

    refresh_nuggets_schedule()
    time.sleep(1)

    from refresh_odds import refresh_odds
    refresh_odds()
    time.sleep(1)

    refresh_injuries()
    time.sleep(1)

    refresh_jokic_stats()
    time.sleep(1)

    # === WEEKLY DATA ===
    print("\n" + "-" * 40)
    print("WEEKLY DATA")
    print("-" * 40)

    refresh_roster()
    time.sleep(1)

    refresh_contracts()
    time.sleep(1)

    refresh_salary_cap_status()

    print("\n" + "=" * 60)
    print("Full cache refresh complete!")
    print(f"Cache files saved to: {CACHE_DIR}")
    print("=" * 60)


if __name__ == '__main__':
    main()
