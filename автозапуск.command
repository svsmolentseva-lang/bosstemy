#!/bin/bash
# Автозапуск «Босса темы» на этом макбуке.
#
# Ставит сервис в автозагрузку: сервер поднимается сам при включении
# компьютера, сам перезапускается, если упал. Запускать руками больше
# ничего не нужно.
#
# Запустить второй раз - предложит выключить автозапуск.

cd "$(dirname "$0")" || exit 1

export LANG="${LANG:-ru_RU.UTF-8}"
export LC_ALL="$LANG"
export PYTHONIOENCODING=utf-8

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
oops() { printf '\n\033[31m%s\033[0m\n' "$*"; }
bye()  { say ""; say "Нажмите Enter, чтобы закрыть окно."; read -r _; exit "${1:-0}"; }

LABEL="ru.boss-temy.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DIR="$(pwd)"
DB="${DB_PATH:-$HOME/boss.db}"
PORT="${PORT:-8080}"
LOG_DIR="$DIR/logs"
PY="$(command -v python3)"

[ -z "$PY" ] && { oops "Не найден python3."; bye 1; }

# ── выключение, если уже стоит ──────────────────────────────────────────
if [ -f "$PLIST" ]; then
  say "Автозапуск уже настроен."
  printf 'Выключить его? [да/нет]: '
  read -r ANSWER
  case "$ANSWER" in
    да|Да|ДА|yes|y|д)
      launchctl unload "$PLIST" 2>/dev/null
      rm -f "$PLIST"
      say ""
      say "Выключил. Сервер больше не поднимается сам."
      say "Запускать по-старому: bash пилот.command"
      bye 0
      ;;
    *)
      say ""
      say "Оставил как есть. Перезапустить сервис сейчас:"
      launchctl unload "$PLIST" 2>/dev/null
      launchctl load "$PLIST" 2>/dev/null
      say "  перезапущен"
      bye 0
      ;;
  esac
fi

# ── установка ───────────────────────────────────────────────────────────
step "1/3  Готовлю автозапуск"
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

cat > "$PLIST" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$DIR/run_web.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>DB_PATH</key><string>$DB</string>
    <key>PORT</key><string>$PORT</string>
    <key>PYTHONIOENCODING</key><string>utf-8</string>
    <key>LANG</key><string>ru_RU.UTF-8</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG_DIR/server.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/server.log</string>
</dict>
</plist>
PLIST_END

step "2/3  Запускаю"
# порт мог остаться занят ручным запуском
lsof -ti :"$PORT" >/dev/null 2>&1 && { pkill -f run_web.py 2>/dev/null; sleep 1; }

launchctl unload "$PLIST" 2>/dev/null
launchctl load "$PLIST" || { oops "Не удалось поставить в автозагрузку."; bye 1; }

ok=""
for _ in 1 2 3 4 5 6 7 8; do
  sleep 1
  curl -s -o /dev/null "http://localhost:$PORT/join" && { ok="да"; break; }
done
if [ -z "$ok" ]; then
  oops "Сервер не отвечает. Что в логе:"
  tail -15 "$LOG_DIR/server.log" 2>/dev/null
  bye 1
fi

step "3/3  Готово"

LAN_IP=""
for iface in en0 en1 en2; do
  LAN_IP=$(ipconfig getifaddr "$iface" 2>/dev/null)
  [ -n "$LAN_IP" ] && break
done

CODE=$(DB_PATH="$DB" python3 - <<'PY'
import os, sys
sys.path.insert(0, '.')
from app import db, seed, logic
db.connect(os.environ['DB_PATH'])
seed.load()
cls = db.q1("SELECT * FROM classes ORDER BY id LIMIT 1")
if cls is None:
    cls = logic.create_class('7 Б', 'ext:teacher', 'Учитель')
    cls = db.q1("SELECT * FROM classes WHERE id = ?", cls['id'])
if logic.active_raid(cls['id']) is None:
    if logic.bank_size(cls['id'], 'Дроби') < 10:
        logic.copy_from_library(cls['id'], 'Дроби')
    logic.create_raid(cls['id'], 'Дроби', days=3)
print(cls['join_code'] + '|' + (logic.teacher_token(cls['id']) or ''), end='')
db.close()
PY
)

say ""
say "  ╭──────────────────────────────────────────────────────────╮"
say "   Сервер работает и будет запускаться сам при включении"
say "   компьютера. Ничего запускать больше не нужно."
say ""
if [ -n "$LAN_IP" ]; then
say "   Ссылка для класса:"
say "   http://$LAN_IP:$PORT/join?code=${CODE%%|*}"
say ""
say "   Ваша панель учителя:"
say "   http://$LAN_IP:$PORT/teacher?t=${CODE##*|}"
say ""
say "   Адрес меняется при смене сети - свежий всегда покажет"
say "   «панель.command»."
fi
say "  ╰──────────────────────────────────────────────────────────╯"
say ""
say "  Логи пишутся в logs/server.log - оттуда их видит Клод."
say "  Выключить автозапуск: запустите этот файл ещё раз."
say ""
bye 0
