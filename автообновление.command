#!/bin/bash
# Учит сервер самому забирать свежий код с GitHub.
#
# После установки порядок работы такой: правим код на маке, запускаем
# гитхаб.command - и через пару минут сервер сам подтягивает изменения
# и перезапускается. Запускать сервер.command больше не нужно.
#
# Сервер получает ключ ТОЛЬКО НА ЧТЕНИЕ (deploy key): он может скачивать
# код и не может ничего записать в репозиторий.

cd "$(dirname "$0")" || exit 1

export LANG="${LANG:-ru_RU.UTF-8}"
export LC_ALL="$LANG"

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
oops() { printf '\n\033[31m%s\033[0m\n' "$*"; }
bye()  { say ""; say "Нажмите Enter, чтобы закрыть окно."; read -r _; exit "${1:-1}"; }

REMOTE_DIR="/opt/boss-temy"
EVERY="${EVERY:-2min}"

say "═══ Автообновление «Босса темы» ═══"
say ""

# ── куда ставим ─────────────────────────────────────────────────────────
DEFAULT_HOST="$(cat .server-host 2>/dev/null)"
if [ -n "$DEFAULT_HOST" ]; then
  printf 'IP-адрес сервера [%s]: ' "$DEFAULT_HOST"
  read -r HOST
  HOST="${HOST:-$DEFAULT_HOST}"
else
  printf 'IP-адрес сервера: '
  read -r HOST
fi
[ -z "$HOST" ] && { oops "Адрес не введён."; bye; }
printf '%s' "$HOST" > .server-host

printf 'Пользователь [root]: '
read -r USER_NAME
USER_NAME="${USER_NAME:-root}"
TARGET="$USER_NAME@$HOST"

URL="$(git remote get-url origin 2>/dev/null)"
[ -z "$URL" ] && { oops "В папке не настроен GitHub. Сначала запустите гитхаб.command."; bye; }
SSH_URL="$(printf '%s' "$URL" | sed -E 's#^https://github\.com/#git@github.com:#')"
case "$SSH_URL" in *.git) : ;; *) SSH_URL="$SSH_URL.git" ;; esac
say ""
say "Репозиторий: $SSH_URL"

# ── 1. вход на сервер ───────────────────────────────────────────────────
step "1/5  Проверяю вход на сервер"
if ! ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$TARGET" 'echo ok' >/dev/null 2>&1; then
  oops "Сервер не пускает без пароля. Сначала запустите сервер.command - он настраивает вход."
  bye
fi
say "      вход работает"

# ── 2. ключ сервера для GitHub ──────────────────────────────────────────
step "2/5  Делаю на сервере ключ только на чтение"
PUBKEY="$(ssh "$TARGET" 'bash -s' <<'R1'
set -e
mkdir -p /root/.ssh && chmod 700 /root/.ssh
[ -f /root/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N '' -C 'boss-temy-server' -f /root/.ssh/id_ed25519 -q
grep -q '^github.com ' /root/.ssh/known_hosts 2>/dev/null || ssh-keyscan -t rsa,ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null
cat /root/.ssh/id_ed25519.pub
R1
)"
[ -z "$PUBKEY" ] && { oops "Ключ на сервере создать не вышло."; bye; }

printf '%s' "$PUBKEY" | pbcopy 2>/dev/null && COPIED=1
say ""
say "  ╭─ ключ сервера ───────────────────────────────────────────╮"
say ""
say "$PUBKEY"
say ""
say "  ╰──────────────────────────────────────────────────────────╯"
[ -n "$COPIED" ] && say "  Ключ скопирован в буфер обмена."
say ""
say "  Теперь на GitHub:"
say "    1. откройте ${URL%.git}/settings/keys"
say "    2. Add deploy key"
say "    3. Title: сервер, Key: вставьте ключ (Cmd+V)"
say "    4. галочку «Allow write access» НЕ ставьте - серверу нужно только чтение"
say "    5. Add key"
say ""
printf '  Добавили? Нажмите Enter, чтобы продолжить: '
read -r _

