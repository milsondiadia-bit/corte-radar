#!/usr/bin/env bash
# Instalacao num VPS Ubuntu limpo. Rodar como root.
set -euo pipefail

APP=/opt/corte-radar

echo "==> dependencias do sistema"
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip ffmpeg git sqlite3

echo "==> usuario de servico"
id -u radar &>/dev/null || useradd --system --home "$APP" --shell /usr/sbin/nologin radar

echo "==> ambiente virtual"
mkdir -p "$APP"
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install --quiet --upgrade pip
"$APP/.venv/bin/pip" install --quiet -r "$APP/requirements.txt"

echo "==> baixando modelo do Whisper (uma vez)"
sudo -u radar HOME="$APP" "$APP/.venv/bin/python" -c \
  "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

echo "==> permissoes"
chown -R radar:radar "$APP"
chmod 600 "$APP/.env"

echo "==> servico"
cp "$APP/deploy/corte-radar.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable corte-radar

echo
echo "Pronto. Suba com:  systemctl start corte-radar"
echo "Acompanhe com:     journalctl -u corte-radar -f"
