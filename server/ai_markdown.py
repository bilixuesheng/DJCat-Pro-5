import hashlib
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request, stream_with_context

DAILY_LIMIT = 15
MAX_CONTENT_LENGTH = 12_000
MAX_CUSTOM_STYLE_LENGTH = 4_000
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


def _systemPrompt(customStyle):
    customStyle = customStyle.strip()
    if not customStyle:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}{CUSTOM_STYLE_PREFIX}{customStyle}"


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


def _quotaCost(now=None):
    hour = (now or datetime.now(TIMEZONE)).astimezone(TIMEZONE).hour
    return 2 if any(start <= hour < end for start, end in PEAK_HOURS) else 1


def _connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(DATABASE_PATH, timeout=10)
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS usage (
            day TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY (day, machine_id)
        )
        """
    )
    return database


def _remaining(machineId):
    with closing(_connect()) as database:
        row = database.execute(
            "SELECT count FROM usage WHERE day = ? AND machine_id = ?",
            (_today(), machineId),
        ).fetchone()
    return max(0, DAILY_LIMIT - (row[0] if row else 0))


def _claim(machineId, cost):
    day = _today()
    with closing(_connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute(
            "SELECT count FROM usage WHERE day = ? AND machine_id = ?",
            (day, machineId),
        ).fetchone()
        count = row[0] if row else 0
        if count + cost > DAILY_LIMIT:
            database.rollback()
            return -1

        database.execute(
            """
            INSERT INTO usage (day, machine_id, count) VALUES (?, ?, ?)
            ON CONFLICT(day, machine_id) DO UPDATE SET count = count + excluded.count
            """,
            (day, machineId, cost),
        )
        database.commit()
    return DAILY_LIMIT - count - cost


def _refund(machineId, cost):
    with closing(_connect()) as database:
        database.execute(
            """
            UPDATE usage SET count = count - ?
            WHERE day = ? AND machine_id = ? AND count >= ?
            """,
            (cost, _today(), machineId, cost),
        )
        database.commit()


def _error(message, status):
    response = jsonify({"message": message})
    response.status_code = status
    return response


@app.get("/ai/markdown/quota")
def quota():
    try:
        machineId = _machineId(request.args.get("machine_id"))
        return jsonify(
            {
                "remaining": _remaining(machineId),
                "limit": DAILY_LIMIT,
                "cost": _quotaCost(),
            }
        )
    except ValueError as error:
        return _error(str(error), 400)
    except RuntimeError as error:
        return _error(str(error), 503)


@app.post("/ai/markdown")
def convert():
    apiKey = os.environ.get("DEEPSEEK_API_KEY")
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

    cost = _quotaCost()
    remaining = _claim(machineId, cost)
    if remaining < 0:
        remaining = _remaining(machineId)
        message = (
            "当前为双倍时段，剩余额度不足，请在非双倍时段再试。"
            if remaining
            else "今天的转换额度已用完，请明天再试。"
        )
        response = _error(message, 429)
        response.headers["X-RateLimit-Limit"] = str(DAILY_LIMIT)
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
                "model": "deepseek-v4-flash",
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
        _refund(machineId, cost)
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
            if not completed:
                _refund(machineId, cost)
            upstream.close()

    return Response(
        stream(),
        content_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-RateLimit-Limit": str(DAILY_LIMIT),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Cost": str(cost),
        },
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
