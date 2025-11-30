# Production Deployment Guide

This guide covers deploying the Bitcoin DCA Service to a production server using **Docker + Nginx** (reverse proxy on host machine).

## Architecture

```
Internet (HTTPS:443)
    ↓
Nginx (host machine)
    ↓ (HTTP:127.0.0.1:8000)
Docker Container (FastAPI)
```

## Prerequisites

- VPS running Ubuntu 22.04 or Debian 11/12
- Domain name with DNS A record pointing to your server IP
- SSH access to the server

---

## Deployment Steps

### 1. Install Docker and Docker Compose

```bash
# Update package list
sudo apt update

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt install docker-compose-plugin

# Verify installation
docker --version
docker compose version
```

### 2. Clone Repository

```bash
cd /opt
git clone https://github.com/zhoudaxia233/WhenShouldUBuyBitcoin.git dca-service
cd dca-service
```

### 3. Configure Environment Variables

```bash
# Copy example file
cp .env.example .env

# Generate SESSION_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Edit .env file
nano .env
```

**Required settings in `.env`:**

```bash
# CRITICAL: Use the generated random string from above
SESSION_SECRET=<paste-generated-secret-here>

# CRITICAL: Must be true in production with HTTPS
SESSION_COOKIE_HTTPS_ONLY=true

# Optional: Binance credentials encryption key (auto-generated on first run)
BINANCE_CRED_ENC_KEY=
```

**Set file permissions:**

```bash
chmod 600 .env
```

### 4. Prepare Data Directory

```bash
# Create directory
mkdir -p data

# Set ownership to container user (UID 1000)
chown -R 1000:1000 data
```

### 5. Create Admin User

```bash
# Run admin creation script
docker compose run --rm dca-service poetry run python scripts/create_admin.py

# Follow prompts:
# - Email: admin@yourdomain.com
# - Password: (minimum 12 characters)
# - Confirm Password: (repeat password)
```

### 6. Start Docker Container

```bash
docker compose up -d --build

# Verify container is running
docker compose ps

# Check logs
docker compose logs -f
```

### 7. Configure Domain Name (DNS)

Before installing Nginx and SSL, you need to point your domain to your server.

**Step 1: Get your server's public IP address**

```bash
# On your VPS, run:
curl ifconfig.me
# or
hostname -I | awk '{print $1}'
```

**Step 2: Configure DNS records at your domain registrar**

Log in to your domain registrar (Namecheap, GoDaddy, Cloudflare, etc.) and add these DNS records:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | @ | `YOUR_SERVER_IP` | 3600 |
| A | www | `YOUR_SERVER_IP` | 3600 |

Example:
- If your domain is `example.com` and server IP is `203.0.113.10`:
  - `A` record: `@` → `203.0.113.10` (for example.com)
  - `A` record: `www` → `203.0.113.10` (for www.example.com)

**Step 3: Verify DNS propagation**

```bash
# From your local machine (not the server):
# Check if DNS is pointing to your server
dig yourdomain.com +short
dig www.yourdomain.com +short

# Both should return your server's IP address
```

DNS propagation can take 5 minutes to 48 hours. Wait until both commands return your server IP before proceeding.

**Alternative: Use online DNS checker**
- https://dnschecker.org/

---

### 8. Install Nginx and Certbot

```bash
# Install packages
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx

# Verify installation (but don't start yet)
nginx -v
certbot --version
```

> **Note**: We'll start Nginx after configuring it to avoid running with default settings.

### 9. Configure Nginx (HTTP Only)

> **Important**: The initial configuration contains only HTTP (port 80). This allows Certbot to verify domain ownership. After running Certbot in the next steps, it will automatically add HTTPS configuration.

**Option 1: Copy from template file (recommended)**

```bash
# Copy template to Nginx sites-available
sudo cp nginx.conf.example /etc/nginx/sites-available/dca-service

# Edit and replace 'yourdomain.com' with your actual domain
sudo nano /etc/nginx/sites-available/dca-service
```

**Option 2: Download directly (if deploying on a different server)**

```bash
# Download from GitHub
sudo curl -o /etc/nginx/sites-available/dca-service \
  https://raw.githubusercontent.com/zhoudaxia233/WhenShouldUBuyBitcoin/main/nginx.conf.example

# Edit and replace 'yourdomain.com' with your actual domain
sudo nano /etc/nginx/sites-available/dca-service
```

**What to change:**

Find this line (around line 24):
```nginx
server_name yourdomain.com;  # REPLACE: Change to your domain
```

Replace with your actual domain:
```nginx
server_name btc.example.com;  # Example for subdomain
# OR
server_name example.com;  # Example for main domain
```

> **Note for subdomains**: If using a subdomain like `btc.example.com`, you only need the subdomain. No need for `www` prefix.

**Enable the site and disable default:**

```bash
# Remove default Nginx welcome page
sudo rm /etc/nginx/sites-enabled/default

# Create symbolic link to enable your site
sudo ln -s /etc/nginx/sites-available/dca-service /etc/nginx/sites-enabled/

# Test configuration (IMPORTANT: must pass before starting)
sudo nginx -t

# Expected output: "syntax is ok" and "test is successful"
```

> **Important**: Do not proceed if `nginx -t` reports errors. Fix the configuration first.

### 10. Start Nginx

```bash
# Start Nginx with your configuration
sudo systemctl start nginx

# Enable Nginx to start on boot
sudo systemctl enable nginx

# Verify Nginx is running
sudo systemctl status nginx
```

### 11. Obtain SSL Certificate

