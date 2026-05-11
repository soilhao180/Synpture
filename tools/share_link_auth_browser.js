const path = require("node:path");

function parseArgs(argv) {
  const options = {
    platform: "",
    userDataDir: "",
    startUrl: "",
  };

  for (let index = 2; index < argv.length; index += 1) {
    const current = argv[index];
    const next = argv[index + 1];
    if (current === "--platform" && next) {
      options.platform = next;
      index += 1;
    } else if (current === "--user-data-dir" && next) {
      options.userDataDir = path.resolve(next);
      index += 1;
    } else if (current === "--start-url" && next) {
      options.startUrl = next;
      index += 1;
    }
  }

  if (!options.platform) {
    throw new Error("Missing required --platform argument.");
  }
  if (!options.userDataDir) {
    throw new Error("Missing required --user-data-dir argument.");
  }
  if (!options.startUrl) {
    throw new Error("Missing required --start-url argument.");
  }
  return options;
}

async function main() {
  const options = parseArgs(process.argv);
  const { chromium } = require("playwright");
  const chromeExecutable = process.env.SHARE_LINK_CHROME_EXE || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

  const context = await chromium.launchPersistentContext(options.userDataDir, {
    executablePath: chromeExecutable,
    headless: false,
    args: ["--start-maximized"],
    viewport: null,
  });

  try {
    const page = context.pages()[0] || (await context.newPage());
    await page.goto(options.startUrl, { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => null);
    await new Promise((resolve) => {
      context.on("close", resolve);
    });
  } finally {
    await context.close().catch(() => null);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
