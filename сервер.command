#!/bin/bash
# Разворачивает «Босса темы» на арендованном сервере и вешает на домен.
#
# Нужен VPS с публичным IP и root-доступом (любой российский провайдер,
# от 150 ₽/мес) и, если хотите красивый адрес, домен - A-запись домена
# должна указывать на IP сервера. Сертификат HTTPS скрипт получает сам.
#
# После установки сервис работает круглосуточно и открывается из любой
# сети - Wi-Fi, мобильный интернет, откуда угодно. Ноутбук можно выключать.
#
# Запускать двойным щелчком. Скрипт спросит адрес сервера и пароль.

cd "$(dirname "$0")" || exit 1

export LANG="${LANG:-ru_RU.UTF-8}"
export LC_ALL="$LANG"
export PYTHONIOENCODING=utf-8

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
oops() { printf '\n\033[31m%s\033[0m\n' "$*"; }
bye()  { say ""; say "Нажмите Enter, чтобы закрыть окно."; read -r _; exit "${1:-1}"; }

PORT="${PORT:-8080}"
REMOTE_DIR="/opt/boss-temy"
TOPIC="${TOPIC:-Дроби}"
CLASS_TITLE="${CLASS_TITLE:-7 Б}"

say "═══ Установка «Босса темы» на сервер ═══"
say ""
say "Понадобится IP-адрес сервера и пароль root - их выдаёт провайдер"
say "письмом сразу после оплаты."
say ""

printf 'IP-адрес сервера: '
read -r HOST
[ -z "$HOST" ] && { oops "Адрес не введён."; bye; }

printf 'Пользователь [root]: '
read -r USER_NAME
USER_NAME="${USER_NAME:-root}"

printf 'Домен, если есть (например boss-temy.ru), иначе Enter: '
read -r DOMAIN
DOMAIN="$(printf '%s' "$DOMAIN" | tr -d ' ' | sed 's#^https\{0,1\}://##; s#/$##')"

TARGET="$USER_NAME@$HOST"
if [ -n "$DOMAIN" ]; then
  BASE="https://$DOMAIN"
else
  BASE="http://$HOST:$PORT"
fi

# ── ключ вместо пароля: чтобы пароль спросили один раз ──────────────────
step "1/6  Настраиваю вход на сервер"
KEY="$HOME/.ssh/id_ed25519"
if [ ! -f "$KEY" ]; then
  say "      создаю ключ доступа"
  ssh-keygen -t ed25519 -N '' -f "$KEY" -q || { oops "Не удалось создать ключ."; bye; }
fi

say "      сейчас спросит пароль от сервера - это единственный раз"
if ! ssh-copy-id -o StrictHostKeyChecking=accept-new -i "$KEY.pub" "$TARGET" 2>&1 | tail -3; then
  oops "Не вышло подключиться. Проверьте адрес, пароль и что сервер запущен."
  bye
fi

if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$TARGET" 'echo ok' >/dev/null 2>&1; then
  oops "Ключ скопирован, но сервер всё равно не пускает. Напишите об этом - разберёмся."
  bye
fi
say "      подключение работает"

# ── домен: проверяем, что он смотрит на этот сервер ─────────────────────
if [ -n "$DOMAIN" ]; then
  step "2/6  Проверяю домен $DOMAIN"
  if command -v dig >/dev/null 2>&1; then
    DNS_IP="$(dig +short "$DOMAIN" A 2>/dev/null | tail -1)"
  else
    DNS_IP="$(python3 -c "import socket,sys
try: print(socket.gethostbyname(sys.argv[1]))
except Exception: pass" "$DOMAIN" 2>/dev/null)"
  fi
  if [ -z "$DNS_IP" ]; then
    oops "      домен пока никуда не ведёт."
    say  "      В панели регистратора добавьте A-запись: @ -> $HOST"
    say  "      Обновление занимает от нескольких минут до пары часов."
    printf '      Продолжить без HTTPS и настроить домен позже? [y/N]: '
    read -r GO
    case "$GO" in y|Y|д|Д) DOMAIN="" ; BASE="http://$HOST:$PORT" ;; *) bye 1 ;; esac
  elif [ "$DNS_IP" != "$HOST" ]; then
    oops "      домен ведёт на $DNS_IP, а сервер - $HOST."
    say  "      Исправьте A-запись у регистратора и запустите скрипт заново."
    printf '      Всё равно продолжить? [y/N]: '
    read -r GO
    case "$GO" in y|Y|д|Д) : ;; *) bye 1 ;; esac
  else
    say "      домен ведёт на этот сервер"
  fi
else
  step "2/6  Домен не задан - адрес будет по IP"
fi

# ── копируем код ────────────────────────────────────────────────────────
step "3/6  Копирую код на сервер"
tar czf - app web run_web.py run_all.py run_max.py requirements.txt Dockerfile 2>/dev/null \
  | ssh "$TARGET" "mkdir -p $REMOTE_DIR && tar xzf - -C $REMOTE_DIR" \
  || { oops "Не удалось скопировать файлы."; bye; }
say "      файлы в $REMOTE_DIR"

# ── ставим и запускаем ──────────────────────────────────────────────────
step "4/6  Устанавливаю и запускаю сервис"
ssh "$TARGET" "PORT=$PORT REMOTE_DIR=$REMOTE_DIR BASE='$BASE' bash -s" <<'REMOTE' || { oops "Установка на сервере не прошла."; bye; }
set -e

if ! command -v python3 >/dev/null 2>&1; then
  (apt-get update -qq && apt-get install -y -qq python3) >/dev/null 2>&1 \
    || (yum install -y python3 >/dev/null 2>&1) \
    || { echo "не удалось установить python3"; exit 1; }
