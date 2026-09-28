#!/bin/bash
# Выкладывает код «Босса темы» в ваш репозиторий на GitHub.
#
# Первый запуск: спросит адрес репозитория и данные для входа - GitHub просит
# логин и токен вместо пароля, токен создаётся в настройках профиля,
# Settings - Developer settings - Personal access tokens.
# Дальше git запомнит доступ в связке ключей мака, и запусков хватит одного щелчка.
#
# База с ответами детей, ключ администратора и логи в репозиторий не попадают -
# за этим следит файл .gitignore.

cd "$(dirname "$0")" || exit 1

export LANG="${LANG:-ru_RU.UTF-8}"
export LC_ALL="$LANG"

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
oops() { printf '\n\033[31m%s\033[0m\n' "$*"; }
bye()  { say ""; say "Нажмите Enter, чтобы закрыть окно."; read -r _; exit "${1:-1}"; }

command -v git >/dev/null 2>&1 || { oops "Git не установлен. Поставьте Xcode Command Line Tools: xcode-select --install"; bye 1; }

step "1/4  Проверяю папку"
if [ ! -d .git ]; then
  git init -q -b main || { oops "Не удалось создать репозиторий."; bye 1; }
  say "      репозиторий заведён"
else
  say "      репозиторий уже есть"
fi

git config user.name  >/dev/null 2>&1 || git config user.name  "Boss Temy"
git config credential.helper osxkeychain 2>/dev/null
git config user.email >/dev/null 2>&1 || git config user.email "boss-temy@example.com"

step "2/4  Куда выкладываем"
REMOTE="$(git remote get-url origin 2>/dev/null)"
if [ -z "$REMOTE" ]; then
  say "      создайте на github.com пустой приватный репозиторий (без README)"
  say "      и вставьте сюда его адрес вида https://github.com/имя/boss-temy.git"
  printf '      Адрес: '
  read -r REMOTE
  [ -z "$REMOTE" ] && { oops "Адрес не введён."; bye 1; }
  git remote add origin "$REMOTE" || { oops "Не удалось запомнить адрес."; bye 1; }
fi
say "      $REMOTE"

step "3/4  Собираю изменения"
git add -A
if git diff --cached --quiet; then
  say "      изменений нет - всё уже выложено"
else
  printf '      Короткое описание изменений [обновление]: '
  read -r MSG
  git commit -q -m "${MSG:-обновление}" || { oops "Коммит не прошёл."; bye 1; }
  say "      готово"
fi

step "4/4  Отправляю на GitHub"
say "      сейчас git спросит логин и пароль:"
say "      Username - ваше имя на GitHub (svsmolentseva-lang),"
say "      Password - токен доступа, а не пароль от сайта."
say "      Токен при вставке не виден, это нормально: Cmd+V и Enter."
say ""
if git push -u origin main; then
  :
else
  printf 'protocol=https\nhost=github.com\n\n' | git credential-osxkeychain erase 2>/dev/null
  oops "Отправить не вышло."
  say  "  Write access to repository not granted - у токена нет права записи."
  say  "    Проще всего сделать классический токен: github.com - Settings -"
  say  "    Developer settings - Personal access tokens - Tokens (classic) -"
  say  "    Generate new token (classic), галочка repo, Generate token."
  say  "  Если пишет, что репозиторий не пустой - выполните: git pull --rebase origin main"
  say  "  Старый токен я из связки ключей убрал, при следующем запуске спросит заново."
  bye 1
fi

say ""
say "      Проверяю, что код действительно лежит на GitHub..."
if git ls-remote --heads origin main | grep -q main; then
  say ""
  say "  Готово. Код на GitHub: ${REMOTE%.git}"
else
  oops "На GitHub ветки main не видно. Откройте репозиторий в браузере и проверьте."
  bye 1
fi
bye 0
