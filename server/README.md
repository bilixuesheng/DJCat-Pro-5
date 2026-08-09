# AI Markdown 服务与管理面板

同一个 Flask 服务提供：

- `api.djcatpro.top/ai/markdown`：桌面端 API；
- `dash.djcatpro.top/admin/`：管理面板；
- 每台机器每日额度、高峰双倍扣除、匿名机器注册和请求统计；
- 使用 Fernet 加密保存的 DeepSeek API Key。

## 安装

```bash
cd /www/wwwroot/djcat-ai
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
install -d -o www -g www -m 700 /www/server/data/djcat-ai
```

生成管理员密码哈希、Session 密钥、设置加密密钥和机器限额盐：

```bash
.venv/bin/python -c "from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass('管理员密码: ')))"
.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
```

在宝塔 Python 项目的环境变量中逐行配置：

```text
DJCATAI_DATABASE_PATH=/www/server/data/djcat-ai/usage.sqlite3
DJCATAI_RATE_LIMIT_SALT=最后一条命令生成的固定随机值
DJCATAI_ADMIN_HOST=dash.djcatpro.top
DJCATAI_ADMIN_USERNAME=管理员用户名
DJCATAI_ADMIN_PASSWORD_HASH=第一条命令生成的完整哈希
DJCATAI_ADMIN_SESSION_SECRET=第二条命令生成的随机值
DJCATAI_SETTINGS_KEY=第三条命令生成的Fernet密钥
```

`DJCATAI_RATE_LIMIT_SALT` 和 `DJCATAI_SETTINGS_KEY` 不能随意更换：前者决定机器匿名指纹，后者用于解密面板保存的 API Key。环境文件应放在网站目录外并限制为 `600` 权限。

Gunicorn 示例：

```bash
.venv/bin/gunicorn --workers 2 --threads 4 --bind 127.0.0.1:18080 ai_markdown:app
```

首次进入面板后，在“AI 配置”中填写 API Key、模型、每日额度和高峰开关。也可以保留 `DEEPSEEK_API_KEY` 环境变量作为回退值。

## Nginx

`api.djcatpro.top` 原有站点继续把 `/ai/markdown` 反代到 `127.0.0.1:18080`，并保持 `proxy_buffering off`。

在宝塔中新建 `dash.djcatpro.top` 站点、申请 SSL 后，将其反向代理配置为：

```nginx
location / {
    proxy_pass http://127.0.0.1:18080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 150s;
}
```

登录接口建议再加一层 Nginx 限速。先把下面这行放进 Nginx 主配置的
`http {}` 内（宝塔“软件商店 → Nginx → 配置修改”）：

```nginx
limit_req_zone $binary_remote_addr zone=djcat_admin_login:10m rate=5r/m;
```

再把下面的 `location` 放进 `dash.djcatpro.top` 站点配置的 `server {}` 内：

```nginx
location = /admin/login {
    limit_req zone=djcat_admin_login burst=5 nodelay;
    proxy_pass http://127.0.0.1:18080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

完成后重启 Python 项目，无需把 `18080` 端口开放到公网。

## 公网防滥用边界

机器码用于匿名额度统计，不是不可伪造的许可证。开源客户端中的任何固定密钥都能被提取，恶意调用者仍可能伪造新的机器标识。公网部署时应在 Nginx 或 Cloudflare 对 `POST /ai/markdown` 和注册接口增加符合实际机器数量的 IP/WAF 速率限制；若需要严格阻止额度绕过，则必须增加账号、授权码或人工审批注册，单靠机器码无法做到。

## 应用市场

同一 Flask 服务还提供：

- `https://api.djcatpro.top/app-store/catalog`：桌面端使用的公开只读目录；
- `https://dash.djcatpro.top/admin/app-store/apps/`：软件和主页预设卡片管理；
- `https://dash.djcatpro.top/admin/app-store/ads/`：广告管理。

下载、图标和广告地址必须使用 HTTPS。程序动作只能填写应用安装目录内的相对 `.exe` 路径，参数在后台按一行一个填写；网址动作只允许 HTTPS。应用的安装目录名创建后不能在后台修改，若需更换目录应新建应用记录。
