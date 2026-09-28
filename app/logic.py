"""Правила игры.

Здесь нет ни одной строчки про мессенджер: только классы, рейды, урон и отчёты.
Поэтому логику можно проверять тестами и запускать в консоли, не имея токена MAX.
"""
import random
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import config, db

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без похожих символов: 0/O, 1/I


# ─────────────────────────── классы и люди ────────────────────────────

def make_join_code() -> str:
    """Код вида 7B-4KM: его учитель диктует классу вслух."""
    while True:
        code = "".join(random.choice(ALPHABET) for _ in range(3))
        code = f"{code[:1]}{code[1:2]}-{code[2:]}{random.choice(ALPHABET)}{random.choice(ALPHABET)}"
        if not db.q1("SELECT 1 FROM classes WHERE join_code = ?", code):
            return code


def create_class(title: str, teacher_ext_id: str, teacher_name: str,
                 subject: str | None = None) -> dict:
    """Заводит класс и привязывает к нему учителя по предмету.

    Учителя к классу привязывает таблица teaching, а не поле users.class_id:
    иначе при создании второго класса учитель «переезжал» бы в него и терял первый.
    """
    teacher = upsert_user(teacher_ext_id, teacher_name, role="teacher")
    code = make_join_code()
    class_id = db.run(
        "INSERT INTO classes (title, join_code, teacher_id) VALUES (?, ?, ?)",
        title, code, teacher["id"],
    )
    assign_teacher(teacher["id"], class_id, subject or config.DEFAULT_SUBJECT)
    return {"id": class_id, "title": title, "join_code": code, "teacher_id": teacher["id"]}


def norm_subject(subject: str | None) -> str:
    """Единый вид названия предмета.

    Иначе «математика», «Математика » и «Математика» станут тремя разными
    предметами, и рейды с учителями разъедутся по ним.
    """
    name = " ".join((subject or "").split())[:40]
    if not name:
        return config.DEFAULT_SUBJECT
    return name[0].upper() + name[1:]


def assign_teacher(teacher_id: int, class_id: int, subject: str) -> None:
    """Учитель ведёт этот предмет в этом классе. Пар может быть сколько угодно."""
    db.run(
        "INSERT OR IGNORE INTO teaching (teacher_id, class_id, subject) VALUES (?, ?, ?)",
        teacher_id, class_id, norm_subject(subject),
    )


def unassign_teacher(teacher_id: int, class_id: int, subject: str) -> None:
    db.run("DELETE FROM teaching WHERE teacher_id = ? AND class_id = ? AND subject = ?",
           teacher_id, class_id, norm_subject(subject))


def teacher_classes(teacher_id: int) -> list[dict]:
    """Классы учителя вместе с предметами, которые он в них ведёт."""
    out: dict[int, dict] = {}
    for r in db.q(
        "SELECT c.id, c.title, c.join_code, t.subject FROM teaching t"
        " JOIN classes c ON c.id = t.class_id WHERE t.teacher_id = ?"
        " ORDER BY c.title, t.subject", teacher_id):
        item = out.setdefault(r["id"], {"id": r["id"], "title": r["title"],
                                        "join_code": r["join_code"], "subjects": []})
        item["subjects"].append(r["subject"])
    return list(out.values())


def library_topics() -> list[str]:
    """Темы, по которым в общей библиотеке уже есть вопросы."""
    return sorted(r["topic"] for r in db.q(
        "SELECT DISTINCT topic FROM questions WHERE class_id IS NULL AND status = 'approved'"))


def topics_by_subject(class_id: int) -> dict[str, list[str]]:
    """Темы, разложенные по предметам: своя подсказка для каждого предмета.

    Иначе в математике всплывают темы обществознания. Берём библиотеку,
    банк класса и прошлые рейды - у всех трёх есть предмет.
    """
    box: dict[str, set[str]] = {}
    rows = db.q(
        "SELECT DISTINCT subject, topic FROM questions"
        " WHERE status = 'approved' AND (class_id IS NULL OR class_id = ?)", class_id)
    rows += db.q("SELECT DISTINCT subject, topic FROM raids WHERE class_id = ?", class_id)
    for r in rows:
        topic = (r["topic"] or "").strip()
        if not topic:
            continue
        box.setdefault(norm_subject(r["subject"]), set()).add(topic)
    return {s: sorted(t) for s, t in sorted(box.items())}


