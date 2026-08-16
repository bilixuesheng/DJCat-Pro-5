import hashlib
import os
import re
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)
from werkzeug.security import check_password_hash

DAILY_LIMIT = 15
MAX_CONTENT_LENGTH = 12_000
MAX_CUSTOM_STYLE_LENGTH = 4_000
MAX_SYSTEM_PROMPT_LENGTH = 20_000
DATABASE_PATH = Path(
    os.environ.get("DJCATAI_DATABASE_PATH", "ai_markdown_usage.sqlite3")
)
TIMEZONE = timezone(timedelta(hours=8))
PEAK_HOURS = ((9, 12), (14, 18))
DEEPSEEK_API = "https://api.deepseek.com/chat/completions"
SYSTEM_PROMPT = """你现在需要转换用户的纯文本内容，用户发来的内容可能是一份作业清单，也可能是一份任务，你需要将其转换为简洁标准的markdown格式。
你可以使用的markdown语法有：加粗**ABC**，分割线---（少用），分点- ，以及这个>。当遇到任务一部分是正常的任务，一部分是其他的警告比如要值日，必须要像下面的示例一样用---分开
此处给一些格式示例：
原输入：
语文作业做小册28页吧
英语大册welcome部分
物理大册往后做吧，然后复习
要求输出：
**【语文】**
- 做小册28页

**【英语】**
- 大册welcome部分

**【物理】**
- 大册往后做
- 复习
原输入：
语文作业：
1、上周写的试卷。2、订正默写
要求输出：
**【语文】**
- 上周写的试卷
- 订正默写

**【英语】**
- 大册的第五第六单元assessment

**【物理】**
- 今天写随堂小练40-42
- 图片里内容添加到笔记上

原输入：
今天数学作业做大册103页
值日人员到卫生区打扫
要求输出：
**【数学】**
- 做大册103页
---
**⚠️请值日人员到卫生区打扫⚠️**

原输入：
英语中午做97页，值日
要求输出：
**【英语】**
- 做97页
---
**⚠️请值日人员到卫生区打扫⚠️**

由于该内容需要在电脑屏幕上显示，尽量让行数不多。"""
CUSTOM_STYLE_PREFIX = """

以上为系统默认提示词，以下为用户希望自定义的微调提示词，若规则有冲突，请以下面的内容为准：
"""

app = Flask(__name__)
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
)
if os.environ.get("DJCATAI_ADMIN_SESSION_SECRET"):
    app.config["SECRET_KEY"] = os.environ["DJCATAI_ADMIN_SESSION_SECRET"]

_databaseInitLock = threading.Lock()
_initializedDatabases = set()


def _systemPrompt(customStyle):
    systemPrompt = _setting("system_prompt", SYSTEM_PROMPT).strip() or SYSTEM_PROMPT
    customStyle = customStyle.strip()
    if not customStyle:
        return systemPrompt
    return f"{systemPrompt}{CUSTOM_STYLE_PREFIX}{customStyle}"


def _machineId(value):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError("无效的设备标识")

    salt = os.environ.get("DJCATAI_RATE_LIMIT_SALT")
    if not salt:
        raise RuntimeError("服务器未配置 DJCATAI_RATE_LIMIT_SALT")
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def _today():
    return datetime.now(TIMEZONE).date().isoformat()


def _nowIso():
    return datetime.now(TIMEZONE).isoformat(timespec="seconds")


def _quotaCost(now=None, peakEnabled=None):
    if peakEnabled is None:
        peakEnabled = _setting("peak_enabled", "1") == "1"
    if not peakEnabled:
        return 1
    hour = (now or datetime.now(TIMEZONE)).astimezone(TIMEZONE).hour
    return 2 if any(start <= hour < end for start, end in PEAK_HOURS) else 1


def _connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(DATABASE_PATH, timeout=10)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    databaseKey = str(DATABASE_PATH.resolve())
    if databaseKey not in _initializedDatabases:
        with _databaseInitLock:
            if databaseKey not in _initializedDatabases:
                database.executescript(
                    """
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS usage (
            day TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY (day, machine_id)
        );
        CREATE TABLE IF NOT EXISTS machines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT NOT NULL UNIQUE,
            registered_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS request_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            cost INTEGER NOT NULL,
            status TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS request_log_day_idx ON request_log(day);
        CREATE INDEX IF NOT EXISTS request_log_machine_idx
            ON request_log(machine_id);
        INSERT OR IGNORE INTO machines(machine_id, registered_at, last_seen_at)
        SELECT
            machine_id,
            MIN(day) || 'T00:00:00+08:00',
            MAX(day) || 'T00:00:00+08:00'
        FROM usage
        GROUP BY machine_id;
                    """
                )
                _initializedDatabases.add(databaseKey)
    return database


