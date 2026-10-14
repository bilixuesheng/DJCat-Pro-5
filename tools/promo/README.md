# 宣传片

电教猫 Pro 5 的 16:9 宣传片（1920 × 1080，60 fps，约 47 秒），成片是 [`djcat-pro-5-promo.mp4`](djcat-pro-5-promo.mp4)。画面是一张 HTML 动画页，逐帧截图后用 ffmpeg 合成；配乐和音效由脚本合成，考试倒计时一段用的是软件自带的 15 分钟提醒 `app/assets/15.wav`。

| 时间 | 场景 |
|:--|:--|
| 0–4 s | 痛点：通知上大屏、考试倒计时、铃声准点响 |
| 4–8 s | Logo 与标语「为电教工作提效增色」 |
| 8–13 s | 主页与自定义卡片的动作序列 |
| 13–21 s | 全屏投送：输入正文 → AI 整理 → 全屏展示 |
| 21–28 s | 考试倒计时：跳到 15 分钟时响起提醒，再切到窗口化 |
| 28–33 s | 定时播报、自动任务、定时关机依次触发 |
| 33–38 s | 应用市场：下载进度环 → 安装中 → 打开 |
| 38–42 s | 便携模式、触控、托盘、设置搜索等细节 |
| 42–47 s | 结尾：下载地址与交流群 |

## 预览

直接用浏览器打开 `promo.html` 即可循环播放（没有声音）；加 `?t=21` 从第 21 秒开始。

## 渲染

需要 Python（numpy）、Node.js、Playwright 的 Chromium 和 ffmpeg；字体从 Google Fonts 加载，渲染时要能联网。

```bash
python tools/promo/music.py        # 配乐 → tools/promo/out/audio.wav
node tools/promo/render.cjs        # 视频 → tools/promo/out/djcat-pro-5-promo.mp4
node tools/promo/render.cjs --stills 10,17.5   # 只截几张静帧检查画面
```

`FPS=30 node tools/promo/render.cjs` 可以降低帧率加快渲染。改完画面或配乐后，把 `out/` 里的新成片复制到本目录覆盖旧的。

## 修改时间轴

画面的时间写在 `promo.html` 各元素的 `animation` 延迟和脚本里的常量上，配乐的时间点写在 `music.py` 的 `CUES` 里，两边要一起改。

图标来自 [Fluent UI System Icons](https://github.com/microsoft/fluentui-system-icons)（MIT），已内嵌在 `icons.js`。
