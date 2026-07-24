#!/usr/bin/env bash
# Déploie naming-tool sur ce VPS : htpasswd, service systemd, config nginx.
# À exécuter avec sudo, depuis un terminal interactif (SSH), pas via l'agent.
#
# Usage : sudo NAMING_TOOL_USER=olivier NAMING_TOOL_PASSWORD='...' bash deploy.sh
set -euo pipefail

DEPLOY_DIR="/home/olive/naming-tool/deploy"
NGINX_SITE="/etc/nginx/sites-available/docalib_demo"

if [[ $EUID -ne 0 ]]; then
  echo "Lance ce script avec sudo : sudo bash $0" >&2
  exit 1
fi

if [[ -z "${NAMING_TOOL_USER:-}" || -z "${NAMING_TOOL_PASSWORD:-}" ]]; then
  echo "Définis NAMING_TOOL_USER et NAMING_TOOL_PASSWORD avant de lancer ce script." >&2
  exit 1
fi

echo "1/5 — htpasswd ($NAMING_TOOL_USER)"
htpasswd -bc /etc/nginx/.htpasswd_naming_tool "$NAMING_TOOL_USER" "$NAMING_TOOL_PASSWORD"

echo "2/5 — service systemd naming-tool-api"
cp "$DEPLOY_DIR/naming-tool-api.service" /etc/systemd/system/naming-tool-api.service
systemctl daemon-reload
systemctl enable --now naming-tool-api
sleep 1
systemctl is-active --quiet naming-tool-api && echo "  service actif" || { echo "  ECHEC démarrage service"; journalctl -u naming-tool-api -n 30 --no-pager; exit 1; }

echo "3/5 — vérif backend local"
curl -sf http://127.0.0.1:8099/health && echo || { echo "  ECHEC health check backend"; exit 1; }

echo "4/5 — insertion des location blocks nginx (si pas déjà présents)"
if grep -q "naming-tool-api" "$NGINX_SITE"; then
  echo "  déjà présent, on ne touche pas au fichier"
else
  cp "$NGINX_SITE" "$NGINX_SITE.bak.$(date +%s)"
  awk -v block="$DEPLOY_DIR/nginx_location_block.conf" '
    /^[[:space:]]*location \/ \{$/ && !done {
      while ((getline line < block) > 0) print line
      done = 1
    }
    { print }
  ' "$NGINX_SITE" > /tmp/docalib_demo.new
  mv /tmp/docalib_demo.new "$NGINX_SITE"
fi

echo "5/5 — test + reload nginx"
nginx -t
systemctl reload nginx

echo
echo "OK — teste sur http://54.38.26.33/naming-tool/"
