const fs = require("node:fs");
const path = require("node:path");

function parseArgs(argv) {
  const options = {
    platform: "",
    shareUrl: "",
    profileDir: "",
    userDataDir: "",
    outputDir: path.resolve("output", "share_link_browser_probe"),
    headless: false,
    timeoutMs: 45000,
  };

  for (let index = 2; index < argv.length; index += 1) {
    const current = argv[index];
    const next = argv[index + 1];
    if (current === "--platform" && next) {
      options.platform = next;
      index += 1;
    } else if (current === "--share-url" && next) {
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
    } else if (current === "--timeout-ms" && next) {
      options.timeoutMs = Number(next);
      index += 1;
    } else if (current === "--headless") {
      options.headless = true;
    }
  }

  if (!options.platform) {
    throw new Error("Missing required --platform argument.");
  }
  if (!options.shareUrl) {
    throw new Error("Missing required --share-url argument.");
  }
  return options;
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
  return dirPath;
}

function normalizePlayUrl(entry) {
  if (!entry || typeof entry !== "object") {
    return null;
  }
  return (
    entry.baseUrl ||
    entry.base_url ||
    (Array.isArray(entry.backupUrl) ? entry.backupUrl[0] : null) ||
    (Array.isArray(entry.backup_url) ? entry.backup_url[0] : null) ||
    null
  );
}

function summarizeDouyinCandidate(payload) {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const text = JSON.stringify(payload);
  if (!/play_addr|video|aweme|detail|item/i.test(text)) {
    return null;
  }

  const container = payload.aweme_detail || payload.aweme || payload.data || payload.item_list || payload;
  const summary = { keys: Object.keys(payload).slice(0, 20) };
  if (container && typeof container === "object") {
    const video = container.video || (Array.isArray(container) ? container[0]?.video : null);
    summary.awemeId = container.aweme_id || container.awemeId || payload.aweme_id || null;
    if (video && typeof video === "object") {
      const playAddr = video.play_addr || video.playAddr || null;
      const bitRate = video.bit_rate || video.bitRate || null;
      if (playAddr) {
        summary.playAddrUrlList = playAddr.url_list || playAddr.urlList || null;
      }
      if (!summary.playAddrUrlList && Array.isArray(bitRate) && bitRate.length > 0) {
        const first = bitRate[0];
        const brPlayAddr = first.play_addr || first.playAddr || null;
        summary.playAddrUrlList = brPlayAddr?.url_list || brPlayAddr?.urlList || null;
      }
    }
  }
  return summary;
}

function chooseBilibiliStreams(playInfoPayload) {
  const dash = playInfoPayload?.data?.dash || {};
  const videos = Array.isArray(dash.video) ? dash.video.slice() : [];
  const audios = Array.isArray(dash.audio) ? dash.audio.slice() : [];

  videos.sort((left, right) => (right.width || 0) - (left.width || 0) || (right.bandwidth || 0) - (left.bandwidth || 0));
  audios.sort((left, right) => (right.bandwidth || 0) - (left.bandwidth || 0) || (right.id || 0) - (left.id || 0));

  const bestVideo = videos[0] || null;
  const bestAudio = audios[0] || null;
  return {
    bestVideoUrl: normalizePlayUrl(bestVideo),
    bestAudioUrl: normalizePlayUrl(bestAudio),
    videoCount: videos.length,
    audioCount: audios.length,
  };
}

