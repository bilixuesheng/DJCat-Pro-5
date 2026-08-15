"""Application catalog and administration routes.

The catalog is kept separate from the AI tables so existing deployments can
enable the marketplace without a data migration that rewrites old records.
"""

import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, abort, jsonify, redirect, render_template, request


ARCHITECTURES = ("x86_64", "arm64")
_INSTALL_DIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")
_DOWNLOAD_TOKEN = re.compile(r"^[a-f0-9]{32}$")
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


def _apiHost():
    return os.environ.get("DJCATAI_API_HOST", "api.djcatpro.top").lower()


def _hostOnly():
    return request.host.partition(":")[0].lower()


def _safeUrl(value, *, httpsOnly=True):
    value = (value or "").strip()
    parsed = urlparse(value)
    if httpsOnly and parsed.scheme != "https":
        return ""
    if not parsed.netloc or parsed.username or parsed.password:
        return ""
    return value


def _safeAction(actionType, target, arguments=""):
    actionType = (actionType or "").strip().lower()
    target = (target or "").strip()
    if actionType == "program":
        if (
            not target.lower().endswith(".exe")
            or target.startswith(("/", "\\"))
            or ":" in target
        ):
            return None
        if any(part in {"", ".", ".."} for part in target.replace("\\", "/").split("/")):
            return None
        if len(target) > 240:
            return None
    elif actionType == "url":
        target = _safeUrl(target)
        if not target:
            return None
    elif actionType == "uri":
        scheme = urlparse(target).scheme.lower()
        if not scheme or scheme in _DANGEROUS_SCHEMES:
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
    return {
        "type": actionType,
        "target": target,
        "arguments": parsedArguments,
    }


def _formArguments(actionType, value):
    if actionType != "program":
        return "{}"
    value = (value or "").strip()
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
    return _safeAction(actionType, target, _formArguments(actionType, arguments))


def _ensureSchema(connect):
    with closing(connect()) as database:
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
                announcement TEXT NOT NULL DEFAULT '',
                open_action_type TEXT,
                open_action_target TEXT,
                open_action_arguments TEXT NOT NULL DEFAULT '{}',
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
            CREATE TABLE IF NOT EXISTS market_advertisements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL,
                app_id INTEGER REFERENCES market_applications(id) ON DELETE SET NULL,
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
        database.commit()


