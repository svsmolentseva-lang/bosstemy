#!/bin/bash
# Пилот «Босса темы» в один клик.
#
# Поднимает сервер, заводит класс и рейд, печатает ссылку для раздачи.
# Ссылка работает для всех, кто в той же сети Wi-Fi. Если установлен
# cloudflared, дополнительно пробуем туннель наружу - но это необязательно.
# Закрыть - Ctrl+C в этом окне.

cd "$(dirname "$0")" || exit 1

# Двойной щелчок запускает скрипт без локали, и кириллица в выводе рассыпается.
export LANG="${LANG:-ru_RU.UTF-8}"
export LC_ALL="$LANG"
export PYTHONIOENCODING=utf-8

DB="${DB_PATH:-$HOME/boss.db}"
PORT="${PORT:-8080}"
TOPIC="${TOPIC:-Дроби}"
CLASS_TITLE="${CLASS_TITLE:-7 Б}"

# Логи кладём в папку проекта: так их видно и вам, и Клоду.
LOG_DIR="$(pwd)/logs"
mkdir -p "$LOG_DIR"
WEB_LOG="$LOG_DIR/server.log"
TUN_LOG="$LOG_DIR/tunnel.log"
RUN_LOG="$LOG_DIR/pilot.log"
WEB_PID=""
TUN_PID=""
CAF_PID=""

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
oops() { printf '\n\033[31m%s\033[0m\n' "$*"; }

cleanup() {
  say ""
  step "Останавливаю…"
  [ -n "$WEB_PID" ] && kill "$WEB_PID" 2>/dev/null
  [ -n "$TUN_PID" ] && kill "$TUN_PID" 2>/dev/null
  [ -n "$CAF_PID" ] && kill "$CAF_PID" 2>/dev/null
  say "Готово. База осталась в $DB - цифры пилота никуда не делись."
  exit 0
}
trap cleanup INT TERM

printf '\n===== запуск %s =====\n' "$(date '+%Y-%m-%d %H:%M')" >> "$RUN_LOG"
exec > >(tee -a "$RUN_LOG") 2>&1

# ── проверки ────────────────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || {
  oops "Не найден python3. Установите его и запустите снова."
  read -r _; exit 1;
}


# ── сервер ──────────────────────────────────────────────────────────────
step "1/4  Запускаю сервер"

# Порт мог остаться занят прошлым запуском - тогда новый сервер молча падает,
# а проверка «страница отвечает» видит чужой процесс и думает, что всё хорошо.
if lsof -ti :"$PORT" >/dev/null 2>&1; then
  say "      порт $PORT занят прошлым запуском - освобождаю"
  pkill -f run_web.py 2>/dev/null
  sleep 1
  if lsof -ti :"$PORT" >/dev/null 2>&1; then
    oops "Порт $PORT занят чем-то посторонним:"
    lsof -i :"$PORT" | head -3
    say ""
    say "Закройте эту программу или запустите пилот на другом порту:"
    say "    PORT=8090 bash пилот.command"
    cleanup
  fi
fi

DB_PATH="$DB" PORT="$PORT" python3 run_web.py > "$WEB_LOG" 2>&1 &
WEB_PID=$!

ok=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  sleep 1
  # проверяем и что наш процесс жив, и что страница отвечает
  kill -0 "$WEB_PID" 2>/dev/null || break
  if curl -s -o /dev/null "http://localhost:$PORT/join"; then ok="да"; break; fi
done
if [ -z "$ok" ]; then
  oops "Сервер не поднялся. Что он написал:"
  cat "$WEB_LOG"
  cleanup
fi
say "      сервер на localhost:$PORT, база $DB"

# ── адрес в локальной сети ──────────────────────────────────────────────
step "2/4  Определяю адрес в сети"

LAN_IP=""
for iface in en0 en1 en2; do
  LAN_IP=$(ipconfig getifaddr "$iface" 2>/dev/null)
  [ -n "$LAN_IP" ] && break
done

if [ -n "$LAN_IP" ]; then
  URL="http://$LAN_IP:$PORT"
  say "      $URL  (для тех, кто в той же сети Wi-Fi)"
else
  URL="http://localhost:$PORT"
  oops "      Не вижу адреса в сети - похоже, Wi-Fi выключен."
  say "      Пока работает только на этом компьютере."
fi