> **What Certbot does**: Certbot will verify domain ownership via HTTP, obtain an SSL certificate from Let's Encrypt, and **automatically modify** your nginx configuration to add:
> - HTTPS (port 443) server block
> - SSL certificate paths
> - HTTP to HTTPS redirect
> - Security headers

```bash
# Run Certbot (replace with your actual domain)
sudo certbot --nginx -d btc.example.com

# For main domains with www subdomain, use:
# sudo certbot --nginx -d example.com -d www.example.com

# Follow prompts:
# 1. Enter email address (for renewal notifications)
# 2. Agree to Terms of Service: A
# 3. Share email with EFF: N (optional)
# 4. Certbot will automatically configure nginx and reload it

# Verify certificate installation
sudo certbot certificates

# Test automatic renewal
sudo certbot renew --dry-run
```

**What changed after Certbot:**

Check the modified nginx config:
```bash
sudo cat /etc/nginx/sites-available/dca-service
```

You should now see:
- New HTTPS `server` block listening on port 443
- SSL certificate paths
- HTTP to HTTPS redirect
- Additional security headers

### 12. Configure Firewall

```bash
# Install UFW
sudo apt install ufw

# Allow SSH (IMPORTANT - don't lock yourself out!)
sudo ufw allow 22/tcp

# Allow HTTP and HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Enable firewall
sudo ufw enable

# Check status
sudo ufw status
```

### 13. Verify Deployment

**Access your application:**
```
https://yourdomain.com
```

**Expected behavior:**
- Redirects to `/api/auth/login`
- HTTPS padlock appears in browser
- Can log in with admin credentials
- Can log out successfully

**Test rate limiting:**
```bash
# From your local machine, test login rate limiting
for i in {1..10}; do 
    curl -X POST https://yourdomain.com/api/auth/login \
        -d "email=test@test.com&password=wrong" || true
    echo "Attempt $i"
    sleep 1
done

# First 5 attempts: 401 Unauthorized
# After 5 attempts: 429 Too Many Requests (rate limited)
```

---

## Data Persistence

All data is stored in `/opt/dca-service/data/`:
- `dca.db` - SQLite database (users, transactions, strategies)
- `dca_service.log` - Application logs

**Backup database:**

```bash
# Manual backup
cp /opt/dca-service/data/dca.db /opt/backups/dca_backup_$(date +%Y%m%d).db

# Automated daily backup (optional)
cat > /opt/backup-dca.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR
cp /opt/dca-service/data/dca.db "$BACKUP_DIR/dca_backup_$DATE.db"
find $BACKUP_DIR -name "dca_backup_*.db" -mtime +30 -delete
EOF

chmod +x /opt/backup-dca.sh
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/backup-dca.sh") | crontab -
```

---

## Maintenance

### View Logs

```bash
# Docker container logs
docker compose logs -f

# Nginx access logs
sudo tail -f /var/log/nginx/dca-access.log

# Nginx error logs
sudo tail -f /var/log/nginx/dca-error.log
```

### Update Application

```bash
cd /opt/dca-service
git pull
docker compose down
docker compose up -d --build
docker compose logs -f
```

### Restart Services

```bash
# Restart Docker container
docker compose restart

# Restart Nginx
sudo systemctl restart nginx
```

### Monitoring

```bash
# Check Docker container status
docker compose ps

# Check Nginx status
sudo systemctl status nginx

# Check firewall status
sudo ufw status

# Check disk space
df -h

# Check SSL certificate expiry
sudo certbot certificates
```

---

## Troubleshooting

### 502 Bad Gateway

```bash
# Check if Docker container is running
docker compose ps
docker compose logs

# Restart container
docker compose restart
```

### SSL Certificate Errors

```bash
# Renew certificate
sudo certbot renew

# Check certificate status
sudo certbot certificates
```

### Login Returns 401 After Logout

```bash
# Verify SESSION_COOKIE_HTTPS_ONLY setting
grep SESSION_COOKIE_HTTPS_ONLY .env

# Should be: SESSION_COOKIE_HTTPS_ONLY=true

# Restart container if changed
docker compose restart
```

### Cannot Connect to Server

```bash
# Check firewall
sudo ufw status

# Ensure ports 80 and 443 are allowed
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

---

## Security Checklist

Before going live, verify:

- [ ] `SESSION_SECRET` is a strong random string (32+ bytes)
- [ ] `SESSION_COOKIE_HTTPS_ONLY=true` in `.env`
- [ ] `.env` file permissions are 600
- [ ] HTTPS is working (browser shows padlock)
- [ ] HTTP auto-redirects to HTTPS
- [ ] Login rate limiting is active (test with multiple failed attempts)
- [ ] SSL certificate auto-renewal is configured (`certbot renew --dry-run`)
- [ ] Firewall is enabled and configured (only ports 22, 80, 443 open)
- [ ] Database backup script is set up (optional but recommended)
- [ ] Admin user is created and login works
- [ ] Docker container restarts automatically (`restart: unless-stopped`)

---

## Quick Reference

**Important file locations:**
- Application: `/opt/dca-service/`
- Database: `/opt/dca-service/data/dca.db`
- Environment: `/opt/dca-service/.env`
- Nginx config: `/etc/nginx/sites-available/dca-service`
- Nginx logs: `/var/log/nginx/dca-*.log`
- SSL certificates: `/etc/letsencrypt/live/yourdomain.com/`

**Common commands:**
```bash
# View Docker logs
docker compose logs -f

# Restart application
docker compose restart

# Update application
git pull && docker compose up -d --build

# Check all services
docker compose ps && sudo systemctl status nginx && sudo ufw status
```
