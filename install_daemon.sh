#!/bin/bash
#
# Install script for NBA Stats Live Daemon
# Run as root: sudo ./install_daemon.sh
#
# This script:
# 1. Creates systemd service for live_daemon.py
# 2. Sets up logging to /var/log/nbastats/
# 3. Configures logrotate for log rotation
#

set -e

# Configuration
SERVICE_NAME="nbastats-live"
APP_DIR="/var/www/nbastats"
VENV_DIR="$APP_DIR/venv"
LOG_DIR="/var/log/nbastats"
USER="www-data"
GROUP="www-data"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== NBA Stats Live Daemon Installer ===${NC}"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Please run as root (sudo ./install_daemon.sh)${NC}"
    exit 1
fi

# Check if app directory exists
if [ ! -d "$APP_DIR" ]; then
    echo -e "${RED}Error: App directory not found: $APP_DIR${NC}"
    echo "Please update APP_DIR in this script to match your installation."
    exit 1
fi

# Check if venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}Error: Virtual environment not found: $VENV_DIR${NC}"
    exit 1
fi

# Check if live_daemon.py exists
if [ ! -f "$APP_DIR/live_daemon.py" ]; then
    echo -e "${RED}Error: live_daemon.py not found in $APP_DIR${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 1: Creating log directory${NC}"
mkdir -p "$LOG_DIR"
chown "$USER:$GROUP" "$LOG_DIR"
chmod 755 "$LOG_DIR"
echo "  Created $LOG_DIR"

echo
echo -e "${YELLOW}Step 2: Creating systemd service${NC}"

cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=NBA Stats Live Game Daemon
Documentation=https://github.com/jasper9/nbastats.fun
After=network.target

[Service]
Type=simple
User=$USER
Group=$GROUP
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$VENV_DIR/bin/python $APP_DIR/live_daemon.py
Restart=always
RestartSec=10

# Logging
StandardOutput=append:$LOG_DIR/live_daemon.log
StandardError=append:$LOG_DIR/live_daemon.log

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR/cache $LOG_DIR

[Install]
WantedBy=multi-user.target
EOF

echo "  Created /etc/systemd/system/${SERVICE_NAME}.service"

echo
echo -e "${YELLOW}Step 3: Setting up logrotate${NC}"

cat > /etc/logrotate.d/${SERVICE_NAME} << EOF
$LOG_DIR/live_daemon.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 644 $USER $GROUP
    postrotate
        systemctl kill -s HUP ${SERVICE_NAME}.service 2>/dev/null || true
    endscript
}
EOF

echo "  Created /etc/logrotate.d/${SERVICE_NAME}"

echo
echo -e "${YELLOW}Step 4: Reloading systemd${NC}"
systemctl daemon-reload
echo "  Systemd reloaded"

echo
echo -e "${YELLOW}Step 5: Enabling service${NC}"
systemctl enable ${SERVICE_NAME}.service
echo "  Service enabled to start on boot"

echo
echo -e "${GREEN}=== Installation Complete ===${NC}"
echo
echo "Commands:"
echo "  Start daemon:    sudo systemctl start ${SERVICE_NAME}"
echo "  Stop daemon:     sudo systemctl stop ${SERVICE_NAME}"
echo "  Restart daemon:  sudo systemctl restart ${SERVICE_NAME}"
echo "  View status:     sudo systemctl status ${SERVICE_NAME}"
echo "  View logs:       sudo tail -f $LOG_DIR/live_daemon.log"
echo "  View journal:    sudo journalctl -u ${SERVICE_NAME} -f"
echo
echo -e "${YELLOW}Would you like to start the daemon now? [y/N]${NC}"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    systemctl start ${SERVICE_NAME}.service
    echo -e "${GREEN}Daemon started!${NC}"
    echo
    systemctl status ${SERVICE_NAME}.service --no-pager
else
    echo "Run 'sudo systemctl start ${SERVICE_NAME}' to start the daemon"
fi