# Туннель наружу - необязательная добавка. Нужен, только если класс
# сидит в других сетях. В России домены Cloudflare часто недоступны,
# поэтому его отсутствие не должно ломать пилот.
TUNNEL_URL=""
if command -v cloudflared >/dev/null 2>&1; then
  : > "$TUN_LOG"
  cloudflared tunnel --url "http://localhost:$PORT" > "$TUN_LOG" 2>&1 &
  TUN_PID=$!
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    sleep 1
    TUNNEL_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TUN_LOG" | head -1)
    [ -n "$TUNNEL_URL" ] && break
  done
  if [ -n "$TUNNEL_URL" ]; then
    # проверяем, что адрес вообще резолвится - иначе он бесполезен
    HOST=$(printf '%s' "$TUNNEL_URL" | sed 's|https://||')
    if nslookup "$HOST" >/dev/null 2>&1; then
      say "      туннель наружу: $TUNNEL_URL"
    else
      say "      туннель поднялся, но его домен не открывается у вашего провайдера - пропускаем"
      TUNNEL_URL=""
      kill "$TUN_PID" 2>/dev/null; TUN_PID=""
    fi
  else
    say "      туннель не поднялся - работаем по локальной сети"
    kill "$TUN_PID" 2>/dev/null; TUN_PID=""
  fi
fi

# ── класс и рейд ────────────────────────────────────────────────────────
step "3/4  Завожу класс и рейд"
JOIN_LINK=$(DB_PATH="$DB" WEBAPP_URL="$URL" TOPIC="$TOPIC" CLASS_TITLE="$CLASS_TITLE" python3 - <<'PY'
import os, sys
sys.path.insert(0, '.')
from app import db, seed, logic

db.connect(os.environ['DB_PATH'])
seed.load()

topic = os.environ.get('TOPIC', 'Дроби')
title = os.environ.get('CLASS_TITLE', '7 Б')

cls = db.q1("SELECT * FROM classes ORDER BY id LIMIT 1")
if cls is None:
    cls = logic.create_class(title, 'ext:teacher', 'Учитель')
    cls = db.q1("SELECT * FROM classes WHERE id = ?", cls['id'])

raid = logic.active_raid(cls['id'])
if raid is None:
    if logic.bank_size(cls['id'], topic) < 10:
        logic.copy_from_library(cls['id'], topic)
    raid = logic.create_raid(cls['id'], topic, days=3)

print(f"{os.environ['WEBAPP_URL']}/join?code={cls['join_code']}|{cls['join_code']}|"
      f"{raid['topic']}|{raid['hp_left']}|{raid['hp_max']}|{logic.teacher_token(cls['id'])}", end='')
db.close()
PY
)

if [ -z "$JOIN_LINK" ]; then
  oops "Не удалось завести класс. Смотрите ошибку выше."
  cleanup
fi

LINK=$(printf '%s' "$JOIN_LINK" | cut -d'|' -f1)
CODE=$(printf '%s' "$JOIN_LINK" | cut -d'|' -f2)
RTOPIC=$(printf '%s' "$JOIN_LINK" | cut -d'|' -f3)
HPL=$(printf '%s' "$JOIN_LINK" | cut -d'|' -f4)
HPM=$(printf '%s' "$JOIN_LINK" | cut -d'|' -f5)
TTOK=$(printf '%s' "$JOIN_LINK" | cut -d'|' -f6)
say "      класс «$CLASS_TITLE», код $CODE, рейд «$RTOPIC» на $HPL/$HPM HP"

# не даём макбуку уснуть, пока идёт пилот
caffeinate -s > /dev/null 2>&1 &
CAF_PID=$!

# ── всё готово ──────────────────────────────────────────────────────────
step "4/4  Готово"
say ""
say "  ╭──────────────────────────────────────────────────────────╮"
say "   Ссылка для класса - киньте её в чат:"
say ""
say "   $LINK"
say ""
say "   Работает для всех, кто в той же сети Wi-Fi, что и вы."
if [ -n "$TUNNEL_URL" ]; then
say ""
say "   Из любой сети (если у ребят откроется):"
say "   $TUNNEL_URL/join?code=$CODE"
fi
say ""
say "   Проверить самой: откройте ссылку и назовитесь."
say ""
say "   Ваша панель учителя - только для вас:"
say "   $URL/teacher?t=$TTOK"
say "  ╰──────────────────────────────────────────────────────────╯"
say ""
say "  Как идут дела - запустите рядом «панель.command»."
say "  Пока это окно открыто, пилот работает. Ctrl+C - остановить."
say ""
[ -n "$(command -v open)" ] && open "$LINK" >/dev/null 2>&1

while true; do
  sleep 60
  if ! kill -0 "$WEB_PID" 2>/dev/null; then oops "Сервер упал:"; tail -5 "$WEB_LOG"; cleanup; fi
  if [ -n "$TUN_PID" ] && ! kill -0 "$TUN_PID" 2>/dev/null; then
    say "  (туннель наружу отвалился - по локальной сети всё работает)"
    TUN_PID=""
  fi
done
