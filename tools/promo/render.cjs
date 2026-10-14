// 把 promo.html 逐帧渲染成 MP4。
//
//   python tools/promo/music.py                 # 先合成配乐 tools/promo/out/audio.wav
//   node tools/promo/render.cjs                 # 输出 tools/promo/out/djcat-pro-5-promo.mp4
//   node tools/promo/render.cjs --stills 5,17.5 # 只截几张静帧检查画面
//
// 需要 ffmpeg 与 Playwright（Chromium）；字体从 Google Fonts 加载，渲染时要能联网。
// 环境变量 FPS 可改帧率，默认 60。
const fs = require("node:fs");
const path = require("node:path");
const { spawn, execSync } = require("node:child_process");
const { pathToFileURL } = require("node:url");

function loadPlaywright() {
  try {
    return require("playwright");
  } catch {
    const globalRoot = execSync("npm root -g").toString().trim();
    return require(path.join(globalRoot, "playwright"));
  }
}

const ROOT = __dirname;
const OUT_DIR = path.join(ROOT, "out");
const FPS = Number(process.env.FPS || 60);

async function main() {
  const args = process.argv.slice(2);
  const stillsIndex = args.indexOf("--stills");
  const stills = stillsIndex >= 0 ? args[stillsIndex + 1].split(",").map(Number) : null;
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const { chromium } = loadPlaywright();
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
  const browser = await chromium.launch(proxy ? { proxy: { server: proxy } } : {});
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(path.join(ROOT, "promo.html")).href + "?render", { waitUntil: "networkidle" });

  // 字体按 unicode-range 分片懒加载：先把整条时间轴走一遍，让用到的分片都下载完。
  const duration = await page.evaluate(async () => {
    for (let t = 0; t < window.DURATION; t += 0.25) window.seek(t);
    await document.fonts.ready;
    return window.DURATION;
  });
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);

  if (stills) {
    for (const t of stills) {
      await page.evaluate(x => window.seek(x), t);
      const file = path.join(OUT_DIR, `still-${t.toFixed(2)}.png`);
      await page.screenshot({ path: file });
      console.log(file);
    }
    await browser.close();
    return;
  }

  const audio = path.join(OUT_DIR, "audio.wav");
  const output = path.join(OUT_DIR, "djcat-pro-5-promo.mp4");
  const ffArgs = ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-i", "-"];
  if (fs.existsSync(audio)) ffArgs.push("-i", audio);
  ffArgs.push(
    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
  );
  if (fs.existsSync(audio)) ffArgs.push("-c:a", "aac", "-b:a", "192k", "-shortest");
  ffArgs.push("-movflags", "+faststart", output);
  const ffmpeg = spawn("ffmpeg", ffArgs, { stdio: ["pipe", "inherit", "inherit"] });
  const finished = new Promise((resolve, reject) => {
    ffmpeg.on("close", code => (code === 0 ? resolve() : reject(new Error(`ffmpeg exited with ${code}`))));
  });

  const frames = Math.round(duration * FPS);
  const started = Date.now();
  for (let f = 0; f < frames; f++) {
    await page.evaluate(x => window.seek(x), f / FPS);
    const png = await page.screenshot({ type: "png" });
    if (!ffmpeg.stdin.write(png)) await new Promise(r => ffmpeg.stdin.once("drain", r));
    if (f % FPS === 0) {
      const elapsed = (Date.now() - started) / 1000;
      process.stdout.write(`\r${f}/${frames} frames, ${elapsed.toFixed(0)} s`);
    }
  }
  ffmpeg.stdin.end();
  await finished;
  await browser.close();
  console.log(`\n${output}`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
