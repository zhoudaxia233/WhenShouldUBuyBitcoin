#!/bin/bash
set -e

# 自动切换到脚本所在目录（项目根目录）
cd "$(dirname "$0")"

echo "📍 Working directory: $(pwd)"
echo ""

echo "🔄 Pulling latest code..."
git pull
echo ""

echo "🛑 Stopping containers..."
docker compose down
echo ""

echo "🏗️  Building and starting..."
docker compose up -d --build
echo ""

echo "🧹 Cleaning up old images..."
docker image prune -a -f
echo ""

echo "✅ Update completed!"
echo ""
echo "📊 Container Status:"
docker compose ps
echo ""
echo "💾 Docker Disk Usage:"
docker system df

