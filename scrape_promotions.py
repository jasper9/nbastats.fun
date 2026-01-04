#!/usr/bin/env python3
"""
One-time script to scrape promotional schedule from nuggets.com
and update data/special_events.json

Usage: python scrape_promotions.py
"""

import json
from pathlib import Path

# Data extracted from https://www.nba.com/nuggets/promotional-schedule
# Scraped on 2026-01-03
PROMOTIONS_RAW = """
October 25|Opening Night|vs. Phoenix, 7:00 PM tipoff
October 29|Filipino History Month|vs. New Orleans, 7:00 PM, special ticket offer
November 3|Grateful Dead Ticket Package|vs. Sacramento, 7:00 PM
November 7|NBA Cup Group Play|vs. Golden State, 8:00 PM
November 8|Military Appreciation Night|vs. Indiana, 7:00 PM
November 17|City Edition Debut|vs. Chicago, 7:00 PM
November 22|Native American Heritage Night|vs. Sacramento, 8:00 PM, Southwest-sponsored
November 28|NBA Cup Group Play|vs. San Antonio, 7:30 PM
December 1|Pride Night|vs. Dallas, 7:00 PM, Southwest-sponsored
December 18|Aaron Gordon Bobblehead Giveaway|vs. Orlando, First 5,000 Fans in Attendance, 7:00 PM
December 20|City Edition Night|vs. Houston, 3:00 PM
December 22|Hello Kitty Offer|vs. Utah, 7:00 PM
December 25|Christmas Day / City Edition|vs. Minnesota, 8:30 PM
January 9|Bruce Brown Bobblehead|vs. Atlanta, First 5,000 Fans in Attendance, 7:00 PM
January 17|CO Avalanche Crossover / City Edition|vs. Washington, 7:00 PM
January 18|Be A Good Person Offer|vs. Charlotte, 6:00 PM
January 27|CO Rockies Crossover|vs. Detroit, 7:00 PM
January 30|Serbian Heritage Ticket Package|vs. LA Clippers, 8:00 PM
February 9|Black Excellence Night|vs. Cleveland, 7:00 PM, Southwest-sponsored
February 11|CO Rapids Crossover / City Edition|vs. Memphis, 8:00 PM
March 1|AANHPI Heritage Night|vs. Minnesota, 1:30 PM, Southwest-sponsored
March 6|City Edition Night|vs. New York, 7:00 PM
March 11|Women's Empowerment Night|vs. Houston, 8:00 PM, Southwest-sponsored
March 17|Christian Braun Bobblehead / City Edition|vs. Philadelphia, First 5,000 Fans, 7:00 PM, Ball-presented
March 20|Somos Los Nuggets Night|vs. Toronto, 7:00 PM, Southwest-sponsored
March 22|Rocky's Birthday|vs. Portland, 3:00 PM
March 27|Special Olympics Colorado Night|vs. Utah, 7:00 PM
April 4|City Edition Night|vs. San Antonio, 1:00 PM
April 10|Nuggets Nation Appreciation / City Edition|vs. OKC, 7:00 PM
"""

# Month to number mapping
MONTH_MAP = {
    'January': 1, 'February': 2, 'March': 3, 'April': 4,
    'May': 5, 'June': 6, 'July': 7, 'August': 8,
    'September': 9, 'October': 10, 'November': 11, 'December': 12
}

# Event type categorization
def categorize_event(title):
    title_lower = title.lower()
    if 'bobblehead' in title_lower:
        return 'giveaway'
    elif 'night' in title_lower or 'heritage' in title_lower or 'appreciation' in title_lower:
        return 'theme-night'
    elif 'city edition' in title_lower:
        return 'city-edition'
    elif 'crossover' in title_lower:
        return 'crossover'
    elif 'offer' in title_lower or 'package' in title_lower:
        return 'ticket-offer'
    elif 'cup' in title_lower:
        return 'nba-cup'
    else:
        return 'special'


def parse_promotions():
    """Parse the raw promotions data into structured events."""
    events = {}

    for line in PROMOTIONS_RAW.strip().split('\n'):
        if not line.strip():
            continue

        parts = line.split('|')
        if len(parts) < 2:
            continue

        date_str = parts[0].strip()
        title = parts[1].strip()
        details = parts[2].strip() if len(parts) > 2 else ''

        # Parse month and day
        month_name, day = date_str.split()
        month_num = MONTH_MAP.get(month_name, 0)
        day_num = int(day)

        # Determine year (Oct-Dec = 2025, Jan-Apr = 2026)
        if month_num >= 10:
            year = 2025
        else:
            year = 2026

        date_key = f"{year}-{month_num:02d}-{day_num:02d}"

        # Build description from details
        description = details if details else None

        events[date_key] = {
            'title': title,
            'type': categorize_event(title)
        }
        if description:
            events[date_key]['description'] = description

    return events


def main():
    # Parse promotions
    events = parse_promotions()

    # Load existing file
    data_file = Path(__file__).parent / 'data' / 'special_events.json'

    if data_file.exists():
        with open(data_file, 'r') as f:
            existing = json.load(f)
    else:
        existing = {'_comment': 'Special events for Nuggets games', 'events': {}}

    # Merge new events (new ones override existing)
    existing['events'].update(events)

    # Sort by date
    sorted_events = dict(sorted(existing['events'].items()))
    existing['events'] = sorted_events

    # Save
    with open(data_file, 'w') as f:
        json.dump(existing, f, indent=2)

    print(f"Updated {data_file}")
    print(f"Total events: {len(sorted_events)}")
    print("\nEvents by type:")
    type_counts = {}
    for event in sorted_events.values():
        t = event.get('type', 'unknown')
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, count in sorted(type_counts.items()):
        print(f"  {t}: {count}")


if __name__ == '__main__':
    main()
