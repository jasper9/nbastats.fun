#!/usr/bin/env python3
"""
Refresh all cached data for the NBA stats app.
Run this manually or set up a cron job (e.g., daily at 6am):
    0 6 * * * cd /path/to/nba_fun && ./venv/bin/python refresh_cache.py
"""

import json
import time
from datetime import datetime
from pathlib import Path

CACHE_DIR = Path(__file__).parent / 'cache'
JOKIC_PLAYER_ID = 203999


def ensure_cache_dir():
    CACHE_DIR.mkdir(exist_ok=True)


def save_cache(filename, data):
    """Save data to a cache file with timestamp."""
    data['_cached_at'] = datetime.now().isoformat()
    with open(CACHE_DIR / filename, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  Saved {filename}")


def refresh_jokic_career_stats():
    """Cache Jokic's career statistics."""
    print("\n[1/5] Fetching Jokic career stats...")
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
    print("\n[2/5] Fetching team standings...")
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
    print("\n[3/5] Fetching all-time records...")
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


def refresh_triple_doubles():
    """Cache triple-double data for all tracked players."""
    print("\n[4/5] Fetching triple-double data...")
    from nba_api.stats.endpoints import playergamelogs

    PLAYERS_TO_TRACK = [
        (201566, 'Russell Westbrook', True, list(range(2008, 2026))),
        (203999, 'Nikola Jokić', True, list(range(2015, 2026))),
        (2544, 'LeBron James', True, list(range(2003, 2026))),
        (201935, 'James Harden', True, list(range(2009, 2026))),
        (1629029, 'Luka Dončić', True, list(range(2018, 2026))),
    ]

    HISTORICAL_PLAYERS = [
        {'player_id': 0, 'name': 'Oscar Robertson', 'total': 181, 'active': False},
        {'player_id': 0, 'name': 'Magic Johnson', 'total': 138, 'active': False},
        {'player_id': 0, 'name': 'Jason Kidd', 'total': 107, 'active': False},
        {'player_id': 0, 'name': 'Wilt Chamberlain', 'total': 78, 'active': False},
        {'player_id': 0, 'name': 'Larry Bird', 'total': 59, 'active': False},
        {'player_id': 0, 'name': 'Fat Lever', 'total': 43, 'active': False},
    ]

    results = []

    for player_id, name, is_active, seasons in PLAYERS_TO_TRACK:
        print(f"  Fetching {name}...", end=" ", flush=True)
        total_td = 0
        season_breakdown = []
        recent_games = []

        for year in seasons:
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

                # Recent games for Jokic
                if year == 2025 and player_id == JOKIC_PLAYER_ID:
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
                continue

        print(f"{total_td} triple-doubles")
        results.append({
            'player_id': player_id,
            'name': name,
            'total': total_td,
            'active': is_active,
            'season_breakdown': season_breakdown,
            'recent_games': recent_games
        })

    # Add historical players
    for hist in HISTORICAL_PLAYERS:
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
    """Cache league leaders for all stat categories."""
    print("\n[5/5] Fetching league leaders...")
    from nba_api.stats.endpoints import leagueleaders

    STAT_CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', 'FG_PCT', 'FG3_PCT',
                       'FT_PCT', 'EFF', 'FGM', 'FGA', 'FTM', 'FTA', 'OREB', 'DREB', 'MIN']

    all_leaders = {}

    for stat in STAT_CATEGORIES:
        try:
            print(f"  Fetching {stat}...", end=" ", flush=True)
            leaders = leagueleaders.LeagueLeaders(
                season='2025-26',
                stat_category_abbreviation=stat,
                timeout=60
            )
            df = leaders.league_leaders.get_data_frame()
            all_leaders[stat] = df.head(50).to_dict('records')
            print("OK")
            time.sleep(0.5)
        except Exception as e:
            print(f"Error: {e}")
            continue

    save_cache('league_leaders.json', {'leaders': all_leaders})
    return all_leaders


def main():
    print("=" * 60)
    print(f"NBA Stats Cache Refresh - {datetime.now().isoformat()}")
    print("=" * 60)

    ensure_cache_dir()

    # Refresh all data
    refresh_jokic_career_stats()
    time.sleep(1)

    refresh_team_standings()
    time.sleep(1)

    refresh_alltime_records()
    time.sleep(1)

    refresh_triple_doubles()
    time.sleep(1)

    refresh_league_leaders()

    print("\n" + "=" * 60)
    print("Cache refresh complete!")
    print(f"Cache files saved to: {CACHE_DIR}")
    print("=" * 60)


if __name__ == '__main__':
    main()
