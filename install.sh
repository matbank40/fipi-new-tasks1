#!/usr/bin/env bash
# Установка на Ubuntu/Debian. Запускать из папки /opt/fipi_bot под root.
set -e
apt-get update
apt-get install -y python3 python3-venv fonts-inter fonts-dejavu-core || apt-get install -y python3 python3-venv fonts-dejavu-core
python3 -m venv venv
venv/bin/pip install -U pip
venv/bin/pip install -r requirements.txt
venv/bin/python -m playwright install --with-deps chromium
[ -f .env ] || cp .env.example .env
cp fipi-bot.service /etc/systemd/system/fipi-bot.service
systemctl daemon-reload
echo
echo "Готово. Впиши токен:  nano /opt/fipi_bot/.env"
echo "Потом:               systemctl enable --now fipi-bot"
echo "Логи:                journalctl -u fipi-bot -f"
