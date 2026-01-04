# NBA Fun Project - Claude Code Guidelines

## Project Overview
A Flask-based dashboard for tracking Nikola Jokić and Denver Nuggets stats, standings, injuries, and betting odds. Deployed at nbastats.fun.

## Key Files

### Core Application
- `app.py` - Flask app with routes and template filters
- `templates/index.html` - Main dashboard (schedule, injuries, standings)
- `templates/jokic.html` - Dedicated Jokić page (career stats, triple-doubles, records)
- `templates/more.html` - Nuggets stats (roster, recent games, contracts)
- `templates/leaders.html` - League leaders by stat category

### Data Refresh
- `refresh_cache.py` - **Main script** - refreshes all data (run daily via cron)
- `refresh_balldontlie.py` - Module with BALLDONTLIE API functions (imported by refresh_cache.py)
- `refresh_odds.py` - Module with odds API functions (imported by refresh_cache.py)

### Cache Files (in `cache/`)
- `jokic_career.json` - Career stats and season rankings
- `nuggets_schedule.json` - Schedule with odds data
- `injuries.json` - Injury report with content change tracking
- `contracts.json` - Player contracts with extension info
- `standings.json`, `roster.json`, `recent_games.json`, etc.

### Static Data Files (in `data/`)
- `special_events.json` - Promotional events/giveaways for home games
- `jersey_schedule.json` - Uniform schedule for all remaining games

### One-Time Scraper Scripts
- `scrape_promotions.py` - Scrapes nuggets.com promotional schedule → `data/special_events.json`
- `scrape_jerseys.py` - Scrapes NBA LockerVision jersey schedule → `data/jersey_schedule.json`

## Development Conventions

### Git Commits
**ALWAYS make a git commit after completing a feature.** Don't wait for the user to ask.

Commit message format:
```
Short description of change

- Bullet point details
- What was added/changed

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
```

### Environment
- Use virtual environment: `source venv/bin/activate`
- Flask runs on port 5001: `python app.py`
- Environment variables in `.env` (GA_TRACKING_ID, API keys)

### API Keys (in .env)
- `ODDS_API_KEY` - the-odds-api.com
- `BALLDONTLIE_API_KEY` - balldontlie.io
- `GA_TRACKING_ID` - Google Analytics

## Data Sources

### NBA Stats API (via nba_api package)
- Career stats, season rankings, league leaders
- Historical data, all-time records

### BALLDONTLIE API
- **v1**: Games, roster, injuries, contracts
- **v2**: Betting odds (Polymarket, Kalshi vendors)

### the-odds-api.com
- Traditional sportsbook odds (DraftKings, FanDuel, etc.)
- Usually available closer to game time

## Feature Notes

### Odds Display
- Shows multiple bookmakers in comparison table
- Both providers stored in `odds_providers` dict
- Falls back to best available when single source
- Green highlighting + FAV badge for favorite team

### Injury Tracking
- MD5 hash comparison detects actual content changes
- `_content_changed_at` only updates when data changes
- Sorted by return date (earliest first)

### Contracts
- Captures both CURRENT and UPCOMING EXTENSION status
- Shows extension details with effective end year
- Highlights expiring contracts (current year)
- Shows "FREE AGENT" badge for players whose contracts have expired

### Special Events (Promotions)
- Static data in `data/special_events.json`
- Shows in game modal when clicking calendar games
- Types: giveaway, theme-night, city-edition, crossover, ticket-offer, nba-cup, special
- Gold banner displays event title and description
- One-time scrape from nuggets.com via `scrape_promotions.py`

### Jersey Schedule
- Static data in `data/jersey_schedule.json`
- Scraped from NBA LockerVision (lockervision.nba.com)
- Shows uniform type in game modal with official NBA jersey image
- Four edition types: Association (white), Icon (navy), Statement (red), City (rainbow)
- Images from NBA CDN: `appimages.nba.com/p/tr:n-slnfre/2025/uniform/Denver%20Nuggets/DEN_[AE|IE|SE|CE].jpg`
- **No cron needed** - jerseys are assigned for entire season upfront
- Re-run `scrape_jerseys.py` only at start of next season

## Testing Changes
1. Run Flask: `source venv/bin/activate && python app.py`
2. **Use Claude in Chrome extension** to visually verify UI changes at `http://localhost:5001`
   - Take screenshots to confirm layout/styling
   - Navigate between pages to test links
   - Check responsive behavior if needed
3. Check console/network for errors
4. Run refresh scripts to test data fetching

## Common Tasks

### Refresh all data
```bash
source venv/bin/activate
python refresh_cache.py
```

### Check API responses
```python
source venv/bin/activate
python -c "
import requests
import os
from dotenv import load_dotenv
load_dotenv()
# ... test API calls
"
```