def _setting(key, default=None):
    with closing(_connect()) as database:
        row = database.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def _dailyLimit():
    try:
        return max(1, min(10_000, int(_setting("daily_limit", DAILY_LIMIT))))
    except (TypeError, ValueError):
        return DAILY_LIMIT


def _deepseekModel():
    return _setting("deepseek_model", "deepseek-v4-flash")


def _fernet():
    key = os.environ.get("DJCATAI_SETTINGS_KEY")
    if not key:
        raise RuntimeError("服务器未配置 DJCATAI_SETTINGS_KEY")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as error:
        raise RuntimeError("DJCATAI_SETTINGS_KEY 格式无效") from error


def _deepseekApiKey():
    encrypted = _setting("deepseek_api_key")
    if not encrypted:
        return os.environ.get("DEEPSEEK_API_KEY", "")
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except (InvalidToken, UnicodeDecodeError) as error:
        raise RuntimeError("面板中保存的 DeepSeek API Key 无法解密") from error


def _saveAISettings(
    dailyLimit,
    peakEnabled,
    model,
    systemPrompt,
    apiKey="",
    clearApiKey=False,
):
    settings = [
        ("daily_limit", str(dailyLimit)),
        ("peak_enabled", "1" if peakEnabled else "0"),
        ("deepseek_model", model),
        ("system_prompt", systemPrompt),
    ]
    if apiKey and not clearApiKey:
        settings.append(
            (
                "deepseek_api_key",
                _fernet().encrypt(apiKey.encode()).decode(),
            )
        )
    with closing(_connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        database.executemany(
            """
            INSERT INTO settings(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            settings,
        )
        if clearApiKey:
            database.execute("DELETE FROM settings WHERE key = 'deepseek_api_key'")
        database.commit()


def _saveSystemPrompt(systemPrompt):
    with closing(_connect()) as database:
        database.execute(
            """
            INSERT INTO settings(key, value) VALUES ('system_prompt', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (systemPrompt,),
        )
        database.commit()


def _registerMachine(machineId):
    now = _nowIso()
    with closing(_connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute(
            "SELECT id FROM machines WHERE machine_id = ?", (machineId,)
        ).fetchone()
        if row:
            machineNumber = row["id"]
            database.execute(
                "UPDATE machines SET last_seen_at = ? WHERE id = ?",
                (now, machineNumber),
            )
        else:
            cursor = database.execute(
                """
                INSERT INTO machines(machine_id, registered_at, last_seen_at)
                VALUES (?, ?, ?)
                """,
                (machineId, now, now),
            )
            machineNumber = cursor.lastrowid
        database.commit()
    return f"DJ-{machineNumber:06d}"


def _recordFailedRequest(machineId, cost, day=None):
    day = day or _today()
    with closing(_connect()) as database:
        database.execute(
            """
            INSERT INTO request_log(day, machine_id, requested_at, cost, status)
            VALUES (?, ?, ?, ?, 'failed')
            """,
            (day, machineId, _nowIso(), cost),
        )
        database.commit()


def _requestFinished(requestId, success, machineId=None, cost=0, day=None):
    with closing(_connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        if not success and machineId:
            database.execute(
                """
                UPDATE usage SET count = count - ?
                WHERE day = ? AND machine_id = ? AND count >= ?
                """,
                (cost, day or _today(), machineId, cost),
            )
        database.execute(
            "UPDATE request_log SET status = ? WHERE id = ?",
            ("success" if success else "failed", requestId),
        )
        database.commit()


def _remaining(machineId, day=None, limit=None):
    day = day or _today()
    limit = limit or _dailyLimit()
    with closing(_connect()) as database:
        row = database.execute(
            "SELECT count FROM usage WHERE day = ? AND machine_id = ?",
            (day, machineId),
        ).fetchone()
    return max(0, limit - (row[0] if row else 0))


def _claimInTransaction(database, machineId, cost, day, limit):
    row = database.execute(
        "SELECT count FROM usage WHERE day = ? AND machine_id = ?",
        (day, machineId),
    ).fetchone()
    count = row[0] if row else 0
    if count + cost > limit:
        return -1

    database.execute(
        """
        INSERT INTO usage (day, machine_id, count) VALUES (?, ?, ?)
        ON CONFLICT(day, machine_id) DO UPDATE SET count = count + excluded.count
        """,
        (day, machineId, cost),
    )
    return limit - count - cost


def _claim(machineId, cost, day=None, limit=None):
    day = day or _today()
    limit = limit or _dailyLimit()
    with closing(_connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        remaining = _claimInTransaction(database, machineId, cost, day, limit)
        if remaining < 0:
            database.rollback()
            return -1
        database.commit()
    return remaining


def _claimRequest(machineId, cost, day, limit):
    with closing(_connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        remaining = _claimInTransaction(database, machineId, cost, day, limit)
        if remaining < 0:
            database.rollback()
            return -1, None
        cursor = database.execute(
            """
            INSERT INTO request_log(day, machine_id, requested_at, cost, status)
            VALUES (?, ?, ?, ?, 'processing')
            """,
            (day, machineId, _nowIso(), cost),
        )
        database.commit()
    return remaining, cursor.lastrowid


def _refund(machineId, cost, day=None):
    day = day or _today()
    with closing(_connect()) as database:
        database.execute(
            """
            UPDATE usage SET count = count - ?
            WHERE day = ? AND machine_id = ? AND count >= ?
            """,
            (cost, day, machineId, cost),
        )
        database.commit()


def _error(message, status):
    response = jsonify({"message": message})
    response.status_code = status
    return response


@app.post("/ai/markdown/register")
def registerMachine():
    try:
        machineId = _machineId((request.get_json(silent=True) or {}).get("machine_id"))
        return jsonify({"machine_code": _registerMachine(machineId)})
    except ValueError as error:
        return _error(str(error), 400)
    except RuntimeError as error:
        return _error(str(error), 503)


@app.get("/ai/markdown/quota")
def quota():
    try:
        machineId = _machineId(request.args.get("machine_id"))
        machineCode = _registerMachine(machineId)
        peakEnabled = _setting("peak_enabled", "1") == "1"
        return jsonify(
            {
                "remaining": _remaining(machineId),
                "limit": _dailyLimit(),
                "cost": _quotaCost(peakEnabled=peakEnabled),
                "peak_enabled": peakEnabled,
                "machine_code": machineCode,
            }
        )
    except ValueError as error:
        return _error(str(error), 400)
    except RuntimeError as error:
        return _error(str(error), 503)


@app.post("/ai/markdown")
def convert():
    try:
        apiKey = _deepseekApiKey()
    except RuntimeError as error:
        return _error(str(error), 503)
    if not apiKey:
        return _error("服务器未配置 DEEPSEEK_API_KEY", 503)

    body = request.get_json(silent=True) or {}
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        return _error("请输入要转换的内容", 400)
    if len(content) > MAX_CONTENT_LENGTH:
        return _error(f"输入内容不能超过 {MAX_CONTENT_LENGTH} 个字符", 400)

    customStyle = body.get("custom_style", "")
    if not isinstance(customStyle, str):
        return _error("自定义 Markdown 风格必须是文本", 400)
    if len(customStyle) > MAX_CUSTOM_STYLE_LENGTH:
        return _error(
            f"自定义 Markdown 风格不能超过 {MAX_CUSTOM_STYLE_LENGTH} 个字符",
            400,
        )

    try:
        machineId = _machineId(body.get("machine_id"))
    except ValueError as error:
        return _error(str(error), 400)
    except RuntimeError as error:
        return _error(str(error), 503)

    _registerMachine(machineId)
    day = _today()
    limit = _dailyLimit()
    cost = _quotaCost()
    model = _deepseekModel()
    try:
        remaining, requestId = _claimRequest(machineId, cost, day, limit)
    except sqlite3.Error:
        return _error("额度服务暂时不可用，请稍后再试。", 503)
    if remaining < 0:
        remaining = _remaining(machineId, day, limit)
        _recordFailedRequest(machineId, 0, day)
        message = (
            "当前为双倍时段，剩余额度不足，请在非双倍时段再试。"
            if remaining
            else "今天的转换额度已用完，请明天再试。"
        )
        response = _error(message, 429)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Cost"] = str(cost)
        return response

    upstream = None
    try:
        upstream = requests.post(
            DEEPSEEK_API,
            headers={
                "Authorization": f"Bearer {apiKey}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _systemPrompt(customStyle)},
                    {"role": "user", "content": content.strip()},
                ],
                "thinking": {"type": "disabled"},
                "stream": True,
                "max_tokens": 1500,
            },
            stream=True,
            timeout=(10, 120),
        )
        upstream.raise_for_status()
    except requests.RequestException:
        if upstream:
            upstream.close()
        _requestFinished(requestId, False, machineId, cost, day)
        return _error("AI 服务暂时不可用，请稍后再试。", 502)

    @stream_with_context
    def stream():
        completed = False
        try:
            for line in upstream.iter_lines(chunk_size=1):
                if line:
                    if line.startswith(b"data:") and line[5:].strip() == b"[DONE]":
                        completed = True
                    yield line + b"\n\n"
        finally:
            _requestFinished(
                requestId,
                completed,
                machineId if not completed else None,
                cost,
                day,
            )
            upstream.close()

    return Response(
        stream(),
        content_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Cost": str(cost),
        },
    )


def _adminHost():
    return os.environ.get("DJCATAI_ADMIN_HOST", "dash.djcatpro.top").lower()


def _onAdminHost():
    return request.host.partition(":")[0].lower() == _adminHost()


def _adminConfigured():
    return all(
        (
            app.secret_key,
            os.environ.get("DJCATAI_ADMIN_USERNAME"),
            os.environ.get("DJCATAI_ADMIN_PASSWORD_HASH"),
        )
    )


def _csrfToken():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _checkCsrf():
    expected = session.get("csrf_token", "")
    received = request.form.get("csrf_token", "")
    if not expected or not secrets.compare_digest(expected, received):
        abort(400, "无效的请求令牌")


def _isAjaxRequest():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or (
        request.accept_mimetypes.best == "application/json"
    )


def _adminResponse(message, category, endpoint, status=200, url_values=None):
    if _isAjaxRequest():
        return jsonify(message=message, category=category), status
    flash(message, category)
    return redirect(url_for(endpoint, **(url_values or {})))


def _adminRoute(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _onAdminHost():
            abort(404)
        if not _adminConfigured():
            return "管理面板环境变量未配置完整", 503
        return view(*args, **kwargs)

    return wrapped


def _loginRequired(view):
    @wraps(view)
    @_adminRoute
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("adminLogin"))
        return view(*args, **kwargs)

    return wrapped


def _dashboardStats():
    day = _today()
    with closing(_connect()) as database:
        machines = database.execute("SELECT COUNT(*) FROM machines").fetchone()[0]
        requestsByStatus = {
            row["status"]: row["count"]
            for row in database.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM request_log WHERE day = ? GROUP BY status
                """,
                (day,),
            )
        }
        consumed = database.execute(
            "SELECT COALESCE(SUM(count), 0) FROM usage WHERE day = ?", (day,)
        ).fetchone()[0]
        allRequests = database.execute(
            "SELECT COUNT(*) FROM request_log"
        ).fetchone()[0]
        allByStatus = {
            row["status"]: row["count"]
            for row in database.execute(
                "SELECT status, COUNT(*) AS count FROM request_log GROUP BY status"
            )
        }
        allConsumed = database.execute(
            "SELECT COALESCE(SUM(CASE WHEN status IN ('success', 'processing') "
            "THEN cost ELSE 0 END), 0) FROM request_log"
        ).fetchone()[0]
    market = marketplaceStats(_connect, day)
    today = {
        "ai_requests": sum(requestsByStatus.values()),
        "ai_success": requestsByStatus.get("success", 0),
        "ai_failed": requestsByStatus.get("failed", 0),
        "market_downloads": market["today_downloads"],
    }
    allData = {
        "ai_requests": allRequests,
        "ai_success": allByStatus.get("success", 0),
        "ai_failed": allByStatus.get("failed", 0),
        "market_downloads": market["downloads"],
    }
    return {
        "machines": machines,
        "requests": sum(requestsByStatus.values()),
        "success": requestsByStatus.get("success", 0),
        "failed": requestsByStatus.get("failed", 0),
        "processing": requestsByStatus.get("processing", 0),
        "consumed": consumed,
        "today": today,
        "all": allData,
        "all_consumed": allConsumed,
        "market": market,
    }


def _machineRows(search="", sort="registered"):
    day = _today()
    limit = _dailyLimit()
    with closing(_connect()) as database:
        rows = database.execute(
            """
            SELECT
                m.id,
                m.machine_id,
                m.registered_at,
                m.last_seen_at,
                COALESCE(u.count, 0) AS used,
                COUNT(r.id) AS requests
            FROM machines m
            LEFT JOIN usage u ON u.machine_id = m.machine_id AND u.day = ?
            LEFT JOIN request_log r ON r.machine_id = m.machine_id
            GROUP BY m.id
            """,
            (day,),
        ).fetchall()

    machines = [
        {
            "code": f"DJ-{row['id']:06d}",
            "fingerprint": row["machine_id"],
            "registered_at": row["registered_at"],
            "last_seen_at": row["last_seen_at"],
            "used": row["used"],
            "remaining": max(0, limit - row["used"]),
            "requests": row["requests"],
        }
        for row in rows
    ]
    search = search.strip().lower()
    if search:
        machines = [
            machine
            for machine in machines
            if search in machine["code"].lower()
            or search in machine["fingerprint"].lower()
        ]
    machines.sort(
        key=(
            (lambda machine: machine["code"])
            if sort == "code"
            else (lambda machine: machine["registered_at"])
        ),
        reverse=sort != "code",
    )
    return machines


def _resetMachine(alias):
    match = re.fullmatch(r"DJ-(\d{6})", alias)
    if not match:
        return False
    with closing(_connect()) as database:
        row = database.execute(
            "SELECT machine_id FROM machines WHERE id = ?", (int(match.group(1)),)
        ).fetchone()
        if not row:
            return False
        database.execute(
            "DELETE FROM usage WHERE day = ? AND machine_id = ?",
            (_today(), row["machine_id"]),
        )
        database.commit()
    return True


@app.after_request
def secureResponses(response):
    if request.path.startswith("/admin") or _onAdminHost():
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; img-src 'self' data:; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/")
def adminRoot():
    if not _onAdminHost():
        abort(404)
    return redirect(url_for("adminDashboard"))


@app.route("/admin/login", methods=["GET", "POST"])
@_adminRoute
def adminLogin():
    if request.method == "POST":
        _checkCsrf()
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        valid = secrets.compare_digest(
            username, os.environ["DJCATAI_ADMIN_USERNAME"]
        ) and check_password_hash(
            os.environ["DJCATAI_ADMIN_PASSWORD_HASH"], password
        )
        if valid:
            session.clear()
            session["admin"] = True
            session.permanent = True
            _csrfToken()
            return redirect(url_for("adminDashboard"))
        flash("用户名或密码错误", "error")
    return render_template("admin_login.html", csrf_token=_csrfToken())


@app.get("/admin/")
@_loginRequired
def adminDashboard():
    return render_template(
        "admin_dashboard.html",
        csrf_token=_csrfToken(),
        current_page="home",
        stats=_dashboardStats(),
        daily_limit=_dailyLimit(),
        peak_enabled=_setting("peak_enabled", "1") == "1",
        model=_deepseekModel(),
        ai_configured=bool(
            _setting("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY")
        ),
    )


@app.get("/admin/ai/markdown/")
@_loginRequired
def adminAIMarkdown():
    peakEnabled = _setting("peak_enabled", "1") == "1"
    return render_template(
        "admin_ai_overview.html",
        csrf_token=_csrfToken(),
        current_page="ai_overview",
        stats=_dashboardStats(),
        daily_limit=_dailyLimit(),
        peak_enabled=peakEnabled,
        quota_cost=_quotaCost(peakEnabled=peakEnabled),
        model=_deepseekModel(),
        ai_configured=bool(
            _setting("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY")
        ),
    )


@app.route("/admin/ai/markdown/settings", methods=["GET", "POST"])
@_loginRequired
def adminSettings():
    if request.method == "GET":
        return render_template(
            "admin_ai_settings.html",
            csrf_token=_csrfToken(),
            current_page="ai_settings",
            daily_limit=_dailyLimit(),
            peak_enabled=_setting("peak_enabled", "1") == "1",
            model=_deepseekModel(),
            api_key_configured=bool(
                _setting("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY")
            ),
        )

    _checkCsrf()
    try:
        dailyLimit = int(request.form.get("daily_limit", ""))
    except ValueError:
        dailyLimit = 0
    model = request.form.get("model", "").strip()
    systemPrompt = _setting("system_prompt", SYSTEM_PROMPT)
    if not 1 <= dailyLimit <= 10_000:
        return _adminResponse(
            "每日额度必须在 1 到 10000 之间", "error", "adminSettings", 400
        )
    elif not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", model):
        return _adminResponse("模型名称格式无效", "error", "adminSettings", 400)
    elif not systemPrompt:
        return _adminResponse("系统提示词不能为空", "error", "adminSettings", 400)
    elif len(systemPrompt) > MAX_SYSTEM_PROMPT_LENGTH:
        return _adminResponse(
            f"系统提示词不能超过 {MAX_SYSTEM_PROMPT_LENGTH} 个字符",
            "error",
            "adminSettings",
            400,
        )
    else:
        apiKey = request.form.get("api_key", "").strip()
        try:
            _saveAISettings(
                dailyLimit,
                bool(request.form.get("peak_enabled")),
                model,
                systemPrompt,
                apiKey,
                bool(request.form.get("clear_api_key")),
            )
        except (RuntimeError, sqlite3.Error) as error:
            return _adminResponse(str(error), "error", "adminSettings", 400)
        return _adminResponse("AI 配置已保存", "success", "adminSettings")


@app.route("/admin/ai/markdown/prompt", methods=["GET", "POST"])
@_loginRequired
def adminPrompt():
    if request.method == "GET":
        return render_template(
            "admin_ai_prompt.html",
            csrf_token=_csrfToken(),
            current_page="ai_prompt",
            system_prompt=_setting("system_prompt", SYSTEM_PROMPT),
            max_system_prompt_length=MAX_SYSTEM_PROMPT_LENGTH,
        )

    _checkCsrf()
    systemPrompt = request.form.get("system_prompt", "").strip()
    if not systemPrompt:
        return _adminResponse("系统提示词不能为空", "error", "adminPrompt", 400)
    elif len(systemPrompt) > MAX_SYSTEM_PROMPT_LENGTH:
        return _adminResponse(
            f"系统提示词不能超过 {MAX_SYSTEM_PROMPT_LENGTH} 个字符",
            "error",
            "adminPrompt",
            400,
        )
    else:
        try:
            _saveSystemPrompt(systemPrompt)
        except sqlite3.Error as error:
            return _adminResponse(str(error), "error", "adminPrompt", 400)
        else:
            return _adminResponse("系统提示词已保存", "success", "adminPrompt")


@app.get("/admin/ai/markdown/machines/")
@_loginRequired
def adminMachines():
    search = request.args.get("q", "")
    sort = request.args.get("sort", "registered")
    if sort not in {"registered", "code"}:
        sort = "registered"
    return render_template(
        "admin_ai_machines.html",
        csrf_token=_csrfToken(),
        current_page="ai_machines",
        machines=_machineRows(search, sort),
        search=search,
        sort=sort,
        daily_limit=_dailyLimit(),
    )


@app.post("/admin/ai/markdown/machines/<alias>/reset")
@_loginRequired
def adminResetMachine(alias):
    _checkCsrf()
    reset = _resetMachine(alias)
    return _adminResponse(
        "机器额度已重置" if reset else "未找到该机器",
        "success" if reset else "error",
        "adminMachines",
        200 if reset else 404,
    )


@app.post("/admin/ai/markdown/machines/reset-all")
@app.post("/admin/ai/markdown/reset-all")
@_loginRequired
def adminResetAll():
    _checkCsrf()
    with closing(_connect()) as database:
        database.execute("DELETE FROM usage WHERE day = ?", (_today(),))
        database.commit()
    return _adminResponse("所有机器今日额度已重置", "success", "adminMachines")


@app.post("/admin/logout")
@_loginRequired
def adminLogout():
    _checkCsrf()
    session.clear()
    return redirect(url_for("adminLogin"))


try:
    from .app_store import marketplaceStats, register_app_store
except ImportError:
    from app_store import marketplaceStats, register_app_store

register_app_store(
    app,
    connect=_connect,
    login_required=_loginRequired,
    csrf_token=_csrfToken,
    check_csrf=_checkCsrf,
    admin_response=_adminResponse,
)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "18080")))
