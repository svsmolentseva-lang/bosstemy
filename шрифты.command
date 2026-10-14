#!/bin/bash
# Скачивает шрифт игры (Manrope) к себе, чтобы страницы не ходили за ним к Google.
#
# Запускать один раз. Файлы лягут в web/fonts и поедут в репозиторий вместе
# с остальным кодом, так что на сервере они окажутся сами.
#
# Нужен интернет. Если Google недоступен, скрипт честно об этом скажет
# и ничего не испортит - игра продолжит работать на запасных шрифтах.

cd "$(dirname "$0")" || exit 1

export LANG="${LANG:-ru_RU.UTF-8}"
export LC_ALL="$LANG"

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
oops() { printf '\n\033[31m%s\033[0m\n' "$*"; }
bye()  { say ""; say "Нажмите Enter, чтобы закрыть окно."; read -r _; exit "${1:-1}"; }

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
CSS_URL="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;700;800&display=swap"

say "═══ Шрифты «Босса темы» ═══"
say ""
say "Забираем Manrope с серверов Google один раз -"
say "дальше игра берёт их со своего сервера."

step "1/3  Спрашиваю список файлов"
mkdir -p web/fonts
if ! curl -fsS -A "$UA" "$CSS_URL" -o web/fonts/_google.css; then
  oops "Не получилось достучаться до fonts.googleapis.com."
  say  "Проверьте интернет и запустите файл ещё раз."
  bye 1
fi
say "      список получен"

step "2/3  Качаю сами шрифты"
python3 - <<'PY' || { oops "Не удалось разобрать список шрифтов."; bye 1; }
import re, subprocess, sys, pathlib

src = pathlib.Path("web/fonts/_google.css").read_text(encoding="utf-8")
# Берём только кириллицу и латиницу: расширенные наборы школьнику не нужны
keep = {"cyrillic", "latin"}
blocks = re.findall(r"/\*\s*([a-z-]+)\s*\*/\s*(@font-face\s*\{.*?\})", src, re.S)
out, got = [], 0
for subset, block in blocks:
    if subset not in keep:
        continue
    url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
    family = re.search(r"font-family:\s*'([^']+)'", block).group(1)
    weight = re.search(r"font-weight:\s*(\d+)", block).group(1)
    name = f"{family.lower().replace(' ', '-')}-{weight}-{subset}.woff2"
    r = subprocess.run(["curl", "-fsS", url, "-o", f"web/fonts/{name}"])
    if r.returncode != 0:
        print(f"      не скачался {name}", file=sys.stderr)
        continue
    got += 1
    out.append(block.replace(url, f"/fonts/{name}").replace("url(/", "url('/").replace(".woff2)", ".woff2')"))
    print(f"      {name}")

if not out:
    sys.exit(1)

head = ("/* Шрифты игры. Файлы лежат рядом, в web/fonts - страницы не ходят\n"
        "   за ним в интернет. Manrope распространяется по SIL Open\n"
        "   Font License 1.1. */\n\n")
pathlib.Path("web/fonts/fonts.css").write_text(head + "\n\n".join(out) + "\n", encoding="utf-8")
print(f"      всего файлов: {got}")
PY

step "3/3  Проверяю"
COUNT=$(ls web/fonts/*.woff2 2>/dev/null | wc -l | tr -d ' ')
SIZE=$(du -sh web/fonts 2>/dev/null | cut -f1)
rm -f web/fonts/_google.css
if [ "$COUNT" -lt 4 ]; then
  oops "Скачалось только $COUNT файлов - маловато. Запустите ещё раз."
  bye 1
fi
say "      $COUNT файлов, $SIZE"
say ""
say "  Готово. Теперь запустите гитхаб.command - шрифты уедут на сервер"
say "  вместе с кодом."
bye 0
