# Production Deployment Guide

This guide explains how to deploy the Bitcoin DCA Service on a VPS (Virtual Private Server) securely using Docker.

## Prerequisites

- A VPS (e.g., Vultr, DigitalOcean) running Ubuntu/Debian.
- **Docker Engine** and **Docker Compose** installed on the server.
- **Git** installed.

## 🚀 Deployment Steps

### 1. Clone the Repository
Login to your VPS and clone the code:

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git dca-service
cd dca-service
```

### 2. Setup Configuration & Secrets
Create the `.env` file for your secrets. **Do not commit this file to GitHub.**

```bash
# Copy the template
cp .env.example .env

# Edit the file with your real API keys
nano .env
```

*Tip: You can also upload your local `.env` file securely using SCP from your computer:*
`scp .env root@YOUR_VPS_IP:/root/dca-service/.env`

### 3. Prepare Data Directory (Critical Step)
Since the app runs as a non-root user (UID 1000) for security, we must create the data directory and assign correct permissions before starting.

```bash
# Create the directory to store DB and Logs
mkdir data

# Assign ownership to the container user (UID 1000)
# If you skip this, the app will crash with "Permission Denied"
chown -R 1000:1000 data
```

### 4. Build and Run
```bash
docker compose up -d --build
```

---

## 🔒 How to Access the Dashboard (SSH Tunneling)

For maximum security, the application port is bound to `127.0.0.1` by default. It is **NOT** exposed to the public internet.

To access the dashboard from your local computer (Mac/Windows):

1. **Open a terminal on your local computer** (not the VPS).
2. **Create an SSH Tunnel:**
   ```bash
   # Replace YOUR_VPS_IP with your actual server IP
   ssh -L 8000:127.0.0.1:8000 root@YOUR_VPS_IP
   ```
3. **Open your browser** and visit:
   👉 http://localhost:8000

*Keep the terminal window open while you use the dashboard.*

---

## 📂 Data Persistence

All critical data is persisted in the `./data` directory on the host:

- **Database:** `./data/dca.db` (Transaction history)
- **Logs:** `./data/dca_service.log`
- **Metrics:** `./data/btc_metrics.csv`

Even if you remove the container, this data remains safe.

## 🛠 Management Commands

- **Check Logs:**
  ```bash
  docker compose logs -f
  ```

- **Update App (Code Changes):**
  ```bash
  git pull
  docker compose down
  docker compose up -d --build
  ```

- **Stop App:**
  ```bash
  docker compose down
  ```
