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
install -d -o www -g www -m 700 /www/wwwroot/djcat-ai/data
chown -R www:www /www/wwwroot/djcat-ai
```

项目目录和 `.venv` 都要归运行服务的 `www` 所有，后台的「服务端更新」才能替换代码、安装依赖。`data/` 在项目目录里，但 Nginx 只把请求反代给 gunicorn，不把项目目录当静态文件提供，外网访问不到；Server Update 也从不碰它。

生成管理员密码哈希、Session 密钥、设置加密密钥和机器限额盐：

```bash
.venv/bin/python -c "from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass('管理员密码: ')))"
.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
```

在宝塔 Python 项目的环境变量中逐行配置：

```text
DJCATAI_DATABASE_PATH=/www/wwwroot/djcat-ai/data/usage.sqlite3
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

不要开 `--preload`（`preload_app`）：Server Update 靠给 gunicorn 主进程发 `SIGHUP` 换上新代码，预加载时新 worker 不会重新导入。

首次进入面板后，在“AI 配置”中填写 API Key、模型、每日额度和高峰开关。也可以保留 `DEEPSEEK_API_KEY` 环境变量作为回退值。

## 服务端更新

服务端有自己的版本号 Server Version，写在 `server/version.py`，和客户端版本各自编号。把改了版本号的代码合并进 main，就算发布了一个新版本；只改代码不改版本号，后台不会提示更新。为什么这样设计，见 `docs/adr/0006-server-self-update.md`。

在后台「系统 → 服务端更新」点「检查更新」，服务端从 GitHub 读取 main 上的版本号，比已安装的高就列出这之间改过 `server/` 的提交。点「更新」后依次：

1. 下载检查时读到的那个提交的压缩包，只取 `server/`；
2. `requirements.txt` 有变化时，以 `www` 身份把依赖装进 `.venv`；
3. 用新代码连一份数据库副本试导入，失败就放弃；
4. 把数据库备份到数据库旁边的 `server-update/`（只留最近 3 份），当前代码存为「上一版本」；
5. 逐个替换文件，并删掉上一版装过、新版已经没有的文件；
6. 回应页面之后给 gunicorn 主进程发 `SIGHUP`，页面等新 worker 报出新版本再刷新。

任何一步失败，旧代码都原样保留、继续运行。`.venv`、`data/`、`gunicorn_conf.py`、`uwsgi.ini`、`server.zip` 和 `__pycache__` 永远不碰。新版本若升级了 gunicorn 本身，还要到宝塔面板重启一次项目。

服务器需要能访问 `api.github.com`、`codeload.github.com` 和 PyPI。

回滚把当前版本和上一版本对调，不还原数据库，也不降级依赖。后台打不开时在终端回滚，再到宝塔面板重启项目：

```bash
cd /www/wwwroot/djcat-ai
sudo -u www DJCATAI_DATABASE_PATH=/www/wwwroot/djcat-ai/data/usage.sqlite3 .venv/bin/python server_update.py rollback
```

数据库坏了才需要用备份：先在宝塔面板停止项目，把 `data/server-update/` 里最新的 `database-*.sqlite3` 复制回 `data/usage.sqlite3`，再启动。

第一次使用这个功能的版本（1.4.8）要手动部署：把 `server/` 的内容上传到项目目录覆盖，再到宝塔面板重启项目。之后的版本都在后台更新。

## 应用市场双域名部署

应用市场与管理后台共用一个 Gunicorn 进程，但由 Host 和 Nginx 分域：

- `api.djcatpro.top`：客户端应用目录、广告和下载跳转 API。
- `dash.djcatpro.top`：登录后的软件/广告管理页面。

在服务端环境变量中补充：

```text
DJCATAI_API_HOST=api.djcatpro.top
```

`api.djcatpro.top` 的站点配置需要代理应用市场路径（以及原有 AI API）：

```nginx
location ^~ /app-store/ {
    proxy_pass http://127.0.0.1:18080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 150s;
}

location ^~ /ai/ {
    proxy_pass http://127.0.0.1:18080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 150s;
}
```

`dash.djcatpro.top` 保留已有的 `location /` 代理和登录限速配置。两个站点都应传递 `$host`，不要把 Host 固定为 `127.0.0.1`，否则应用层无法隔离域名。

部署前先备份 SQLite 数据库。SHA-256 是可选的：已有校验值会在客户端下载后核对，留空不会阻断发布或下载。新版首次连接旧库会自动增加可选字段。随后重启 Gunicorn，分别在两个站点执行 `nginx -t`，通过后执行 `systemctl reload nginx`。确认 `18080` 只监听 `127.0.0.1`。

客户端发版顺序固定为：先部署兼容服务端，再构建并上传两种架构的安装包及 `.sha256`，确认 Release 六个附件完整且摘要校验通过，最后才把 beta 更新接口切换到新版本。不要先更新 beta API，否则旧服务端或缺失资产会让客户端拿到不可安装的更新。

上线后的最小检查：

```bash
curl -i https://api.djcatpro.top/app-store/catalog
curl -i https://dash.djcatpro.top/app-store/catalog   # 应为 404
curl -i https://api.djcatpro.top/admin/               # 应为 404
curl -I https://dash.djcatpro.top/admin/login
```

后台新增软件时，安装包、图标和广告图片必须填写 HTTPS 地址。客户端下载请求先访问 `api.djcatpro.top` 的下载接口，再由接口 302 到安装包地址；下载次数在 302 前原子递增。

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
