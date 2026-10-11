"""Error Report：DJCat 把未处理的异常报给服务端，服务端按 Error Signature 归并。

Error Signature 只取异常类型、去掉易变部分的消息和每一帧的文件与函数名。行号不算：
改了上面的代码它就漂移，同一个 bug 会被拆成两组。日志和回溯全文也不算：每行日志都
带时间，消息里常有内存地址、路径和计数，拿它们算指纹，同一个错误每次都是新的一组。
"""

import hashlib
import os
import re
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from math import ceil

from flask import Blueprint, abort, jsonify, render_template, request

TIMEZONE = timezone(timedelta(hours=8))
RETENTION_DAYS = 90
# 同一台机器一天最多记这么多次；超出的直接拒收，不影响已记下的。
MACHINE_DAILY_LIMIT = 100
# 一天最多新出现这么多组：机器标识谁都能编，挡住随手刷出来的海量新组。
NEW_SIGNATURES_DAILY_LIMIT = 200
MAX_FRAMES = 64
MAX_TRACEBACK_LENGTH = 32_000
MAX_MESSAGE_LENGTH = 2_000
MAX_TYPE_LENGTH = 200
MAX_PATH_LENGTH = 300
MAX_VERSION_LENGTH = 64
MAX_OS_LENGTH = 200
PER_PAGE = 20

_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{8,}\b")
_PATH = re.compile(r"(?:[A-Za-z]:|\\\\)[\\/][^'\"\n]*")
_NUMBER = re.compile(r"\d+")
_WHITESPACE = re.compile(r"\s+")

_schemaLock = threading.Lock()
_initializedSchemas = {}


def _today():
    return datetime.now(TIMEZONE).date().isoformat()


def normalizeMessage(message):
    """The part of an exception message that stays the same each time the bug fires."""
    message = _PATH.sub("<path>", message)
    message = _ADDRESS.sub("0x?", message)
    message = _LONG_HEX.sub("<hex>", message)
    message = _NUMBER.sub("N", message)
    return _WHITESPACE.sub(" ", message).strip()


def normalizeFrameFile(path):
    """Where a frame's code lives, independent of where DJCat and Python are installed."""
    path = path.replace("\\", "/")
    _, marker, inside = path.rpartition("site-packages/")
    if marker:
        return inside
    if path.startswith("/") or re.match(r"^[A-Za-z]:/", path):
        return path.rsplit("/", 1)[-1]
    return path


def errorSignature(exceptionType, message, frames):
    parts = [exceptionType, normalizeMessage(message)]
    parts.extend(
        f"{normalizeFrameFile(frame['file']).lower()}:{frame['function']}"
        for frame in frames
    )
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _location(frames):
    """The innermost frame in DJCat's own code, or the innermost frame at all."""
    ownFrames = [
        frame
        for frame in frames
        if normalizeFrameFile(frame["file"]).startswith("app/")
        or normalizeFrameFile(frame["file"]) == "djcat.py"
    ]
    frame = (ownFrames or frames or [None])[-1]
    if frame is None:
        return ""
    return f"{normalizeFrameFile(frame['file'])}:{frame['line']} · {frame['function']}"


def _text(payload, key, limit, required=False):
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} 必须是文本")
    value = value.strip()
    if required and not value:
        raise ValueError(f"缺少 {key}")
    return value[:limit]


def _frames(payload):
    frames = payload.get("frames", [])
    if not isinstance(frames, list):
        raise ValueError("frames 必须是列表")
    result = []
    # 最里面的几帧最能说明问题，太深时丢掉外层。
    for frame in frames[-MAX_FRAMES:]:
        if not isinstance(frame, dict):
            raise ValueError("frames 的每一项必须是对象")
        file = frame.get("file")
        function = frame.get("function")
        line = frame.get("line")
        if not isinstance(file, str) or not isinstance(function, str):
            raise ValueError("frames 缺少文件或函数名")
        if isinstance(line, bool) or not isinstance(line, int) or line < 0:
            raise ValueError("frames 的行号无效")
        result.append(
            {
                "file": file[:MAX_PATH_LENGTH],
                "function": function[:MAX_TYPE_LENGTH],
                "line": line,
            }
        )
    return result


def parseReport(payload):
    if not isinstance(payload, dict):
        raise ValueError("报错内容必须是 JSON 对象")
    traceback = payload.get("traceback", "")
    if not isinstance(traceback, str):
        raise ValueError("traceback 必须是文本")
    return {
        "exception_type": _text(payload, "exception_type", MAX_TYPE_LENGTH, True),
        "message": _text(payload, "message", MAX_MESSAGE_LENGTH),
        "frames": _frames(payload),
        # 回溯最后几行是异常本身，太长时留尾部。
        "traceback": traceback.rstrip()[-MAX_TRACEBACK_LENGTH:],
        "client_version": _text(payload, "client_version", MAX_VERSION_LENGTH),
        "os": _text(payload, "os", MAX_OS_LENGTH),
    }


