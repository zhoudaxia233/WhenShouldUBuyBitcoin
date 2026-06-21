#!/bin/bash
set -euo pipefail

# 自动切换到脚本所在目录（项目根目录）
cd "$(dirname "$0")"

GENERATED_PATHS=(docs/data docs/charts)
generated_backup_dir=""
generated_backup_file=""

is_generated_path() {
    case "$1" in
        docs/data/*|docs/charts/*) return 0 ;;
        *) return 1 ;;
    esac
}

has_generated_artifacts() {
    local dir found
    for dir in "${GENERATED_PATHS[@]}"; do
        [ -d "$dir" ] || continue
        found="$(find "$dir" -mindepth 1 ! -name .gitkeep -print -quit)"
        [ -n "$found" ] && return 0
    done
    return 1
}

restore_generated_artifacts() {
    if [ -n "$generated_backup_file" ] && [ -f "$generated_backup_file" ]; then
        echo "♻️  Restoring server-generated artifacts..."
        tar -xf "$generated_backup_file"
        rm -rf "$generated_backup_dir"
        generated_backup_file=""
        generated_backup_dir=""
    fi
}

prepare_generated_artifacts_for_pull() {
    local status
    status="$(git status --porcelain --untracked-files=all)"

    local line path has_generated=false non_generated=""
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        path="${line:3}"
        if is_generated_path "$path"; then
            has_generated=true
        else
            non_generated+="$line"$'\n'
        fi
    done <<< "$status"
    if has_generated_artifacts; then
        has_generated=true
    fi

    if [ -n "$non_generated" ]; then
        echo "❌ Refusing to update: non-generated local changes exist."
        echo "Commit, stash, or discard these first:"
        printf "%s" "$non_generated"
        exit 1
    fi

    if [ "$has_generated" = true ]; then
        echo "📦 Backing up server-generated artifacts before git pull..."
        generated_backup_dir="$(mktemp -d)"
        generated_backup_file="$generated_backup_dir/generated-artifacts.tar"
        tar -cf "$generated_backup_file" "${GENERATED_PATHS[@]}"
        git restore --staged --worktree -- "${GENERATED_PATHS[@]}"
        git clean -fdx -- "${GENERATED_PATHS[@]}"
    fi
}

echo "📍 Working directory: $(pwd)"
echo ""

echo "🔄 Pulling latest code..."
trap restore_generated_artifacts ERR
prepare_generated_artifacts_for_pull
git pull --ff-only
restore_generated_artifacts
trap - ERR
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
