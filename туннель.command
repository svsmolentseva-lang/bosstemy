#!/bin/bash
# Открывает «Босса темы» наружу через бесплатный туннель Cloudflare.
#
# Что делает: поднимает локальный сервер игры и выдаёт ссылку вида
# https://что-то.trycloudflare.com - она работает с любого телефона
# из любой сети. Ничего покупать и настраивать роутер не нужно.
#
# Запускать двойным щелчком. Чтобы остановить - закрыть окно или Ctrl+C.

cd "$(dirname "$0")" || exit 1

export LANG="${LANG:-ru_RU.UTF-8}"
export LC_ALL="$LANG"
export PYTHONIOENCODING=utf-8

PORT="${PORT:-8080}"
DB="${DB_PATH:-$HOME/boss.db}"
BIN_DIR="$HOME/.boss-temy"
CF="$BIN_DIR/cloudflared"
LOG="$(mktemp -t cf-tunnel)"

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
oops() { printf '\n\033[31m%s\033[0m\n' "$*"; }
bye()  { say ""; say "Нажмите Enter, чтобы закрыть окно."; read -r _; exit "${1:-1}"; }

cleanup() {
  [ -n "$CF_PID" ] && kill "$CF_PID" 2>/dev/null
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null
  rm -f "$LOG"
}
trap cleanup EXIT INT TERM

step "1. Проверяю cloudflared"
if command -v cloudflared >/dev/null 2>&1; then
  CF="$(command -v cloudflared)"
  say "Уже установлен: $CF"
elif [ -x "$CF" ]; then
  say "Уже скачан: $CF"
else
  say "Не найден, скачиваю (около 30 МБ, один раз)."
  mkdir -p "$BIN_DIR" || { oops "Не удалось создать $BIN_DIR"; bye 1; }
  case "$(uname -m)" in
    arm64) ARCH=arm64 ;;
    *)     ARCH=amd64 ;;
  esac
  URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-$ARCH.tgz"
  if ! curl -fsSL "$URL" -o "$BIN_DIR/cf.tgz"; then
    oops "Скачать не получилось. Проверьте интернет или поставьте вручную:"
    say  "  brew install cloudflared"
    bye 1
  fi
  tar -xzf "$BIN_DIR/cf.tgz" -C "$BIN_DIR" && rm -f "$BIN_DIR/cf.tgz"
  chmod +x "$CF" 2>/dev/null
  xattr -dr com.apple.quarantine "$CF" 2>/dev/null
  [ -x "$CF" ] || { oops "Файл скачался, но не запускается. Поставьте вручную: brew install cloudflared"; bye 1; }
  say "Готово."
fi

step "2. Поднимаю туннель"
"$CF" tunnel --no-autoupdate --url "http://localhost:$PORT" >"$LOG" 2>&1 &
CF_PID=$!

PUBLIC=""
for _ in $(seq 1 40); do
  sleep 1
  PUBLIC="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1)"
  [ -n "$PUBLIC" ] && break
done

if [ -z "$PUBLIC" ]; then
  oops "Туннель не поднялся. Последние строки журнала:"
  tail -20 "$LOG"
  bye 1
fi
say "Адрес получен."

step "3. Запускаю сервер игры"
WEBAPP_URL="$PUBLIC" PORT="$PORT" DB_PATH="$DB" python3 run_web.py >/dev/null 2>&1 &
SRV_PID=$!
sleep 3
if ! kill -0 "$SRV_PID" 2>/dev/null; then
  oops "Сервер не запустился. Попробуйте сначала: python3 run_web.py"
  bye 1
fi

ADMIN="$(DB_PATH="$DB" python3 -c "import sys; sys.path.insert(0, '.'); from app import webapp; print(webapp.admin_token())" 2>/dev/null)"

LINKS="$(DB_PATH="$DB" PUBLIC="$PUBLIC" python3 - <<'PYLINKS' 2>/dev/null
import os, sys
sys.path.insert(0, '.')
from app import db, logic
db.connect(os.environ['DB_PATH'])
c = db.q1("SELECT * FROM classes ORDER BY id LIMIT 1")
u = os.environ['PUBLIC']
if c is None:
    print("NOCLASS")
else:
    print(f"{u}/join?code={c['join_code']}")
    print(f"{u}/teacher?t={logic.teacher_token(c['id'])}")
    print(c['title'])
PYLINKS
)"

say ""
printf '\033[1m========================================\033[0m\n'
if [ -z "$LINKS" ] || [ "$LINKS" = "NOCLASS" ]; then
  printf '  Туннель работает: \033[1m%s\033[0m\n\n' "$PUBLIC"
  printf '  Класса в базе ещё нет. Заведите его в кабинете:\n'
  printf '  \033[1m%s/admin?t=%s\033[0m\n' "$PUBLIC" "$ADMIN"
  printf '%s/admin?t=%s' "$PUBLIC" "$ADMIN" | pbcopy 2>/dev/null
else
  JOIN="$(printf '%s\n' "$LINKS" | sed -n 1p)"
  TEACH="$(printf '%s\n' "$LINKS" | sed -n 2p)"
  CLS="$(printf '%s\n' "$LINKS" | sed -n 3p)"
  printf '  Класс «%s»\n\n' "$CLS"
  printf '  Ученикам (уже в буфере обмена):\n'
  printf '  \033[1m%s\033[0m\n\n' "$JOIN"
  printf '  Панель учителя:\n'
  printf '  \033[1m%s\033[0m\n\n' "$TEACH"
  printf '  Кабинет администратора (новые классы и учителя):\n'
  printf '  \033[1m%s/admin?t=%s\033[0m\n' "$PUBLIC" "$ADMIN"
  printf '%s' "$JOIN" | pbcopy 2>/dev/null
fi
printf '\033[1m========================================\033[0m\n'
say ""
say "Ссылка живёт, пока открыто это окно."
say "После перезапуска адрес будет другим."
say ""
say "Чтобы остановить - закройте окно или нажмите Ctrl+C."

wait "$SRV_PID"
