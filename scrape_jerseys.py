#!/usr/bin/env python3
"""
One-time script to parse jersey schedule from NBA LockerVision
and save to data/jersey_schedule.json

Data scraped from https://lockervision.nba.com/team/denver-nuggets on 2026-01-03
"""

import json
import re
from pathlib import Path

# Raw text extracted from LockerVision page
RAW_DATA = """
Denver NuggetsBrooklyn NetsAssociation EditionATIcon EditionShopShop Barclays CenterBrooklynSUN, JAN 4, 202603:30 PM EST
Denver NuggetsPhiladelphia 76ersAssociation EditionATIcon EditionShopShop Wells Fargo CenterPhiladelphiaMON, JAN 5, 202608:30 PM EST
Denver NuggetsBoston CelticsIcon EditionATCity EditionShopShop TD GardenBostonWED, JAN 7, 202607:00 PM EST
Atlanta HawksDenver NuggetsAssociation EditionATIcon EditionShopShop Ball ArenaDenverFRI, JAN 9, 202609:00 PM EST
Milwaukee BucksDenver NuggetsAssociation EditionATStatement EditionShopShop Ball ArenaDenverSUN, JAN 11, 202608:00 PM EST
Denver NuggetsNew Orleans PelicansStatement EditionATAssociation EditionShopShop Smoothie King CenterNew OrleansTUE, JAN 13, 202608:00 PM EST
Denver NuggetsDallas MavericksAssociation EditionATCity EditionShopShop American Airlines CenterDallasWED, JAN 14, 202609:30 PM EST
Washington WizardsDenver NuggetsAssociation EditionATCity EditionShopShop Ball ArenaDenverSAT, JAN 17, 202609:00 PM EST
Charlotte HornetsDenver NuggetsAssociation EditionATStatement EditionShopShop Ball ArenaDenverSUN, JAN 18, 202608:00 PM EST
Los Angeles LakersDenver NuggetsIcon EditionATIcon EditionShopShop Ball ArenaDenverTUE, JAN 20, 202610:00 PM EST
Denver NuggetsWashington WizardsAssociation EditionATStatement EditionShopShop Capital One ArenaWashingtonTHU, JAN 22, 202607:00 PM EST
Denver NuggetsMilwaukee BucksAssociation EditionATStatement EditionShopShop Fiserv ForumMilwaukeeFRI, JAN 23, 202608:00 PM EST
Denver NuggetsMemphis GrizzliesStatement EditionATCity EditionShopShop FedExForumMemphisSUN, JAN 25, 202603:30 PM EST
Detroit PistonsDenver NuggetsAssociation EditionATIcon EditionShopShop Ball ArenaDenverTUE, JAN 27, 202609:00 PM EST
Brooklyn NetsDenver NuggetsStatement EditionATAssociation EditionShopShop Ball ArenaDenverTHU, JAN 29, 202609:00 PM EST
Los Angeles ClippersDenver NuggetsAssociation EditionATCity EditionShopShop Ball ArenaDenverFRI, JAN 30, 202610:00 PM EST
Oklahoma City ThunderDenver NuggetsStatement EditionATStatement EditionShopShop Ball ArenaDenverSUN, FEB 1, 202609:30 PM EST
Denver NuggetsDetroit PistonsAssociation EditionATIcon EditionShopShop Little Caesars ArenaDetroitTUE, FEB 3, 202607:00 PM EST
Denver NuggetsNew York KnicksCity EditionATAssociation EditionShopShop Madison Square GardenNew YorkWED, FEB 4, 202607:00 PM EST
Denver NuggetsChicago BullsCity EditionATAssociation EditionShopShop United CenterChicagoSAT, FEB 7, 202608:00 PM EST
Cleveland CavaliersDenver NuggetsAssociation EditionATStatement EditionShopShop Ball ArenaDenverMON, FEB 9, 202609:00 PM EST
Memphis GrizzliesDenver NuggetsCity EditionATCity EditionShopShop Ball ArenaDenverWED, FEB 11, 202610:00 PM EST
Denver NuggetsLos Angeles ClippersStatement EditionATAssociation EditionShopShop Intuit DomeLos AngelesTHU, FEB 19, 202610:30 PM EST
Denver NuggetsPortland Trail BlazersAssociation EditionATIcon EditionShopShop Moda CenterPortlandFRI, FEB 20, 202610:00 PM EST
Denver NuggetsGolden State WarriorsAssociation EditionATStatement EditionShopShop Chase CenterSan FranciscoSUN, FEB 22, 202603:30 PM EST
Boston CelticsDenver NuggetsCity EditionATIcon EditionShopShop Ball ArenaDenverWED, FEB 25, 202610:00 PM EST
Denver NuggetsOklahoma City ThunderAssociation EditionATCity EditionShopShop Paycom CenterOklahoma CityFRI, FEB 27, 202609:30 PM EST
Minnesota TimberwolvesDenver NuggetsAssociation EditionATStatement EditionShopShop Ball ArenaDenverSUN, MAR 1, 202603:30 PM EST
Denver NuggetsUtah JazzAssociation EditionATStatement EditionShopShop Delta CenterSalt Lake CityMON, MAR 2, 202609:00 PM EST
Los Angeles LakersDenver NuggetsIcon EditionATIcon EditionShopShop Ball ArenaDenverTHU, MAR 5, 202610:00 PM EST
New York KnicksDenver NuggetsAssociation EditionATCity EditionShopShop Ball ArenaDenverFRI, MAR 6, 202609:00 PM EST
Denver NuggetsOklahoma City ThunderAssociation EditionATIcon EditionShopShop Paycom CenterOklahoma CityMON, MAR 9, 202607:30 PM EST
Houston RocketsDenver NuggetsAssociation EditionATStatement EditionShopShop Ball ArenaDenverWED, MAR 11, 202610:00 PM EST
Denver NuggetsSan Antonio SpursAssociation EditionATIcon EditionShopShop Frost Bank CenterSan AntonioTHU, MAR 12, 202609:00 PM EST
Denver NuggetsLos Angeles LakersAssociation EditionATIcon EditionShopShop Crypto.com ArenaLos AngelesSAT, MAR 14, 202608:30 PM EST
Philadelphia 76ersDenver NuggetsAssociation EditionATCity EditionShopShop Ball ArenaDenverTUE, MAR 17, 202609:00 PM EST
Toronto RaptorsDenver NuggetsIcon EditionATStatement EditionShopShop Ball ArenaDenverFRI, MAR 20, 202609:00 PM EST
Portland Trail BlazersDenver NuggetsStatement EditionATStatement EditionShopShop Ball ArenaDenverSUN, MAR 22, 202605:00 PM EST
Denver NuggetsPhoenix SunsAssociation EditionATIcon EditionShopShop PHX ArenaPhoenixTUE, MAR 24, 202611:00 PM EST
Dallas MavericksDenver NuggetsAssociation EditionATIcon EditionShopShop Ball ArenaDenverWED, MAR 25, 202610:00 PM EST
Utah JazzDenver NuggetsAssociation EditionATIcon EditionShopShop Ball ArenaDenverFRI, MAR 27, 202609:00 PM EST
Golden State WarriorsDenver NuggetsAssociation EditionATStatement EditionShopShop Ball ArenaDenverSUN, MAR 29, 202610:00 PM EST
Denver NuggetsUtah JazzAssociation EditionATIcon EditionShopShop Delta CenterSalt Lake CityWED, APR 1, 202609:00 PM EST
San Antonio SpursDenver NuggetsAssociation EditionATCity EditionShopShop Ball ArenaDenverSAT, APR 4, 202603:00 PM EST
Portland Trail BlazersDenver NuggetsAssociation EditionATIcon EditionShopShop Ball ArenaDenverMON, APR 6, 202609:00 PM EST
Memphis GrizzliesDenver NuggetsAssociation EditionATIcon EditionShopShop Ball ArenaDenverWED, APR 8, 202609:00 PM EST
Oklahoma City ThunderDenver NuggetsAssociation EditionATCity EditionShopShop Ball ArenaDenverFRI, APR 10, 202610:00 PM EST
Denver NuggetsSan Antonio SpursStatement EditionATAssociation EditionShopShop Frost Bank CenterSan AntonioSUN, APR 12, 202608:30 PM EST
"""