def class_topics(class_id: int) -> list[str]:
    """Темы, по которым у класса есть свои вопросы или прошлые рейды."""
    seen = {r["topic"] for r in db.q(
        "SELECT DISTINCT topic FROM questions WHERE class_id = ? AND status = 'approved'", class_id)}
    seen |= {r["topic"] for r in db.q("SELECT DISTINCT topic FROM raids WHERE class_id = ?", class_id)}
    return sorted(x for x in seen if x)


def planned_hp(class_id: int, days: int) -> int:
    """Здоровье босса под размер класса и срок рейда.

    Потолок - если бы каждый каждый день выбирал дневной лимит. На деле так
    не бывает, поэтому берём половину: босс падает, когда до конца дошла
    примерно половина класса. Меньше стартового значения не опускаемся.
    """
    size = len(class_roster(class_id)) or 1
    ceiling = size * days * config.DAILY_HIT_CAP * config.DAMAGE_PER_HIT
    return max(config.DEFAULT_RAID_HP, ceiling // 2)


def known_subjects() -> list[str]:
    """Предметы, которые уже где-то встречались - для подсказки в кабинете."""
    seen = {r["subject"] for r in db.q("SELECT DISTINCT subject FROM teaching")}
    seen |= {r["subject"] for r in db.q("SELECT DISTINCT subject FROM raids")}
    return sorted(x for x in seen if x)


def teaches(teacher_id: int, class_id: int, subject: str | None = None) -> bool:
    if subject:
        subject = norm_subject(subject)
        return db.q1("SELECT 1 FROM teaching WHERE teacher_id = ? AND class_id = ? AND subject = ?",
                     teacher_id, class_id, subject) is not None
    return db.q1("SELECT 1 FROM teaching WHERE teacher_id = ? AND class_id = ?",
                 teacher_id, class_id) is not None


def upsert_user(ext_id: str, name: str, role: str = "student", class_id: int | None = None) -> dict:
    row = db.q1("SELECT * FROM users WHERE ext_id = ?", ext_id)
    if row:
        return dict(row)
    uid = db.run(
        "INSERT INTO users (ext_id, name, role, class_id) VALUES (?, ?, ?, ?)",
        ext_id, name, role, class_id,
    )
    return dict(db.q1("SELECT * FROM users WHERE id = ?", uid))


def join_by_link(code: str, name: str) -> dict | None:
    """Вход без мессенджера: ученик открывает ссылку и называет имя.

    Каждому выдаётся личный секрет - иначе одноклассник подставит чужое имя
    в адресе и будет бить за него. Для пилота этого достаточно; в MAX вместо
    секрета работает подпись платформы.
    """
    cls = db.q1("SELECT * FROM classes WHERE join_code = ?", code.strip().upper())
    if not cls:
        return None
    name = " ".join(name.split())[:30] or "Ученик"
    token = secrets.token_urlsafe(9)
    uid = db.run(
        "INSERT INTO users (ext_id, token, name, role, class_id) VALUES (?, ?, ?, 'student', ?)",
        f"web:{token}", token, name, cls["id"],
    )
    return {"token": token, "name": name, "class": dict(cls),
            "user": dict(db.q1("SELECT * FROM users WHERE id = ?", uid))}


def teacher_token(class_id: int) -> str | None:
    """Личная ссылка учителя на его панель. Заводим при первом обращении."""
    row = db.q1(
        "SELECT u.* FROM teaching t JOIN users u ON u.id = t.teacher_id"
        " WHERE t.class_id = ? ORDER BY u.id LIMIT 1", class_id,
    ) or db.q1(
        "SELECT * FROM users WHERE class_id = ? AND role = 'teacher' ORDER BY id LIMIT 1",
        class_id,
    )
    if not row:
        return None
    if row["token"]:
        return row["token"]
    token = secrets.token_urlsafe(9)
    db.run("UPDATE users SET token = ? WHERE id = ?", token, row["id"])
    return token


def token_for(user_id: int) -> str:
    """Личный секрет для входа по ссылке. Заводим при первом обращении."""
    row = db.q1("SELECT * FROM users WHERE id = ?", user_id)
    if row and row["token"]:
        return row["token"]
    token = secrets.token_urlsafe(9)
    db.run("UPDATE users SET token = ? WHERE id = ?", token, user_id)
    return token


def user_by_token(token: str) -> dict | None:
    row = db.q1("SELECT * FROM users WHERE token = ?", token)
    return dict(row) if row else None


def class_roster(class_id: int) -> list[dict]:
    """Список учеников с их личными ссылками - учителю для раздачи."""
    return [dict(r) for r in db.q(
        "SELECT name, token FROM users WHERE class_id = ? AND role = 'student'"
        " AND token IS NOT NULL ORDER BY name", class_id)]


def join_class(code: str, ext_id: str, name: str) -> dict | None:
    """Ученик входит по коду. Ни фамилии, ни школы мы не спрашиваем."""
    cls = db.q1("SELECT * FROM classes WHERE join_code = ?", code.strip().upper())
    if not cls:
        return None
    user = upsert_user(ext_id, name, role="student", class_id=cls["id"])
    db.run("UPDATE users SET class_id = ? WHERE id = ?", cls["id"], user["id"])
    return {"class": dict(cls), "user": dict(db.q1("SELECT * FROM users WHERE id = ?", user["id"]))}


# ─────────────────────────── банк вопросов ────────────────────────────

def bank_size(class_id: int, topic: str, include_library: bool = False) -> int:
    if include_library:
        row = db.q1(
            "SELECT COUNT(*) n FROM questions WHERE topic = ? AND status = 'approved'"
            " AND (class_id = ? OR class_id IS NULL)",
            topic, class_id,
        )
    else:
        row = db.q1(
            "SELECT COUNT(*) n FROM questions WHERE topic = ? AND status = 'approved' AND class_id = ?",
            topic, class_id,
        )
    return row["n"]


def library_size(class_id: int, topic: str) -> int:
    """Сколько вопросов можно докинуть из общей библиотеки."""
    row = db.q1(
        "SELECT COUNT(*) n FROM questions WHERE topic = ? AND status = 'approved' AND class_id IS NULL",
        topic,
    )
    return row["n"]


def copy_from_library(class_id: int, topic: str, subject: str | None = None) -> int:
    """Копирует библиотечные вопросы в банк класса. Возвращает, сколько добавилось."""
    rows = db.q(
        "SELECT * FROM questions WHERE topic = ? AND status = 'approved' AND class_id IS NULL",
        topic,
    )
    added = 0
    for r in rows:
        exists = db.q1(
            "SELECT 1 FROM questions WHERE class_id = ? AND text = ?", class_id, r["text"]
        )
        if exists:
            continue
        db.run(
            "INSERT INTO questions (class_id, topic, text, answer, options, status, subject)"
            " VALUES (?, ?, ?, ?, ?, 'approved', ?)",
            class_id, r["topic"], r["text"], r["answer"], r["options"],
            norm_subject(subject or r["subject"]),
        )
        added += 1
    return added


def submit_question(class_id: int, author_id: int, topic: str,
                    text: str, answer: str, options: list[str]) -> int:
    """Вопрос от ученика уходит на проверку учителю, а не сразу в игру."""
    return db.run(
        "INSERT INTO questions (class_id, topic, text, answer, options, author_id, status)"
        " VALUES (?, ?, ?, ?, ?, ?, 'pending')",
        class_id, topic, text.strip(), answer.strip(), "|".join(options), author_id,
    )


def pending_questions(class_id: int) -> list[dict]:
    return [dict(r) for r in db.q(
        "SELECT q.*, u.name AS author_name FROM questions q"
        " LEFT JOIN users u ON u.id = q.author_id"
        " WHERE q.class_id = ? AND q.status = 'pending' ORDER BY q.id",
        class_id,
    )]


def moderate(question_id: int, approve: bool, reason: str = "") -> None:
    db.run(
        "UPDATE questions SET status = ?, reject_reason = ? WHERE id = ?",
        "approved" if approve else "rejected", reason or None, question_id,
    )


def author_score(question_id: int) -> int:
    """Очки автору: сколько человек споткнулось на его вопросе.

    Если ошибаются почти все - вопрос сломан, а не хитёр. Очков нет.
    """
    row = db.q1(
        "SELECT COUNT(*) total, SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) fails"
        " FROM answers WHERE question_id = ?",
        question_id,
    )
    total = row["total"] or 0
    fails = row["fails"] or 0
    if total < 3:
        return 0
    if fails / total > config.BROKEN_QUESTION_FAIL_RATE:
        return 0
    return fails


# ─────────────────────────────── рейды ────────────────────────────────

@dataclass
class Hit:
    correct: bool
    damage: int
    hp_left: int
    skip_reason: str | None = None   # почему урон не засчитан
    victory: bool = False


BOSSES = {
    "bobr": "Курвабобр",
    "yaga": "Баба Яга",
}


def create_raid(class_id: int, topic: str, days: int, hp: int | None = None,
                subject: str | None = None, boss: str | None = None) -> dict:
    hp = hp or config.DEFAULT_RAID_HP
    deadline = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    boss = boss if boss in BOSSES else "bobr"
    raid_id = db.run(
        "INSERT INTO raids (class_id, topic, hp_max, hp_left, deadline, subject, boss)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        class_id, topic, hp, hp, deadline, norm_subject(subject), boss,
    )
    return dict(db.q1("SELECT * FROM raids WHERE id = ?", raid_id))


def active_raids(class_id: int) -> list[dict]:
    """Все открытые рейды класса. По предмету может идти свой, они не мешают друг другу."""
    return [dict(r) for r in db.q(
        "SELECT * FROM raids WHERE class_id = ? AND status = 'active'"
        " ORDER BY deadline, id", class_id)]


def active_raid(class_id: int, subject: str | None = None) -> dict | None:
    """Один рейд: по предмету, если он задан, иначе ближайший по сроку."""
    if subject:
        row = db.q1(
            "SELECT * FROM raids WHERE class_id = ? AND subject = ? AND status = 'active'"
            " ORDER BY deadline, id LIMIT 1", class_id, subject)
    else:
        row = db.q1(
            "SELECT * FROM raids WHERE class_id = ? AND status = 'active'"
            " ORDER BY deadline, id LIMIT 1", class_id)
    return dict(row) if row else None


def extend_raid(raid_id: int, days: int = 1) -> str:
    raid = db.q1("SELECT * FROM raids WHERE id = ?", raid_id)
    new_deadline = (datetime.strptime(raid["deadline"], "%Y-%m-%d") + timedelta(days=days))
    db.run("UPDATE raids SET deadline = ? WHERE id = ?", new_deadline.strftime("%Y-%m-%d"), raid_id)
    return new_deadline.strftime("%Y-%m-%d")


def close_raid(raid_id: int) -> None:
    db.run("UPDATE raids SET status = 'closed' WHERE id = ?", raid_id)


def clone_raid(raid_id: int, target_class_id: int, days: int) -> dict:
    """Повторить готовый рейд в другом классе вместе с банком вопросов."""
    src = db.q1("SELECT * FROM raids WHERE id = ?", raid_id)
    for r in db.q(
        "SELECT * FROM questions WHERE class_id = ? AND topic = ? AND status = 'approved'",
        src["class_id"], src["topic"],
    ):
        if not db.q1("SELECT 1 FROM questions WHERE class_id = ? AND text = ?",
                     target_class_id, r["text"]):
            db.run(
                "INSERT INTO questions (class_id, topic, text, answer, options, status)"
                " VALUES (?, ?, ?, ?, ?, 'approved')",
                target_class_id, r["topic"], r["text"], r["answer"], r["options"],
            )
    return create_raid(target_class_id, src["topic"], days, src["hp_max"])


def next_question(raid_id: int, user_id: int) -> dict | None:
    """Вопрос, на который этот ученик ещё не отвечал верно."""
    raid = db.q1("SELECT * FROM raids WHERE id = ?", raid_id)
    row = db.q1(
        "SELECT * FROM questions WHERE topic = ? AND status = 'approved'"
        " AND (class_id = ? OR class_id IS NULL)"
        " AND id NOT IN ("
        "   SELECT question_id FROM answers WHERE raid_id = ? AND user_id = ? AND is_correct = 1"
        " ) ORDER BY RANDOM() LIMIT 1",
        raid["topic"], raid["class_id"], raid_id, user_id,
    )
    if not row:
        return None
    item = dict(row)
    item["options"] = item["options"].split("|")
    return item


def hits_today(user_id: int) -> int:
    row = db.q1(
        "SELECT COUNT(*) n FROM answers"
        " WHERE user_id = ? AND damage > 0 AND date(created_at) = date('now')",
        user_id,
    )
    return row["n"]


def submit_answer(raid_id: int, user_id: int, question_id: int,
                  given: str, elapsed_sec: float) -> Hit:
    """Главная функция игры. Здесь же живёт вся защита от накрутки."""
    raid = db.q1("SELECT * FROM raids WHERE id = ?", raid_id)
    question = db.q1("SELECT * FROM questions WHERE id = ?", question_id)
    if raid is None or question is None:
        raise ValueError("Рейд или вопрос не найден")

    correct = given.strip().lower() == question["answer"].strip().lower()
    damage = 0
    skip = None

    if not correct:
        skip = "wrong"
    elif raid["status"] != "active":
        skip = "raid_closed"
    elif elapsed_sec < config.MIN_ANSWER_SECONDS:
        # ответ быстрее, чем можно прочитать вопрос - это тык наугад
        skip = "too_fast"
    elif db.q1(
        "SELECT 1 FROM answers WHERE raid_id = ? AND user_id = ? AND question_id = ? AND is_correct = 1",
        raid_id, user_id, question_id,
    ):
        skip = "repeat"
    elif hits_today(user_id) >= config.DAILY_HIT_CAP:
        # чтобы один человек не выносил босса за класс
        skip = "daily_cap"
    else:
        damage = min(config.DAMAGE_PER_HIT, raid["hp_left"])

    db.run(
        "INSERT INTO answers (raid_id, user_id, question_id, is_correct, damage, skip_reason)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        raid_id, user_id, question_id, 1 if correct else 0, damage, skip,
    )

    hp_left = raid["hp_left"] - damage
    victory = False
    if damage:
        db.run("UPDATE raids SET hp_left = ? WHERE id = ?", hp_left, raid_id)
        if hp_left <= 0:
            db.run("UPDATE raids SET status = 'won', hp_left = 0 WHERE id = ?", raid_id)
            hp_left, victory = 0, True

    return Hit(correct=correct, damage=damage, hp_left=hp_left,
               skip_reason=skip if skip != "wrong" else None, victory=victory)


# ─────────────────────────────── отчёты ───────────────────────────────

def raid_report(raid_id: int) -> dict:
    """То, что учитель видит на панели класса утром перед контрольной."""
    raid = dict(db.q1("SELECT * FROM raids WHERE id = ?", raid_id))

    roster = db.q(
        "SELECT id, name FROM users WHERE class_id = ? AND role = 'student' ORDER BY name",
        raid["class_id"],
    )
    active_ids = {r["user_id"] for r in db.q(
        "SELECT DISTINCT user_id FROM answers WHERE raid_id = ?", raid_id
    )}

    weak = db.q(
        "SELECT q.id, q.text, COUNT(*) fails FROM answers a"
        " JOIN questions q ON q.id = a.question_id"
        " WHERE a.raid_id = ? AND a.is_correct = 0"
        " GROUP BY q.id ORDER BY fails DESC LIMIT 5",
        raid_id,
    )

    return {
        "raid": raid,
        "total_students": len(roster),
        "participants": len([r for r in roster if r["id"] in active_ids]),
        "absentees": [r["name"] for r in roster if r["id"] not in active_ids],
        "weak": [{"question_id": r["id"], "text": r["text"], "fails": r["fails"]} for r in weak],
        "bank": bank_size(raid["class_id"], raid["topic"], include_library=True),
    }


def class_progress(raid_id: int) -> dict:
    """Что видит ученик в мини-приложении."""
    raid = dict(db.q1("SELECT * FROM raids WHERE id = ?", raid_id))
    today = db.q(
        "SELECT DISTINCT user_id FROM answers WHERE raid_id = ? AND date(created_at) = date('now')",
        raid_id,
    )
    roster = db.q1(
        "SELECT COUNT(*) n FROM users WHERE class_id = ? AND role = 'student'", raid["class_id"]
    )
    return {
        "topic": raid["topic"],
        "subject": raid["subject"] or "",
        "boss": raid["boss"] or "bobr",
        "boss_name": BOSSES.get(raid["boss"] or "bobr", "Босс"),
        "hp_left": raid["hp_left"],
        "hp_max": raid["hp_max"],
        "deadline": raid["deadline"],
        "contributed_today": len(today),
        "class_size": roster["n"],
        "status": raid["status"],
    }
