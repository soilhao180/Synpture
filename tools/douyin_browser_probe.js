const fs = require("node:fs");
const path = require("node:path");

function parseArgs(argv) {
  const options = {
    shareUrl: "",
    profileDir: "Default",
    userDataDir: process.env.LOCALAPPDATA
      ? path.join(process.env.LOCALAPPDATA, "Google", "Chrome", "User Data")
      : "",
    outputDir: path.resolve("output", "douyin_browser_probe"),
    headless: false,
    timeoutMs: 30000,
  };

  for (let index = 2; index < argv.length; index += 1) {
    const current = argv[index];
    const next = argv[index + 1];
    if (current === "--share-url" && next) {
      options.shareUrl = next;
      index += 1;
    } else if (current === "--profile-dir" && next) {
      options.profileDir = next;
      index += 1;
    } else if (current === "--user-data-dir" && next) {
      options.userDataDir = next;
      index += 1;
    } else if (current === "--output-dir" && next) {
      options.outputDir = path.resolve(next);
      index += 1;
    } else if (current === "--headless") {
      options.headless = true;
    } else if (current === "--timeout-ms" && next) {
      options.timeoutMs = Number(next);
      index += 1;
    }
  }

  if (!options.shareUrl) {
    throw new Error("Missing required --share-url argument.");
  }
  if (!options.userDataDir) {
    throw new Error("Chrome user data directory could not be resolved.");
  }
  return options;
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
  return dirPath;
}

function summarizeCandidate(payload) {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const keys = Object.keys(payload);
  const text = JSON.stringify(payload);
  if (!/play_addr|video|aweme|detail|item/i.test(text)) {
    return null;
  }

  const summary = {
    keys: keys.slice(0, 20),
  };

  const container = payload.aweme_detail || payload.aweme || payload.data || payload.item_list || payload;
  if (container && typeof container === "object") {
    const video = container.video || (Array.isArray(container) ? container[0]?.video : null);
    const awemeId = container.aweme_id || container.awemeId || payload.aweme_id || null;
    summary.awemeId = awemeId;
    if (video && typeof video === "object") {
      const playAddr = video.play_addr || video.playAddr || null;
      const bitRate = video.bit_rate || video.bitRate || null;
      if (playAddr) {
        summary.playAddrKeys = Object.keys(playAddr).slice(0, 20);
        summary.playAddrUrlList =
          playAddr.url_list || playAddr.urlList || playAddr.data_size ? playAddr.url_list || playAddr.urlList || null : null;
      }
      if (Array.isArray(bitRate) && bitRate.length > 0) {
        const first = bitRate[0];
        const brPlayAddr = first.play_addr || first.playAddr || null;
        if (brPlayAddr && !summary.playAddrUrlList) {
          summary.playAddrUrlList = brPlayAddr.url_list || brPlayAddr.urlList || null;
        }
      }
    }
  }

  return summary;
}

async function main() {
  const options = parseArgs(process.argv);
  ensureDir(options.outputDir);

  const { chromium } = require("playwright");
  const chromeExecutable = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

  const networkEvents = [];
  let finalUrl = "";
  let finalTitle = "";
  let foundMediaUrls = [];

  const context = await chromium.launchPersistentContext(options.userDataDir, {
    executablePath: chromeExecutable,
    channel: "chrome",
    headless: options.headless,
    args: [`--profile-directory=${options.profileDir}`],
  });

  try {
    const page = context.pages()[0] || (await context.newPage());

    page.on("response", async (response) => {
      try {
        const url = response.url();
        const status = response.status();
        const headers = response.headers();
        const contentType = headers["content-type"] || "";
        const record = { url, status, contentType };

        if (/video|aweme|detail|item/i.test(url) || /json/i.test(contentType)) {
          if (/json/i.test(contentType)) {
            const text = await response.text();
            let parsed = null;
            try {
              parsed = JSON.parse(text);
            } catch {
              parsed = null;
            }
            const summary = summarizeCandidate(parsed);
            if (summary) {
              record.summary = summary;
              if (Array.isArray(summary.playAddrUrlList)) {
                foundMediaUrls = foundMediaUrls.concat(summary.playAddrUrlList);
              }
            } else {
              record.preview = text.slice(0, 300);
            }
          } else {
            record.location = headers.location || null;
          }
          networkEvents.push(record);
        }
      } catch (error) {
        networkEvents.push({
          url: response.url(),
          status: response.status(),
          error: String(error),
        });
      }
    });

    await page.goto(options.shareUrl, { waitUntil: "domcontentloaded", timeout: options.timeoutMs });
    await page.waitForTimeout(8000);

    finalUrl = page.url();
    finalTitle = await page.title();

    const html = await page.content();
    const htmlPath = path.join(options.outputDir, "page.html");
    fs.writeFileSync(htmlPath, html, "utf-8");

    const screenshotPath = path.join(options.outputDir, "page.png");
    await page.screenshot({ path: screenshotPath, fullPage: false });

    const report = {
      shareUrl: options.shareUrl,
      profileDir: options.profileDir,
      userDataDir: options.userDataDir,
      finalUrl,
      finalTitle,
      foundMediaUrls: Array.from(new Set(foundMediaUrls)),
      networkEvents,
      artifacts: {
        htmlPath,
        screenshotPath,
      },
    };

    const reportPath = path.join(options.outputDir, "report.json");
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf-8");
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await context.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