function chooseBilibiliStreamsFromMediaCandidates(mediaCandidates) {
  const audioCandidates = mediaCandidates.filter((item) => /audio\//i.test(item.contentType || "") || /mime_type=audio/i.test(item.url));
  const videoCandidates = mediaCandidates.filter((item) => /video\//i.test(item.contentType || "") || /mime_type=video/i.test(item.url));
  return {
    bestAudioUrl: audioCandidates[0]?.url || null,
    bestVideoUrl: videoCandidates[0]?.url || null,
    audioCount: audioCandidates.length,
    videoCount: videoCandidates.length,
  };
}

async function main() {
  const options = parseArgs(process.argv);
  ensureDir(options.outputDir);

  const { chromium } = require("playwright");
  const chromeExecutable = process.env.SHARE_LINK_CHROME_EXE || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

  const mediaCandidates = [];
  const jsonCandidates = [];
  const douyinMediaUrls = [];
  let bilibiliPlayInfo = null;

  const usePersistentContext = Boolean(options.userDataDir);
  const launchOptions = {
    executablePath: chromeExecutable,
    headless: options.headless,
  };

  let browser = null;
  const context = usePersistentContext
    ? await chromium.launchPersistentContext(options.userDataDir, {
        ...launchOptions,
        args: options.profileDir ? [`--profile-directory=${options.profileDir}`] : [],
      })
    : await chromium.launch(launchOptions).then((launchedBrowser) => {
        browser = launchedBrowser;
        return browser.newContext({
          userAgent:
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
          locale: "zh-CN",
        });
      });

  try {
    const page = context.pages()[0] || (await context.newPage());

    page.on("response", async (response) => {
      const url = response.url();
      const status = response.status();
      const headers = response.headers();
      const contentType = headers["content-type"] || "";

      try {
        if (options.platform === "douyin") {
          if (/video|aweme|detail|item/i.test(url) || /json/i.test(contentType)) {
            const record = { url, status, contentType };
            if (/json/i.test(contentType)) {
              const text = await response.text();
              let parsed = null;
              try {
                parsed = JSON.parse(text);
              } catch {
                parsed = null;
              }
              const summary = summarizeDouyinCandidate(parsed);
              if (summary) {
                record.summary = summary;
                if (Array.isArray(summary.playAddrUrlList)) {
                  douyinMediaUrls.push(...summary.playAddrUrlList);
                }
              } else {
                record.preview = text.slice(0, 300);
              }
            } else {
              record.location = headers.location || null;
            }
            jsonCandidates.push(record);
          }
        }

        if (options.platform === "bilibili") {
          if (url.includes("/x/player/wbi/v2")) {
            const text = await response.text();
            const parsed = JSON.parse(text);
            bilibiliPlayInfo = parsed;
            jsonCandidates.push({ url, status, contentType, preview: text.slice(0, 500) });
          } else if (/json/i.test(contentType) && /api\.bilibili\.com/.test(url)) {
            const text = await response.text();
            jsonCandidates.push({ url, status, contentType, preview: text.slice(0, 500) });
          }
        }

        if (/\.m4s|mime_type=video_mp4|\/aweme\/v1\/play\/|video_mp4/i.test(url) || /video\/mp4|audio\/mp4|application\/octet-stream/i.test(contentType)) {
          mediaCandidates.push({ url, status, contentType, location: headers.location || null });
        }
      } catch (error) {
        jsonCandidates.push({
          url,
          status,
          contentType,
          error: String(error),
        });
      }
    });

    await page.goto(options.shareUrl, { waitUntil: "domcontentloaded", timeout: options.timeoutMs });
    await page.waitForTimeout(options.platform === "douyin" ? 8000 : 6000);

    const finalUrl = page.url();
    const finalTitle = await page.title();
    const htmlPath = path.join(options.outputDir, "page.html");
    const screenshotPath = path.join(options.outputDir, "page.png");

    fs.writeFileSync(htmlPath, await page.content(), "utf-8");
    await page.screenshot({ path: screenshotPath, fullPage: false });

    let bestVideoUrl = null;
    let bestAudioUrl = null;
    let bestMediaUrl = null;
    let extra = {};

    if (options.platform === "douyin") {
      const uniqueUrls = Array.from(new Set(douyinMediaUrls));
      bestMediaUrl = uniqueUrls[0] || null;
      extra = { foundMediaUrls: uniqueUrls };
    } else if (options.platform === "bilibili") {
      let pagePlayInfo = null;
      try {
        pagePlayInfo = await page.evaluate(() => {
          const payload = window.__playinfo__;
          if (!payload || typeof payload !== "object") {
            return null;
          }
          return JSON.parse(JSON.stringify(payload));
        });
      } catch (error) {
        pagePlayInfo = null;
      }

      const selectedFromPage = chooseBilibiliStreams(pagePlayInfo);
      const selectedFromNetwork = chooseBilibiliStreams(bilibiliPlayInfo);
      const selectedFromMedia = chooseBilibiliStreamsFromMediaCandidates(mediaCandidates);
      const selected =
        selectedFromPage.bestAudioUrl || selectedFromPage.bestVideoUrl
          ? selectedFromPage
          : selectedFromNetwork.bestAudioUrl || selectedFromNetwork.bestVideoUrl
            ? selectedFromNetwork
            : selectedFromMedia;

      bestVideoUrl = selected.bestVideoUrl;
      bestAudioUrl = selected.bestAudioUrl;
      bestMediaUrl = bestAudioUrl || bestVideoUrl;
      extra = {
        playInfoSummary: {
          videoCount: selected.videoCount,
          audioCount: selected.audioCount,
        },
        playInfoSource:
          selected === selectedFromPage
            ? "window.__playinfo__"
            : selected === selectedFromNetwork
              ? "network_response"
              : "media_candidates",
      };
    }

    const report = {
      platform: options.platform,
      shareUrl: options.shareUrl,
      profileDir: options.profileDir || null,
      userDataDir: options.userDataDir || null,
      finalUrl,
      finalTitle,
      bestMediaUrl,
      bestVideoUrl,
      bestAudioUrl,
      mediaCandidates,
      jsonCandidates,
      artifacts: {
        htmlPath,
        screenshotPath,
      },
      ...extra,
    };

    const reportPath = path.join(options.outputDir, "report.json");
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf-8");
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await context.close();
    if (browser) {
      await browser.close();
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
