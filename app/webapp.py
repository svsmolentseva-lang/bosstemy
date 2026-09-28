"""Мини-приложение: HTTP-сервер со шкалой босса.

Специально на стандартной библиотеке - без Flask и FastAPI. Меньше зависимостей,
проще развернуть, и школьнику видно, что происходит на каждой строчке.

Экран открывается внутри MAX как мини-приложение и обращается сюда за состоянием
рейда. Разбор данных о пользователе - в app/auth.py.
"""
import json
import mimetypes
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import auth, config, db, logic

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

# когда бот выдал вопрос - чтобы поймать ответ быстрее, чем можно прочитать
_served: dict[tuple[int, int], float] = {}

# бот, которому вебхук отдаёт события. Ставится из run_all.py
BOT = None

_ADMIN_FILE = os.path.join(os.path.dirname(WEB_DIR), ".admin-token")


def admin_token() -> str:
    """Ключ кабинета администратора: из окружения, из файла или новый."""
    if config.ADMIN_TOKEN:
        return config.ADMIN_TOKEN
    if os.path.isfile(_ADMIN_FILE):
        with open(_ADMIN_FILE, encoding="utf-8") as f:
            saved = f.read().strip()
        if saved:
            return saved
    import secrets
    token = secrets.token_urlsafe(12)
    with open(_ADMIN_FILE, "w", encoding="utf-8") as f:
        f.write(token)
    try:
        os.chmod(_ADMIN_FILE, 0o600)
    except OSError:
        pass
    return token


