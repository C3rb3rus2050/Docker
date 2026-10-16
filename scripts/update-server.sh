#!/usr/bin/env bash
# Run after git pull from an existing Docker Compose installation.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
umask 077

docker compose config -q
# Build before stopping the working deployment; a build failure causes no downtime.
docker compose build
backup_dir="${KEST_BACKUP_DIR:-$repo_dir/../Steuer-Tool-Backups}"
mkdir -p -- "$backup_dir"
backup_file="$backup_dir/Steuer-Tool_$(date +%Y-%m-%d_%H%M%S)_$$.tar.gz"

docker compose stop
restart_on_backup_error() {
    printf '%s\n' 'Update vor dem Start abgebrochen. Vorhandene Container werden wieder gestartet.' >&2
    docker compose start || true
}
trap restart_on_backup_error ERR
if [[ -d data/kest ]]; then
    # Stopped SQLite has no writers. Archive includes secrets and configuration.
    tar -czf "$backup_file" data/kest
    chmod 600 "$backup_file"
    tar -tzf "$backup_file" >/dev/null
    printf 'Sicherung: %s\n' "$backup_file"
else
    printf '%s\n' 'Keine bisherige data/kest-Ablage gefunden; Erstinstallation.'
    mkdir -p data/kest
fi
if [[ "$(id -u)" == 0 ]]; then
    chown -R 10001:10001 data/kest
fi
trap - ERR
docker compose up -d --wait --wait-timeout 120
docker compose ps
printf '%s\n' 'Update gestartet. Vorhandene Buchungen und Belege jetzt in der Anwendung prüfen.'
