import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

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
MAX_REQUEST_BYTES = 64 * 1024
PROCESSING_TIMEOUT = timedelta(minutes=15)
REQUEST_LOG_RETENTION_DAYS = 180
CONVERSION_LOG_RETENTION_DAYS = 30
DATABASE_PATH = Path(
    os.environ.get("DJCATAI_DATABASE_PATH", "ai_markdown_usage.sqlite3")
)
TIMEZONE = timezone(timedelta(hours=8))
PEAK_HOURS = ((9, 12), (14, 18))
DEEPSEEK_API = "https://api.deepseek.com/chat/completions"


def _httpsResponseChain(response, requestedUrl):
    urls = [requestedUrl]
    history = getattr(response, "history", ())
    if isinstance(history, (list, tuple)):
        urls.extend(
            item.url
            for item in history
            if isinstance(getattr(item, "url", None), str)
        )
    effectiveUrl = getattr(response, "url", None)
    urls.append(effectiveUrl if isinstance(effectiveUrl, str) else requestedUrl)
    for url in urls:
        try:
            if urlparse(url).scheme.lower() != "https":
                return False
        except ValueError:
            return False
    return True


DEFAULT_PROMPT_TEMPLATE = (
    "你现在需要转换用户的纯文本内容，用户发来的内容可能是一份作业清单，"
    "也可能是一份任务，你需要将其转换为简洁标准的markdown格式。\n"
    "你可以使用的markdown语法有：加粗**ABC**，分割线---（少用），分点- ，"
    "以及这个>。当遇到任务一部分是正常的任务，一部分是其他的警告比如要值日，"
    "必须要像下面的示例一样用---分开\n"
    "由于该内容需要在电脑屏幕上显示，尽量让行数不多。"
)

DEFAULT_EXAMPLES = [
    (
        "语文作业做小册28页吧\n英语大册welcome部分\n物理大册往后做吧，然后复习",
        "**【语文】**\n- 做小册28页\n\n**【英语】**\n- 大册welcome部分\n\n"
        "**【物理】**\n- 大册往后做\n- 复习",
    ),
    (
        "语文作业：\n1、上周写的试卷。2、订正默写",
        "**【语文】**\n- 上周写的试卷\n- 订正默写\n\n"
        "**【英语】**\n- 大册的第五第六单元assessment\n\n"
        "**【物理】**\n- 今天写随堂小练40-42\n- 图片里内容添加到笔记上",
    ),
    (
        "今天数学作业做大册103页\n值日人员到卫生区打扫",
        "**【数学】**\n- 做大册103页\n---\n**⚠️请值日人员到卫生区打扫⚠️**",
    ),
    (
        "英语中午做97页，值日",
        "**【英语】**\n- 做97页\n---\n**⚠️请值日人员到卫生区打扫⚠️**",
    ),
]

_LEGACY_SYSTEM_PROMPT = (
    "你现在需要转换用户的纯文本内容，用户发来的内容可能是一份作业清单，"
    "也可能是一份任务，你需要将其转换为简洁标准的markdown格式。\n"
    "你可以使用的markdown语法有：加粗**ABC**，分割线---（少用），分点- ，"
    "以及这个>。当遇到任务一部分是正常的任务，一部分是其他的警告比如要值日，"
    "必须要像下面的示例一样用---分开\n"
    "此处给一些格式示例：\n"
    "原输入：\n语文作业做小册28页吧\n英语大册welcome部分\n"
    "物理大册往后做吧，然后复习\n"
    "要求输出：\n**【语文】**\n- 做小册28页\n\n**【英语】**\n- 大册welcome部分"
    "\n\n**【物理】**\n- 大册往后做\n- 复习\n"
    "原输入：\n语文作业：\n1、上周写的试卷。2、订正默写\n"
    "要求输出：\n**【语文】**\n- 上周写的试卷\n- 订正默写\n\n"
    "**【英语】**\n- 大册的第五第六单元assessment\n\n"
    "**【物理】**\n- 今天写随堂小练40-42\n- 图片里内容添加到笔记上\n\n"
    "原输入：\n今天数学作业做大册103页\n值日人员到卫生区打扫\n"
    "要求输出：\n**【数学】**\n- 做大册103页\n---\n"
    "**⚠️请值日人员到卫生区打扫⚠️**\n\n"
    "原输入：\n英语中午做97页，值日\n"
    "要求输出：\n**【英语】**\n- 做97页\n---\n"
    "**⚠️请值日人员到卫生区打扫⚠️**\n\n"
    "由于该内容需要在电脑屏幕上显示，尽量让行数不多。"
)
CUSTOM_STYLE_PREFIX = """

以上为系统默认提示词，以下为用户希望自定义的微调提示词，若规则有冲突，请以下面的内容为准：
"""

app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
)
if os.environ.get("DJCATAI_ADMIN_SESSION_SECRET"):
    app.config["SECRET_KEY"] = os.environ["DJCATAI_ADMIN_SESSION_SECRET"]

_databaseInitLock = threading.Lock()
_initializedDatabases = {}