# ── 3. подключаем репозиторий к папке сервиса ───────────────────────────
step "3/5  Подключаю репозиторий к $REMOTE_DIR"
ssh "$TARGET" "SSH_URL='$SSH_URL' REMOTE_DIR='$REMOTE_DIR' bash -s" <<'R2' || { oops "Подключить репозиторий не вышло. Проверьте, что ключ добавлен в Deploy keys."; bye; }
set -e
command -v git >/dev/null 2>&1 || { apt-get update -qq >/dev/null 2>&1; DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git >/dev/null 2>&1; }
if ! git ls-remote "$SSH_URL" >/dev/null 2>&1; then
  echo "GitHub не пускает сервер - ключ не добавлен или добавлен не в тот репозиторий"; exit 1
fi
mkdir -p "$REMOTE_DIR"
cd "$REMOTE_DIR"
[ -d .git ] || git init -q -b main
git remote remove origin 2>/dev/null || true
git remote add origin "$SSH_URL"
git fetch -q origin main
git reset -q --hard origin/main
echo "код из репозитория на месте, $(git rev-parse --short HEAD)"
R2
say "      репозиторий подключён"

# ── 4. таймер обновления ────────────────────────────────────────────────
step "4/5  Ставлю обновление каждые $EVERY"
ssh "$TARGET" "REMOTE_DIR='$REMOTE_DIR' EVERY='$EVERY' bash -s" <<'R3' || { oops "Таймер поставить не вышло."; bye; }
set -e
cat > /usr/local/bin/boss-temy-update <<UPD
#!/bin/bash
cd $REMOTE_DIR || exit 0
git fetch -q origin main || exit 0
OLD=\$(git rev-parse HEAD)
NEW=\$(git rev-parse origin/main)
[ "\$OLD" = "\$NEW" ] && exit 0
git reset -q --hard origin/main
systemctl restart boss-temy
logger -t boss-temy-update "обновлено до \$NEW"
UPD
chmod +x /usr/local/bin/boss-temy-update

cat > /etc/systemd/system/boss-temy-update.service <<UNIT
[Unit]
Description=Boss temy - обновление кода с GitHub

[Service]
Type=oneshot
ExecStart=/usr/local/bin/boss-temy-update
UNIT

cat > /etc/systemd/system/boss-temy-update.timer <<TIMER
[Unit]
Description=Boss temy - проверка обновлений

[Timer]
OnBootSec=1min
OnUnitActiveSec=$EVERY
Unit=boss-temy-update.service

[Install]
WantedBy=timers.target
TIMER

systemctl daemon-reload
systemctl enable --now boss-temy-update.timer >/dev/null 2>&1
systemctl restart boss-temy
sleep 2
systemctl is-active --quiet boss-temy || { echo "сервис не поднялся"; journalctl -u boss-temy -n 20 --no-pager; exit 1; }
echo "таймер работает"
R3
say "      сервер будет проверять GitHub каждые $EVERY"

# ── 5. проверка ─────────────────────────────────────────────────────────
step "5/5  Проверяю"
ssh "$TARGET" 'systemctl list-timers boss-temy-update.timer --no-pager | sed -n 1,2p; echo; cd /opt/boss-temy && git log --oneline -1'
say ""
say "  ╭──────────────────────────────────────────────────────────╮"
say "   Готово. Теперь порядок такой:"
say "     правим код на маке -> гитхаб.command -> ждём пару минут."
say ""
say "   Обновить прямо сейчас, не дожидаясь:"
say "     ssh $TARGET 'boss-temy-update'"
say "   Посмотреть, что обновлялось:"
say "     ssh $TARGET 'journalctl -t boss-temy-update -n 20'"
say "  ╰──────────────────────────────────────────────────────────╯"
bye 0
