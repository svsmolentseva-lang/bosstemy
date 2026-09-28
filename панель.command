#!/bin/bash
# Панель учителя: как идёт рейд, кто участвовал, где класс спотыкается.
# Запускать во время пилота или после него - сервер для этого не нужен.

cd "$(dirname "$0")" || exit 1

export LANG="${LANG:-ru_RU.UTF-8}"
export LC_ALL="$LANG"
export PYTHONIOENCODING=utf-8
DB="${DB_PATH:-$HOME/boss.db}"
LOG_DIR="$(pwd)/logs"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/panel.log") 2>&1

DB_PATH="$DB" python3 - <<'PY'
import os, sys
sys.path.insert(0, '.')
from app import db, logic
from app.texts import plural

def plural_fails(n):
    return plural(n, 'ошибка', 'ошибки', 'ошибок')

db.connect(os.environ['DB_PATH'])

cls = db.q1("SELECT * FROM classes ORDER BY id LIMIT 1")
if cls is None:
    print("Класса ещё нет - запустите «пилот.command».")
    raise SystemExit

raid = db.q1("SELECT * FROM raids WHERE class_id = ? ORDER BY id DESC LIMIT 1", cls['id'])
if raid is None:
    print("Рейда ещё не было.")
    raise SystemExit

rep = logic.raid_report(raid['id'])
r = rep['raid']
bar_len = 30
filled = int(bar_len * r['hp_left'] / r['hp_max']) if r['hp_max'] else 0
bar = '█' * filled + '·' * (bar_len - filled)

status = {'active': 'идёт', 'won': 'БОСС ПОВЕРЖЕН', 'closed': 'закрыт'}.get(r['status'], r['status'])

print()
print(f"  Класс «{cls['title']}»  ·  код {cls['join_code']}")
print(f"  Рейд «{r['topic']}» - {status}, до {r['deadline']}")
print()
print(f"  {bar}  {r['hp_left']} / {r['hp_max']} HP")
print()
print(f"  Участвовали: {rep['participants']} из {rep['total_students']}")
print(f"  Банк темы:   {plural(rep['bank'], 'вопрос', 'вопроса', 'вопросов')}")

if rep['weak']:
    print()
    print("  Где класс спотыкается:")
    for w in rep['weak']:
        print(f"    · {w['text']} - {plural_fails(w['fails'])}")

if rep['absentees']:
    print()
    print(f"  Ещё не заходили: {', '.join(rep['absentees'])}")

pending = logic.pending_questions(cls['id'])
if pending:
    print()
    print(f"  На проверке {plural(len(pending), 'вопрос', 'вопроса', 'вопросов')} от учеников:")
    for q in pending:
        print(f"    №{q['id']} от {q['author_name'] or 'ученика'}: {q['text']} → {q['answer']}")
    print()
    print("  Одобрить: DB_PATH=~/boss.db python3 -c \\")
    print("    \"import sys;sys.path.insert(0,'.');from app import db,logic;"
          "db.connect();logic.moderate(НОМЕР, True)\"")

ip = os.popen("ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null").read().strip() or "localhost"
port = os.environ.get("PORT", "8080")
print()
print(f"  Панель в браузере:  http://{ip}:{port}/teacher?t={logic.teacher_token(cls['id'])}")
print(f"  Ссылка для класса:  http://{ip}:{port}/join?code={cls['join_code']}")
from app import webapp
print(f"  Кабинет админа:     http://{ip}:{port}/admin?t={webapp.admin_token()}")

roster = logic.class_roster(cls['id'])
if roster:
    print()
    print(f"  Вошли по ссылке: {', '.join(x['name'] for x in roster)}")

print()
db.close()
PY

echo "Нажмите Enter, чтобы закрыть."
read -r _