def _databaseIdentity(path, database):
    try:
        info = os.stat(path)
    except OSError:
        return None
    schemaVersion = database.execute("PRAGMA schema_version").fetchone()[0]
    # Inodes can be reused when a database is replaced at the same path. The
    # schema version distinguishes an empty replacement without tracking writes.
    return (info.st_dev, info.st_ino, schemaVersion)


def _migratePromptExamples(database):
    existing = database.execute(
        "SELECT COUNT(*) FROM prompt_examples"
    ).fetchone()[0]
    if existing:
        return
    now = _nowIso()
    database.executemany(
        """
        INSERT INTO prompt_examples(input_content, output_content, sort_order, created_at)
        VALUES (?, ?, ?, ?)
        """,
        [
            (inputText, outputText, index, now)
            for index, (inputText, outputText) in enumerate(DEFAULT_EXAMPLES)
        ],
    )
    stored = database.execute(
        "SELECT value FROM settings WHERE key = 'system_prompt'"
    ).fetchone()
    if stored and stored[0].strip() == _LEGACY_SYSTEM_PROMPT.strip():
        database.execute(
            "UPDATE settings SET value = ? WHERE key = 'system_prompt'",
            (DEFAULT_PROMPT_TEMPLATE,),
        )
    database.commit()


def _promptExamples():
    with closing(_connect()) as database:
        return database.execute(
            "SELECT input_content, output_content FROM prompt_examples "
            "ORDER BY sort_order, id"
        ).fetchall()


def _formatExamples(rows):
    if not rows:
        return ""
    parts = ["此处给一些格式示例："]
    for row in rows:
        parts.append(
            f"原输入：\n{row['input_content']}\n"
            f"要求输出：\n{row['output_content']}"
        )
    return "\n".join(parts)


def _systemPrompt(customStyle):
    template = (
        _setting("system_prompt", DEFAULT_PROMPT_TEMPLATE).strip()
        or DEFAULT_PROMPT_TEMPLATE
    )
    examplesText = _formatExamples(_promptExamples())
    systemPrompt = f"{template}\n{examplesText}" if examplesText else template
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
    now = (now or datetime.now(TIMEZONE)).astimezone(TIMEZONE)
    hour = now.hour
    if not any(start <= hour < end for start, end in PEAK_HOURS):
        return 1
    if _setting("holiday_exempt", "0") == "1" and _isOffPeakDay(now):
        return 1
    return 2


def _isOffPeakDay(now=None):
    now = (now or datetime.now(TIMEZONE)).astimezone(TIMEZONE)
    if now.weekday() >= 5:
        return True
    try:
        _refreshHolidayCache()
    except Exception:
        pass
    holidays = _cachedHolidays()
    return now.strftime("%Y-%m-%d") in holidays


def _cachedHolidays():
    with closing(_connect()) as database:
        row = database.execute(
            "SELECT value FROM settings WHERE key = 'holiday_cache'"
        ).fetchone()
    if not row:
        return set()
    try:
        data = json.loads(row[0])
        return set(data.get("dates", []))
    except (json.JSONDecodeError, AttributeError):
        return set()


def _refreshHolidayCache():
    today = _today()
    with closing(_connect()) as database:
        row = database.execute(
            "SELECT value FROM settings WHERE key = 'holiday_cache'"
        ).fetchone()
    if row:
        try:
            data = json.loads(row[0])
            if data.get("refreshed") == today:
                return True
        except (json.JSONDecodeError, AttributeError):
            pass
    year = datetime.now(TIMEZONE).year
    dates = set()
    for y in (year, year + 1):
        try:
            resp = requests.get(
                f"https://date.nager.at/api/v3/PublicHolidays/{y}/CN",
                timeout=10,
            )
            if resp.ok:
                for item in resp.json():
                    dates.add(item["date"])
        except (requests.RequestException, KeyError, ValueError):
            pass
    if not dates:
        return False
    cache = json.dumps({"refreshed": today, "dates": sorted(dates)})
    with closing(_connect()) as database:
        database.execute(
            "INSERT INTO settings(key, value) VALUES ('holiday_cache', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (cache,),
        )
        database.commit()
    return True