fi

cat > /etc/systemd/system/boss-temy.service <<UNIT
[Unit]
Description=Boss temy
After=network.target

[Service]
WorkingDirectory=$REMOTE_DIR
Environment=DB_PATH=$REMOTE_DIR/boss.db
Environment=PORT=$PORT
Environment=WEBAPP_URL=$BASE
ExecStart=$(command -v python3) $REMOTE_DIR/run_web.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable boss-temy >/dev/null 2>&1
systemctl restart boss-temy

# открываем порты, если включён файрвол
if command -v ufw >/dev/null 2>&1; then
  ufw allow "$PORT"/tcp >/dev/null 2>&1
  ufw allow 80/tcp  >/dev/null 2>&1
  ufw allow 443/tcp >/dev/null 2>&1
fi
if command -v firewall-cmd >/dev/null 2>&1; then
  for p in "$PORT" 80 443; do firewall-cmd --add-port="$p"/tcp --permanent >/dev/null 2>&1; done
  firewall-cmd --reload >/dev/null 2>&1
fi

sleep 2
systemctl is-active --quiet boss-temy || { echo "сервис не запустился"; journalctl -u boss-temy -n 20 --no-pager; exit 1; }
echo "сервис работает"
REMOTE
say "      сервис поднят и будет перезапускаться сам"

# ── HTTPS на домене ─────────────────────────────────────────────────────
if [ -n "$DOMAIN" ]; then
  step "5/6  Ставлю HTTPS для $DOMAIN"
  say "      сертификат бесплатный, обновляется сам"
  ssh "$TARGET" "DOMAIN=$DOMAIN PORT=$PORT bash -s" <<'REMOTE_TLS' || { oops "HTTPS настроить не вышло. Сайт пока работает по http://IP:порт."; }
set -e
export DEBIAN_FRONTEND=noninteractive

if ! command -v caddy >/dev/null 2>&1; then
  apt-get update -qq >/dev/null 2>&1
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gnupg >/dev/null 2>&1
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -qq >/dev/null 2>&1
  apt-get install -y -qq caddy >/dev/null 2>&1
fi

cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    reverse_proxy 127.0.0.1:$PORT
}
CADDY

systemctl enable caddy >/dev/null 2>&1
systemctl restart caddy
sleep 5
systemctl is-active --quiet caddy || { echo "caddy не запустился"; journalctl -u caddy -n 20 --no-pager; exit 1; }
echo "https работает"
REMOTE_TLS
else
  step "5/6  HTTPS пропускаю - домен не задан"
fi

# ── класс, рейд и ключ кабинета ─────────────────────────────────────────
step "6/6  Завожу класс и выдаю ссылки"
OUT=$(ssh "$TARGET" "cd $REMOTE_DIR && DB_PATH=$REMOTE_DIR/boss.db TOPIC='$TOPIC' CLASS_TITLE='$CLASS_TITLE' python3 - <<'PY'
import os, sys
sys.path.insert(0, '.')
from app import db, seed, logic, webapp
db.connect(os.environ['DB_PATH'])
seed.load()
topic = os.environ.get('TOPIC', 'Дроби')
title = os.environ.get('CLASS_TITLE', '7 Б')
cls = db.q1(\"SELECT * FROM classes ORDER BY id LIMIT 1\")
if cls is None:
    cls = logic.create_class(title, 'ext:teacher', 'Учитель')
    cls = db.q1(\"SELECT * FROM classes WHERE id = ?\", cls['id'])
raid = logic.active_raid(cls['id'])
if raid is None:
    if logic.bank_size(cls['id'], topic) < 10:
        logic.copy_from_library(cls['id'], topic)
    logic.create_raid(cls['id'], topic, days=3)
print(cls['join_code'])
print(logic.teacher_token(cls['id']))
print(webapp.admin_token())
db.close()
PY")

CODE="$(printf '%s\n' "$OUT" | sed -n 1p)"
TTOKEN="$(printf '%s\n' "$OUT" | sed -n 2p)"
ATOKEN="$(printf '%s\n' "$OUT" | sed -n 3p)"
[ -z "$CODE" ] && { oops "Класс завести не удалось."; bye; }
say "      класс «$CLASS_TITLE», код $CODE"

# ── проверка снаружи ────────────────────────────────────────────────────
HTTP=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "$BASE/join")
if [ "$HTTP" = "200" ]; then
  say "      страница отвечает"
else
  oops "      страница не открылась (код $HTTP)."
  say "      Если домен только что куплен, дайте записям разойтись и проверьте снова."
  say "      Если адрес по IP - в панели сервера разрешите входящие на порт $PORT."
fi

say ""
say "  ╭──────────────────────────────────────────────────────────╮"
say "   Ссылки постоянные - сервер работает круглосуточно."
say ""
say "   Ученикам:     $BASE/join?code=$CODE"
say "   Учителю:      $BASE/teacher?t=$TTOKEN"
say "   Кабинет:      $BASE/admin?t=$ATOKEN"
say "  ╰──────────────────────────────────────────────────────────╯"
say ""
printf '%s' "$BASE/join?code=$CODE" | pbcopy 2>/dev/null && say "  Ссылка для учеников скопирована в буфер обмена."
say ""
say "  Перезапустить:      ssh $TARGET 'systemctl restart boss-temy'"
say "  Посмотреть логи:    ssh $TARGET 'journalctl -u boss-temy -n 50'"
say "  Обновить код:       запустите этот скрипт заново,"
say "                      либо один раз автообновление.command - и дальше"
say "                      сервер будет сам забирать код с GitHub"
say ""
bye 0