class Handler(BaseHTTPRequestHandler):
    # ─────────────────────────── маршруты ───────────────────────────

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self.static("index.html")
        if url.path in ("/raids", "/raids.html"):
            return self.static("raids.html")
        if url.path in ("/join", "/join.html"):
            return self.static("join.html")
        if url.path in ("/teacher", "/teacher.html"):
            return self.static("teacher.html")
        if url.path in ("/admin", "/admin.html"):
            return self.static("admin.html")
        if url.path == "/api/admin":
            return self.api_admin(parse_qs(url.query))
        if url.path == "/api/raids":
            return self.api_raids(parse_qs(url.query))
        if url.path == "/api/teacher":
            return self.api_teacher(parse_qs(url.query))
        if url.path == "/api/state":
            return self.api_state(parse_qs(url.query))
        if url.path.startswith("/boss/"):
            return self.static("boss/" + os.path.basename(url.path))
        if url.path.startswith("/static/"):
            return self.static(os.path.basename(url.path))
        self.fail(404, "не найдено")

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/api/answer":
            return self.api_answer(parse_qs(url.query))
        if url.path == "/api/join":
            return self.api_join()
        if url.path == "/api/moderate":
            return self.api_moderate(parse_qs(url.query))
        if url.path == "/api/raid":
            return self.api_raid_create(parse_qs(url.query))
        if url.path == "/api/student/remove":
            return self.api_student_remove(parse_qs(url.query))
        if url.path == "/api/extend":
            return self.api_extend(parse_qs(url.query))
        if url.path == "/api/admin/class":
            return self.api_admin_class(parse_qs(url.query))
        if url.path == "/api/admin/teacher":
            return self.api_admin_teacher(parse_qs(url.query))
        if url.path == "/api/admin/assign":
            return self.api_admin_assign(parse_qs(url.query))
        if url.path == config.WEBHOOK_PATH:
            return self.webhook()
        self.fail(404, "не найдено")

    # ───────────────────────────── вебхук MAX ─────────────────────────────

    def webhook(self):
        """События от MAX приходят сюда.

        В проде MAX требует именно вебхук: long polling разрешён только
        для разработки. Адрес держим в секрете (см. WEBHOOK_PATH) - это
        простейшая защита от посторонних запросов.
        """
        if BOT is None:
            return self.fail(503, "бот не запущен")
        length = int(self.headers.get("Content-Length", 0))
        try:
            raw = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.fail(400, "не json")

        from .transport import MaxTransport
        update = MaxTransport._parse(raw)
        if update:
            try:
                BOT.handle(update)
            except Exception as e:                      # noqa: BLE001
                print(f"[вебхук] ошибка обработки: {e}")
        # MAX ждёт быстрый 200, иначе будет слать событие заново
        self.json({"ok": True})

    # ──────────────────────────── ручки API ────────────────────────────

    def api_join(self):
        """Вход по ссылке: ученик называет имя и получает личный секрет."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.fail(400, "не json")

        code = str(payload.get("code", "")).strip()
        name = str(payload.get("name", "")).strip()
        if not code or not name:
            return self.fail(400, "нужны код класса и имя")

        res = logic.join_by_link(code, name)
        if not res:
            return self.fail(404, "такого кода нет - проверь написание")
        if res.get("taken"):
            return self.fail(409, f"логин «{res['name']}» в классе уже занят - придумай другой."
                                  " А если это ты играл раньше, открой свою ссылку"
                                  " на том устройстве")
        self.json({"token": res["token"], "name": res["name"], "class": res["class"]["title"]})

    # ─────────────────────── кабинет администратора ───────────────────────

    @staticmethod
    def admin_ok(query):
        token = (query.get("t") or [""])[0]
        if not token or token != admin_token():
            raise PermissionError("нужен ключ администратора")

    def body_json(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def api_admin(self, query):
        """Всё, что видит администратор: классы, учителя, открытые рейды."""
        try:
            self.admin_ok(query)
        except PermissionError as e:
            return self.fail(403, str(e))
        base = config.WEBAPP_URL.rstrip("/")
        classes = []
        for c in db.q("SELECT * FROM classes ORDER BY title"):
            raids = [{"subject": r["subject"], "topic": r["topic"], "deadline": r["deadline"],
                      "hp_left": r["hp_left"], "hp_max": r["hp_max"]}
                     for r in db.q("SELECT * FROM raids WHERE class_id = ? AND status = 'active'"
                                   " ORDER BY deadline", c["id"])]
            teachers = [{"id": r["id"], "name": r["name"], "subject": r["subject"]}
                        for r in db.q(
                            "SELECT u.id, u.name, t.subject FROM teaching t"
                            " JOIN users u ON u.id = t.teacher_id WHERE t.class_id = ?"
                            " ORDER BY u.name, t.subject", c["id"])]
            classes.append({
                "id": c["id"], "title": c["title"], "code": c["join_code"],
                "join_url": f"{base}/join?code={c['join_code']}",
                "students": db.q1("SELECT COUNT(*) n FROM users WHERE class_id = ? AND role='student'",
                                  c["id"])["n"],
                "teachers": teachers, "raids": raids,
            })
        teachers = []
        for u in db.q("SELECT * FROM users WHERE role = 'teacher' ORDER BY name"):
            token = logic.token_for(u["id"])
            teachers.append({
                "id": u["id"], "name": u["name"],
                "panel_url": f"{base}/teacher?t={token}",
                "classes": logic.teacher_classes(u["id"]),
            })
        self.json({"classes": classes, "teachers": teachers,
                   "subjects": logic.known_subjects()})

    def api_admin_class(self, query):
        try:
            self.admin_ok(query)
        except PermissionError as e:
            return self.fail(403, str(e))
        data = self.body_json()
        title = (data.get("title") or "").strip()
        if not title:
            return self.fail(400, "нужно название класса")
        code = logic.make_join_code()
        cid = db.run("INSERT INTO classes (title, join_code) VALUES (?, ?)", title, code)
        base = config.WEBAPP_URL.rstrip("/")
        out = {"ok": True, "id": cid, "title": title, "code": code,
               "join_url": f"{base}/join?code={code}"}
        # можно сразу завести учителя - тогда обе ссылки выдаются за один шаг
        tname = (data.get("teacher_name") or "").strip()
        if tname:
            subject = (data.get("subject") or "").strip() or config.DEFAULT_SUBJECT
            ext = (data.get("teacher_ext_id") or "").strip() or f"t:{tname.lower().replace(' ', '-')}"
            teacher = logic.upsert_user(ext, tname, role="teacher")
            logic.assign_teacher(teacher["id"], cid, subject)
            out["teacher"] = {
                "id": teacher["id"], "name": tname, "subject": subject,
                "panel_url": f"{base}/teacher?t={logic.token_for(teacher['id'])}",
            }
        self.json(out)

    def api_admin_teacher(self, query):
        try:
            self.admin_ok(query)
        except PermissionError as e:
            return self.fail(403, str(e))
        data = self.body_json()
        name = (data.get("name") or "").strip()
        if not name:
            return self.fail(400, "нужно имя учителя")
        ext = (data.get("ext_id") or "").strip() or f"t:{name.lower().replace(' ', '-')}"
        user = logic.upsert_user(ext, name, role="teacher")
        token = logic.token_for(user["id"])
        base = config.WEBAPP_URL.rstrip("/")
        self.json({"ok": True, "id": user["id"], "name": name,
                   "panel_url": f"{base}/teacher?t={token}"})

    def api_admin_assign(self, query):
        try:
            self.admin_ok(query)
        except PermissionError as e:
            return self.fail(403, str(e))
        data = self.body_json()
        try:
            teacher_id = int(data.get("teacher_id"))
            class_id = int(data.get("class_id"))
        except (TypeError, ValueError):
            return self.fail(400, "нужны учитель и класс")
        subject = (data.get("subject") or "").strip()
        if not subject:
            return self.fail(400, "нужен предмет")
        if data.get("remove"):
            logic.unassign_teacher(teacher_id, class_id, subject)
        else:
            logic.assign_teacher(teacher_id, class_id, subject)
        self.json({"ok": True})

    # ───────────────────────── список рейдов ученика ─────────────────────────

    def api_raids(self, query):
        """Все открытые рейды класса - ученик видит их сразу при входе."""
        try:
            user = auth.identify(query, headers=None)
        except PermissionError as e:
            return self.fail(403, str(e))
        raids = []
        for r in logic.active_raids(user["class_id"]):
            progress = logic.class_progress(r["id"])
            mine = db.q1(
                "SELECT COUNT(*) n FROM answers WHERE raid_id = ? AND user_id = ?"
                " AND damage > 0 AND date(created_at) = date('now')", r["id"], user["id"])["n"]
            raids.append({
                "id": r["id"], "subject": r["subject"], "topic": r["topic"],
                "deadline": r["deadline"], "hp_left": r["hp_left"], "hp_max": r["hp_max"],
                "boss": r["boss"] or "bobr",
                "boss_name": logic.BOSSES.get(r["boss"] or "bobr", "Босс"),
                "contributed_today": progress["contributed_today"],
                "class_size": progress["class_size"],
                "mine_today": mine,
            })
        cls = db.q1("SELECT * FROM classes WHERE id = ?", user["class_id"])
        self.json({"me": user["name"], "class": cls["title"] if cls else "",
                   "hits_today": logic.hits_today(user["id"]),
                   "daily_cap": config.DAILY_HIT_CAP, "raids": raids})

    # ─────────────────────────── экран учителя ───────────────────────────

    @staticmethod
    def teacher_of(query):
        """Учитель по личной ссылке. Рейда может и не быть - это нормально."""
        user = auth.identify(query, headers=None)
        if user["role"] != "teacher":
            raise PermissionError("эта страница только для учителя")
        return user

    @staticmethod
    def scope_of(user, query):
        """Класс, с которым учитель работает прямо сейчас.

        Учитель может вести несколько классов и несколько предметов в одном
        классе, поэтому панель передаёт номер класса. Без номера берём первый.
        """
        classes = logic.teacher_classes(user["id"])
        if not classes and user["class_id"]:
            row = db.q1("SELECT * FROM classes WHERE id = ?", user["class_id"])
            if row:
                classes = [{"id": row["id"], "title": row["title"],
                            "join_code": row["join_code"], "subjects": []}]
        if not classes:
            raise PermissionError("за учителем пока не закреплён ни один класс")
        want = (query.get("class") or query.get("class_id") or [None])[0]
        chosen = classes[0]
        if want and str(want).isdigit():
            for c in classes:
                if c["id"] == int(want):
                    chosen = c
        return classes, chosen

    def api_teacher(self, query):
        try:
            user = self.teacher_of(query)
            classes, cls = self.scope_of(user, query)
        except PermissionError as e:
            return self.fail(403, str(e))

        class_id = cls["id"]
        raids = logic.active_raids(class_id)
        raid = None
        want = (query.get("raid") or query.get("raid_id") or [None])[0]
        if want and str(want).isdigit():
            raid = next((r for r in raids if r["id"] == int(want)), None)
        if raid is None:
            raid = raids[0] if raids else db.q1(
                "SELECT * FROM raids WHERE class_id = ? ORDER BY id DESC LIMIT 1", class_id)
        if raid is not None:
            raid = dict(raid)

        payload = {
            "teacher": user["name"],
            "class": {"id": class_id, "title": cls["title"], "code": cls["join_code"],
                      "subjects": cls.get("subjects") or []},
            "classes": [{"id": c["id"], "title": c["title"], "subjects": c["subjects"]}
                        for c in classes],
            "raids": [{"id": r["id"], "subject": r["subject"], "topic": r["topic"],
                       "deadline": r["deadline"], "hp_left": r["hp_left"],
                       "hp_max": r["hp_max"]} for r in raids],
            "raid": None,
            "pending": logic.pending_questions(class_id),
            "roster": logic.class_roster(class_id),
            "topics": logic.topics_by_subject(class_id),
            "bosses": [{"key": k, "name": n} for k, n in logic.BOSSES.items()],
        }
        if raid is not None:
            rep = logic.raid_report(raid["id"])
            payload["raid"] = {
                "id": raid["id"],
                "subject": raid.get("subject") or "",
                "topic": rep["raid"]["topic"],
                "status": rep["raid"]["status"],
                "deadline": rep["raid"]["deadline"],
                "hp_left": rep["raid"]["hp_left"],
                "hp_max": rep["raid"]["hp_max"],
                "participants": rep["participants"],
                "total": rep["total_students"],
                "absentees": rep["absentees"],
                "skills": rep["skills"],
                "weak": rep["weak"],
                "bank": rep["bank"],
            }
        self.json(payload)

    def api_moderate(self, query):
        try:
            user = self.teacher_of(query)
            _classes, cls = self.scope_of(user, query)
        except PermissionError as e:
            return self.fail(403, str(e))

        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        qid = int(payload.get("question_id", 0))
        approve = bool(payload.get("approve"))

        question = db.q1("SELECT * FROM questions WHERE id = ?", qid)
        if not question or question["class_id"] != cls["id"]:
            return self.fail(404, "вопрос не найден")

        logic.moderate(qid, approve)
        self.json({"ok": True, "pending": logic.pending_questions(cls["id"])})

    def api_student_remove(self, query):
        """Учитель убирает лишний логин - опечатку или второй вход того же ребёнка."""
        try:
            user = self.teacher_of(query)
            _classes, cls = self.scope_of(user, query)
        except PermissionError as e:
            return self.fail(403, str(e))

        data = self.body_json()
        try:
            uid = int(data.get("id"))
        except (TypeError, ValueError):
            return self.fail(400, "нужен номер ученика")

        if not logic.remove_student(cls["id"], uid):
            return self.fail(400, "убрать не вышло: такого ученика в классе нет или он уже отвечал на вопросы")
        self.json({"ok": True, "roster": logic.class_roster(cls["id"])})

    def api_raid_create(self, query):
        """Учитель объявляет рейд: предмет, тема, срок. Босса выбирает он."""
        try:
            user = self.teacher_of(query)
            _classes, cls = self.scope_of(user, query)
        except PermissionError as e:
            return self.fail(403, str(e))

        data = self.body_json()
        topic = " ".join(str(data.get("topic", "")).split())[:60]
        subject = str(data.get("subject", "")).strip()
        try:
            days = int(data.get("days", 3))
        except (TypeError, ValueError):
            days = 3
        days = max(1, min(days, 14))
        if not topic:
            return self.fail(400, "нужна тема рейда")

        class_id = cls["id"]
        if any(r["topic"] == topic and (r["subject"] or "") == logic.norm_subject(subject)
               for r in logic.active_raids(class_id)):
            return self.fail(400, "по этой теме рейд уже идёт")

        # мало своих вопросов - подтягиваем из общей библиотеки
        if logic.bank_size(class_id, topic) < config.MIN_BANK_FOR_RAID:
            logic.copy_from_library(class_id, topic, subject)
        bank = logic.bank_size(class_id, topic)
        if bank < config.MIN_BANK_FOR_RAID:
            return self.fail(400, f"в теме «{topic}» всего {bank} вопросов,"
                                  f" нужно хотя бы {config.MIN_BANK_FOR_RAID}")

        raid = logic.create_raid(class_id, topic, days,
                                 hp=logic.planned_hp(class_id, days), subject=subject,
                                 boss=str(data.get("boss", "")).strip())
        self.json({"ok": True, "raid": {"id": raid["id"], "subject": raid["subject"],
                                        "topic": raid["topic"], "deadline": raid["deadline"],
                                        "hp_max": raid["hp_max"]}, "bank": bank})

    def api_extend(self, query):
        try:
            user = self.teacher_of(query)
            _classes, cls = self.scope_of(user, query)
        except PermissionError as e:
            return self.fail(403, str(e))
        raids = logic.active_raids(cls["id"])
        want = (query.get("raid") or query.get("raid_id") or [None])[0]
        raid = None
        if want and str(want).isdigit():
            raid = next((r for r in raids if r["id"] == int(want)), None)
        if raid is None:
            raid = raids[0] if raids else None
        if not raid:
            return self.fail(404, "активного рейда нет")
        new_deadline = logic.extend_raid(raid["id"], days=1)
        self.json({"ok": True, "deadline": new_deadline})

    def api_state(self, query):
        try:
            user, raid = self.context(query)
        except PermissionError as e:
            return self.fail(403, str(e))

        state = logic.class_progress(raid["id"])
        state["me"] = {"name": user["name"], "hits_today": logic.hits_today(user["id"])}
        state["question"] = self.take_question(raid, user)
        self.json(state)

    def api_answer(self, query):
        try:
            user, raid = self.context(query)
        except PermissionError as e:
            return self.fail(403, str(e))

        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        question_id = int(payload.get("question_id", 0))
        given = str(payload.get("given", ""))

        # время меряем на сервере: клиенту в таких вещах верить нельзя
        served_at = _served.pop((user["id"], question_id), None)
        elapsed = (time.monotonic() - served_at) if served_at else 999.0

        hit = logic.submit_answer(raid["id"], user["id"], question_id, given, elapsed)
        progress = logic.class_progress(raid["id"])

        self.json({
            "correct": hit.correct,
            "damage": hit.damage,
            "hp_left": hit.hp_left,
            "skip_reason": hit.skip_reason,
            "victory": hit.victory,
            "contributed_today": progress["contributed_today"],
            "class_size": progress["class_size"],
            "question": self.take_question(raid, user) if not hit.victory else None,
        })

    # ──────────────────────────── помощники ────────────────────────────

    @staticmethod
    def take_question(raid, user):
        q = logic.next_question(raid["id"], user["id"])
        if not q:
            return None
        _served[(user["id"], q["id"])] = time.monotonic()
        return {"id": q["id"], "text": q["text"], "options": q["options"]}

    @staticmethod
    def context(query):
        """Кто открыл экран и какой рейд он выбрал.

        В классе может идти несколько рейдов по разным предметам, поэтому
        экран передаёт номер рейда. Без номера берём ближайший по сроку.
        """
        user = auth.identify(query, headers=None)
        want = (query.get("raid") or query.get("raid_id") or [None])[0]
        raid = None
        if want and str(want).isdigit():
            raid = next((r for r in logic.active_raids(user["class_id"])
                         if r["id"] == int(want)), None)
            if raid is None:
                raise PermissionError("этот рейд уже закрыт")
        else:
            raid = logic.active_raid(user["class_id"])
        if not raid:
            raise PermissionError("активного рейда нет")
        return user, raid

    def static(self, name):
        path = os.path.join(WEB_DIR, name)
        if not os.path.isfile(path):
            return self.fail(404, "нет файла")
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def fail(self, code, message):
        self.json({"error": message}, code=code)

    def log_message(self, fmt, *args):
        pass  # не засоряем вывод


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    db.connect()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Мини-приложение слушает http://{host}:{port}")
    server.serve_forever()