def marketplaceStats(connect, day):
    """Return marketplace totals for the dashboard without changing catalog data."""

    _ensureSchema(connect)
    with closing(connect()) as database:
        todayDownloads = database.execute(
            "SELECT COUNT(*) FROM market_download_events "
            "WHERE date(downloaded_at, '+8 hours') = ?",
            (day,),
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


def _appPayload(database, row):
    packages = database.execute(
        "SELECT architecture, enabled FROM market_packages WHERE app_id = ?",
        (row["id"],),
    ).fetchall()
    presets = database.execute(
        """
        SELECT id, title, description, action_type, action_target, action_arguments
        FROM market_presets WHERE app_id = ? ORDER BY sort_order, id
        """,
        (row["id"],),
    ).fetchall()
    packageMap = {
        package["architecture"]: {"enabled": bool(package["enabled"])}
        for package in packages
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
        "announcement": row["announcement"] or "",
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
        return None, {"packages": {}, "open_action_arguments": ""}
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
                "SELECT * FROM market_applications ORDER BY recommended DESC, name COLLATE NOCASE"
            ).fetchall()
            apps = [_appPayload(database, row) for row in rows]
            ads = [
                {
                    "id": ad["id"],
                    "title": ad["title"],
                    "description": ad["description"],
                    "image_url": ad["image_url"],
                    "app_id": ad["app_id"],
                }
                for ad in database.execute(
                    """
                    SELECT id, title, description, image_url, app_id
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
            rangeHeader = request.headers.get("Range", "").strip()
            token = request.args.get("token", "").strip().lower()
            shouldCount = not rangeHeader or rangeHeader == "bytes=1-1"
            if _DOWNLOAD_TOKEN.fullmatch(token):
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
                    "UPDATE market_applications SET download_count = download_count + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (app_id,),
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
                "SELECT * FROM market_applications ORDER BY updated_at DESC, id DESC"
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

    def _renderApp(appId):
        _ensureSchema(connect)
        with closing(connect()) as database:
            row, form = _adminFormData(database, appId)
        if appId is not None and row is None:
            abort(404)
        return render_template(
            "admin_app_store_app.html",
            csrf_token=csrf_token(),
            current_page="app_store_apps",
            app=row,
            form=form,
            architectures=ARCHITECTURES,
        )

    def _saveApp(appId):
        check_csrf()
        values = {
            "name": request.form.get("name", "").strip(),
            "developer": request.form.get("developer", "").strip(),
            "description": request.form.get("description", "").strip(),
            "version": request.form.get("version", "").strip(),
            "icon_url": _safeUrl(request.form.get("icon_url"), httpsOnly=True),
            "install_dir": request.form.get("install_dir", "").strip(),
            "recommended": 1 if request.form.get("recommended") else 0,
            "announcement": request.form.get("announcement", "").strip(),
        }
        errors = []
        if not values["name"]:
            errors.append("软件名称不能为空")
        if not values["version"]:
            errors.append("软件版本不能为空")
        if not _INSTALL_DIR.fullmatch(values["install_dir"]):
            errors.append("安装目录只能包含字母、数字、空格、点、下划线和短横线")
        if request.form.get("icon_url", "").strip() and not values["icon_url"]:
            errors.append("图标链接必须是 HTTPS 地址")
        actionType = request.form.get("open_action_type", "").strip().lower()
        action = _formAction(
            actionType,
            request.form.get("open_action_target"),
            request.form.get("open_action_arguments", ""),
        )
        if actionType and not action:
            errors.append("打开动作配置无效")
        packages = {}
        for architecture in ARCHITECTURES:
            url = _safeUrl(request.form.get(f"{architecture}_url"), httpsOnly=True)
            enabled = bool(request.form.get(f"{architecture}_enabled"))
            if enabled and not url:
                errors.append(f"{architecture} 安装包启用时必须填写 HTTPS 链接")
            if url:
                packages[architecture] = (enabled, url)
        if errors:
            for error in errors:
                from flask import flash

                flash(error, "error")
            return _renderApp(appId), 400
        _ensureSchema(connect)
        with closing(connect()) as database:
            try:
                database.execute("BEGIN IMMEDIATE")
                if appId is None:
                    cursor = database.execute(
                        """
                        INSERT INTO market_applications
                        (name, developer, description, version, icon_url, install_dir,
                         recommended, announcement, open_action_type, open_action_target,
                         open_action_arguments)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            values["name"], values["developer"], values["description"],
                            values["version"], values["icon_url"], values["install_dir"],
                            values["recommended"], values["announcement"],
                            action["type"] if action else None,
                            action["target"] if action else None,
                            json.dumps(action["arguments"] if action else {}, ensure_ascii=False),
                        ),
                    )
                    appId = cursor.lastrowid
                else:
                    database.execute(
                        """
                        UPDATE market_applications SET name=?, developer=?, description=?,
                        version=?, icon_url=?, install_dir=?, recommended=?, announcement=?,
                        open_action_type=?, open_action_target=?, open_action_arguments=?,
                        updated_at=CURRENT_TIMESTAMP WHERE id=?
                        """,
                        (
                            values["name"], values["developer"], values["description"],
                            values["version"], values["icon_url"], values["install_dir"],
                            values["recommended"], values["announcement"],
                            action["type"] if action else None,
                            action["target"] if action else None,
                            json.dumps(action["arguments"] if action else {}, ensure_ascii=False),
                            appId,
                        ),
                    )
                    database.execute("DELETE FROM market_packages WHERE app_id = ?", (appId,))
                database.executemany(
                    "INSERT INTO market_packages(app_id, architecture, enabled, download_url) VALUES (?, ?, ?, ?)",
                    [(appId, architecture, int(enabled), url) for architecture, (enabled, url) in packages.items()],
                )
                database.commit()
            except sqlite3.IntegrityError as error:
                database.rollback()
                return admin_response(
                    f"保存失败：{error}",
                    "error",
                    "app_store.adminApps",
                    400,
                )
        return admin_response("软件信息已保存", "success", "app_store.adminApps")

    @blueprint.post("/admin/app-store/apps/<int:app_id>/delete")
    @login_required
    def adminDeleteApp(app_id):
        check_csrf()
        _ensureSchema(connect)
        with closing(connect()) as database:
            database.execute("DELETE FROM market_applications WHERE id = ?", (app_id,))
            database.commit()
        return admin_response("软件已删除", "success", "app_store.adminApps")

    def _renderPresets():
        _ensureSchema(connect)
        with closing(connect()) as database:
            rows = database.execute(
                """
                SELECT p.*, a.name AS app_name
                FROM market_presets p
                JOIN market_applications a ON a.id = p.app_id
                ORDER BY a.name COLLATE NOCASE, p.sort_order, p.id
                """
            ).fetchall()
            apps = database.execute(
                "SELECT id, name FROM market_applications ORDER BY name COLLATE NOCASE"
            ).fetchall()
        presets = []
        for row in rows:
            preset = dict(row)
            preset["action_arguments"] = _argumentsText(preset["action_arguments"])
            presets.append(preset)
        return render_template(
            "admin_app_store_presets.html",
            csrf_token=csrf_token(),
            current_page="app_store_presets",
            presets=presets,
            apps=apps,
        )

    @blueprint.route("/admin/app-store/presets/", methods=["GET", "POST"])
    @login_required
    def adminPresets():
        if request.method == "POST":
            return _savePreset(None)
        return _renderPresets()

    @blueprint.post("/admin/app-store/presets/<int:preset_id>")
    @login_required
    def adminPreset(preset_id):
        return _savePreset(preset_id)

    def _savePreset(presetId):
        check_csrf()
        title = request.form.get("preset_title", "").strip()
        description = request.form.get("preset_description", "").strip()
        actionType = request.form.get("preset_action_type", "").strip().lower()
        action = _formAction(
            actionType,
            request.form.get("preset_action_target"),
            request.form.get("preset_action_arguments", ""),
        )
        try:
            appId = int(request.form.get("preset_app_id"))
            sortOrder = int(request.form.get("preset_sort_order", "0"))
        except (TypeError, ValueError):
            appId, sortOrder = None, 0
        if request.form.get("delete"):
            _ensureSchema(connect)
            with closing(connect()) as database:
                database.execute("DELETE FROM market_presets WHERE id = ?", (presetId,))
                database.commit()
            return admin_response("预设卡片已删除", "success", "app_store.adminPresets")
        errors = []
        if appId is None:
            errors.append("请选择软件")
        if not title:
            errors.append("卡片标题不能为空")
        if not action:
            errors.append("预设卡片动作配置无效")
        if errors:
            return admin_response("；".join(errors), "error", "app_store.adminPresets", 400)
        _ensureSchema(connect)
        with closing(connect()) as database:
            if not database.execute("SELECT 1 FROM market_applications WHERE id = ?", (appId,)).fetchone():
                return admin_response("选择的软件不存在", "error", "app_store.adminPresets", 400)
            values = (
                appId,
                title[:80],
                description[:240],
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
            else:
                database.execute(
                    """
                    UPDATE market_presets SET app_id=?, title=?, description=?, action_type=?,
                    action_target=?, action_arguments=?, sort_order=? WHERE id=?
                    """,
                    values + (presetId,),
                )
                message = "预设卡片已保存"
            database.commit()
        return admin_response(message, "success", "app_store.adminPresets")

    @blueprint.route("/admin/app-store/ads/", methods=["GET", "POST"])
    @login_required
    def adminAds():
        if request.method == "POST":
            check_csrf()
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            imageUrl = _safeUrl(request.form.get("image_url"), httpsOnly=True)
            try:
                appId = int(request.form.get("app_id")) if request.form.get("app_id") else None
                sortOrder = int(request.form.get("sort_order", "0"))
            except ValueError:
                appId, sortOrder = None, 0
            if not title or not imageUrl:
                return admin_response("广告标题和 HTTPS 图片链接不能为空", "error", "app_store.adminAds", 400)
            _ensureSchema(connect)
            with closing(connect()) as database:
                if not _applicationExists(database, appId):
                    return admin_response(
                        "绑定的软件不存在",
                        "error",
                        "app_store.adminAds",
                        400,
                    )
                database.execute(
                    "INSERT INTO market_advertisements(title, description, image_url, app_id, sort_order, enabled) VALUES (?, ?, ?, ?, ?, ?)",
                    (title, description, imageUrl, appId, sortOrder, int(bool(request.form.get("enabled")))),
                )
                database.commit()
            return admin_response("广告已新增", "success", "app_store.adminAds")
        _ensureSchema(connect)
        with closing(connect()) as database:
            ads = database.execute(
                """
                SELECT ad.*, a.name AS app_name FROM market_advertisements ad
                LEFT JOIN market_applications a ON a.id = ad.app_id
                ORDER BY ad.sort_order, ad.id
                """
            ).fetchall()
            apps = database.execute("SELECT id, name FROM market_applications ORDER BY name COLLATE NOCASE").fetchall()
        return render_template(
            "admin_app_store_ads.html",
            csrf_token=csrf_token(),
            current_page="app_store_ads",
            ads=ads,
            apps=apps,
        )

    @blueprint.post("/admin/app-store/ads/<int:ad_id>")
    @login_required
    def adminAd(ad_id):
        check_csrf()
        if request.form.get("delete"):
            with closing(connect()) as database:
                database.execute("DELETE FROM market_advertisements WHERE id = ?", (ad_id,))
                database.commit()
            return admin_response("广告已删除", "success", "app_store.adminAds")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        imageUrl = _safeUrl(request.form.get("image_url"), httpsOnly=True)
        try:
            appId = int(request.form.get("app_id")) if request.form.get("app_id") else None
            sortOrder = int(request.form.get("sort_order", "0"))
        except ValueError:
            appId, sortOrder = None, 0
        if not title or not imageUrl:
            return admin_response("广告标题和 HTTPS 图片链接不能为空", "error", "app_store.adminAds", 400)
        with closing(connect()) as database:
            if not _applicationExists(database, appId):
                return admin_response(
                    "绑定的软件不存在",
                    "error",
                    "app_store.adminAds",
                    400,
                )
            database.execute(
                "UPDATE market_advertisements SET title=?, description=?, image_url=?, app_id=?, sort_order=?, enabled=? WHERE id=?",
                (title, description, imageUrl, appId, sortOrder, int(bool(request.form.get("enabled"))), ad_id),
            )
            database.commit()
        return admin_response("广告已保存", "success", "app_store.adminAds")

    app.register_blueprint(blueprint)
