# nbastats.fun

A web dashboard tracking Nikola Jokic's NBA statistics, including career stats, triple-double records, season rankings, conference standings, and all-time records watch.

**Live site:** [nbastats.fun](https://nbastats.fun)

## Features

### Main Dashboard
- Conference standings for East and West
- Injury report with return dates and game status
- Interactive schedule calendar with game modals
- Betting odds from multiple sources (FanDuel, DraftKings, Polymarket, Kalshi)
- Special events/promotions displayed in game modals
- Jersey schedule showing which uniform for each game (with images)

### Jokić Page
- Career statistics with highlight cards
- Per-game league rankings (clickable to full leaderboards)
- Triple-double all-time leaderboard tracking
- All-time records watch showing players Jokić is chasing

### Nuggets Page
- Full roster with contract status and injury indicators
- Recent game results
- Team salary cap information

## Local Development

### Prerequisites

- Python 3.10+
- pip

### Setup

```bash
# Clone the repository
git clone https://github.com/jasper9/nbastats.fun.git
cd nba_fun

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Populate the cache (required before first run)
python refresh_cache.py

# Run the development server
python app.py
```

Visit `http://localhost:5001` in your browser.

### Refreshing the Cache

The app reads from cached JSON files to avoid hitting NBA API rate limits. Refresh the cache to get updated stats:

```bash
source venv/bin/activate
python refresh_cache.py
```

This fetches:
- Jokić career stats and per-game rankings
- Team standings (East and West)
- All-time records for Jokić to chase
- Triple-double data for active players
- League leaders for all stat categories
- Nuggets roster, injuries, and contracts (via BALLDONTLIE)
- Betting odds from multiple sources
- Recent game results

**Note:** The NBA API can be slow and occasionally times out. The script handles this gracefully.

### One-Time Data Scrapes

These scripts populate static data that doesn't need regular updates:

```bash
# Scrape promotional events (run once at start of season)
python scrape_promotions.py

# Scrape jersey schedule from NBA LockerVision (run once at start of season)
python scrape_jerseys.py
```

## Production Deployment (Ubuntu)

### Automated Setup

A setup script is included for deploying to an Ubuntu 22.04+ server.

**One-liner install:**
```bash
curl -sSL https://raw.githubusercontent.com/jasper9/nbastats.fun/main/setup_server.sh | sudo bash
```

**Or clone first:**
```bash
git clone https://github.com/jasper9/nbastats.fun.git /tmp/nbastats
cd /tmp/nbastats
sudo ./setup_server.sh
```

### What the Script Configures

| Component | Details |
|-----------|---------|
| Web Server | Nginx (reverse proxy) |
| App Server | Gunicorn (3 workers, unix socket) |
| Process Manager | systemd (auto-restart on failure) |
| SSL | Let's Encrypt via certbot (auto-renew) |
| Firewall | UFW (ports 80, 443, 22) |
| Cache Refresh | Cron daily at 6am MT |
| Logs | `/var/log/nbastats/` |

### Before Running the Script

1. Point your DNS A records to the server's IP:
   - `nbastats.fun` -> `<server IP>`
   - `www.nbastats.fun` -> `<server IP>`
2. Wait for DNS propagation (~5-15 minutes)

### Useful Commands

```bash
# Check app status
sudo systemctl status nbastats

# Restart the app
sudo systemctl restart nbastats

# View app logs
sudo journalctl -u nbastats -f
sudo tail -f /var/log/nbastats/access.log
sudo tail -f /var/log/nbastats/error.log

# View cache refresh logs
sudo tail -f /var/log/nbastats/refresh.log

# Manually refresh cache
cd /var/www/nbastats
sudo -u www-data ./venv/bin/python refresh_cache.py

# Update the app from git
cd /var/www/nbastats
sudo git pull
sudo systemctl restart nbastats
```

### Cron Job

The cache automatically refreshes daily at 6am Mountain Time:

```
0 13 * * * www-data cd /var/www/nbastats && /var/www/nbastats/venv/bin/python refresh_cache.py
```

(13:00 UTC = 6:00 AM MT during daylight saving time)

## Project Structure

```
nba_fun/
├── app.py                    # Flask application
├── refresh_cache.py          # Main cache refresh (run via cron)
├── refresh_balldontlie.py    # BALLDONTLIE API data fetch
├── refresh_odds.py           # Betting odds fetch
├── scrape_promotions.py      # One-time: scrape promotional schedule
├── scrape_jerseys.py         # One-time: scrape jersey schedule from LockerVision
├── requirements.txt          # Python dependencies
├── setup_server.sh           # Production server setup
├── templates/
│   ├── index.html            # Main dashboard (schedule, injuries, standings)
│   ├── jokic.html            # Jokić stats page
│   ├── more.html             # Nuggets roster/contracts page
│   └── leaders.html          # League leaders page
├── cache/                    # Cached JSON data (gitignored, refreshed by cron)
│   ├── jokic_career.json
│   ├── nuggets_schedule.json
│   ├── injuries.json
│   ├── contracts.json
│   ├── standings.json
│   └── ...
└── data/                     # Static data files (checked into git)
    ├── special_events.json   # Promotional events for home games
    └── jersey_schedule.json  # Uniform schedule (from NBA LockerVision)
```

## Tech Stack

- **Backend:** Flask, Python
- **Frontend:** Vanilla HTML/CSS/JS (Oswald + Roboto fonts)
- **Production:** Nginx, Gunicorn, Let's Encrypt

## Data Sources

| Source | Data | Refresh |
|--------|------|---------|
| [nba_api](https://github.com/swar/nba_api) | Career stats, league leaders, standings | Daily cron |
| [BALLDONTLIE API](https://balldontlie.io) | Injuries, roster, contracts, games, odds | Daily cron |
| [the-odds-api](https://the-odds-api.com) | Traditional sportsbook odds | Daily cron |
| [NBA LockerVision](https://lockervision.nba.com) | Jersey/uniform schedule | One-time per season |
| [nuggets.com](https://nba.com/nuggets) | Promotional schedule | One-time per season |
