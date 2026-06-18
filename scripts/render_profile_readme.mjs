/**
 * @file render_profile_readme
 * @project holic512 GitHub profile
 * @module Profile README / 图片渲染
 * @description 读取 JSON 数据与 HTML 模板，使用 Playwright 生成 README 首页 PNG。
 * @logic 1. 注入 data/profile-readme.json；2. 在 Chromium 中渲染 HTML；3. 截取 .profile-canvas 输出 assets/profile-readme.png。
 * @dependencies Package: playwright, File: templates/profile-readme.html, File: data/profile-readme.json
 * @index_tags Playwright, README 图片生成, HTML 转 PNG, GitHub Actions
 * @author holic512
 */

import { chromium } from "playwright";
import { readFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const templatePath = path.join(root, "templates", "profile-readme.html");
const dataPath = path.join(root, "data", "profile-readme.json");
const outputPath = path.join(root, "assets", "profile-readme.png");

async function main() {
  const [template, dataSource] = await Promise.all([
    readFile(templatePath, "utf8"),
    readFile(dataPath, "utf8")
  ]);
  const data = JSON.parse(dataSource);
  const html = template.replace("__PROFILE_DATA__", JSON.stringify(data).replace(/</g, "\\u003c"));

  await mkdir(path.dirname(outputPath), { recursive: true });

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({
      viewport: { width: 1080, height: 1740 },
      deviceScaleFactor: 2
    });
    await page.setContent(html, { waitUntil: "load" });
    const canvas = page.locator(".profile-canvas");
    await canvas.screenshot({
      path: outputPath,
      animations: "disabled"
    });
  } finally {
    await browser.close();
  }

  console.log(`Rendered ${path.relative(root, outputPath)}`);
}

await main();
