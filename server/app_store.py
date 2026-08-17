"""Application catalog and administration routes.

The catalog is kept separate from the AI tables so existing deployments can
enable the marketplace without a data migration that rewrites old records.
"""

import hashlib
import json
import os
import re
import sqlite3
import threading
from contextlib import closing
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request

ARCHITECTURES = ("x86_64", "arm64")
_INSTALL_DIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")
_DOWNLOAD_TOKEN = re.compile(r"^[a-f0-9]{32}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_RESERVED_INSTALL_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_MAX_URL_LENGTH = 2048
_MAX_ARGUMENTS_LENGTH = 4096
_DOWNLOAD_EVENT_RETENTION_DAYS = 180
_DANGEROUS_SCHEMES = {
    "cmd",
    "data",
    "file",
    "ftp",
    "http",
    "https",
    "javascript",
    "ms-settings",
    "powershell",
    "shell",
    "vbscript",
}
_schemaInitLock = threading.Lock()
_initializedSchemas = set()
_schemaIdentities = {}


def _schemaIdentity(databaseKey):
    if not databaseKey:
        return None
    try:
        info = os.stat(databaseKey)
    except OSError:
        return None
    # Data writes change ctime/size, so the cache key must describe the file
    # itself rather than its mutable contents.  Replacing the SQLite file
    # changes its device/inode pair and invalidates the schema cache.
    return (info.st_dev, info.st_ino)


def _apiHost():
    return os.environ.get("DJCATAI_API_HOST", "api.djcatpro.top").lower()


def _hostOnly():
    return request.host.partition(":")[0].lower()


def _safeUrl(value):
    value = (value or "").strip()
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    if len(value) > _MAX_URL_LENGTH or any(char in value for char in "\r\n\x00"):
        return ""
    if parsed.scheme != "https":
        return ""
    if not parsed.netloc or parsed.username or parsed.password:
        return ""
    return value


def _safeInstallDir(value):
    baseName = value.rstrip(" .").split(".", 1)[0].upper()
    return bool(
        _INSTALL_DIR.fullmatch(value)
        and not value.endswith((".", " "))
        and baseName not in _RESERVED_INSTALL_NAMES
    )


def _safeSha256(value):
    value = str(value or "").strip().lower()
    return value if _SHA256.fullmatch(value) else ""


def _safeProgramTarget(value):
    parts = value.replace("\\", "/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    return all(
        not any(char in '<>"|?*' for char in part)
        and not part.endswith((".", " "))
        and part.rstrip(" .").split(".", 1)[0].upper()
        not in _RESERVED_INSTALL_NAMES
        for part in parts
    )


def _hasControlCharacters(value):
    if isinstance(value, str):
        return any(ord(char) < 32 or ord(char) == 127 for char in value)
    if isinstance(value, dict):
        return any(
            _hasControlCharacters(key) or _hasControlCharacters(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_hasControlCharacters(item) for item in value)
    return False


def _safeAction(actionType, target, arguments=""):
    actionType = (actionType or "").strip().lower()
    target = (target or "").strip()
    if _hasControlCharacters(target):
        return None
    if actionType == "program":
        if (
            not target.lower().endswith(".exe")
            or target.startswith(("/", "\\"))
            or ":" in target
        ):
            return None
        if not _safeProgramTarget(target):
            return None
        if len(target) > 240:
            return None
    elif actionType == "url":
        target = _safeUrl(target)
        if not target:
            return None
    elif actionType == "uri":
        try:
            scheme = urlparse(target).scheme.lower()
        except ValueError:
            return None
        if (
            len(target) > _MAX_URL_LENGTH
            or len(scheme) < 2
            or scheme in _DANGEROUS_SCHEMES
        ):
            return None
        if any(char in target for char in ("\r", "\n", "\x00")):
            return None
    else:
        return None
    try:
        parsedArguments = json.loads(arguments) if isinstance(arguments, str) and arguments else {}
    except (TypeError, ValueError):
        return None
    if not isinstance(parsedArguments, dict):
        return None
    if _hasControlCharacters(parsedArguments):
        return None
    return {
        "type": actionType,
        "target": target,
        "arguments": parsedArguments,
    }


def _formArguments(actionType, value):
    if actionType != "program":
        return "{}"
    value = (value or "").strip()
    if len(value) > _MAX_ARGUMENTS_LENGTH:
        return None
    try:
        parsed = json.loads(value) if value else {}
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("args"), list):
        arguments = [str(argument) for argument in parsed["args"]]
    else:
        arguments = [line for line in value.splitlines() if line.strip()]
    return json.dumps({"args": arguments[:50]}, ensure_ascii=False)


def _argumentsText(value):
    try:
        parsed = json.loads(value or "{}") if isinstance(value, str) else value
    except (TypeError, ValueError):
        return ""
    arguments = parsed.get("args", []) if isinstance(parsed, dict) else []
    return "\n".join(str(argument) for argument in arguments if isinstance(argument, str))


def _formAction(actionType, target, arguments):
    arguments = _formArguments(actionType, arguments)
    return _safeAction(actionType, target, arguments) if arguments is not None else None


def _ensureSchema(connect):
    with closing(connect()) as database, _schemaInitLock:
        databaseRow = database.execute("PRAGMA database_list").fetchone()
        databaseKey = databaseRow[2] if databaseRow else ""
        identity = _schemaIdentity(databaseKey)
        if (
            databaseKey
            and databaseKey in _initializedSchemas
            and _schemaIdentities.get(databaseKey) == identity
        ):
            return
        database.execute("PRAGMA foreign_keys = ON")
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                developer TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL DEFAULT '',
                icon_url TEXT NOT NULL DEFAULT '',
                install_dir TEXT NOT NULL,
                recommended INTEGER NOT NULL DEFAULT 0,
                recommended_order INTEGER,
                sort_order INTEGER NOT NULL DEFAULT 0,
                announcement TEXT NOT NULL DEFAULT '',
                open_action_type TEXT,
                open_action_target TEXT,
                open_action_arguments TEXT NOT NULL DEFAULT '{}',
                manifest_revision INTEGER NOT NULL DEFAULT 1,
                download_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS market_applications_install_dir_idx
                ON market_applications(install_dir);
            CREATE TABLE IF NOT EXISTS market_packages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id INTEGER NOT NULL REFERENCES market_applications(id) ON DELETE CASCADE,
                architecture TEXT NOT NULL CHECK (architecture IN ('x86_64', 'arm64')),
                enabled INTEGER NOT NULL DEFAULT 1,
                download_url TEXT NOT NULL,
                sha256 TEXT NOT NULL DEFAULT '',
                UNIQUE(app_id, architecture)
            );
            CREATE TABLE IF NOT EXISTS market_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id INTEGER NOT NULL REFERENCES market_applications(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                action_type TEXT NOT NULL,
                action_target TEXT NOT NULL,
                action_arguments TEXT NOT NULL DEFAULT '{}',
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS market_presets_order_idx
                ON market_presets(app_id, sort_order, id);
            CREATE TABLE IF NOT EXISTS market_advertisements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL,
                app_id INTEGER REFERENCES market_applications(id) ON DELETE SET NULL,
                button_url TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS market_ads_order_idx
                ON market_advertisements(enabled, sort_order, id);
            CREATE TABLE IF NOT EXISTS market_download_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id INTEGER NOT NULL REFERENCES market_applications(id) ON DELETE CASCADE,
                architecture TEXT NOT NULL CHECK (architecture IN ('x86_64', 'arm64')),
                downloaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS market_download_events_time_idx
                ON market_download_events(downloaded_at);
            CREATE TABLE IF NOT EXISTS market_download_requests (
                token TEXT PRIMARY KEY,
                app_id INTEGER NOT NULL REFERENCES market_applications(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS market_download_requests_time_idx
                ON market_download_requests(created_at);
            """
        )
        database.execute("BEGIN IMMEDIATE")
        applicationColumns = {
            row[1] for row in database.execute("PRAGMA table_info(market_applications)")
        }
        if "sort_order" not in applicationColumns:
            database.execute(
                "ALTER TABLE market_applications "
                "ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
            )
        if "recommended_order" not in applicationColumns:
            database.execute(
                "ALTER TABLE market_applications ADD COLUMN recommended_order INTEGER"
            )
        if "manifest_revision" not in applicationColumns:
            database.execute(
                "ALTER TABLE market_applications "
                "ADD COLUMN manifest_revision INTEGER NOT NULL DEFAULT 1"
            )
        packageColumns = {
            row[1] for row in database.execute("PRAGMA table_info(market_packages)")
        }
        if "sha256" not in packageColumns:
            database.execute(
                "ALTER TABLE market_packages ADD COLUMN sha256 TEXT NOT NULL DEFAULT ''"
            )
        recommendedRows = database.execute(
            "SELECT id FROM market_applications WHERE recommended = 1 "
            "ORDER BY CASE WHEN recommended_order IS NULL THEN 1 ELSE 0 END, "
            "recommended_order, sort_order, id"
        ).fetchall()
        database.executemany(
            "UPDATE market_applications SET recommended_order = ? WHERE id = ?",
            [(index, row["id"]) for index, row in enumerate(recommendedRows)],
        )
        database.execute(
            "UPDATE market_applications SET recommended_order = NULL "
            "WHERE recommended = 0"
        )
        database.execute(
            "CREATE INDEX IF NOT EXISTS market_apps_order_idx "
            "ON market_applications(sort_order, id)"
        )
        database.execute(
            "CREATE INDEX IF NOT EXISTS market_recommended_order_idx "
            "ON market_applications(recommended, recommended_order, id)"
        )
        advertisementColumns = {
            row[1]
            for row in database.execute(
                "PRAGMA table_info(market_advertisements)"
            )
        }
        if "button_url" not in advertisementColumns:
            database.execute(
                "ALTER TABLE market_advertisements "
                "ADD COLUMN button_url TEXT NOT NULL DEFAULT ''"
            )
        duplicateInstallDir = database.execute(
            "SELECT GROUP_CONCAT(id || ':' || install_dir, ', ') AS items "
            "FROM market_applications GROUP BY install_dir COLLATE NOCASE "
            "HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicateInstallDir is not None:
            raise RuntimeError(
                "应用市场安装目录冲突，请先修复旧数据："
                f"{duplicateInstallDir['items']}"
            )
        database.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "market_applications_install_dir_nocase_idx "
            "ON market_applications(install_dir COLLATE NOCASE)"
        )
        database.commit()
        if databaseKey:
            _initializedSchemas.add(databaseKey)
            _schemaIdentities[databaseKey] = identity


def marketplaceStats(connect, day):
    """Return marketplace totals for the dashboard without changing catalog data."""

    _ensureSchema(connect)
    with closing(connect()) as database:
        todayDownloads = database.execute(
            "SELECT COUNT(*) FROM market_download_events "
            "WHERE downloaded_at >= datetime(?, '-8 hours') "
            "AND downloaded_at < datetime(?, '+1 day', '-8 hours')",
            (day, day),
        ).fetchone()[0]
        totalDownloads = database.execute(
            "SELECT COALESCE(SUM(download_count), 0) FROM market_applications"
        ).fetchone()[0]
        appCount = database.execute(
            "SELECT COUNT(*) FROM market_applications"
        ).fetchone()[0]
        adCount = database.execute(
            "SELECT COUNT(*) FROM market_advertisements WHERE enabled = 1"
        ).fetchone()[0]
        presetCount = database.execute(
            "SELECT COUNT(*) FROM market_presets"
        ).fetchone()[0]
    return {
        "today_downloads": todayDownloads,
        "downloads": totalDownloads,
        "apps": appCount,
        "ads": adCount,
        "presets": presetCount,
    }


def _actionArguments(value):
    try:
        arguments = json.loads(value or "{}")
    except (TypeError, ValueError):
        arguments = {}
    return arguments if isinstance(arguments, dict) else {}


def _rowAction(row, prefix="open"):
    actionType = row[f"{prefix}_action_type"]
    if not actionType:
        return None
    return {
        "type": actionType,
        "target": row[f"{prefix}_action_target"] or "",
        "arguments": _actionArguments(row[f"{prefix}_action_arguments"]),
    }


def _appPayload(row, packages, presets):
    packageMap = {}
    for package in packages:
        sha256 = _safeSha256(package["sha256"])
        packageMap[package["architecture"]] = {
            "enabled": bool(package["enabled"]),
            "sha256": sha256,
        }
    return {
        "id": row["id"],
        "name": row["name"],
        "developer": row["developer"],
        "description": row["description"],
        "version": row["version"],
        "icon_url": row["icon_url"],
        "install_dir": row["install_dir"],
        "recommended": bool(row["recommended"]),
        "recommended_order": row["recommended_order"],
        "announcement": row["announcement"] or "",
        "manifest_revision": row["manifest_revision"],
        "open_action": _rowAction(row),
        "packages": packageMap,
        "presets": [
            {
                "id": preset["id"],
                "title": preset["title"],
                "description": preset["description"],
                "action": {
                    "type": preset["action_type"],
                    "target": preset["action_target"],
                    "arguments": _actionArguments(preset["action_arguments"]),
                },
            }
            for preset in presets
        ],
    }


def _adminFormData(database, appId=None):
    if appId is None:
        return None, {
            "packages": {
                architecture: {"enabled": True, "download_url": "", "sha256": ""}
                for architecture in ARCHITECTURES
            },
            "open_action_arguments": "",
        }
    row = database.execute(
        "SELECT * FROM market_applications WHERE id = ?", (appId,)
    ).fetchone()
    if not row:
        return None, {"packages": {}, "open_action_arguments": ""}
    packages = {
        package["architecture"]: package
        for package in database.execute(
            "SELECT * FROM market_packages WHERE app_id = ?", (appId,)
        )
    }
    form = dict(row)
    form["packages"] = packages
    form["open_action_arguments"] = _argumentsText(form["open_action_arguments"])
    return row, form


def _applicationExists(database, appId):
    return appId is None or database.execute(
        "SELECT 1 FROM market_applications WHERE id = ?", (appId,)
    ).fetchone() is not None


def _advertisementForm():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    imageUrl = _safeUrl(request.form.get("image_url"))
    appIdValue = request.form.get("app_id", "").strip()
    buttonType = request.form.get("button_type", "").strip().lower()
    if not buttonType:
        buttonType = "app" if appIdValue else "none"
    if buttonType not in {"none", "app", "url"}:
        return None, "广告按钮类型无效"
    try:
        appId = int(appIdValue) if buttonType == "app" and appIdValue else None
    except ValueError:
        return None, "绑定的软件无效"
    buttonUrl = (
        _safeUrl(request.form.get("button_url"))
        if buttonType == "url"
        else ""
    )
    sortOrderValue = request.form.get("sort_order")
    try:
        sortOrder = (
            int(sortOrderValue) if sortOrderValue is not None else None
        )
    except ValueError:
        sortOrder = None
    if not title or not imageUrl:
        return None, "广告标题和 HTTPS 图片链接不能为空"
    if len(title) > 120 or len(description) > 300:
        return None, "广告标题或简介过长"
    if sortOrderValue is not None and sortOrder is None:
        return None, "广告顺序无效"
    if buttonType == "app" and appId is None:
        return None, "请选择广告按钮绑定的软件"
    if buttonType == "url" and not buttonUrl:
        return None, "广告按钮链接必须是 HTTPS 地址"
    return (
        title,
        description,
        imageUrl,
        appId,
        buttonUrl,
        sortOrder,
        int(bool(request.form.get("enabled"))),
    ), ""


def _requestedOrder():
    values = request.form.getlist("item_id")
    try:
        ids = [int(value) for value in values]
    except (TypeError, ValueError):
        return None
    if not ids or len(ids) != len(set(ids)) or any(itemId <= 0 for itemId in ids):
        return None
    return ids


def _requestedExpectedOrder():
    values = request.form.getlist("expected_item_id")
    try:
        ids = [int(value) for value in values]
    except (TypeError, ValueError):
        return None
    if not ids or len(ids) != len(set(ids)) or any(itemId <= 0 for itemId in ids):
        return None
    return ids


def _reorderItems(database, kind, ids, expectedIds, appId=None):
    if kind == "applications":
        rows = database.execute(
            "SELECT id FROM market_applications ORDER BY sort_order, id"
        ).fetchall()
        update = "UPDATE market_applications SET sort_order = ? WHERE id = ?"
    elif kind == "advertisements":
        rows = database.execute(
            "SELECT id FROM market_advertisements ORDER BY sort_order, id"
        ).fetchall()
        update = "UPDATE market_advertisements SET sort_order = ? WHERE id = ?"
    elif kind == "presets":
        rows = database.execute(
            "SELECT id FROM market_presets WHERE app_id = ? ORDER BY sort_order, id",
            (appId,),
        ).fetchall()
        update = "UPDATE market_presets SET sort_order = ? WHERE id = ?"
    elif kind == "recommendations":
        rows = database.execute(
            "SELECT id FROM market_applications WHERE recommended = 1 "
            "ORDER BY recommended_order, sort_order, id"
        ).fetchall()
        update = (
            "UPDATE market_applications SET recommended_order = ? WHERE id = ?"
        )
    else:
        raise ValueError("无效的排序类型")
    currentIds = [row["id"] for row in rows]
    if currentIds != expectedIds or len(ids) != len(currentIds) or set(ids) != set(currentIds):
        return False
    database.executemany(
        update,
        [(sortOrder, rowId) for sortOrder, rowId in enumerate(ids)],
    )
    return True


def _formErrors(errors, renderer):
    message = "；".join(errors)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or (
        request.accept_mimetypes.best == "application/json"
    ):
        return jsonify(message=message, category="error"), 400
    for error in errors:
        flash(error, "error")
    return renderer(), 400


def register_app_store(
    app,
    *,
    connect,
    login_required,
    csrf_token,
    check_csrf,
    admin_response,
):
    """Register public catalog and dashboard routes on the existing Flask app."""

    _ensureSchema(connect)
    blueprint = Blueprint("app_store", __name__)

    def apiRoute(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if _hostOnly() != _apiHost():
                abort(404)
            return view(*args, **kwargs)

        return wrapped

    @blueprint.get("/app-store/catalog")
    @apiRoute
    def catalog():
        _ensureSchema(connect)
        with closing(connect()) as database:
            rows = database.execute(
                "SELECT * FROM market_applications ORDER BY sort_order, id"
            ).fetchall()
            packagesByApp = {}
            for package in database.execute(
                "SELECT app_id, architecture, enabled, sha256 FROM market_packages"
            ):
                packagesByApp.setdefault(package["app_id"], []).append(package)
            presetsByApp = {}
            for preset in database.execute(
                """
                SELECT app_id, id, title, description, action_type, action_target,
                       action_arguments
                FROM market_presets ORDER BY app_id, sort_order, id
                """
            ):
                presetsByApp.setdefault(preset["app_id"], []).append(preset)
            apps = [
                _appPayload(
                    row,
                    packagesByApp.get(row["id"], ()),
                    presetsByApp.get(row["id"], ()),
                )
                for row in rows
            ]
            ads = [
                {
                    "id": ad["id"],
                    "title": ad["title"],
                    "description": ad["description"],
                    "image_url": ad["image_url"],
                    "app_id": ad["app_id"],
                    "button_type": (
                        "app" if ad["app_id"] is not None else (
                            "url" if ad["button_url"] else "none"
                        )
                    ),
                    "button_url": ad["button_url"],
                }
                for ad in database.execute(
                    """
                    SELECT id, title, description, image_url, app_id, button_url
                    FROM market_advertisements
                    WHERE enabled = 1 ORDER BY sort_order, id
                    """
                )
            ]
        payload = {"apps": apps, "ads": ads, "architectures": list(ARCHITECTURES)}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        etag = '"' + hashlib.sha256(encoded).hexdigest() + '"'
        if request.if_none_match.contains(etag.strip('"')):
            response = app.make_response(("", 304))
        else:
            response = jsonify(payload)
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "public, max-age=300"
        return response

    @blueprint.get("/app-store/apps/<int:app_id>/download")
    @apiRoute
    def download(app_id):
        architecture = request.args.get("arch", "").lower()
        if architecture not in ARCHITECTURES:
            return jsonify(message="不支持的客户端架构"), 400
        _ensureSchema(connect)
        with closing(connect()) as database:
            row = database.execute(
                """
                SELECT p.download_url
                FROM market_packages p
                JOIN market_applications a ON a.id = p.app_id
                WHERE a.id = ? AND p.architecture = ? AND p.enabled = 1
                """,
                (app_id, architecture),
            ).fetchone()
            if not row:
                return jsonify(message="该架构暂未提供安装包"), 404
            url = _safeUrl(row["download_url"])
            if not url:
                return jsonify(message="安装包链接配置无效"), 503
            token = request.args.get("token", "").strip().lower()
            shouldCount = False
            if _DOWNLOAD_TOKEN.fullmatch(token):
                existingToken = database.execute(
                    "SELECT 1 FROM market_download_requests WHERE token = ?",
                    (token,),
                ).fetchone()
                if existingToken:
                    shouldCount = False
                else:
                    database.execute(
                        "DELETE FROM market_download_requests "
                        "WHERE created_at < datetime('now', '-1 day')"
                    )
                    shouldCount = bool(
                        database.execute(
                            "INSERT OR IGNORE INTO market_download_requests(token, app_id) "
                            "VALUES (?, ?)",
                            (token, app_id),
                        ).rowcount
                    )
            if shouldCount:
                database.execute(
                    "UPDATE market_applications "
                    "SET download_count = download_count + 1 WHERE id = ?",
                    (app_id,),
                )
                database.execute(
                    "DELETE FROM market_download_events "
                    "WHERE downloaded_at < datetime('now', ?)",
                    (f"-{_DOWNLOAD_EVENT_RETENTION_DAYS} days",),
                )
                database.execute(
                    "INSERT INTO market_download_events(app_id, architecture) VALUES (?, ?)",
                    (app_id, architecture),
                )
                database.commit()
        return redirect(url, code=302)

    @blueprint.get("/admin/app-store/apps/")
    @login_required
    def adminApps():
        _ensureSchema(connect)
        with closing(connect()) as database:
            rows = database.execute(
                "SELECT * FROM market_applications ORDER BY sort_order, id"
            ).fetchall()
        return render_template(
            "admin_app_store_apps.html",
            csrf_token=csrf_token(),
            current_page="app_store_apps",
            apps=rows,
        )

    @blueprint.route("/admin/app-store/apps/new", methods=["GET", "POST"])
    @login_required
    def adminNewApp():
        return _saveApp(None) if request.method == "POST" else _renderApp(None)

    @blueprint.route("/admin/app-store/apps/<int:app_id>", methods=["GET", "POST"])
    @login_required
    def adminApp(app_id):
        return _saveApp(app_id) if request.method == "POST" else _renderApp(app_id)

    def _renderApp(appId, submitted=None):
        _ensureSchema(connect)
        with closing(connect()) as database:
            row, storedForm = _adminFormData(database, appId)
        if appId is not None and row is None:
            abort(404)
        return render_template(
            "admin_app_store_app.html",
            csrf_token=csrf_token(),
            current_page="app_store_apps",
            app=row,
            form=submitted or storedForm,
            architectures=ARCHITECTURES,
        )

    def _saveApp(appId):
        check_csrf()
        rawIconUrl = request.form.get("icon_url", "").strip()
        values = {
            "name": request.form.get("name", "").strip(),
            "developer": request.form.get("developer", "").strip(),
            "description": request.form.get("description", "").strip(),
            "version": request.form.get("version", "").strip(),
            "icon_url": _safeUrl(rawIconUrl),
            "install_dir": request.form.get("install_dir", "").strip(),
            "recommended": (
                1 if request.form.get("recommended") else 0
            ) if "recommended" in request.form else None,
            "announcement": request.form.get("announcement", "").strip(),
        }
        errors = []
        if not values["name"]:
            errors.append("软件名称不能为空")
        if not values["version"]:
            errors.append("软件版本不能为空")
        if not _safeInstallDir(values["install_dir"]):
            errors.append("安装目录包含无效或 Windows 保留名称")
        for field, label, limit in (
            ("name", "软件名称", 120),
            ("developer", "开发者", 120),
            ("description", "软件简介", 1000),
            ("version", "软件版本", 64),
            ("announcement", "软件公告", 1000),
        ):
            if len(values[field]) > limit:
                errors.append(f"{label}不能超过 {limit} 个字符")
        if request.form.get("icon_url", "").strip() and not values["icon_url"]:
            errors.append("图标链接必须是 HTTPS 地址")
        actionType = request.form.get("open_action_type", "").strip().lower()
        action = _formAction(
            actionType,
            request.form.get("open_action_target"),
            request.form.get("open_action_arguments", ""),
        )
        if actionType and not action:
            errors.append(
                "HTTPS 网页目标必须以 https:// 开头；"
                "classisland:// 等自定义协议请选择“系统协议”"
                if actionType == "url"
                else "打开动作配置无效"
            )
        packages = {}
        packageForm = {}
        for architecture in ARCHITECTURES:
            rawUrl = request.form.get(f"{architecture}_url", "").strip()
            url = _safeUrl(rawUrl)
            sha256 = request.form.get(f"{architecture}_sha256", "").strip().lower()
            enabled = bool(request.form.get(f"{architecture}_enabled"))
            packageForm[architecture] = {
                "enabled": enabled,
                "download_url": rawUrl,
                "sha256": sha256,
            }
            if enabled and not url:
                errors.append(f"{architecture} 安装包启用时必须填写 HTTPS 链接")
            elif rawUrl and not url:
                errors.append(f"{architecture} 安装包链接无效")
            if sha256 and not _SHA256.fullmatch(sha256):
                errors.append(f"{architecture} 安装包 SHA-256 格式无效")
            if url:
                packages[architecture] = (enabled, url, sha256)
        submitted = {
            **values,
            "icon_url": rawIconUrl,
            "open_action_type": actionType,
            "open_action_target": request.form.get("open_action_target", "").strip(),
            "open_action_arguments": request.form.get("open_action_arguments", ""),
            "packages": packageForm,
        }
        if appId is not None:
            _ensureSchema(connect)
            with closing(connect()) as database:
                existing = database.execute(
                    "SELECT install_dir FROM market_applications WHERE id = ?",
                    (appId,),
                ).fetchone()
            if existing is None:
                return admin_response(
                    "软件不存在", "error", "app_store.adminApps", 404
                )
            if values["install_dir"] != existing["install_dir"]:
                errors.append("已发布软件不能直接修改安装目录，请新建软件或执行迁移")
        if errors:
            return _formErrors(errors, lambda: _renderApp(appId, submitted))
        _ensureSchema(connect)
        with closing(connect()) as database:
            try:
                database.execute("BEGIN IMMEDIATE")
                existingApp = (
                    database.execute(
                        "SELECT * FROM market_applications WHERE id = ?",
                        (appId,),
                    ).fetchone()
                    if appId is not None
                    else None
                )
                if appId is not None and existingApp is None:
                    database.rollback()
                    return admin_response(
                        "软件不存在",
                        "error",
                        "app_store.adminApps",
                        404,
                    )
                duplicate = database.execute(
                    "SELECT id FROM market_applications "
                    "WHERE install_dir = ? COLLATE NOCASE "
                    "AND (? IS NULL OR id <> ?)",
                    (values["install_dir"], appId, appId),
                ).fetchone()
                if duplicate:
                    database.rollback()
                    return _formErrors(
                        ["安装目录已被其他软件使用"],
                        lambda: _renderApp(appId, submitted),
                    )
                if appId is None:
                    sortOrder = database.execute(
                        "SELECT COALESCE(MAX(sort_order), -1) + 1 "
                        "FROM market_applications"
                    ).fetchone()[0]
                    recommended = values["recommended"] or 0
                    recommendedOrder = (
                        database.execute(
                            "SELECT COALESCE(MAX(recommended_order), -1) + 1 "
                            "FROM market_applications WHERE recommended = 1"
                        ).fetchone()[0]
                        if recommended
                        else None
                    )
                    cursor = database.execute(
                        """
                        INSERT INTO market_applications
                        (name, developer, description, version, icon_url, install_dir,
                         recommended, recommended_order, sort_order, announcement,
                         open_action_type, open_action_target, open_action_arguments)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            values["name"], values["developer"], values["description"],
                            values["version"], values["icon_url"], values["install_dir"],
                            recommended, recommendedOrder, sortOrder, values["announcement"],
                            action["type"] if action else None,
                            action["target"] if action else None,
                            json.dumps(action["arguments"] if action else {}, ensure_ascii=False),
                        ),
                    )
                    appId = cursor.lastrowid
                else:
                    currentPackages = {
                        package["architecture"]: (
                            bool(package["enabled"]),
                            package["download_url"],
                            package["sha256"],
                        )
                        for package in database.execute(
                            "SELECT architecture, enabled, download_url, sha256 "
                            "FROM market_packages WHERE app_id = ?",
                            (appId,),
                        )
                    }
                    manifestChanged = (
                        _rowAction(existingApp) != action
                        or currentPackages != packages
                        or any(
                            str(existingApp[field] or "") != values[field]
                            for field in (
                                "name",
                                "developer",
                                "description",
                                "version",
                                "icon_url",
                                "install_dir",
                                "announcement",
                            )
                        )
                    )
                    database.execute(
                        """
                        UPDATE market_applications SET name=?, developer=?, description=?,
                        version=?, icon_url=?, install_dir=?, announcement=?,
                        open_action_type=?, open_action_target=?, open_action_arguments=?,
                        manifest_revision=manifest_revision+?,
                        updated_at=CURRENT_TIMESTAMP WHERE id=?
                        """,
                        (
                            values["name"], values["developer"], values["description"],
                            values["version"], values["icon_url"], values["install_dir"],
                            values["announcement"],
                            action["type"] if action else None,
                            action["target"] if action else None,
                            json.dumps(action["arguments"] if action else {}, ensure_ascii=False),
                            int(manifestChanged),
                            appId,
                        ),
                    )
                    if values["recommended"] is not None:
                        if values["recommended"]:
                            recommendedOrder = database.execute(
                                "SELECT COALESCE(MAX(recommended_order), -1) + 1 "
                                "FROM market_applications WHERE recommended = 1 "
                                "AND id <> ?",
                                (appId,),
                            ).fetchone()[0]
                            database.execute(
                                "UPDATE market_applications SET recommended = 1, "
                                "recommended_order = COALESCE(recommended_order, ?) "
                                "WHERE id = ?",
                                (recommendedOrder, appId),
                            )
                        else:
                            database.execute(
                                "UPDATE market_applications SET recommended = 0, "
                                "recommended_order = NULL WHERE id = ?",
                                (appId,),
                            )
                    database.execute("DELETE FROM market_packages WHERE app_id = ?", (appId,))
                database.executemany(
                    "INSERT INTO market_packages"
                    "(app_id, architecture, enabled, download_url, sha256) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [
                        (appId, architecture, int(enabled), url, sha256)
                        for architecture, (enabled, url, sha256) in packages.items()
                    ],
                )
                database.commit()
            except sqlite3.IntegrityError as error:
                database.rollback()
                return _formErrors(
                    [f"保存失败：{error}"],
                    lambda: _renderApp(appId, submitted),
                )
        return admin_response("软件信息已保存", "success", "app_store.adminApps")

    @blueprint.post("/admin/app-store/apps/<int:app_id>/delete")
    @login_required
    def adminDeleteApp(app_id):
        check_csrf()
        _ensureSchema(connect)
        with closing(connect()) as database:
            deleted = database.execute(
                "DELETE FROM market_applications WHERE id = ?", (app_id,)
            )
            if not deleted.rowcount:
                return admin_response(
                    "软件不存在",
                    "error",
                    "app_store.adminApps",
                    404,
                )
            database.commit()
        return admin_response("软件已删除", "success", "app_store.adminApps")

    @blueprint.post("/admin/app-store/apps/order")
    @login_required
    def adminOrderApps():
        check_csrf()
        ids = _requestedOrder()
        expectedIds = _requestedExpectedOrder()
        if ids is None or expectedIds is None:
            return admin_response("软件顺序无效", "error", "app_store.adminApps", 400)
        _ensureSchema(connect)
        with closing(connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            if not _reorderItems(database, "applications", ids, expectedIds):
                database.rollback()
                return admin_response("软件顺序已过期，请刷新后重试", "error", "app_store.adminApps", 409)
            database.commit()
        return admin_response("软件顺序已更新", "success", "app_store.adminApps")

    def _renderPresets(appId=None):
        if appId is None and request.args.get("app_id"):
            try:
                appId = int(request.args["app_id"])
            except (TypeError, ValueError):
                abort(404)
        if appId is not None and appId <= 0:
            abort(404)
        if request.args.get("edit"):
            try:
                return _renderPresetForm(appId, int(request.args["edit"]))
            except (TypeError, ValueError):
                abort(404)
        _ensureSchema(connect)
        with closing(connect()) as database:
            apps = database.execute(
                """
                SELECT a.id, a.name, a.version, a.sort_order,
                       COUNT(p.id) AS preset_count
                FROM market_applications a
                LEFT JOIN market_presets p ON p.app_id = a.id
                GROUP BY a.id
                ORDER BY a.sort_order, a.id
                """
            ).fetchall()
            selectedApp = next(
                (item for item in apps if item["id"] == appId),
                None,
            )
            if appId is not None and selectedApp is None:
                abort(404)
            rows = (
                database.execute(
                    "SELECT * FROM market_presets WHERE app_id = ? "
                    "ORDER BY sort_order, id",
                    (appId,),
                ).fetchall()
                if selectedApp is not None
                else []
            )

        presets = []
        for row in rows:
            preset = dict(row)
            preset["action_arguments"] = _argumentsText(
                preset["action_arguments"]
            )
            presets.append(preset)
        return render_template(
            "admin_app_store_presets.html",
            csrf_token=csrf_token(),
            current_page="app_store_presets",
            presets=presets,
            apps=apps,
            selected_app=selectedApp,
        )

    def _renderPresetForm(appId, presetId=None, submitted=None):
        _ensureSchema(connect)
        with closing(connect()) as database:
            selectedApp = database.execute(
                "SELECT id, name, version FROM market_applications WHERE id = ?",
                (appId,),
            ).fetchone()
            if selectedApp is None:
                abort(404)
            row = (
                database.execute(
                    "SELECT * FROM market_presets WHERE id = ? AND app_id = ?",
                    (presetId, appId),
                ).fetchone()
                if presetId is not None
                else None
            )
        if presetId is not None and row is None:
            abort(404)
        preset = submitted if submitted is not None else (
            dict(row) if row is not None else None
        )
        if preset is not None and submitted is None:
            preset["action_arguments"] = _argumentsText(
                preset["action_arguments"]
            )
        return render_template(
            "admin_app_store_preset.html",
            csrf_token=csrf_token(),
            current_page="app_store_presets",
            selected_app=selectedApp,
            preset=preset,
            editing=presetId is not None,
        )

    @blueprint.get("/admin/app-store/presets/")
    @blueprint.get("/admin/app-store/presets/<int:app_id>/")
    @login_required
    def adminPresets(app_id=None):
        return _renderPresets(app_id)

    @blueprint.route(
        "/admin/app-store/presets/<int:app_id>/new", methods=["GET", "POST"]
    )
    @login_required
    def adminNewPreset(app_id):
        return (
            _savePreset(app_id, None)
            if request.method == "POST"
            else _renderPresetForm(app_id)
        )

    @blueprint.route(
        "/admin/app-store/presets/<int:app_id>/items/<int:preset_id>",
        methods=["GET", "POST"],
    )
    @login_required
    def adminPreset(app_id, preset_id):
        return (
            _savePreset(app_id, preset_id)
            if request.method == "POST"
            else _renderPresetForm(app_id, preset_id)
        )

    @blueprint.post("/admin/app-store/presets/")
    @login_required
    def adminCreatePresetLegacy():
        return _savePreset(None, None)

    @blueprint.post("/admin/app-store/presets/<int:preset_id>")
    @login_required
    def adminPresetLegacy(preset_id):
        return _savePreset(None, preset_id)

    def _savePreset(appId, presetId):
        check_csrf()
        if request.form.get("delete"):
            _ensureSchema(connect)
            with closing(connect()) as database:
                database.execute("BEGIN IMMEDIATE")
                row = database.execute(
                    "SELECT app_id FROM market_presets WHERE id = ?",
                    (presetId,),
                ).fetchone()
                if row is None:
                    return admin_response(
                        "预设卡片不存在",
                        "error",
                        "app_store.adminPresets",
                        404,
                    )
                if appId is not None and row["app_id"] != appId:
                    return admin_response(
                        "预设卡片不存在",
                        "error",
                        "app_store.adminPresets",
                        404,
                    )
                database.execute(
                    "DELETE FROM market_presets WHERE id = ?", (presetId,)
                )
                database.execute(
                    "UPDATE market_applications "
                    "SET manifest_revision = manifest_revision + 1 WHERE id = ?",
                    (row["app_id"],),
                )
                database.commit()
            return admin_response(
                "预设卡片已删除",
                "success",
                "app_store.adminPresets",
                url_values={"app_id": row["app_id"]},
            )

        title = request.form.get("preset_title", "").strip()
        description = request.form.get("preset_description", "").strip()
        actionType = request.form.get("preset_action_type", "").strip().lower()
        action = _formAction(
            actionType,
            request.form.get("preset_action_target"),
            request.form.get("preset_action_arguments", ""),
        )
        if appId is None:
            try:
                appId = int(request.form.get("preset_app_id"))
            except (TypeError, ValueError):
                appId = None
        errors = []
        if appId is None:
            errors.append("请选择软件")
        if not title:
            errors.append("卡片标题不能为空")
        if len(title) > 80:
            errors.append("卡片标题不能超过 80 个字符")
        if len(description) > 240:
            errors.append("卡片简介不能超过 240 个字符")
        if not action:
            errors.append(
                "HTTPS 网页目标必须以 https:// 开头；"
                "classisland:// 等自定义协议请选择“系统协议”"
                if actionType == "url"
                else "预设卡片动作配置无效"
            )
        redirectValues = {"app_id": appId} if appId else None
        if errors:
            if appId is not None:
                submitted = {
                    "id": presetId,
                    "title": title,
                    "description": description,
                    "action_type": actionType,
                    "action_target": request.form.get(
                        "preset_action_target", ""
                    ).strip(),
                    "action_arguments": request.form.get(
                        "preset_action_arguments", ""
                    ),
                }
                return _formErrors(
                    errors,
                    lambda: _renderPresetForm(appId, presetId, submitted),
                )
            return admin_response(
                "；".join(errors), "error", "app_store.adminPresets", 400
            )
        _ensureSchema(connect)
        with closing(connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            if not database.execute("SELECT 1 FROM market_applications WHERE id = ?", (appId,)).fetchone():
                return admin_response(
                    "选择的软件不存在",
                    "error",
                    "app_store.adminPresets",
                    400,
                )
            current = (
                database.execute(
                    "SELECT * FROM market_presets WHERE id = ?",
                    (presetId,),
                ).fetchone()
                if presetId is not None
                else None
            )
            if presetId is not None and current is None:
                return admin_response(
                    "预设卡片不存在",
                    "error",
                    "app_store.adminPresets",
                    404,
                    url_values=redirectValues,
                )
            if current is not None and current["app_id"] != appId:
                return admin_response(
                    "预设卡片不存在",
                    "error",
                    "app_store.adminPresets",
                    404,
                    url_values=redirectValues,
                )
            sortOrder = (
                current["sort_order"]
                if current is not None
                else database.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 "
                    "FROM market_presets WHERE app_id = ?",
                    (appId,),
                ).fetchone()[0]
            )
            values = (
                appId,
                title,
                description,
                action["type"],
                action["target"],
                json.dumps(action["arguments"], ensure_ascii=False),
                sortOrder,
            )
            if presetId is None:
                database.execute(
                    """
                    INSERT INTO market_presets
                    (app_id, title, description, action_type, action_target, action_arguments, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                message = "预设卡片已新增"
                manifestChanged = True
            else:
                updated = database.execute(
                    """
                    UPDATE market_presets SET app_id=?, title=?, description=?, action_type=?,
                    action_target=?, action_arguments=?, sort_order=? WHERE id=?
                    """,
                    values + (presetId,),
                )
                if not updated.rowcount:
                    database.rollback()
                    return admin_response(
                        "预设卡片不存在",
                        "error",
                        "app_store.adminPresets",
                        404,
                        url_values=redirectValues,
                    )
                message = "预设卡片已保存"
                manifestChanged = values != (
                    current["app_id"],
                    current["title"],
                    current["description"],
                    current["action_type"],
                    current["action_target"],
                    current["action_arguments"],
                    current["sort_order"],
                )
            if manifestChanged:
                database.execute(
                    "UPDATE market_applications "
                    "SET manifest_revision = manifest_revision + 1 WHERE id = ?",
                    (appId,),
                )
            database.commit()
        return admin_response(
            message,
            "success",
            "app_store.adminPresets",
            url_values={"app_id": appId},
        )

    @blueprint.post("/admin/app-store/presets/<int:app_id>/order")
    @login_required
    def adminOrderPresets(app_id):
        check_csrf()
        ids = _requestedOrder()
        expectedIds = _requestedExpectedOrder()
        if ids is None or expectedIds is None:
            return admin_response(
                "预设卡片顺序无效",
                "error",
                "app_store.adminPresets",
                400,
                url_values={"app_id": app_id},
            )
        _ensureSchema(connect)
        with closing(connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            if not _reorderItems(
                database, "presets", ids, expectedIds, app_id
            ):
                database.rollback()
                return admin_response(
                    "预设卡片顺序已过期，请刷新后重试",
                    "error",
                    "app_store.adminPresets",
                    409,
                    url_values={"app_id": app_id},
                )
            if ids != expectedIds:
                database.execute(
                    "UPDATE market_applications "
                    "SET manifest_revision = manifest_revision + 1 WHERE id = ?",
                    (app_id,),
                )
            database.commit()
        return admin_response(
            "预设卡片顺序已更新",
            "success",
            "app_store.adminPresets",
            url_values={"app_id": app_id},
        )

    @blueprint.route("/admin/app-store/ads/", methods=["GET", "POST"])
    @login_required
    def adminAds():
        if request.method == "POST":
            return _saveAd(None)
        if request.args.get("edit"):
            try:
                return _renderAd(int(request.args["edit"]))
            except (TypeError, ValueError):
                abort(404)
        _ensureSchema(connect)
        with closing(connect()) as database:
            ads = database.execute(
                """
                SELECT ad.*, a.name AS app_name FROM market_advertisements ad
                LEFT JOIN market_applications a ON a.id = ad.app_id
                ORDER BY ad.sort_order, ad.id
                """
            ).fetchall()
        return render_template(
            "admin_app_store_ads.html",
            csrf_token=csrf_token(),
            current_page="app_store_ads",
            ads=ads,
        )

    def _renderAd(adId=None, submitted=None):
        _ensureSchema(connect)
        with closing(connect()) as database:
            ad = (
                database.execute(
                    "SELECT * FROM market_advertisements WHERE id = ?", (adId,)
                ).fetchone()
                if adId is not None
                else None
            )
            apps = database.execute(
                "SELECT id, name FROM market_applications ORDER BY sort_order, id"
            ).fetchall()
        if adId is not None and ad is None:
            abort(404)
        return render_template(
            "admin_app_store_ad.html",
            csrf_token=csrf_token(),
            current_page="app_store_ads",
            ad=submitted or ad,
            apps=apps,
            editing=adId is not None,
        )

    @blueprint.route("/admin/app-store/ads/new", methods=["GET", "POST"])
    @login_required
    def adminNewAd():
        return _saveAd(None) if request.method == "POST" else _renderAd()

    @blueprint.route("/admin/app-store/ads/<int:ad_id>", methods=["GET", "POST"])
    @login_required
    def adminAd(ad_id):
        return _saveAd(ad_id) if request.method == "POST" else _renderAd(ad_id)

    def _saveAd(adId):
        check_csrf()
        _ensureSchema(connect)
        if request.form.get("delete"):
            with closing(connect()) as database:
                database.execute("BEGIN IMMEDIATE")
                deleted = database.execute(
                    "DELETE FROM market_advertisements WHERE id = ?", (adId,)
                )
                if not deleted.rowcount:
                    return admin_response(
                        "广告不存在",
                        "error",
                        "app_store.adminAds",
                        404,
                    )
                database.commit()
            return admin_response("广告已删除", "success", "app_store.adminAds")
        values, error = _advertisementForm()
        if error:
            appId = request.form.get("app_id", "").strip()
            submitted = {
                "id": adId,
                "title": request.form.get("title", "").strip(),
                "description": request.form.get("description", "").strip(),
                "image_url": request.form.get("image_url", "").strip(),
                "app_id": int(appId) if appId.isdigit() else None,
                "button_type": request.form.get("button_type", "").strip(),
                "button_url": request.form.get("button_url", "").strip(),
                "enabled": bool(request.form.get("enabled")),
            }
            return _formErrors(
                [error], lambda: _renderAd(adId, submitted)
            )
        title, description, imageUrl, appId, buttonUrl, sortOrder, enabled = values
        with closing(connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            if not _applicationExists(database, appId):
                submitted = {
                    "id": adId,
                    "title": title,
                    "description": description,
                    "image_url": imageUrl,
                    "app_id": appId,
                    "button_type": "app",
                    "button_url": buttonUrl,
                    "enabled": bool(enabled),
                }
                return _formErrors(
                    ["绑定的软件不存在"],
                    lambda: _renderAd(adId, submitted),
                )
            current = database.execute(
                "SELECT sort_order FROM market_advertisements WHERE id = ?",
                (adId,),
            ).fetchone()
            if adId is not None and current is None:
                return admin_response(
                    "广告不存在", "error", "app_store.adminAds", 404
                )
            if sortOrder is None:
                sortOrder = (
                    current["sort_order"]
                    if current is not None
                    else database.execute(
                        "SELECT COALESCE(MAX(sort_order), -1) + 1 "
                        "FROM market_advertisements"
                    ).fetchone()[0]
                )
            if adId is None:
                database.execute(
                    "INSERT INTO market_advertisements"
                    "(title, description, image_url, app_id, button_url, "
                    "sort_order, enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        title,
                        description,
                        imageUrl,
                        appId,
                        buttonUrl,
                        sortOrder,
                        enabled,
                    ),
                )
                message = "广告已新增"
            else:
                database.execute(
                    "UPDATE market_advertisements SET title=?, description=?, "
                    "image_url=?, app_id=?, button_url=?, sort_order=?, enabled=? "
                    "WHERE id=?",
                    (
                        title,
                        description,
                        imageUrl,
                        appId,
                        buttonUrl,
                        sortOrder,
                        enabled,
                        adId,
                    ),
                )
                message = "广告已保存"
            database.commit()
        return admin_response(message, "success", "app_store.adminAds")

    @blueprint.post("/admin/app-store/ads/order")
    @login_required
    def adminOrderAds():
        check_csrf()
        ids = _requestedOrder()
        expectedIds = _requestedExpectedOrder()
        if ids is None or expectedIds is None:
            return admin_response("广告顺序无效", "error", "app_store.adminAds", 400)
        _ensureSchema(connect)
        with closing(connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            if not _reorderItems(database, "advertisements", ids, expectedIds):
                database.rollback()
                return admin_response(
                    "广告顺序已过期，请刷新后重试",
                    "error",
                    "app_store.adminAds",
                    409,
                )
            database.commit()
        return admin_response("广告顺序已更新", "success", "app_store.adminAds")

    @blueprint.get("/admin/app-store/recommendations/")
    @login_required
    def adminRecommendations():
        _ensureSchema(connect)
        with closing(connect()) as database:
            rows = database.execute(
                "SELECT * FROM market_applications WHERE recommended = 1 "
                "ORDER BY recommended_order, sort_order, id"
            ).fetchall()
        return render_template(
            "admin_app_store_recommendations.html",
            csrf_token=csrf_token(),
            current_page="app_store_recommendations",
            apps=rows,
        )

    @blueprint.route(
        "/admin/app-store/recommendations/new", methods=["GET", "POST"]
    )
    @login_required
    def adminNewRecommendation():
        _ensureSchema(connect)
        if request.method == "GET":
            with closing(connect()) as database:
                apps = database.execute(
                    "SELECT id, name, version FROM market_applications "
                    "WHERE recommended = 0 ORDER BY sort_order, id"
                ).fetchall()
            return render_template(
                "admin_app_store_recommendation.html",
                csrf_token=csrf_token(),
                current_page="app_store_recommendations",
                apps=apps,
            )
        check_csrf()
        try:
            appId = int(request.form.get("app_id"))
        except (TypeError, ValueError):
            appId = None
        with closing(connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            if appId is None or not database.execute(
                "SELECT 1 FROM market_applications WHERE id = ? AND recommended = 0",
                (appId,),
            ).fetchone():
                return admin_response(
                    "请选择尚未推荐的软件",
                    "error",
                    "app_store.adminNewRecommendation",
                    400,
                )
            sortOrder = database.execute(
                "SELECT COALESCE(MAX(recommended_order), -1) + 1 "
                "FROM market_applications WHERE recommended = 1"
            ).fetchone()[0]
            database.execute(
                "UPDATE market_applications SET recommended = 1, "
                "recommended_order = ? WHERE id = ?",
                (sortOrder, appId),
            )
            database.commit()
        return admin_response(
            "推荐软件已新增", "success", "app_store.adminRecommendations"
        )

    @blueprint.post("/admin/app-store/recommendations/<int:app_id>/delete")
    @login_required
    def adminDeleteRecommendation(app_id):
        check_csrf()
        _ensureSchema(connect)
        with closing(connect()) as database:
            updated = database.execute(
                "UPDATE market_applications SET recommended = 0, "
                "recommended_order = NULL WHERE id = ? AND recommended = 1",
                (app_id,),
            )
            if not updated.rowcount:
                return admin_response(
                    "推荐软件不存在",
                    "error",
                    "app_store.adminRecommendations",
                    404,
                )
            database.commit()
        return admin_response(
            "已取消推荐", "success", "app_store.adminRecommendations"
        )

    @blueprint.post("/admin/app-store/recommendations/order")
    @login_required
    def adminOrderRecommendations():
        check_csrf()
        ids = _requestedOrder()
        expectedIds = _requestedExpectedOrder()
        if ids is None or expectedIds is None:
            return admin_response(
                "推荐顺序无效",
                "error",
                "app_store.adminRecommendations",
                400,
            )
        _ensureSchema(connect)
        with closing(connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            if not _reorderItems(database, "recommendations", ids, expectedIds):
                database.rollback()
                return admin_response(
                    "推荐顺序已过期，请刷新后重试",
                    "error",
                    "app_store.adminRecommendations",
                    409,
                )
            database.commit()
        return admin_response(
            "推荐顺序已更新", "success", "app_store.adminRecommendations"
        )

    app.register_blueprint(blueprint)