def _connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(DATABASE_PATH, timeout=10)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    databaseKey = str(DATABASE_PATH.resolve())
    identity = _databaseIdentity(databaseKey, database)
    if _initializedDatabases.get(databaseKey) != identity:
        with _databaseInitLock:
            identity = _databaseIdentity(databaseKey, database)
            if _initializedDatabases.get(databaseKey) != identity:
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
        CREATE INDEX IF NOT EXISTS request_log_status_requested_idx
            ON request_log(status, requested_at);
        CREATE TABLE IF NOT EXISTS request_daily_stats (
            day TEXT PRIMARY KEY,
            requests INTEGER NOT NULL DEFAULT 0,
            success INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            consumed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS machine_request_totals (
            machine_id TEXT PRIMARY KEY,
            requests INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS conversion_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT NOT NULL,
            input_content TEXT NOT NULL,
            output_content TEXT NOT NULL,
            custom_style TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE INDEX IF NOT EXISTS conversion_logs_status_idx
            ON conversion_logs(status);
        CREATE INDEX IF NOT EXISTS conversion_logs_created_idx
            ON conversion_logs(created_at);
        CREATE TABLE IF NOT EXISTS prompt_examples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            input_content TEXT NOT NULL,
            output_content TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        INSERT OR IGNORE INTO machines(machine_id, registered_at, last_seen_at)
        SELECT
            machine_id,
            MIN(day) || 'T00:00:00+08:00',
            MAX(day) || 'T00:00:00+08:00'
        FROM usage
        GROUP BY machine_id;
                    """
                )
                _migratePromptExamples(database)
                _initializedDatabases[databaseKey] = _databaseIdentity(
                    databaseKey, database
                )
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
    apiKey="",
    clearApiKey=False,
    holidayExempt=False,
):
    settings = [
        ("daily_limit", str(dailyLimit)),
        ("peak_enabled", "1" if peakEnabled else "0"),
        ("deepseek_model", model),
        ("holiday_exempt", "1" if holidayExempt else "0"),
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


def _registeredMachineCode(machineId):
    with closing(_connect()) as database:
        row = database.execute(
            "SELECT id FROM machines WHERE machine_id = ?", (machineId,)
        ).fetchone()
    return f"DJ-{row['id']:06d}" if row else ""


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
        cursor = database.execute(
            """
            UPDATE request_log SET status = ?
            WHERE id = ? AND status = 'processing'
            """,
            ("success" if success else "failed", requestId),
        )
        if cursor.rowcount != 1:
            database.commit()
            return False
        if not success and machineId:
            database.execute(
                """
                UPDATE usage SET count = count - ?
                WHERE day = ? AND machine_id = ? AND count >= ?
                """,
                (cost, day or _today(), machineId, cost),
            )
        database.commit()
    return True


def _recoverStaleRequests():
    cutoff = (datetime.now(TIMEZONE) - PROCESSING_TIMEOUT).isoformat(
        timespec="seconds"
    )
    with closing(_connect()) as database:
        rows = database.execute(
            """
            SELECT id, day, machine_id, cost
            FROM request_log
            WHERE status = 'processing' AND requested_at < ?
            """,
            (cutoff,),
        ).fetchall()
        if not rows:
            return 0
        database.execute("BEGIN IMMEDIATE")
        for row in rows:
            cursor = database.execute(
                """
                UPDATE request_log SET status = 'failed'
                WHERE id = ? AND status = 'processing'
                """,
                (row["id"],),
            )
            if cursor.rowcount != 1:
                continue
            database.execute(
                """
                UPDATE usage SET count = MAX(0, count - ?)
                WHERE day = ? AND machine_id = ?
                """,
                (row["cost"], row["day"], row["machine_id"]),
            )
        database.commit()
    return len(rows)


def _rollupOldRequests(force=False):
    cutoff = (
        datetime.now(TIMEZONE).date() - timedelta(days=REQUEST_LOG_RETENTION_DAYS)
    ).isoformat()
    today = _today()
    with closing(_connect()) as database:
        marker = database.execute(
            "SELECT value FROM settings WHERE key = 'request_log_rollup_day'"
        ).fetchone()
        if not force and marker and marker[0] == today:
            return 0
        database.execute("BEGIN IMMEDIATE")
        if not force:
            marker = database.execute(
                "SELECT value FROM settings WHERE key = 'request_log_rollup_day'"
            ).fetchone()
            if marker and marker[0] == today:
                database.commit()
                return 0
        candidate = database.execute(
            """
            SELECT 1 FROM request_log
            WHERE day < ? AND status <> 'processing'
            LIMIT 1
            """,
            (cutoff,),
        ).fetchone()
        if not candidate:
            database.execute(
                "INSERT INTO settings(key, value) VALUES ('request_log_rollup_day', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (today,),
            )
            database.commit()
            return 0
        dailyRows = database.execute(
            """
            SELECT day, COUNT(*) AS requests,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN status = 'success' THEN cost ELSE 0 END) AS consumed
            FROM request_log
            WHERE day < ? AND status <> 'processing'
            GROUP BY day
            """,
            (cutoff,),
        ).fetchall()
        machineRows = database.execute(
            """
            SELECT machine_id, COUNT(*) AS requests
            FROM request_log
            WHERE day < ? AND status <> 'processing'
            GROUP BY machine_id
            """,
            (cutoff,),
        ).fetchall()
        database.executemany(
            """
            INSERT INTO request_daily_stats(day, requests, success, failed, consumed)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
                requests = requests + excluded.requests,
                success = success + excluded.success,
                failed = failed + excluded.failed,
                consumed = consumed + excluded.consumed
            """,
            [
                (
                    row["day"],
                    row["requests"],
                    row["success"],
                    row["failed"],
                    row["consumed"],
                )
                for row in dailyRows
            ],
        )
        database.executemany(
            """
            INSERT INTO machine_request_totals(machine_id, requests)
            VALUES (?, ?)
            ON CONFLICT(machine_id) DO UPDATE SET
                requests = requests + excluded.requests
            """,
            [(row["machine_id"], row["requests"]) for row in machineRows],
        )
        database.execute(
            "DELETE FROM request_log WHERE day < ? AND status <> 'processing'",
            (cutoff,),
        )
        database.execute("DELETE FROM usage WHERE day < ?", (cutoff,))
        database.execute(
            "INSERT INTO settings(key, value) VALUES ('request_log_rollup_day', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (today,),
        )
        database.commit()
    return len(dailyRows)


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
    _recoverStaleRequests()
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


@app.errorhandler(413)
def _requestTooLarge(error):
    return _error("请求内容过大", 413)


@app.post("/ai/markdown/register")
def registerMachine():
    try:
        machineId = _machineId((request.get_json(silent=True) or {}).get("machine_id"))
        return jsonify({"machine_code": _registerMachine(machineId)})
    except ValueError as error:
        return _error(str(error), 400)
    except (RuntimeError, sqlite3.Error) as error:
        return _error(str(error), 503)


@app.get("/ai/markdown/quota")
def quota():
    try:
        machineId = _machineId(request.args.get("machine_id"))
        machineCode = _registeredMachineCode(machineId)
        if not machineCode:
            return _error("设备尚未注册", 404)
        _recoverStaleRequests()
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
    except (RuntimeError, sqlite3.Error) as error:
        return _error(str(error), 503)


@app.post("/ai/markdown")
def convert():
    if request.content_length and request.content_length > MAX_REQUEST_BYTES:
        return _error("请求内容过大", 413)
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

    day = _today()
    try:
        _registerMachine(machineId)
        limit = _dailyLimit()
        cost = _quotaCost()
        model = _deepseekModel()
        systemPrompt = _systemPrompt(customStyle)
    except (RuntimeError, sqlite3.Error):
        return _error("AI 配置暂时不可用，请稍后再试。", 503)
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
                    {"role": "system", "content": systemPrompt},
                    {"role": "user", "content": content.strip()},
                ],
                "thinking": {"type": "disabled"},
                "stream": True,
                "max_tokens": 1500,
            },
            stream=True,
            timeout=(10, 120),
        )
        if not _httpsResponseChain(upstream, DEEPSEEK_API):
            raise requests.RequestException("AI 服务连接未保持 HTTPS")
        upstream.raise_for_status()
    except (requests.RequestException, TypeError, ValueError):
        if upstream is not None:
            upstream.close()
        _requestFinished(requestId, False, machineId, cost, day)
        return _error("AI 服务暂时不可用，请稍后再试。", 502)

    @stream_with_context
    def stream():
        completed = False
        outputChunks = []
        try:
            for line in upstream.iter_lines(chunk_size=1):
                if line:
                    if line.startswith(b"data:") and line[5:].strip() == b"[DONE]":
                        completed = True
                    else:
                        _collectOutputChunk(line, outputChunks)
                    yield line + b"\n\n"
        finally:
            try:
                upstream.close()
            finally:
                _requestFinished(
                    requestId,
                    completed,
                    machineId if not completed else None,
                    cost,
                    day,
                )
                if completed:
                    outputText = "".join(outputChunks)
                    if outputText.strip():
                        _saveConversionLog(
                            machineId, content.strip(), outputText, customStyle
                        )

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


def _collectOutputChunk(line, chunks):
    if not line.startswith(b"data:"):
        return
    payload = line[5:].strip()
    if not payload or payload == b"[DONE]":
        return
    try:
        data = json.loads(payload)
        delta = data.get("choices", [{}])[0].get("delta", {})
        content = delta.get("content")
        if content:
            chunks.append(content)
    except (json.JSONDecodeError, IndexError, AttributeError):
        pass


def _saveConversionLog(machineId, inputContent, outputContent, customStyle):
    try:
        with closing(_connect()) as database:
            database.execute(
                """
                INSERT INTO conversion_logs
                    (machine_id, input_content, output_content, custom_style, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (machineId, inputContent, outputContent, customStyle, _nowIso()),
            )
            database.commit()
    except sqlite3.Error:
        pass


def _cleanupConversionLogs():
    cutoff = (
        datetime.now(TIMEZONE).date() - timedelta(days=CONVERSION_LOG_RETENTION_DAYS)
    ).isoformat()
    today = _today()
    with closing(_connect()) as database:
        marker = database.execute(
            "SELECT value FROM settings WHERE key = 'conversion_log_cleanup_day'"
        ).fetchone()
        if marker and marker[0] == today:
            return 0
        database.execute("BEGIN IMMEDIATE")
        marker = database.execute(
            "SELECT value FROM settings WHERE key = 'conversion_log_cleanup_day'"
        ).fetchone()
        if marker and marker[0] == today:
            database.commit()
            return 0
        deleted = database.execute(
            "DELETE FROM conversion_logs WHERE created_at < ? AND status = 'pending'",
            (cutoff,),
        ).rowcount
        database.execute(
            "INSERT INTO settings(key, value) VALUES ('conversion_log_cleanup_day', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (today,),
        )
        database.commit()
    return deleted


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


def _adminResponse(
    message, category, endpoint, status=200, url_values=None, renderer=None
):
    if _isAjaxRequest():
        return jsonify(message=message, category=category), status
    flash(message, category)
    if renderer is not None:
        return renderer(), status
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
    retentionStart = (
        datetime.now(TIMEZONE).date() - timedelta(days=REQUEST_LOG_RETENTION_DAYS)
    ).isoformat()
    _recoverStaleRequests()
    _rollupOldRequests()
    if _setting("holiday_exempt", "0") == "1":
        try:
            _refreshHolidayCache()
        except Exception:
            pass
    with closing(_connect()) as database:
        machines = database.execute("SELECT COUNT(*) FROM machines").fetchone()[0]
        consumed = database.execute(
            "SELECT COALESCE(SUM(count), 0) FROM usage WHERE day = ?", (day,)
        ).fetchone()[0]
        recentStats = database.execute(
            """
            SELECT
                COUNT(*) AS requests,
                COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) AS success,
                COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed,
                COALESCE(SUM(CASE WHEN status IN ('success', 'processing') THEN cost ELSE 0 END), 0) AS consumed,
                COALESCE(SUM(CASE WHEN day = ? THEN 1 ELSE 0 END), 0) AS today_requests,
                COALESCE(SUM(CASE WHEN day = ? AND status = 'success' THEN 1 ELSE 0 END), 0) AS today_success,
                COALESCE(SUM(CASE WHEN day = ? AND status = 'failed' THEN 1 ELSE 0 END), 0) AS today_failed,
                COALESCE(SUM(CASE WHEN day = ? AND status = 'processing' THEN 1 ELSE 0 END), 0) AS today_processing
            FROM request_log WHERE day >= ?
            """,
            (day, day, day, day, retentionStart),
        ).fetchone()
        summaryStats = database.execute(
            """
            SELECT COALESCE(SUM(requests), 0) AS requests,
                   COALESCE(SUM(success), 0) AS success,
                   COALESCE(SUM(failed), 0) AS failed,
                   COALESCE(SUM(consumed), 0) AS consumed
            FROM request_daily_stats
            """
        ).fetchone()
    market = marketplaceStats(_connect, day)
    today = {
        "ai_requests": recentStats["today_requests"],
        "ai_success": recentStats["today_success"],
        "ai_failed": recentStats["today_failed"],
        "market_downloads": market["today_downloads"],
    }
    allData = {
        "ai_requests": recentStats["requests"] + summaryStats["requests"],
        "ai_success": recentStats["success"] + summaryStats["success"],
        "ai_failed": recentStats["failed"] + summaryStats["failed"],
        "market_downloads": market["downloads"],
    }
    return {
        "machines": machines,
        "requests": recentStats["today_requests"],
        "success": recentStats["today_success"],
        "failed": recentStats["today_failed"],
        "processing": recentStats["today_processing"],
        "consumed": consumed,
        "today": today,
        "all": allData,
        "all_consumed": recentStats["consumed"] + summaryStats["consumed"],
        "market": market,
    }


def _machineRows(search="", sort="registered"):
    day = _today()
    limit = _dailyLimit()
    _rollupOldRequests()
    with closing(_connect()) as database:
        rows = database.execute(
            """
            SELECT
                m.id,
                m.machine_id,
                m.registered_at,
                m.last_seen_at,
                COALESCE(u.count, 0) AS used,
                COALESCE(t.requests, 0) + COALESCE(r.requests, 0) AS requests
            FROM machines m
            LEFT JOIN usage u ON u.machine_id = m.machine_id AND u.day = ?
            LEFT JOIN machine_request_totals t ON t.machine_id = m.machine_id
            LEFT JOIN (
                SELECT machine_id, COUNT(*) AS requests
                FROM request_log GROUP BY machine_id
            ) r ON r.machine_id = m.machine_id
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
    match = re.fullmatch(r"DJ-(\d{6,})", alias)
    if not match:
        return False
    with closing(_connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute(
            "SELECT machine_id FROM machines WHERE id = ?", (int(match.group(1)),)
        ).fetchone()
        if not row:
            database.rollback()
            return False
        day = _today()
        database.execute(
            "UPDATE request_log SET status = 'reset' "
            "WHERE day = ? AND machine_id = ? AND status = 'processing'",
            (day, row["machine_id"]),
        )
        database.execute(
            "DELETE FROM usage WHERE day = ? AND machine_id = ?",
            (day, row["machine_id"]),
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
    username = ""
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
    return render_template(
        "admin_login.html", csrf_token=_csrfToken(), username=username
    )


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


@app.get("/admin/dashboard/stats")
@_loginRequired
def adminDashboardStats():
    return jsonify(_dashboardStats())


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


def _renderAdminSettings(submitted=None):
    values = submitted or {
        "daily_limit": _dailyLimit(),
        "peak_enabled": _setting("peak_enabled", "1") == "1",
        "holiday_exempt": _setting("holiday_exempt", "0") == "1",
        "model": _deepseekModel(),
        "clear_api_key": False,
    }
    return render_template(
        "admin_ai_settings.html",
        csrf_token=_csrfToken(),
        current_page="ai_settings",
        api_key_configured=bool(
            _setting("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY")
        ),
        **values,
    )


@app.route("/admin/ai/markdown/settings", methods=["GET", "POST"])
@_loginRequired
def adminSettings():
    if request.method == "GET":
        return _renderAdminSettings()

    _checkCsrf()
    submitted = {
        "daily_limit": request.form.get("daily_limit", ""),
        "peak_enabled": bool(request.form.get("peak_enabled")),
        "holiday_exempt": bool(request.form.get("holiday_exempt")),
        "model": request.form.get("model", ""),
        "clear_api_key": bool(request.form.get("clear_api_key")),
    }
    try:
        dailyLimit = int(submitted["daily_limit"])
    except ValueError:
        dailyLimit = 0
    model = submitted["model"].strip()
    if not 1 <= dailyLimit <= 10_000:
        return _adminResponse(
            "每日额度必须在 1 到 10000 之间",
            "error",
            "adminSettings",
            400,
            renderer=lambda: _renderAdminSettings(submitted),
        )
    elif not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", model):
        return _adminResponse(
            "模型名称格式无效",
            "error",
            "adminSettings",
            400,
            renderer=lambda: _renderAdminSettings(submitted),
        )
    else:
        apiKey = request.form.get("api_key", "").strip()
        try:
            _saveAISettings(
                dailyLimit,
                submitted["peak_enabled"],
                model,
                apiKey,
                submitted["clear_api_key"],
                submitted["holiday_exempt"],
            )
            if submitted["holiday_exempt"]:
                _refreshHolidayCache()
        except (RuntimeError, sqlite3.Error) as error:
            return _adminResponse(
                str(error),
                "error",
                "adminSettings",
                400,
                renderer=lambda: _renderAdminSettings(submitted),
            )
        return _adminResponse("AI 配置已保存", "success", "adminSettings")


def _conversionLogRows(status="all", page=1, perPage=20):
    _cleanupConversionLogs()
    offset = (page - 1) * perPage
    with closing(_connect()) as database:
        if status == "all":
            total = database.execute(
                "SELECT COUNT(*) FROM conversion_logs"
            ).fetchone()[0]
            rows = database.execute(
                """
                SELECT cl.id, cl.machine_id, cl.input_content, cl.output_content,
                       cl.custom_style, cl.created_at, cl.status,
                       m.id AS machine_number
                FROM conversion_logs cl
                LEFT JOIN machines m ON m.machine_id = cl.machine_id
                ORDER BY cl.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (perPage, offset),
            ).fetchall()
        else:
            total = database.execute(
                "SELECT COUNT(*) FROM conversion_logs WHERE status = ?",
                (status,),
            ).fetchone()[0]
            rows = database.execute(
                """
                SELECT cl.id, cl.machine_id, cl.input_content, cl.output_content,
                       cl.custom_style, cl.created_at, cl.status,
                       m.id AS machine_number
                FROM conversion_logs cl
                LEFT JOIN machines m ON m.machine_id = cl.machine_id
                WHERE cl.status = ?
                ORDER BY cl.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (status, perPage, offset),
            ).fetchall()
    logs = []
    for row in rows:
        code = f"DJ-{row['machine_number']:06d}" if row["machine_number"] else ""
        logs.append({
            "id": row["id"],
            "machine_code": code,
            "input_content": row["input_content"],
            "output_content": row["output_content"],
            "custom_style": row["custom_style"],
            "created_at": row["created_at"],
            "status": row["status"],
        })
    totalPages = max(1, (total + perPage - 1) // perPage)
    return logs, total, totalPages


def _getConversionLog(logId):
    with closing(_connect()) as database:
        row = database.execute(
            """
            SELECT cl.id, cl.machine_id, cl.input_content, cl.output_content,
                   cl.custom_style, cl.created_at, cl.status,
                   m.id AS machine_number
            FROM conversion_logs cl
            LEFT JOIN machines m ON m.machine_id = cl.machine_id
            WHERE cl.id = ?
            """,
            (logId,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "machine_code": (
            f"DJ-{row['machine_number']:06d}" if row["machine_number"] else ""
        ),
        "input_content": row["input_content"],
        "output_content": row["output_content"],
        "custom_style": row["custom_style"],
        "created_at": row["created_at"],
        "status": row["status"],
    }


def _updateConversionLogStatus(logId, status):
    with closing(_connect()) as database:
        cursor = database.execute(
            "UPDATE conversion_logs SET status = ? WHERE id = ?",
            (status, logId),
        )
        database.commit()
    return cursor.rowcount == 1


def _addPromptExample(inputContent, outputContent):
    now = _nowIso()
    with closing(_connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        maxOrder = database.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM prompt_examples"
        ).fetchone()[0]
        cursor = database.execute(
            """
            INSERT INTO prompt_examples(input_content, output_content, sort_order, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (inputContent, outputContent, maxOrder + 1, now),
        )
        database.commit()
    return cursor.lastrowid


def _updatePromptExample(exampleId, inputContent, outputContent):
    with closing(_connect()) as database:
        cursor = database.execute(
            "UPDATE prompt_examples SET input_content = ?, output_content = ? WHERE id = ?",
            (inputContent, outputContent, exampleId),
        )
        database.commit()
    return cursor.rowcount == 1


def _deletePromptExample(exampleId):
    with closing(_connect()) as database:
        cursor = database.execute(
            "DELETE FROM prompt_examples WHERE id = ?", (exampleId,)
        )
        database.commit()
    return cursor.rowcount == 1


def _reorderPromptExamples(orderedIds, originalIds):
    with closing(_connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        currentRows = database.execute(
            "SELECT id FROM prompt_examples ORDER BY sort_order, id"
        ).fetchall()
        currentIds = [row["id"] for row in currentRows]
        if currentIds != originalIds:
            database.rollback()
            return False
        for index, exampleId in enumerate(orderedIds):
            database.execute(
                "UPDATE prompt_examples SET sort_order = ? WHERE id = ?",
                (index, exampleId),
            )
        database.commit()
    return True


def _allPromptExamples():
    with closing(_connect()) as database:
        rows = database.execute(
            "SELECT id, input_content, output_content, sort_order, created_at "
            "FROM prompt_examples ORDER BY sort_order, id"
        ).fetchall()
    return [dict(row) for row in rows]


def _resetPromptExamples():
    now = _nowIso()
    with closing(_connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        database.execute("DELETE FROM prompt_examples")
        database.executemany(
            """
            INSERT INTO prompt_examples(input_content, output_content, sort_order, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (inputText, outputText, index, now)
                for index, (inputText, outputText) in enumerate(DEFAULT_EXAMPLES)
            ],
        )
        database.commit()


def _renderAdminPrompt(systemPrompt=None):
    return render_template(
        "admin_ai_prompt.html",
        csrf_token=_csrfToken(),
        current_page="ai_prompt",
        system_prompt=(
            _setting("system_prompt", DEFAULT_PROMPT_TEMPLATE)
            if systemPrompt is None
            else systemPrompt
        ),
        max_system_prompt_length=MAX_SYSTEM_PROMPT_LENGTH,
    )


@app.route("/admin/ai/markdown/prompt", methods=["GET", "POST"])
@_loginRequired
def adminPrompt():
    if request.method == "GET":
        return _renderAdminPrompt()

    _checkCsrf()
    submittedPrompt = request.form.get("system_prompt", "")
    systemPrompt = submittedPrompt.strip()
    if not systemPrompt:
        return _adminResponse(
            "系统提示词不能为空",
            "error",
            "adminPrompt",
            400,
            renderer=lambda: _renderAdminPrompt(submittedPrompt),
        )
    elif len(systemPrompt) > MAX_SYSTEM_PROMPT_LENGTH:
        return _adminResponse(
            f"系统提示词不能超过 {MAX_SYSTEM_PROMPT_LENGTH} 个字符",
            "error",
            "adminPrompt",
            400,
            renderer=lambda: _renderAdminPrompt(submittedPrompt),
        )
    else:
        try:
            _saveSystemPrompt(systemPrompt)
        except sqlite3.Error as error:
            return _adminResponse(
                str(error),
                "error",
                "adminPrompt",
                400,
                renderer=lambda: _renderAdminPrompt(submittedPrompt),
            )
        else:
            return _adminResponse("系统提示词已保存", "success", "adminPrompt")


@app.get("/admin/ai/markdown/logs/")
@_loginRequired
def adminConversionLogs():
    status = request.args.get("status", "all")
    if status not in {"all", "pending", "approved", "rejected"}:
        status = "all"
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    logs, total, totalPages = _conversionLogRows(status, page)
    return render_template(
        "admin_ai_logs.html",
        csrf_token=_csrfToken(),
        current_page="ai_logs",
        logs=logs,
        status=status,
        page=page,
        total=total,
        total_pages=totalPages,
    )


@app.get("/admin/ai/markdown/logs/<int:logId>/add")
@_loginRequired
def adminConversionLogAdd(logId):
    log = _getConversionLog(logId)
    if not log:
        return _adminResponse("未找到该记录", "error", "adminConversionLogs", 404)
    return render_template(
        "admin_ai_log_add.html",
        csrf_token=_csrfToken(),
        current_page="ai_logs",
        log=log,
        mode="add",
    )


@app.post("/admin/ai/markdown/logs/<int:logId>/add")
@_loginRequired
def adminConversionLogAddSubmit(logId):
    _checkCsrf()
    log = _getConversionLog(logId)
    if not log:
        return _adminResponse("未找到该记录", "error", "adminConversionLogs", 404)
    inputContent = request.form.get("input_content", "").strip()
    outputContent = request.form.get("output_content", "").strip()
    if not inputContent or not outputContent:
        return _adminResponse(
            "输入和输出内容不能为空", "error", "adminConversionLogs", 400
        )
    _addPromptExample(inputContent, outputContent)
    _updateConversionLogStatus(logId, "approved")
    return _adminResponse("示例已加入提示词", "success", "adminConversionLogs")


@app.get("/admin/ai/markdown/logs/review")
@_loginRequired
def adminConversionLogReview():
    with closing(_connect()) as database:
        row = database.execute(
            """
            SELECT cl.id, cl.machine_id, cl.input_content, cl.output_content,
                   cl.custom_style, cl.created_at, cl.status,
                   m.id AS machine_number
            FROM conversion_logs cl
            LEFT JOIN machines m ON m.machine_id = cl.machine_id
            WHERE cl.status = 'pending'
            ORDER BY cl.created_at ASC
            LIMIT 1
            """,
        ).fetchone()
    if not row:
        return _adminResponse(
            "没有待审批的记录", "info", "adminConversionLogs"
        )
    log = {
        "id": row["id"],
        "machine_code": (
            f"DJ-{row['machine_number']:06d}" if row["machine_number"] else ""
        ),
        "input_content": row["input_content"],
        "output_content": row["output_content"],
        "custom_style": row["custom_style"],
        "created_at": row["created_at"],
        "status": row["status"],
    }
    pendingCount = 0
    with closing(_connect()) as database:
        pendingCount = database.execute(
            "SELECT COUNT(*) FROM conversion_logs WHERE status = 'pending'"
        ).fetchone()[0]
    return render_template(
        "admin_ai_log_review.html",
        csrf_token=_csrfToken(),
        current_page="ai_logs",
        log=log,
        pending_count=pendingCount,
    )


@app.post("/admin/ai/markdown/logs/<int:logId>/approve")
@_loginRequired
def adminConversionLogApprove(logId):
    _checkCsrf()
    log = _getConversionLog(logId)
    if not log:
        return _adminResponse("未找到该记录", "error", "adminConversionLogs", 404)
    inputContent = request.form.get("input_content", "").strip()
    outputContent = request.form.get("output_content", "").strip()
    if not inputContent or not outputContent:
        return _adminResponse(
            "输入和输出内容不能为空", "error", "adminConversionLogs", 400
        )
    _addPromptExample(inputContent, outputContent)
    _updateConversionLogStatus(logId, "approved")
    return _adminResponse("示例已加入提示词", "success", "adminConversionLogReview")


@app.post("/admin/ai/markdown/logs/<int:logId>/reject")
@_loginRequired
def adminConversionLogReject(logId):
    _checkCsrf()
    _updateConversionLogStatus(logId, "rejected")
    return _adminResponse("已标记为未通过", "success", "adminConversionLogReview")


@app.post("/admin/ai/markdown/logs/<int:logId>/status")
@_loginRequired
def adminConversionLogSetStatus(logId):
    _checkCsrf()
    status = request.form.get("status", "")
    if status not in {"pending", "approved", "rejected"}:
        return _adminResponse("无效的状态", "error", "adminConversionLogs", 400)
    _updateConversionLogStatus(logId, status)
    return _adminResponse("状态已更新", "success", "adminConversionLogs")


@app.get("/admin/ai/markdown/examples/")
@_loginRequired
def adminPromptExamples():
    examples = _allPromptExamples()
    return render_template(
        "admin_ai_examples.html",
        csrf_token=_csrfToken(),
        current_page="ai_examples",
        examples=examples,
    )


@app.post("/admin/ai/markdown/examples/<int:exampleId>/edit")
@_loginRequired
def adminPromptExampleEdit(exampleId):
    _checkCsrf()
    inputContent = request.form.get("input_content", "").strip()
    outputContent = request.form.get("output_content", "").strip()
    if not inputContent or not outputContent:
        return _adminResponse(
            "输入和输出内容不能为空", "error", "adminPromptExamples", 400
        )
    if not _updatePromptExample(exampleId, inputContent, outputContent):
        return _adminResponse("未找到该示例", "error", "adminPromptExamples", 404)
    return _adminResponse("示例已更新", "success", "adminPromptExamples")


@app.post("/admin/ai/markdown/examples/<int:exampleId>/delete")
@_loginRequired
def adminPromptExampleDelete(exampleId):
    _checkCsrf()
    if not _deletePromptExample(exampleId):
        return _adminResponse("未找到该示例", "error", "adminPromptExamples", 404)
    return _adminResponse("示例已删除", "success", "adminPromptExamples")


@app.post("/admin/ai/markdown/examples/reorder")
@_loginRequired
def adminPromptExamplesReorder():
    _checkCsrf()
    try:
        orderedIds = json.loads(request.form.get("order", "[]"))
        originalIds = json.loads(request.form.get("original", "[]"))
    except (json.JSONDecodeError, TypeError):
        return _adminResponse("排序数据无效", "error", "adminPromptExamples", 400)
    if not isinstance(orderedIds, list) or not isinstance(originalIds, list):
        return _adminResponse("排序数据无效", "error", "adminPromptExamples", 400)
    if not _reorderPromptExamples(orderedIds, originalIds):
        if _isAjaxRequest():
            return jsonify(message="排序已过期，请刷新页面后重试", category="error"), 409
        flash("排序已过期，请刷新页面后重试", "error")
        return redirect(url_for("adminPromptExamples"))
    return _adminResponse("排序已保存", "success", "adminPromptExamples")


@app.post("/admin/ai/markdown/examples/reset")
@_loginRequired
def adminPromptExamplesReset():
    _checkCsrf()
    _resetPromptExamples()
    return _adminResponse("已恢复默认示例", "success", "adminPromptExamples")


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
        database.execute("BEGIN IMMEDIATE")
        day = _today()
        database.execute(
            "UPDATE request_log SET status = 'reset' "
            "WHERE day = ? AND status = 'processing'",
            (day,),
        )
        database.execute("DELETE FROM usage WHERE day = ?", (day,))
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