def _ensureSchema(database):
    path = database.execute("PRAGMA database_list").fetchone()[2]
    schemaVersion = database.execute("PRAGMA schema_version").fetchone()[0]
    try:
        info = os.stat(path)
        identity = (info.st_dev, info.st_ino, schemaVersion)
    except OSError:
        identity = None
    if identity is not None and _initializedSchemas.get(path) == identity:
        return
    with _schemaLock:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS error_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signature TEXT NOT NULL UNIQUE,
                exception_type TEXT NOT NULL,
                message TEXT NOT NULL,
                location TEXT NOT NULL,
                traceback TEXT NOT NULL,
                last_version TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS error_groups_last_seen_idx
                ON error_groups(last_seen_at);
            CREATE TABLE IF NOT EXISTS error_occurrences (
                group_id INTEGER NOT NULL
                    REFERENCES error_groups(id) ON DELETE CASCADE,
                machine_id TEXT NOT NULL,
                day TEXT NOT NULL,
                count INTEGER NOT NULL,
                first_at TEXT NOT NULL,
                last_at TEXT NOT NULL,
                client_version TEXT NOT NULL,
                os TEXT NOT NULL,
                PRIMARY KEY (group_id, machine_id, day)
            );
            CREATE INDEX IF NOT EXISTS error_occurrences_day_idx
                ON error_occurrences(day);
            CREATE INDEX IF NOT EXISTS error_occurrences_machine_day_idx
                ON error_occurrences(machine_id, day);
            """
        )
        schemaVersion = database.execute("PRAGMA schema_version").fetchone()[0]
        if identity is not None:
            _initializedSchemas[path] = (identity[0], identity[1], schemaVersion)


def _open(connect):
    database = connect()
    try:
        _ensureSchema(database)
    except Exception:
        database.close()
        raise
    return closing(database)


class ReportRejected(Exception):
    pass


def recordReport(connect, machineId, report, now=None):
    """Count one occurrence of ``report`` from ``machineId``; returns the group ID."""
    now = now or datetime.now(TIMEZONE)
    nowIso = now.isoformat(timespec="seconds")
    day = now.date().isoformat()
    cutoff = (now.date() - timedelta(days=RETENTION_DAYS)).isoformat()
    signature = errorSignature(
        report["exception_type"], report["message"], report["frames"]
    )
    location = _location(report["frames"])
    with _open(connect) as database:
        database.execute("BEGIN IMMEDIATE")
        # 清理挂在写入路径上：报错本来就少，后台没人打开也照样过期。
        database.execute("DELETE FROM error_occurrences WHERE day < ?", (cutoff,))
        database.execute(
            "DELETE FROM error_groups WHERE id NOT IN "
            "(SELECT DISTINCT group_id FROM error_occurrences)"
        )
        reportedToday = database.execute(
            "SELECT COALESCE(SUM(count), 0) FROM error_occurrences "
            "WHERE machine_id = ? AND day = ?",
            (machineId, day),
        ).fetchone()[0]
        if reportedToday >= MACHINE_DAILY_LIMIT:
            database.commit()
            raise ReportRejected("这台电脑今天报告的错误太多了")
        row = database.execute(
            "SELECT id FROM error_groups WHERE signature = ?", (signature,)
        ).fetchone()
        if row is None:
            newToday = database.execute(
                "SELECT COUNT(*) FROM error_groups WHERE first_seen_at >= ?",
                (day,),
            ).fetchone()[0]
            if newToday >= NEW_SIGNATURES_DAILY_LIMIT:
                database.commit()
                raise ReportRejected("今天新出现的错误太多了")
            groupId = database.execute(
                """
                INSERT INTO error_groups(
                    signature, exception_type, message, location, traceback,
                    last_version, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signature,
                    report["exception_type"],
                    report["message"],
                    location,
                    report["traceback"],
                    report["client_version"],
                    nowIso,
                    nowIso,
                ),
            ).lastrowid
        else:
            groupId = row["id"]
            # 留最新一次的回溯：行号和版本对得上最近的代码。
            database.execute(
                """
                UPDATE error_groups
                SET message = ?, location = ?, traceback = ?, last_version = ?,
                    last_seen_at = ?
                WHERE id = ?
                """,
                (
                    report["message"],
                    location,
                    report["traceback"],
                    report["client_version"],
                    nowIso,
                    groupId,
                ),
            )
        database.execute(
            """
            INSERT INTO error_occurrences(
                group_id, machine_id, day, count, first_at, last_at,
                client_version, os
            ) VALUES (?, ?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(group_id, machine_id, day) DO UPDATE SET
                count = count + 1,
                last_at = excluded.last_at,
                client_version = excluded.client_version,
                os = excluded.os
            """,
            (
                groupId,
                machineId,
                day,
                nowIso,
                nowIso,
                report["client_version"],
                report["os"],
            ),
        )
        database.commit()
    return groupId


