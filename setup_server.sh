#!/bin/bash
#
# Production server setup for nbastats.fun
# Run as root on a fresh Ubuntu 22.04+ VM
#
# Usage: sudo ./setup_server.sh
#

set -e

DOMAIN="nbastats.fun"
APP_DIR="/var/www/nbastats"
APP_USER="www-data"
REPO_URL="https://github.com/$(git remote get-url origin 2>/dev/null | sed 's/.*github.com[:/]\(.*\)\.git/\1/' || echo 'YOUR_USERNAME/nba_fun')"

echo "=============================================="
echo "  nbastats.fun Production Server Setup"
echo "=============================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Please run as root (sudo ./setup_server.sh)"
    exit 1
fi

# -------------------------------------------
# Step 1: System Updates & Dependencies
# -------------------------------------------
echo "[1/8] Installing system dependencies..."
apt update
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git ufw

# -------------------------------------------
# Step 2: Configure Firewall
# -------------------------------------------
echo "[2/8] Configuring firewall..."
ufw allow 'Nginx Full'
ufw allow OpenSSH
ufw --force enable

# -------------------------------------------
# Step 3: Clone/Setup Application
# -------------------------------------------
echo "[3/8] Setting up application directory..."
mkdir -p $APP_DIR
cd $APP_DIR

# If directory is empty, clone the repo
if [ ! -f "app.py" ]; then
    echo "Cloning repository..."
    git clone $REPO_URL .
fi

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

# Create cache directory
mkdir -p cache
chown -R $APP_USER:$APP_USER $APP_DIR

# -------------------------------------------
# Step 4: Initial Cache Population
# -------------------------------------------
echo "[4/8] Populating initial cache..."
cd $APP_DIR
source venv/bin/activate
python refresh_cache.py || echo "Warning: Cache refresh failed, will retry later"
chown -R $APP_USER:$APP_USER cache/

# -------------------------------------------
# Step 5: Create Gunicorn Systemd Service
# -------------------------------------------
echo "[5/8] Creating systemd service..."
cat > /etc/systemd/system/nbastats.service << 'EOF'
[Unit]
Description=NBA Stats Flask Application
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/nbastats
Environment="PATH=/var/www/nbastats/venv/bin"
ExecStart=/var/www/nbastats/venv/bin/gunicorn --workers 3 --bind unix:nbastats.sock --access-logfile /var/log/nbastats/access.log --error-logfile /var/log/nbastats/error.log app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Create log directory
mkdir -p /var/log/nbastats
chown -R $APP_USER:$APP_USER /var/log/nbastats

# Enable and start the service
systemctl daemon-reload
systemctl enable nbastats
systemctl start nbastats

# -------------------------------------------
# Step 6: Configure Nginx
# -------------------------------------------
echo "[6/8] Configuring Nginx..."
cat > /etc/nginx/sites-available/nbastats << EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    location / {
        proxy_pass http://unix:/var/www/nbastats/nbastats.sock;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 300s;
        proxy_read_timeout 300s;
    }

    location /static {
        alias /var/www/nbastats/static;
        expires 30d;
    }
}
EOF

# Enable the site
ln -sf /etc/nginx/sites-available/nbastats /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Test and reload nginx
nginx -t
systemctl reload nginx

# -------------------------------------------
# Step 7: SSL Certificate (Let's Encrypt)
# -------------------------------------------
echo "[7/8] Setting up SSL certificate..."
echo ""
echo "IMPORTANT: Make sure your DNS is configured!"
echo "  - A record: $DOMAIN -> [this server's IP]"
echo "  - A record: www.$DOMAIN -> [this server's IP]"
echo ""
read -p "Is DNS configured and propagated? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN --redirect
    echo "SSL certificate installed successfully!"
else
    echo "Skipping SSL setup. Run this later:"
    echo "  sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN"
fi

# -------------------------------------------
# Step 8: Setup Cron Job for Cache Refresh
# -------------------------------------------
echo "[8/8] Setting up daily cache refresh cron job..."
cat > /etc/cron.d/nbastats-refresh << 'EOF'
# Refresh NBA stats cache daily at 6am Mountain Time (12:00 UTC in winter, 13:00 UTC in summer)
0 13 * * * www-data cd /var/www/nbastats && /var/www/nbastats/venv/bin/python refresh_cache.py >> /var/log/nbastats/refresh.log 2>&1
EOF

chmod 644 /etc/cron.d/nbastats-refresh

# -------------------------------------------
# Done!
# -------------------------------------------
echo ""
echo "=============================================="
echo "  Setup Complete!"
echo "=============================================="
echo ""
echo "Application URL: https://$DOMAIN"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status nbastats    # Check app status"
echo "  sudo systemctl restart nbastats   # Restart app"
echo "  sudo journalctl -u nbastats -f    # View app logs"
echo "  sudo tail -f /var/log/nbastats/access.log"
echo "  sudo tail -f /var/log/nbastats/error.log"
echo ""
echo "To update the app:"
echo "  cd /var/www/nbastats"
echo "  sudo git pull"
echo "  sudo systemctl restart nbastats"
echo ""
echo "To manually refresh cache:"
echo "  cd /var/www/nbastats"
echo "  sudo -u www-data ./venv/bin/python refresh_cache.py"
echo ""