# Month abbreviation to number
MONTH_MAP = {
    'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
    'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
}

def parse_game_line(line):
    """Parse a single game line into structured data."""
    # Pattern to extract date
    date_pattern = r'([A-Z]{3}), ([A-Z]{3}) (\d+), (\d{4})'
    date_match = re.search(date_pattern, line)

    if not date_match:
        return None

    day_of_week, month_abbr, day, year = date_match.groups()
    month_num = MONTH_MAP.get(month_abbr, 0)
    date_str = f"{year}-{month_num:02d}-{int(day):02d}"

    # Determine if home or away (Ball Arena = home)
    is_home = 'Ball ArenaDenver' in line

    # Extract jersey editions - pattern: "Edition" appears twice
    editions = re.findall(r'(Association|Icon|Statement|City) Edition', line)

    if len(editions) >= 2:
        if is_home:
            # For home games, Nuggets jersey is the second one (after AT)
            nuggets_jersey = editions[1]
        else:
            # For away games, Nuggets jersey is the first one (before AT)
            nuggets_jersey = editions[0]
    else:
        nuggets_jersey = editions[0] if editions else "Unknown"

    # Extract opponent from the line
    # The opponent is the team that isn't Denver Nuggets
    teams_pattern = r'(Atlanta Hawks|Boston Celtics|Brooklyn Nets|Charlotte Hornets|Chicago Bulls|Cleveland Cavaliers|Dallas Mavericks|Detroit Pistons|Golden State Warriors|Houston Rockets|Indiana Pacers|Los Angeles Clippers|Los Angeles Lakers|Memphis Grizzlies|Miami Heat|Milwaukee Bucks|Minnesota Timberwolves|New Orleans Pelicans|New York Knicks|Oklahoma City Thunder|Orlando Magic|Philadelphia 76ers|Phoenix Suns|Portland Trail Blazers|Sacramento Kings|San Antonio Spurs|Toronto Raptors|Utah Jazz|Washington Wizards)'
    teams = re.findall(teams_pattern, line)
    opponent = teams[0] if teams else "Unknown"

    return {
        'date': date_str,
        'opponent': opponent,
        'is_home': is_home,
        'nuggets_jersey': nuggets_jersey
    }


def main():
    games = []
    jersey_schedule = {}

    for line in RAW_DATA.strip().split('\n'):
        line = line.strip()
        if not line:
            continue

        game = parse_game_line(line)
        if game:
            games.append(game)
            jersey_schedule[game['date']] = {
                'opponent': game['opponent'],
                'is_home': game['is_home'],
                'jersey': game['nuggets_jersey']
            }

    # Save to file
    data_file = Path(__file__).parent / 'data' / 'jersey_schedule.json'

    output = {
        '_comment': 'Nuggets jersey schedule from NBA LockerVision. Scraped 2026-01-03.',
        '_source': 'https://lockervision.nba.com/team/denver-nuggets',
        'schedule': jersey_schedule
    }

    with open(data_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Saved {len(jersey_schedule)} games to {data_file}")

    # Summary by jersey type
    jersey_counts = {}
    for game in jersey_schedule.values():
        j = game['jersey']
        jersey_counts[j] = jersey_counts.get(j, 0) + 1

    print("\nJersey breakdown:")
    for jersey, count in sorted(jersey_counts.items()):
        print(f"  {jersey}: {count} games")


if __name__ == '__main__':
    main()