_GROUP_SELECT = """
    SELECT g.*,
           COALESCE(SUM(o.count), 0) AS occurrences,
           COUNT(DISTINCT o.machine_id) AS machines
    FROM error_groups g
    LEFT JOIN error_occurrences o ON o.group_id = g.id
"""


def errorGroups(connect, page=1, perPage=PER_PAGE):
    with _open(connect) as database:
        total = database.execute("SELECT COUNT(*) FROM error_groups").fetchone()[0]
        totalPages = max(1, ceil(total / perPage))
        page = min(max(1, page), totalPages)
        rows = database.execute(
            _GROUP_SELECT
            + " GROUP BY g.id ORDER BY g.last_seen_at DESC, g.id DESC LIMIT ? OFFSET ?",
            (perPage, (page - 1) * perPage),
        ).fetchall()
    return [dict(row) for row in rows], total, page, totalPages


def errorGroup(connect, groupId):
    with _open(connect) as database:
        group = database.execute(
            _GROUP_SELECT + " WHERE g.id = ? GROUP BY g.id", (groupId,)
        ).fetchone()
        if group is None:
            return None, []
        # Machine Code 由机器表的自增编号生成，与 AI 写 Markdown 的「注册机器」一致。
        occurrences = database.execute(
            """
            SELECT o.*, m.id AS machine_number
            FROM error_occurrences o
            LEFT JOIN machines m ON m.machine_id = o.machine_id
            WHERE o.group_id = ?
            ORDER BY o.last_at DESC
            LIMIT 200
            """,
            (groupId,),
        ).fetchall()
    return dict(group), [
        {
            **dict(row),
            "machine_code": (
                f"DJ-{row['machine_number']:06d}"
                if row["machine_number"] is not None
                else "未注册"
            ),
        }
        for row in occurrences
    ]


def deleteErrorGroup(connect, groupId):
    with _open(connect) as database:
        deleted = database.execute(
            "DELETE FROM error_groups WHERE id = ?", (groupId,)
        ).rowcount
        database.commit()
    return bool(deleted)


def todayErrorStats(connect, day=None):
    day = day or _today()
    with _open(connect) as database:
        row = database.execute(
            "SELECT COALESCE(SUM(count), 0), COUNT(DISTINCT group_id) "
            "FROM error_occurrences WHERE day = ?",
            (day,),
        ).fetchone()
    return {"occurrences": row[0], "groups": row[1]}


def registerErrorReports(
    app,
    *,
    connect,
    machineId,
    registerMachine,
    loginRequired,
    csrfToken,
    checkCsrf,
    adminResponse,
):
    """Register the public Error Report endpoint and its Admin Console pages."""

    with _open(connect):
        pass

    @app.post("/error-reports")
    def submitErrorReport():
        # 与 Application Catalog 一样只在 API 域名上接收。
        apiHost = os.environ.get("DJCATAI_API_HOST", "api.djcatpro.top").lower()
        if request.host.partition(":")[0].lower() != apiHost:
            abort(404)
        payload = request.get_json(silent=True)
        try:
            report = parseReport(payload)
            machine = machineId((payload or {}).get("machine_id"))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except RuntimeError as error:
            return jsonify(error=str(error)), 503
        registerMachine(machine)
        try:
            recordReport(connect, machine, report)
        except ReportRejected as error:
            return jsonify(error=str(error)), 429
        return jsonify(ok=True)

    blueprint = Blueprint("error_reports", __name__, url_prefix="/admin/error-reports")

    @blueprint.get("/")
    @loginRequired
    def page():
        try:
            pageNumber = int(request.args.get("page", "1"))
        except ValueError:
            pageNumber = 1
        groups, total, pageNumber, totalPages = errorGroups(connect, pageNumber)
        return render_template(
            "admin_error_reports.html",
            current_page="error_reports",
            csrf_token=csrfToken(),
            groups=groups,
            total=total,
            page=pageNumber,
            total_pages=totalPages,
            today=todayErrorStats(connect),
            retention_days=RETENTION_DAYS,
        )

    @blueprint.get("/<int:groupId>")
    @loginRequired
    def detail(groupId):
        group, occurrences = errorGroup(connect, groupId)
        if group is None:
            abort(404)
        return render_template(
            "admin_error_report.html",
            current_page="error_reports",
            csrf_token=csrfToken(),
            group=group,
            occurrences=occurrences,
        )

    @blueprint.post("/<int:groupId>/delete")
    @loginRequired
    def delete(groupId):
        checkCsrf()
        if not deleteErrorGroup(connect, groupId):
            return adminResponse("这组报错已经不存在", "error", "error_reports.page", 404)
        # 详情页删除后回到列表；列表里删除只移走那一行。
        return adminResponse(
            "已删除这组报错，再次出现时会重新记录",
            "success",
            "error_reports.page",
            navigate=request.form.get("from") == "detail",
        )

    app.register_blueprint(blueprint)
