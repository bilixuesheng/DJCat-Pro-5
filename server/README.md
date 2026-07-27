# AI Markdown 中转服务

服务端保存 DeepSeek 密钥并执行每日额度限制；桌面端只访问
`https://api.djcatpro.top/ai/markdown`。

```bash
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt

export DEEPSEEK_API_KEY="你的密钥"
export DJCATAI_RATE_LIMIT_SALT="固定的随机值"
export DJCATAI_DATABASE_PATH="/var/lib/djcat-ai/usage.sqlite3"

.venv/bin/gunicorn --workers 2 --threads 4 --bind 127.0.0.1:8000 server.ai_markdown:app
```

随机值只生成一次并固定保存：
`python3 -c 'import secrets; print(secrets.token_hex(32))'`。

生产环境请把环境变量放在仓库和网站目录之外、权限为 `600` 的服务配置文件中，
确保数据库目录可由服务账户写入，并通过 HTTPS 反向代理。Nginx 需要关闭流式响应
缓冲；可在 `http` 块增加按 IP 的突发请求保护：

```nginx
limit_req_zone $binary_remote_addr zone=djcat_ai:10m rate=1r/s;

location /ai/markdown {
    limit_req zone=djcat_ai burst=3 nodelay;
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 150s;
}
```
