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
- `templates/live.html` - Live game win probability tracker

### Data Refresh Scripts
- `refresh_cache.py` - **Full refresh** - runs all data refreshes (for manual use)
- `refresh_hourly.py` - Standings, recent games (run via hourly cron)
- `refresh_daily.py` - Stats, schedule, odds, injuries (run via daily cron)
- `refresh_weekly.py` - Roster, contracts, salary cap (run via weekly cron)
- `refresh_balldontlie.py` - Module with BALLDONTLIE API functions
- `refresh_odds.py` - Module with odds API functions

### Live Game Daemon
- `live_daemon.py` - Long-running daemon for automatic game history capture
- `install_daemon.sh` - Installer script for systemd service + logrotate

### Cache Files (in `cache/`)
- `jokic_career.json` - Career stats and season rankings
- `nuggets_schedule.json` - Schedule with odds data and `balldontlie_id` for history linking
- `injuries.json` - Injury report with content change tracking
- `contracts.json` - Player contracts with extension info
- `standings.json`, `roster.json`, `recent_games.json`, etc.
- `live_history/game_*.json` - Win probability snapshots for completed games

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

### Live Win Probability
- `/live` page shows real-time win probability during games
- Polls BALLDONTLIE v2 API for live odds from 12+ bookmakers
- Converts moneylines to implied probability using: `prob = |ml| / (|ml| + 100)` for favorites
- Shows consensus (average) probability across all bookmakers
- Chart.js graph tracks probability changes over time
- Auto-refreshes every 30 seconds
- Game states: PRE-GAME, LIVE (with quarter/time), FINAL

### Live Game History
- `/live/<game_id>` shows historical win probability for completed games
- Snapshots stored in `cache/live_history/game_*.json`
- Calendar links to history via `balldontlie_id` field in schedule
- Charts show: probability swing with max gaps, score progression
- Box score with quarter-by-quarter highlights (winner in green)
- **Live daemon** (`live_daemon.py`) automatically captures snapshots during games

### Live Daemon
The live daemon runs as a systemd service to automatically capture game data:
- Checks every minute for Nuggets games
- Starts polling 30 min before game time
- Captures snapshots every 30 seconds during live games
- Updates schedule cache with `balldontlie_id` when game ends
- Handles timezone differences (parses ET/CT/MT/PT from API)
- Logs to `/var/log/nbastats/live_daemon.log`

Install with: `sudo ./install_daemon.sh`
Control with: `sudo systemctl [start|stop|restart|status] nbastats-live`

## Testing Changes
1. Run Flask: `source venv/bin/activate && python app.py`
2. **Use Claude in Chrome extension** to visually verify UI changes at `http://localhost:5001`
   - Take screenshots to confirm layout/styling
   - Navigate between pages to test links
   - Check responsive behavior if needed
3. Check console/network for errors
4. Run refresh scripts to test data fetching

## Common Tasks

### Refresh data (by frequency)
```bash
source venv/bin/activate

# Full refresh (all data)
python refresh_cache.py

# Hourly data only (standings, recent games)
python refresh_hourly.py

# Daily data only (stats, schedule, odds, injuries)
python refresh_daily.py

# Weekly data only (roster, contracts, salary cap)
python refresh_weekly.py
```

### Production cron setup
```bash
# Hourly - standings and recent games
0 * * * * /var/www/nbastats/venv/bin/python /var/www/nbastats/refresh_hourly.py > /dev/null 2>&1

# Daily at 6am - stats, schedule, odds, injuries
0 6 * * * /var/www/nbastats/venv/bin/python /var/www/nbastats/refresh_daily.py > /dev/null 2>&1

# Weekly on Sunday at 6am - roster, contracts, salary cap
0 6 * * 0 /var/www/nbastats/venv/bin/python /var/www/nbastats/refresh_weekly.py > /dev/null 2>&1
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
