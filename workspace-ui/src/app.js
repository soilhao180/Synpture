const DEFAULT_VIEW = "share_link";
const FORCE_WORKSPACE_ENTRY = new URLSearchParams(window.location.search).get("enterWorkspace") === "1";

const THEME_STORAGE_KEY = "synpture-theme-preference";

const THEME_OPTIONS = [
  { id: "system", label: "跟随系统" },
  { id: "light", label: "浅色模式" },
  { id: "dark", label: "深色模式" },
];

const TOOL_VIEWS = [
  { id: "share_link", label: "分享链接" },
  { id: "local_media", label: "本地媒体" },
  { id: "text_input", label: "文本输入" },
  { id: "recovery", label: "恢复项目" },
];

const VIEW_CONTENT = {
  share_link: {
    eyebrow: "采集",
    title: "分享链接接入",
    description: "左侧是授权入口，右侧是链接输入与执行入口。",
  },
  local_media: {
    eyebrow: "采集",
    title: "本地媒体上传",
    description: "上传本地音视频文件后，启动转录与整理流程。",
  },
  text_input: {
    eyebrow: "采集",
    title: "文本输入",
    description: "支持文本文件上传与直接粘贴两种输入方式。",
  },
  recovery: {
    eyebrow: "恢复",
    title: "恢复项目",
    description: "打开已有项目，或从上传的目录中恢复继续处理。",
  },
};

const TOOL_IDLE_PROGRESS = {
  share_link: {
    title: "当前进度",
    phaseLabel: "等待输入分享链接",
    subtitle: "输入有效链接后即可开始执行。",
    progressPercent: 0,
    detailLines: ["授权入口已就位，输入有效链接后即可创建新项目任务。"],
    history: [],
  },
  local_media: {
    title: "当前进度",
    phaseLabel: "等待选择本地媒体文件",
    subtitle: "选择音视频文件后即可启动转录整理流程。",
    progressPercent: 0,
    detailLines: ["先选择音视频文件，处理成功后会自动切换到项目工作区。"],
    history: [],
  },
  text_input: {
    title: "当前进度",
    phaseLabel: "等待输入文本内容",
    subtitle: "上传文本文件或直接粘贴内容后即可开始执行。",
    progressPercent: 0,
    detailLines: ["可上传文本文件或直接粘贴内容，随后进入结构化整理流程。"],
    history: [],
  },
  recovery: {
    title: "当前进度",
    phaseLabel: "等待恢复来源",
    subtitle: "选择已有项目或上传恢复目录后即可继续处理。",
    progressPercent: 0,
    detailLines: ["打开已有项目，或上传恢复目录继续处理。"],
    history: [],
  },
};

const FALLBACK_START_PAGE = {
  logoUrl: "/assets/icons/start-page-logo.svg",
  enterButtonUrl: "/shared-assets/start-page/Frame-10.svg",
  legacyButtonFallbackUrl: "/shared-assets/start-page/frame-8.png",
};

const FRONTEND_SESSION_HEARTBEAT_MS = 10000;

const TASK_PHASE_FLOW = [
  { phase: "input", label: "任务创建", description: "任务已进入队列，等待开始执行。" },
  { phase: "acquisition", label: "内容获取", description: "正在获取链接、文件或文本内容。" },
  { phase: "transcription", label: "转录处理", description: "正在提取音频并生成原始转录稿。" },
  { phase: "chunking", label: "结构整理", description: "正在切分内容并准备进入第一稿。" },
  { phase: "first_pass", label: "第一稿生成", description: "正在根据提示词整理出第一稿。" },
  { phase: "template_pass", label: "二次深化", description: "正在执行你选中的 skill 模板。" },
  { phase: "artifact_write", label: "结果写入", description: "正在写入项目结果文件。" },
];

const app = document.querySelector("#app");
let startPageCleanup = null;
let toastTimer = null;
let toastStartedAt = 0;
let toastRemaining = 0;
let startPageTransitionTimer = null;
let workspaceIntroTimer = null;
let frontendSessionClientId = null;
let frontendSessionHeartbeatTimer = null;

const state = {
  bootstrapping: true,
  bootstrap: null,
  bootstrapError: "",
  startPageEntered: FORCE_WORKSPACE_ENTRY,
  startPageTransitioning: false,
  workspaceIntro: false,
  activeToolView: parseViewFromHash(),
  selectedHistoryRunId: null,
  runPayloads: {},
  loadingRunId: null,
  leftDrawerOpen: false,
  rightDrawerMode: null,
  progressDetailsOpen: false,
  activeTaskId: null,
  activeTaskStatus: null,
  activeTemplateId: null,
  templatePanelTab: "catalog",
  selectedTemplateRecordId: null,
  themePreference: loadThemePreference(),
  taskPollTimer: null,
  toast: null,
  rawTranscriptOpen: false,
  textMode: "paste",
  shareLink: "",
  localMediaFile: null,
  localMediaLabel: "未选择文件",
  textFile: null,
  textFileLabel: "未选择文件",
  pastedText: "",
  recoveryFiles: [],
  recoveryDirLabel: "未选择目录",
  settingsForm: {
    summaryApiBaseUrl: "",
    summaryApiKey: "",
    summaryApiModel: "",
    transcribeBackend: "auto",
  },
  settingsResult: null,
  settingsBusyAction: null,
  transcriptionPrompt: null,
  resourcePrompt: null,
  resourceBusyId: null,
  pendingResourceAction: null,
  transcriptionDetailsOpen: false,
  transcriptionBusyAction: null,
  pendingTranscriptionAction: null,
};

window.addEventListener("hashchange", () => {
  state.activeToolView = parseViewFromHash();
  state.selectedHistoryRunId = null;
  safeRenderApp();
});

init();
applyThemePreference();
watchSystemTheme();
setupFrontendSessionLifecycle();

async function init() {
  ensureInitialHash();
  await openFrontendSession();
  await refreshBootstrap({ preserveSelection: false });
  safeRenderApp();
}

let oglRuntimePromise = null;

function ensureInitialHash() {
  if (!window.location.hash) {
    window.location.hash = `#/${DEFAULT_VIEW}`;
  }
}

function parseViewFromHash() {
  const hash = window.location.hash.replace(/^#\//, "").trim();
  return TOOL_VIEWS.some((item) => item.id === hash) ? hash : DEFAULT_VIEW;
}

function isTaskRunning() {
  return Boolean(state.activeTaskId);
}

function isActionDisabled(action) {
  if (state.resourcePrompt) {
    return ![
      "download-runtime-resource",
      "select-runtime-resource-file",
      "retry-runtime-resource",
      "dismiss-resource-prompt",
    ].includes(action);
  }
  if (state.transcriptionPrompt) {
    return ![
      "confirm-cpu-fallback",
      "retry-gpu-check",
      "toggle-transcription-details",
      "dismiss-transcription-prompt",
    ].includes(action);
  }
  if (state.settingsBusyAction) {
    return [
      "toggle-health",
      "toggle-settings",
      "run-health-check",
      "save-settings",
      "test-connection",
      "load-models",
      "test-model",
      "set-theme",
    ].includes(action);
  }
  if (!isTaskRunning()) {
    return false;
  }
  return [
    "toggle-history",
    "refresh-history",
    "toggle-health",
    "toggle-settings",
    "run-health-check",
    "save-settings",
    "test-connection",
    "load-models",
    "test-model",
    "submit-share-link",
    "submit-local-media",
    "submit-text-file",
    "submit-pasted-text",
    "submit-recovery-upload",
    "open-resume-candidate",
    "open-auth",
    "check-auth",
    "resume-first-pass-inline",
    "run-template",
    "rerun-template",
  ].includes(action);
}

function isHistorySelectionLocked() {
  return isTaskRunning();
}

function isToolNavigationLocked() {
  return isTaskRunning();
}

function isSettingsBusy(action = null) {
  if (!state.settingsBusyAction) {
    return false;
  }
  return action ? state.settingsBusyAction === action : true;
}

function getSettingsActionLabel(action, idleLabel, busyLabel) {
  return isSettingsBusy(action) ? busyLabel : idleLabel;
}

function getButtonBusyClass(action) {
  return isSettingsBusy(action) ? " is-busy" : "";
}

function isTranscriptionBusy(action = null) {
  if (!state.transcriptionBusyAction) {
    return false;
  }
  return action ? state.transcriptionBusyAction === action : true;
}

function getTranscriptionButtonBusyClass(action) {
  return isTranscriptionBusy(action) ? " is-busy" : "";
}

function formatMetaLine(values) {
  return values
    .map((value) => String(value ?? "").trim())
    .filter(Boolean)
    .join(" · ");
}

function getTemplateRunState(templateId) {
  if (!isTaskRunning() || !state.activeTemplateId || state.activeTemplateId !== templateId) {
    return null;
  }
  const percent = Number(state.activeTaskStatus?.progressPercent ?? 0);
  return {
    percent: Math.max(0, Math.min(100, percent)),
    label: state.activeTaskStatus?.message ?? state.activeTaskStatus?.phaseLabel ?? "正在执行",
  };
}

function getSelectedTemplateRecord(cards) {
  if (!Array.isArray(cards) || !cards.length) {
    return null;
  }
  return cards.find((item) => item.id === state.selectedTemplateRecordId) ?? cards[0];
}

function getTemplateStatusLabel(option, runState) {
  if (runState) {
    return `${runState.percent}%`;
  }
  if (option.completed) {
    return option.statusLabel ?? "已生成";
  }
  return option.statusLabel ?? "绛夊緟";
}

function mapValueRating(value) {
  const raw = String(value ?? "").trim();
  const normalized = raw.toLowerCase();
  if (normalized.includes("高价值") || normalized.includes("很值得看") || normalized.includes("high")) {
    return { label: "高价值", tone: "high" };
  }
  if (normalized.includes("值得看") || normalized.includes("有部分价值") || normalized.includes("worth")) {
    return { label: "值得看", tone: "worth" };
  }
  if (
    normalized.includes("普通") ||
    normalized.includes("一般") ||
    normalized.includes("信息重复偏多") ||
    normalized.includes("medium")
  ) {
    return { label: "普通", tone: "normal" };
  }
  if (
    normalized.includes("不值得") ||
    normalized.includes("低价值") ||
    normalized.includes("low") ||
    normalized.includes("weak") ||
    normalized.includes("not")
  ) {
    return { label: "不值得", tone: "negative" };
  }
  return { label: raw || "待判断", tone: "normal" };
}

function inferRecoveryPhase(recoveryState) {
  switch (recoveryState) {
    case "completed":
      return "artifact_write";
    case "partial_templates":
      return "template_pass";
    case "first_pass_only":
      return "first_pass";
    case "transcript_only":
      return "transcription";
    default:
      return "input";
  }
}

function buildProgressTimeline(status) {
  const currentPhase = status?.phase ?? "input";
  const currentMessage = status?.message ?? "";
  const history = Array.isArray(status?.history) ? status.history.filter(Boolean) : [];
  const phaseIndex = Math.max(0, TASK_PHASE_FLOW.findIndex((item) => item.phase === currentPhase));
  return TASK_PHASE_FLOW.map((step, index) => {
    const matched = [...history].reverse().find((entry) => {
      const label = String(entry?.label ?? "");
      return label.includes(step.label);
    });
    const isDone = index < phaseIndex || status?.state === "succeeded";
    const isCurrent = index === phaseIndex && status?.state !== "succeeded";
    return {
      label: step.label,
      detail:
        matched?.detail ||
        (isCurrent ? currentMessage || step.description : isDone ? "已完成" : step.description),
      updatedAt: matched?.updatedAt || (isCurrent ? status?.updatedAt : ""),
      progressPercent: matched?.progressPercent ?? (isCurrent ? status?.progressPercent ?? 0 : isDone ? 100 : 0),
      tone: isCurrent ? "current" : isDone ? "done" : "pending",
    };
  });
}

function buildStoredProgressTimeline(progress, source = {}) {
  return buildProgressTimeline({
    phase: source.currentPhase || inferRecoveryPhase(source.recoveryState),
    state: source.recoveryState === "completed" ? "succeeded" : "running",
    message: progress.subtitle || source.currentMessage || progress.phaseLabel || "",
    updatedAt: source.updatedAt || "",
    progressPercent: Number(progress.progressPercent ?? 0),
    history: Array.isArray(progress.history) ? progress.history : [],
  });
}

function loadThemePreference() {
  try {
    const stored = window.localStorage?.getItem(THEME_STORAGE_KEY);
    return THEME_OPTIONS.some((item) => item.id === stored) ? stored : "dark";
  } catch {
    return "dark";
  }
}

function getResolvedTheme(preference = state.themePreference) {
  if (preference === "light" || preference === "dark") {
    return preference;
  }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyThemePreference() {
  const preference = THEME_OPTIONS.some((item) => item.id === state.themePreference) ? state.themePreference : "system";
  const resolved = getResolvedTheme(preference);
  document.documentElement.dataset.themePreference = preference;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
}

function setThemePreference(preference) {
  if (!THEME_OPTIONS.some((item) => item.id === preference)) {
    return;
  }
  state.themePreference = preference;
  try {
    window.localStorage?.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Theme choice is local UI state; storage failures should not block the workspace.
  }
  applyThemePreference();
}

function watchSystemTheme() {
  const media = window.matchMedia?.("(prefers-color-scheme: light)");
  if (!media) {
    return;
  }
  media.addEventListener?.("change", () => {
    if (state.themePreference === "system") {
      applyThemePreference();
      safeRenderApp();
    }
  });
}

function setupFrontendSessionLifecycle() {
  window.addEventListener("pagehide", () => {
    closeFrontendSession();
  });
  window.addEventListener("beforeunload", () => {
    closeFrontendSession();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      void sendFrontendSessionSignal("heartbeat");
      startFrontendSessionHeartbeat();
    }
  });
}

function getFrontendSessionClientId() {
  if (!frontendSessionClientId) {
    frontendSessionClientId = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }
  return frontendSessionClientId;
}

async function openFrontendSession() {
  await sendFrontendSessionSignal("open");
  startFrontendSessionHeartbeat();
}

function startFrontendSessionHeartbeat() {
  stopFrontendSessionHeartbeat();
  frontendSessionHeartbeatTimer = window.setInterval(() => {
    void sendFrontendSessionSignal("heartbeat");
  }, FRONTEND_SESSION_HEARTBEAT_MS);
}

function stopFrontendSessionHeartbeat() {
  if (frontendSessionHeartbeatTimer) {
    window.clearInterval(frontendSessionHeartbeatTimer);
    frontendSessionHeartbeatTimer = null;
  }
}

function closeFrontendSession() {
  stopFrontendSessionHeartbeat();
  sendFrontendSessionSignal("close", { useBeacon: true });
}

async function sendFrontendSessionSignal(mode, { useBeacon = false } = {}) {
  const clientId = getFrontendSessionClientId();
  const payload = JSON.stringify({
    clientId,
    page: state.selectedHistoryRunId ? "run" : state.startPageEntered ? "workspace" : "start-page",
  });
  const url = `/api/runtime/frontend-session/${mode}`;
  if (useBeacon && typeof navigator.sendBeacon === "function") {
    try {
      navigator.sendBeacon(url, new Blob([payload], { type: "application/json" }));
      return;
    } catch {
      // Fallback to fetch below.
    }
  }
  try {
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      keepalive: useBeacon,
    });
  } catch {
    // Session telemetry should not block the workspace experience.
  }
}

function safeRenderApp() {
  try {
    renderApp();
  } catch (error) {
    console.error(error);
    app.innerHTML = `
      <section class="surface-card workspace-message">
        <div class="view-head">
          <div class="view-kicker">系统</div>
          <h1>界面渲染失败</h1>
          <p>${escapeHtml(error?.message ?? "发生未知渲染错误。")}</p>
        </div>
      </section>
    `;
  }
}

function renderApp() {
  if (!state.startPageEntered) {
    syncBodyMode(true);
    app.innerHTML = renderStartPage();
    mountStartPageAurora();
    bindEvents();
    return;
  }

  syncBodyMode(false);
  destroyStartPageAurora();

  if (state.bootstrapping && !state.bootstrap) {
    app.innerHTML = renderLoadingScreen("正在准备工作台...");
    return;
  }

  if (state.bootstrapError && !state.bootstrap) {
    app.innerHTML = renderFatalError(state.bootstrapError);
    bindEvents();
    return;
  }

  app.innerHTML = `
    <div class="app-shell ${state.workspaceIntro ? "is-entering" : ""}">
      ${renderTopNav()}
      ${renderGlobalFeedback()}
      <input id="runtime-resource-file-input" class="hidden-file-input" type="file" />
      <div class="workspace-stage ${state.selectedHistoryRunId ? "is-history-focus" : ""}">
        <div class="workspace-rail workspace-rail--left ${state.leftDrawerOpen ? "is-open" : "is-closed"}">
          ${state.leftDrawerOpen ? renderProjectDrawer() : ""}
        </div>
        <main class="center-shell">
          ${renderProgressCard()}
          ${renderCenterView()}
        </main>
        <div class="workspace-rail workspace-rail--right ${state.rightDrawerMode ? "is-open" : "is-closed"}">
          ${state.rightDrawerMode === "health" ? renderHealthDrawer() : ""}
          ${state.rightDrawerMode === "settings" ? renderSettingsDrawer() : ""}
        </div>
      </div>
    </div>
  `;

  bindEvents();
}

function renderStartPage() {
  const startPage = state.bootstrap?.startPage ?? FALLBACK_START_PAGE;
  return `
    <section class="start-page-shell start-page-shell--interactive" data-action="enter-workspace" aria-label="进入工作台" role="button" tabindex="0">
      <div id="start-page-aurora" class="soft-aurora-container start-page-backdrop" aria-hidden="true"></div>
      <div class="start-page-content">
        <div class="start-page-logo-shell">
          <img class="start-page-logo" src="${escapeHtml(startPage.logoUrl)}" alt="Synpture" />
        </div>
      </div>
    </section>
  `;
}

function syncBodyMode(isStartPage) {
  applyThemePreference();
  document.body.classList.toggle("is-start-page", Boolean(isStartPage));
}

function destroyStartPageAurora() {
  if (typeof startPageCleanup === "function") {
    startPageCleanup();
  }
  startPageCleanup = null;
}

async function loadOglRuntime() {
  if (!oglRuntimePromise) {
    oglRuntimePromise = import("../vendor/ogl/index.js");
  }
  return oglRuntimePromise;
}

function mountStartPageAurora() {
  const container = app.querySelector("#start-page-aurora");
  if (!container || container.dataset.mounted === "1") {
    return;
  }
  container.dataset.mounted = "1";

  const vertexShader = `
    attribute vec2 uv;
    attribute vec2 position;
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = vec4(position, 0.0, 1.0);
    }
  `;

  const fragmentShader = `
    precision highp float;

    uniform float uTime;
    uniform vec3 uResolution;
    uniform float uSpeed;
    uniform float uScale;
    uniform float uBrightness;
    uniform vec3 uColor1;
    uniform vec3 uColor2;
    uniform float uNoiseFreq;
    uniform float uNoiseAmp;
    uniform float uBandHeight;
    uniform float uBandSpread;
    uniform float uOctaveDecay;
    uniform float uLayerOffset;
    uniform float uColorSpeed;
    uniform vec2 uMouse;
    uniform float uMouseInfluence;
    uniform bool uEnableMouse;

    #define TAU 6.28318

    vec3 gradientHash(vec3 p) {
      p = vec3(
        dot(p, vec3(127.1, 311.7, 234.6)),
        dot(p, vec3(269.5, 183.3, 198.3)),
        dot(p, vec3(169.5, 283.3, 156.9))
      );
      vec3 h = fract(sin(p) * 43758.5453123);
      float phi = acos(2.0 * h.x - 1.0);
      float theta = TAU * h.y;
      return vec3(cos(theta) * sin(phi), sin(theta) * cos(phi), cos(phi));
    }

    float quinticSmooth(float t) {
      float t2 = t * t;
      float t3 = t * t2;
      return 6.0 * t3 * t2 - 15.0 * t2 * t2 + 10.0 * t3;
    }

    vec3 cosineGradient(float t, vec3 a, vec3 b, vec3 c, vec3 d) {
      return a + b * cos(TAU * (c * t + d));
    }

    float perlin3D(float amplitude, float frequency, float px, float py, float pz) {
      float x = px * frequency;
      float y = py * frequency;

      float fx = floor(x); float fy = floor(y); float fz = floor(pz);
      float cx = ceil(x);  float cy = ceil(y);  float cz = ceil(pz);

      vec3 g000 = gradientHash(vec3(fx, fy, fz));
      vec3 g100 = gradientHash(vec3(cx, fy, fz));
      vec3 g010 = gradientHash(vec3(fx, cy, fz));
      vec3 g110 = gradientHash(vec3(cx, cy, fz));
      vec3 g001 = gradientHash(vec3(fx, fy, cz));
      vec3 g101 = gradientHash(vec3(cx, fy, cz));
      vec3 g011 = gradientHash(vec3(fx, cy, cz));
      vec3 g111 = gradientHash(vec3(cx, cy, cz));

      float d000 = dot(g000, vec3(x - fx, y - fy, pz - fz));
      float d100 = dot(g100, vec3(x - cx, y - fy, pz - fz));
      float d010 = dot(g010, vec3(x - fx, y - cy, pz - fz));
      float d110 = dot(g110, vec3(x - cx, y - cy, pz - fz));
      float d001 = dot(g001, vec3(x - fx, y - fy, pz - cz));
      float d101 = dot(g101, vec3(x - cx, y - fy, pz - cz));
      float d011 = dot(g011, vec3(x - fx, y - cy, pz - cz));
      float d111 = dot(g111, vec3(x - cx, y - cy, pz - cz));

      float sx = quinticSmooth(x - fx);
      float sy = quinticSmooth(y - fy);
      float sz = quinticSmooth(pz - fz);

      float lx00 = mix(d000, d100, sx);
      float lx10 = mix(d010, d110, sx);
      float lx01 = mix(d001, d101, sx);
      float lx11 = mix(d011, d111, sx);

      float ly0 = mix(lx00, lx10, sy);
      float ly1 = mix(lx01, lx11, sy);

      return amplitude * mix(ly0, ly1, sz);
    }

    float auroraGlow(float t, vec2 shift) {
      vec2 uv = gl_FragCoord.xy / uResolution.y;
      uv += shift;

      float noiseVal = 0.0;
      float freq = uNoiseFreq;
      float amp = uNoiseAmp;
      vec2 samplePos = uv * uScale;

      for (float i = 0.0; i < 3.0; i += 1.0) {
        noiseVal += perlin3D(amp, freq, samplePos.x, samplePos.y, t);
        amp *= uOctaveDecay;
        freq *= 2.0;
      }

      float yBand = uv.y * 10.0 - uBandHeight * 10.0;
      return 0.3 * max(exp(uBandSpread * (1.0 - 1.1 * abs(noiseVal + yBand))), 0.0);
    }

    void main() {
      vec2 uv = gl_FragCoord.xy / uResolution.xy;
      float t = uSpeed * 0.4 * uTime;

      vec2 shift = vec2(0.0);
      if (uEnableMouse) {
        shift = (uMouse - 0.5) * uMouseInfluence;
      }

      vec3 col = vec3(0.0);
      col += 0.99 * auroraGlow(t, shift) * cosineGradient(uv.x + uTime * uSpeed * 0.2 * uColorSpeed, vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.3, 0.20, 0.20)) * uColor1;
      col += 0.99 * auroraGlow(t + uLayerOffset, shift) * cosineGradient(uv.x + uTime * uSpeed * 0.1 * uColorSpeed, vec3(0.5), vec3(0.5), vec3(2.0, 1.0, 0.0), vec3(0.5, 0.20, 0.25)) * uColor2;

      col *= uBrightness;
      float alpha = clamp(length(col), 0.0, 1.0);
      gl_FragColor = vec4(col, alpha);
    }
  `;

  function hexToVec3(hex) {
    const h = hex.replace("#", "");
    return [
      Number.parseInt(h.slice(0, 2), 16) / 255,
      Number.parseInt(h.slice(2, 4), 16) / 255,
      Number.parseInt(h.slice(4, 6), 16) / 255,
    ];
  }

  loadOglRuntime()
    .then(({ Renderer, Program, Mesh, Triangle }) => {
      if (!container.isConnected) {
        return;
      }

      const renderer = new Renderer({ alpha: true, premultipliedAlpha: false, antialias: true });
      const gl = renderer.gl;
      gl.clearColor(0, 0, 0, 0);

      const geometry = new Triangle(gl);
      const program = new Program(gl, {
        vertex: vertexShader,
        fragment: fragmentShader,
        uniforms: {
          uTime: { value: 0 },
          uResolution: { value: [1, 1, 1] },
          uSpeed: { value: 1 },
          uScale: { value: 1.5 },
          uBrightness: { value: 1 },
          uColor1: { value: hexToVec3("#44E0C7") },
          uColor2: { value: hexToVec3("#53CEFF") },
          uNoiseFreq: { value: 2.5 },
          uNoiseAmp: { value: 1 },
          uBandHeight: { value: 0.5 },
          uBandSpread: { value: 1 },
          uOctaveDecay: { value: 0.1 },
          uLayerOffset: { value: 0 },
          uColorSpeed: { value: 1 },
          uMouse: { value: new Float32Array([0.5, 0.5]) },
          uMouseInfluence: { value: 0.25 },
          uEnableMouse: { value: true },
        },
      });
      const mesh = new Mesh(gl, { geometry, program });
      const canvas = gl.canvas;
      container.appendChild(canvas);

      let currentMouse = [0.5, 0.5];
      let targetMouse = [0.5, 0.5];
      let animationFrameId = 0;

      function handleMouseMove(event) {
        const rect = canvas.getBoundingClientRect();
        targetMouse = [
          (event.clientX - rect.left) / rect.width,
          1 - (event.clientY - rect.top) / rect.height,
        ];
      }

      function handleMouseLeave() {
        targetMouse = [0.5, 0.5];
      }

      function resize() {
        renderer.setSize(container.offsetWidth, container.offsetHeight);
        program.uniforms.uResolution.value = [gl.canvas.width, gl.canvas.height, gl.canvas.width / gl.canvas.height];
      }

      function update(time) {
        animationFrameId = window.requestAnimationFrame(update);
        program.uniforms.uTime.value = time * 0.001;
        currentMouse[0] += 0.05 * (targetMouse[0] - currentMouse[0]);
        currentMouse[1] += 0.05 * (targetMouse[1] - currentMouse[1]);
        program.uniforms.uMouse.value[0] = currentMouse[0];
        program.uniforms.uMouse.value[1] = currentMouse[1];
        renderer.render({ scene: mesh });
      }

      window.addEventListener("resize", resize);
      canvas.addEventListener("mousemove", handleMouseMove);
      canvas.addEventListener("mouseleave", handleMouseLeave);
      resize();
      animationFrameId = window.requestAnimationFrame(update);

      startPageCleanup = () => {
        window.cancelAnimationFrame(animationFrameId);
        window.removeEventListener("resize", resize);
        canvas.removeEventListener("mousemove", handleMouseMove);
        canvas.removeEventListener("mouseleave", handleMouseLeave);
        if (canvas.parentNode === container) {
          container.removeChild(canvas);
        }
        gl.getExtension("WEBGL_lose_context")?.loseContext();
        container.dataset.mounted = "";
      };
    })
    .catch((error) => {
      console.warn("SoftAurora background failed to load", error);
      container.dataset.mounted = "";
    });
}

function renderLoadingScreen(message) {
  return `
    <section class="surface-card workspace-message">
      <div class="view-head">
        <div class="view-kicker">系统</div>
        <h1>正在加载工作台</h1>
        <p>${escapeHtml(message)}</p>
      </div>
    </section>
  `;
}

function renderFatalError(message) {
  return `
    <section class="surface-card workspace-message">
      <div class="view-head">
        <div class="view-kicker">系统</div>
        <h1>工作台初始化失败</h1>
        <p>${escapeHtml(message)}</p>
      </div>
      <div class="button-row">
        <button class="wide-primary" data-action="retry-bootstrap">重新加载</button>
      </div>
    </section>
  `;
}

function renderGlobalFeedback() {
  if (!state.toast && !state.transcriptionPrompt) {
    return "";
  }
  const parts = [];
  if (state.toast) {
    const label = state.toast.tone === "error" ? "错误" : "提示";
    const duration = Math.max(1200, Number(state.toast.remaining ?? state.toast.duration ?? 4200));
    parts.push(`
      <div class="toast-layer" aria-live="polite">
        <section class="toast-card is-${escapeHtml(state.toast.tone)}" data-toast-id="${escapeHtml(state.toast.id)}" style="--toast-duration:${duration}ms;">
          <div class="toast-head">
            <div class="toast-copy">
              <strong>${label}</strong>
              <p>${escapeHtml(state.toast.message)}</p>
            </div>
            <button class="toast-close" data-action="dismiss-toast" aria-label="关闭提示" title="关闭提示">×</button>
          </div>
          <div class="toast-progress">
            <span class="toast-progress-bar"></span>
          </div>
        </section>
      </div>
    `);
  }
  if (state.transcriptionPrompt) {
    parts.push(renderTranscriptionPrompt());
  }
  if (state.resourcePrompt) {
    parts.push(renderResourcePrompt());
  }
  return parts.join("");
}

function getRuntimeResources() {
  return state.bootstrap?.runtimeResources?.resources ?? [];
}

function findRuntimeResource(id) {
  return getRuntimeResources().find((item) => item.id === id) ?? null;
}

function getTranscriptionCapabilityLabel(capability) {
  if (capability?.gpuStatus === "ready") {
    return "GPU 可用";
  }
  if (capability?.cpuFallbackAvailable && capability?.allowCpuFallback) {
    return "CPU 已启用";
  }
  if (capability?.cpuFallbackAvailable) {
    return "需确认";
  }
  return "不可用";
}

function isTranscriptionCapabilityUsable(capability) {
  return capability?.gpuStatus === "ready" || (capability?.cpuFallbackAvailable && capability?.allowCpuFallback);
}

function compactStatusText(value, maxLength = 86) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) {
    return "";
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function isRuntimeResourceHealthCheck(item) {
  const text = [item?.label, item?.detail, item?.recommendation].filter(Boolean).join(" ");
  const lowerText = text.toLowerCase();
  return (
    lowerText.includes("ffmpeg") ||
    lowerText.includes("ffprobe") ||
    lowerText.includes("whisper.cpp") ||
    lowerText.includes("playwright") ||
    lowerText.includes("chrome/chromium") ||
    (lowerText.includes("node") && lowerText.includes("chrome")) ||
    text.includes("运行资源") ||
    text.includes("授权浏览器运行时") ||
    text.includes("本地转录链路")
  );
}

function getVisibleHealthChecks(health) {
  return (health?.checks ?? []).filter((item) => !isRuntimeResourceHealthCheck(item));
}

function getHealthAttentionSummary(health, visibleChecks, transcription) {
  if (!health?.hasRun) {
    return "尚未运行自检。点击按钮后会检查 API、运行资源和本地环境。";
  }
  if (health.status === "ok") {
    return "基础检查已通过，可以开始执行任务。";
  }

  const issues = [];
  for (const resource of getRuntimeResources()) {
    if (resource?.ready) {
      continue;
    }
    const state = resource.state === "invalid" ? "校验失败" : "待安装";
    issues.push(`${resource.title ?? resource.id}: ${state}`);
  }

  if (transcription && !isTranscriptionCapabilityUsable(transcription)) {
    issues.push(`本地转录：${compactStatusText(transcription.gpuReason || transcription.cpuReason)}`);
  }

  for (const item of visibleChecks ?? []) {
    if (item?.state === "ok") {
      continue;
    }
    const label = item.label || "检查项";
    const detail = compactStatusText(item.detail || item.recommendation || item.stateLabel, 68);
    issues.push(detail ? `${label}: ${detail}` : label);
  }

  const uniqueIssues = [...new Set(issues.filter(Boolean))];
  if (!uniqueIssues.length) {
    return "需要关注的内容已在下方运行资源卡片中列出。";
  }
  const shown = uniqueIssues.slice(0, 3);
  const rest = uniqueIssues.length - shown.length;
  return `需要关注：${shown.join("；")}${rest > 0 ? `；另有 ${rest} 项` : ""}。`;
}

function getRuntimeResourceFileName(resource) {
  const configuredName = String(resource?.fileName ?? "").trim();
  if (configuredName) {
    return configuredName;
  }
  const url = String(resource?.url ?? "").trim();
  if (url) {
    try {
      const parsed = new URL(url, window.location.href);
      const fileName = decodeURIComponent(parsed.pathname.split("/").filter(Boolean).pop() ?? "");
      if (fileName) {
        return fileName;
      }
    } catch {
      const fileName = decodeURIComponent(url.split(/[/?#]/).filter(Boolean).pop() ?? "");
      if (fileName) {
        return fileName;
      }
    }
  }
  const target = String(resource?.targetPath ?? "").trim();
  return target.split(/[\\/]/).filter(Boolean).pop() ?? "";
}

function renderResourcePrompt() {
  const resource = state.resourcePrompt;
  const busy = state.resourceBusyId === resource.id;
  const fileName = getRuntimeResourceFileName(resource);
  return `
    <div class="blocking-overlay" aria-modal="true" role="dialog">
      <section class="blocking-card">
        <div class="blocking-card-head">
          <div class="blocking-card-copy">
            <div class="drawer-eyebrow">运行资源</div>
            <h2>${escapeHtml(resource.title ?? "需要下载运行资源")}</h2>
            <p>${escapeHtml(resource.detail ?? resource.description ?? "当前功能需要补齐运行资源。")}</p>
          </div>
          <button class="drawer-icon-button" data-action="dismiss-resource-prompt" aria-label="关闭提示" title="关闭提示">×</button>
        </div>
        <div class="blocking-status-row">
          <span class="status-pill">${escapeHtml(resource.state ?? "missing")}</span>
          <span class="status-pill">${resource.sha256Configured ? "已配置校验" : "缺少 SHA256"}</span>
          <span class="status-pill">${resource.urlConfigured ? "可下载" : "缺少下载地址"}</span>
        </div>
        <div class="blocking-details">
          <p>安装位置：${escapeHtml(resource.targetPath ?? "")}</p>
          ${fileName ? `<p>本地文件应选择：${escapeHtml(fileName)}</p>` : ""}
          ${resource.error ? `<p>${escapeHtml(resource.error)}</p>` : ""}
          ${resource.progressPercent ? `<p>进度：${escapeHtml(String(resource.progressPercent))}%</p>` : ""}
        </div>
        <div class="button-row blocking-actions">
          <button class="drawer-primary${busy ? " is-busy" : ""}" data-action="download-runtime-resource" data-resource-id="${escapeAttribute(resource.id)}" ${busy || !resource.urlConfigured || !resource.sha256Configured ? "disabled" : ""}>${busy ? "处理中..." : "下载并继续"}</button>
          <button class="drawer-chip" data-action="select-runtime-resource-file" data-resource-id="${escapeAttribute(resource.id)}" ${busy ? "disabled" : ""}>选择本地文件</button>
          <button class="drawer-chip" data-action="retry-runtime-resource" data-resource-id="${escapeAttribute(resource.id)}" ${busy ? "disabled" : ""}>重试检查</button>
          <button class="drawer-chip" data-action="dismiss-resource-prompt" ${busy ? "disabled" : ""}>取消</button>
        </div>
      </section>
    </div>
  `;
}

function renderTranscriptionPrompt() {
  const capability = state.transcriptionPrompt;
  const gpuReady = capability.gpuStatus === "ready";
  const gpuRecoverable = Boolean(capability.gpuRecoverable);
  const showDetails = state.transcriptionDetailsOpen;
  const details = Array.isArray(capability.gpuDetails) ? capability.gpuDetails : [];
  return `
    <div class="blocking-overlay" aria-modal="true" role="dialog">
      <section class="blocking-card">
        <div class="blocking-card-head">
          <div class="blocking-card-copy">
            <div class="drawer-eyebrow">转录能力</div>
            <h2>当前电脑无法使用 GPU 转录</h2>
            <p>${escapeHtml(capability.gpuReason ?? "GPU 转录不可用。")}</p>
          </div>
          <button class="drawer-icon-button" data-action="dismiss-transcription-prompt" aria-label="关闭提示" title="关闭提示">×</button>
        </div>
        <div class="blocking-status-row">
          <span class="status-pill"><span class="status-dot ${gpuReady ? "is-live" : "is-idle"}" aria-hidden="true"></span>${gpuReady ? "GPU 可用" : "GPU 不可用"}</span>
          <span class="status-pill">${capability.cpuFallbackAvailable ? "CPU 可用" : "CPU 不可用"}</span>
          ${capability.gpuRecoverable ? `<span class="status-pill">可重试</span>` : `<span class="status-pill">不可重试</span>`}
        </div>
        ${showDetails ? `
          <div class="blocking-details">
            ${details.length ? details.map((item) => `<p>${escapeHtml(item)}</p>`).join("") : `<p>${escapeHtml(capability.cpuReason ?? "")}</p>`}
          </div>
        ` : ""}
        <div class="button-row blocking-actions">
          ${capability.cpuFallbackAvailable ? `<button class="drawer-primary${getTranscriptionButtonBusyClass("confirm-cpu-fallback")}" data-action="confirm-cpu-fallback">${isTranscriptionBusy("confirm-cpu-fallback") ? "切换中..." : "继续使用 CPU"}</button>` : ""}
          <button class="drawer-chip${getTranscriptionButtonBusyClass("retry-gpu-check")}" data-action="retry-gpu-check" ${gpuRecoverable ? "" : "disabled"}>${isTranscriptionBusy("retry-gpu-check") ? "重试中..." : "重试 GPU 检测"}</button>
          <button class="drawer-chip" data-action="toggle-transcription-details">${showDetails ? "收起原因" : "查看原因"}</button>
          <button class="drawer-chip" data-action="dismiss-transcription-prompt">取消</button>
        </div>
      </section>
    </div>
  `;
}

function renderTopNav() {
  const hasHistoryFocus = Boolean(state.selectedHistoryRunId);
  return `
    <header class="top-nav">
      <div class="nav-left">
        <div class="brand-lockup">
          <img class="brand-logo" src="/assets/icons/Frame_11.svg" alt="Synpture" />
        </div>
        <button class="nav-mini-pill ${state.leftDrawerOpen ? "is-active" : ""}" data-action="toggle-history" ${isActionDisabled("toggle-history") ? "disabled" : ""}>项目列表</button>
      </div>
      <div class="nav-center">
        ${TOOL_VIEWS.map(
          (item) => `
            <button class="nav-pill ${!hasHistoryFocus && state.activeToolView === item.id ? "is-active" : ""}" data-view="${item.id}" ${isToolNavigationLocked() ? "disabled" : ""}>
              ${escapeHtml(item.label)}
            </button>
          `,
        ).join("")}
      </div>
      <div class="nav-right">
        <span class="status-pill">
          <span class="status-dot ${state.activeTaskId ? "is-live" : ""}" aria-hidden="true"></span>
          ${state.activeTaskId ? "任务运行中" : "工作台在线"}
        </span>
        ${state.activeTaskId ? `<button class="status-action" data-action="cancel-task">中止</button>` : ""}
        <div class="nav-actions">
          <button class="icon-pill ${state.rightDrawerMode === "health" ? "is-active" : ""}" data-action="toggle-health" aria-label="打开健康自检" title="健康自检" ${isActionDisabled("toggle-health") ? "disabled" : ""}>
            <span class="icon-mask icon-mask--health" aria-hidden="true"></span>
          </button>
          <button class="icon-pill ${state.rightDrawerMode === "settings" ? "is-active" : ""}" data-action="toggle-settings" aria-label="打开系统设置" title="系统设置" ${isActionDisabled("toggle-settings") ? "disabled" : ""}>
            <span class="icon-mask icon-mask--settings" aria-hidden="true"></span>
          </button>
        </div>
      </div>
    </header>
  `;
}

function renderProjectDrawer() {
  const runs = state.bootstrap?.runs ?? [];
  return `
    <aside class="modal-drawer left-drawer open">
      <div class="drawer-head">
        <div class="drawer-head-copy">
          <div class="drawer-eyebrow">项目</div>
          <div class="panel-title">项目列表</div>
        </div>
        <div class="drawer-head-actions">
          <button class="drawer-icon-button" data-action="refresh-history" aria-label="刷新项目列表" title="刷新项目列表" ${isActionDisabled("refresh-history") ? "disabled" : ""}>
            <span class="icon-mask icon-mask--refresh" aria-hidden="true"></span>
          </button>
          <button class="drawer-icon-button" data-action="toggle-history" aria-label="收起项目列表" title="收起项目列表" ${isActionDisabled("toggle-history") ? "disabled" : ""}>
            <span class="icon-mask icon-mask--close" aria-hidden="true"></span>
          </button>
        </div>
      </div>
      <div class="history-list">
        ${runs.length ? runs.map((item) => renderHistoryCard(item)).join("") : `<div class="empty-copy">当前还没有可展示的本地项目。</div>`}
      </div>
      <div class="drawer-tail-actions drawer-tail-actions--center">
        <button class="drawer-icon-button" data-action="toggle-history" aria-label="收起项目列表" title="收起项目列表" ${isActionDisabled("toggle-history") ? "disabled" : ""}>
          <span class="icon-mask icon-mask--close" aria-hidden="true"></span>
        </button>
      </div>
    </aside>
  `;
}

function renderHistoryCard(item) {
  const isSelected = state.selectedHistoryRunId === item.id;
  return `
    <button class="history-card ${isSelected ? "is-selected" : ""}" data-history-select="${escapeHtml(item.id)}" ${isHistorySelectionLocked() ? "disabled" : ""}>
      <div class="history-card-top">
        <span class="history-timestamp">${escapeHtml(item.updatedAt ?? "")}</span>
        <span class="history-progress">${Number(item.progressPercent ?? 0)}%</span>
      </div>
      <h3>${escapeHtml(item.title ?? item.id)}</h3>
      <div class="history-source" title="${escapeHtml(item.runDir ?? "")}">${escapeHtml(item.runDir ?? "")}</div>
    </button>
  `;
}

function renderHealthDrawer() {
  const health = state.bootstrap?.health ?? { hasRun: false, status: "idle", statusText: "未运行", checks: [] };
  const transcription = state.bootstrap?.transcription ?? null;
  const dotTone = health.status === "ok" ? "is-ready" : health.status === "error" ? "is-error" : "is-idle";
  const visibleHealthChecks = getVisibleHealthChecks(health);
  const attentionSummary = getHealthAttentionSummary(health, visibleHealthChecks, transcription);
  return `
    <aside class="modal-drawer right-drawer open">
      <div class="drawer-head">
        <div class="drawer-head-copy">
          <div class="drawer-eyebrow">运行状态</div>
          <div class="panel-title">健康自检</div>
        </div>
        <div class="drawer-head-actions">
          <button class="drawer-icon-button" data-action="toggle-health" aria-label="收起健康自检" title="收起健康自检" ${isActionDisabled("toggle-health") ? "disabled" : ""}>
            <span class="icon-mask icon-mask--close" aria-hidden="true"></span>
          </button>
        </div>
      </div>
      <section class="drawer-card">
        <div class="drawer-card-head">
          <h3>当前状态</h3>
        </div>
        <div class="health-status-line">
          <span class="health-status-dot ${dotTone}" aria-hidden="true"></span>
          <strong>${escapeHtml(health.statusText ?? "未运行")}</strong>
        </div>
        <p class="health-status-summary">${escapeHtml(attentionSummary)}</p>
        <button class="drawer-primary${getButtonBusyClass("run-health-check")}" data-action="run-health-check" ${isActionDisabled("run-health-check") ? "disabled" : ""}>${escapeHtml(getSettingsActionLabel("run-health-check", "自检启动", "自检中..."))}</button>
      </section>
      ${health.hasRun && transcription ? `
        <section class="drawer-card">
          <div class="drawer-card-head">
            <h3>转录能力</h3>
          </div>
          <div class="health-item">
            <div class="health-item-head">
              <strong>本地转录</strong>
              <span class="drawer-pill ${isTranscriptionCapabilityUsable(transcription) ? "is-accent" : ""}">${escapeHtml(getTranscriptionCapabilityLabel(transcription))}</span>
            </div>
            <p>${escapeHtml(transcription.gpuReason ?? "")}</p>
            ${transcription.cpuReason ? `<p>${escapeHtml(transcription.cpuReason)}</p>` : ""}
          </div>
        </section>
      ` : ""}
      ${health.hasRun ? renderRuntimeResourcesCard() : ""}
      ${health.hasRun && visibleHealthChecks.length ? `
        <section class="drawer-card">
          <div class="drawer-card-head">
            <h3>健康项列表</h3>
          </div>
          <div class="health-list">
            ${visibleHealthChecks.map((item) => `
              <div class="health-item">
                <div class="health-item-head">
                  <strong>${escapeHtml(item.label ?? "")}</strong>
                  <span class="drawer-pill ${item.tone === "ready" ? "is-accent" : ""}">${escapeHtml(item.stateLabel ?? "")}</span>
                </div>
                <p>${escapeHtml(item.detail ?? "")}</p>
              </div>
            `).join("")}
          </div>
        </section>
      ` : ""}
    </aside>
  `;
}

function renderSettingsDrawer() {
  const form = state.settingsForm;
  const result = state.settingsResult;
  const resolvedTheme = getResolvedTheme();
  const configuredMask = state.bootstrap?.settings?.summaryApiKeyMask ?? "";
  const hasConfiguredKey = Boolean(state.bootstrap?.settings?.summaryApiKeyConfigured);
  return `
    <aside class="modal-drawer right-drawer open">
      <div class="drawer-head">
        <div class="drawer-head-copy">
          <div class="drawer-eyebrow">配置</div>
          <div class="panel-title">系统设置</div>
        </div>
        <div class="drawer-head-actions">
          <button class="drawer-icon-button" data-action="toggle-settings" aria-label="收起系统设置" title="收起系统设置" ${isActionDisabled("toggle-settings") ? "disabled" : ""}>
            <span class="icon-mask icon-mask--close" aria-hidden="true"></span>
          </button>
        </div>
      </div>
      <section class="drawer-card">
        <div class="drawer-card-head"><h3>系统设置</h3></div>
        <div class="single-column-form">
          <div class="settings-theme-block" role="group" aria-label="界面主题">
            <div class="settings-theme-head">
              <span>界面主题</span>
              <strong>${resolvedTheme === "light" ? "当前浅色" : "当前深色"}</strong>
            </div>
            <div class="theme-toggle">
              ${THEME_OPTIONS.map((option) => `
                <button
                  class="theme-pill ${state.themePreference === option.id ? "is-active" : ""}"
                  data-action="set-theme"
                  data-theme="${option.id}"
                  aria-pressed="${state.themePreference === option.id ? "true" : "false"}"
                  type="button"
                >${escapeHtml(option.label)}</button>
              `).join("")}
            </div>
          </div>
          <label class="settings-field">
            <span>API Base URL</span>
            <input data-setting="summaryApiBaseUrl" value="${escapeAttribute(form.summaryApiBaseUrl ?? "")}" placeholder="https://..." ${isSettingsBusy() ? "disabled" : ""} />
          </label>
          <label class="settings-field">
            <span>API Key</span>
            <input type="password" name="synpture-api-key" autocomplete="new-password" data-setting="summaryApiKey" value="${escapeAttribute(form.summaryApiKey ?? "")}" placeholder="${escapeAttribute(hasConfiguredKey ? `已保存：${configuredMask || "已配置密钥"}；留空则保持当前密钥` : "请输入 API Key")}" ${isSettingsBusy() ? "disabled" : ""} />
          </label>
          <label class="settings-field">
            <span>总结模型</span>
            <input data-setting="summaryApiModel" value="${escapeAttribute(form.summaryApiModel ?? "")}" placeholder="例如 gpt-5.4" ${isSettingsBusy() ? "disabled" : ""} />
          </label>
          <label class="settings-field">
            <span>转录后端</span>
            <input data-setting="transcribeBackend" value="${escapeAttribute(form.transcribeBackend ?? "")}" placeholder="auto / local / remote" ${isSettingsBusy() ? "disabled" : ""} />
          </label>
          <div class="button-row">
            <button class="drawer-primary${getButtonBusyClass("save-settings")}" data-action="save-settings" ${isActionDisabled("save-settings") ? "disabled" : ""}>${escapeHtml(getSettingsActionLabel("save-settings", "保存设置", "保存中..."))}</button>
            <button class="drawer-chip${getButtonBusyClass("test-connection")}" data-action="test-connection" ${isActionDisabled("test-connection") ? "disabled" : ""}>${escapeHtml(getSettingsActionLabel("test-connection", "测试连接", "测试中..."))}</button>
            <button class="drawer-chip${getButtonBusyClass("load-models")}" data-action="load-models" ${isActionDisabled("load-models") ? "disabled" : ""}>${escapeHtml(getSettingsActionLabel("load-models", "获取模型", "获取中..."))}</button>
            <button class="drawer-chip${getButtonBusyClass("test-model")}" data-action="test-model" ${isActionDisabled("test-model") ? "disabled" : ""}>${escapeHtml(getSettingsActionLabel("test-model", "测试模型", "测试中..."))}</button>
          </div>
        </div>
      </section>
      ${result ? `
        <section class="drawer-card">
          <div class="drawer-card-head"><h3>${result.ok ? "操作结果" : "错误信息"}</h3></div>
          <p>${escapeHtml(result.message ?? "操作已完成。")}</p>
          ${Array.isArray(result.models) && result.models.length ? `<div class="chip-row">${result.models.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("")}</div>` : ""}
        </section>
      ` : ""}
    </aside>
  `;
}

function renderProgressCard() {
  const progress = getProgressSource();
  const detailLines = Array.isArray(progress.detailLines) ? progress.detailLines.filter(Boolean) : [];
  const activeRunPayload = state.selectedHistoryRunId ? state.runPayloads[state.selectedHistoryRunId] : null;
  const progressHistory = isTaskRunning()
    ? buildProgressTimeline(state.activeTaskStatus)
    : state.selectedHistoryRunId
      ? buildStoredProgressTimeline(progress, activeRunPayload ?? {})
      : Array.isArray(progress.history)
        ? progress.history.filter(Boolean)
        : [];
  const subtitle = progress.subtitle ?? progress.phaseLabel ?? "等待中";
  const percent = Math.max(0, Math.min(100, Number(progress.progressPercent ?? 0)));
  return `
    <section class="surface-card progress-surface">
      <div class="surface-head">
        <div class="surface-title-wrap">
          <div class="progress-title-row">
            <h2>${escapeHtml(progress.title ?? "当前进度")}</h2>
            <button
              class="progress-toggle-icon ${state.progressDetailsOpen ? "is-open" : ""}"
              data-action="toggle-progress-details"
              aria-label="${state.progressDetailsOpen ? "收起进度详情" : "展开进度详情"}"
              title="${state.progressDetailsOpen ? "收起进度详情" : "展开进度详情"}"
            >
              <span class="progress-toggle-chevron" aria-hidden="true"></span>
            </button>
          </div>
          <div class="surface-status">${escapeHtml(subtitle)}</div>
        </div>
        <div class="surface-percent">${percent}%</div>
      </div>
      <div class="progress-track">
        <div class="progress-fill" style="width:${percent}%;"></div>
      </div>
      ${state.progressDetailsOpen ? `
        <div class="progress-detail-list">
          ${progressHistory.length ? `
            <div class="progress-history">
              ${progressHistory.map((entry) => `
                <div class="progress-history-item ${entry.tone ? `is-${entry.tone}` : ""}">
                  <div class="progress-history-head">
                    <strong>${escapeHtml(entry.label ?? "")}</strong>
                    <span>${escapeHtml(entry.progressPercent ?? "")}%</span>
                  </div>
                  <span>${escapeHtml(entry.updatedAt ?? "")}</span>
                  <p>${escapeHtml(entry.detail ?? "")}</p>
                </div>
              `).join("")}
            </div>
          ` : detailLines.length ? detailLines.map((line) => `<div class="progress-detail-item">${escapeHtml(line)}</div>`).join("") : ""}
        </div>
      ` : ""}
    </section>
  `;
}

function renderCenterView() {
  if (state.selectedHistoryRunId) {
    return renderHistoryWorkspace();
  }

  switch (state.activeToolView) {
    case "local_media":
      return renderLocalMediaView();
    case "text_input":
      return renderTextInputView();
    case "recovery":
      return renderRecoveryView();
    case "share_link":
    default:
      return renderShareLinkView();
  }
}

function renderLocalMediaView() {
  const view = VIEW_CONTENT.local_media;
  const canExecute = state.localMediaFile && !state.activeTaskId && !state.transcriptionPrompt;
  return `
    <section class="surface-card view-card">
      <div class="view-head">
        <div class="view-kicker">${view.eyebrow}</div>
        <h1>${escapeHtml(view.title)}</h1>
        <p>${escapeHtml(view.description)}</p>
      </div>
      <div class="single-column-form">
        <label class="upload-shell">
          <span class="upload-shell-label">媒体文件</span>
          <input id="local-media-input" class="hidden-file-input" type="file" accept="video/*,audio/*" ${isTaskRunning() || state.transcriptionPrompt ? "disabled" : ""} />
          <span class="upload-shell-value">${escapeHtml(state.localMediaLabel)}</span>
        </label>
        <button class="wide-primary" data-action="submit-local-media" ${canExecute ? "" : "disabled"}>开始执行</button>
      </div>
    </section>
  `;
}

function renderRuntimeResourcesCard() {
  const resources = getRuntimeResources();
  if (!resources.length) {
    return "";
  }
  return `
    <section class="drawer-card">
      <div class="drawer-card-head">
        <h3>运行资源</h3>
      </div>
      <div class="runtime-resource-list">
        ${resources.map((item) => {
          const fileName = getRuntimeResourceFileName(item);
          return `
          <div class="runtime-resource-item">
            <div class="runtime-resource-head">
              <strong>${escapeHtml(item.title ?? item.id)}</strong>
              <span class="runtime-resource-state ${item.ready ? "is-ready" : ""}">${escapeHtml(item.ready ? "可用" : item.state ?? "缺失")}</span>
            </div>
            <p class="runtime-resource-copy">${escapeHtml(item.detail ?? item.description ?? "")}</p>
            ${fileName ? `<p class="runtime-resource-file-hint"><span>本地文件</span>${escapeHtml(fileName)}</p>` : ""}
            <div class="runtime-resource-actions">
              <button class="drawer-chip" data-action="download-runtime-resource" data-resource-id="${escapeAttribute(item.id)}" ${item.ready || !item.urlConfigured || !item.sha256Configured || state.resourceBusyId === item.id ? "disabled" : ""}>${state.resourceBusyId === item.id ? "处理中..." : "下载"}</button>
              <button class="drawer-chip" data-action="select-runtime-resource-file" data-resource-id="${escapeAttribute(item.id)}" ${state.resourceBusyId === item.id ? "disabled" : ""}>选择本地文件</button>
              <button class="drawer-chip" data-action="retry-runtime-resource" data-resource-id="${escapeAttribute(item.id)}" ${state.resourceBusyId === item.id ? "disabled" : ""}>刷新</button>
            </div>
          </div>
        `;
        }).join("")}
      </div>
    </section>
  `;
}

function renderShareLinkView() {
  const view = VIEW_CONTENT.share_link;
  const platforms = state.bootstrap?.platforms ?? [];
  const browserRuntime = state.bootstrap?.browserRuntime ?? null;
  const canExecute = state.shareLink.trim().length > 0 && !state.activeTaskId && !state.transcriptionPrompt;
  return `
    <section class="surface-card view-card">
      <div class="view-head">
        <div class="view-kicker">${view.eyebrow}</div>
        <h1>${escapeHtml(view.title)}</h1>
        <p>${escapeHtml(view.description)}</p>
      </div>
      <div class="share-link-layout">
        <section class="surface-card share-link-auth">
          <div class="share-link-section-head">
            <div class="share-link-section-kicker">授权</div>
            <h2>授权入口</h2>
          </div>
          ${browserRuntime ? `
            <div class="share-link-browser-note ${browserRuntime.ok ? "is-ok" : "is-warn"}">
              <strong>${browserRuntime.ok ? "浏览器运行时可用" : "浏览器运行时不可用"}</strong>
              <p>${escapeHtml(browserRuntime.detail ?? "")}${browserRuntime.recommendation ? ` ${escapeHtml(browserRuntime.recommendation)}` : ""}</p>
            </div>
          ` : ""}
          <div class="share-link-auth-grid">
            ${platforms.map((item) => renderShareAuthCard(item)).join("")}
          </div>
        </section>
        <section class="surface-card share-link-execution">
          <div class="share-link-section-head">
            <div class="share-link-section-kicker">执行</div>
            <h2>链接输入</h2>
          </div>
          <div class="share-link-execution-body">
            <div class="field-stack share-link-field-stack">
              <span class="field-label">分享链接</span>
              <input id="share-link-input" class="line-input" name="synpture-share-link" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" inputmode="url" value="${escapeAttribute(state.shareLink)}" placeholder="在此输入链接" ${isTaskRunning() || state.transcriptionPrompt ? "disabled" : ""} />
            </div>
            <button class="wide-primary share-link-primary" data-action="submit-share-link" ${canExecute ? "" : "disabled"}>开始执行</button>
          </div>
        </section>
      </div>
    </section>
  `;
}

function renderShareAuthCard(item) {
  const tooltipLines = [item.summary, ...(item.details ?? [])].filter((line) => String(line ?? "").trim());
  return `
    <article class="mini-panel share-auth-card ${item.placeholder ? "is-placeholder" : ""}">
      <div class="share-auth-card-head">
        <div class="share-auth-card-copy">
          <h3>${escapeHtml(item.title)}</h3>
        </div>
        <span class="status-indicator-wrap">
          <span class="status-indicator status-indicator--${escapeHtml(item.tone ?? "idle")}" aria-label="${escapeHtml(item.statusLabel ?? "")}"></span>
          ${tooltipLines.length ? `<span class="status-tooltip status-tooltip--${escapeHtml(item.tone ?? "idle")}">${tooltipLines.map((line) => `<span>${escapeHtml(line)}</span>`).join("")}</span>` : ""}
        </span>
      </div>
      ${item.placeholder ? `<div class="share-auth-placeholder">待接入</div>` : `
        <div class="button-row share-auth-actions">
          <button class="drawer-chip share-auth-chip" data-action="open-auth" data-platform="${escapeHtml(item.platform)}" ${isActionDisabled("open-auth") ? "disabled" : ""}>打开授权</button>
          <button class="drawer-chip share-auth-chip" data-action="check-auth" data-platform="${escapeHtml(item.platform)}" ${isActionDisabled("check-auth") ? "disabled" : ""}>检查状态</button>
        </div>
      `}
    </article>
  `;
}

async function refreshPlatformStatuses() {
  if (!state.bootstrap) {
    return;
  }
  const platforms = (state.bootstrap.platforms ?? []).filter((item) => !item.placeholder);
  for (const item of platforms) {
    try {
      const payload = await fetchJson(`/api/auth/${encodeURIComponent(item.platform)}/status`);
      replacePlatformCard(payload);
    } catch (error) {
      console.warn(`platform status refresh failed for ${item.platform}`, error);
    }
  }
  safeRenderApp();
}

function renderTextInputView() {
  const view = VIEW_CONTENT.text_input;
  const canSubmitPaste = state.textMode === "paste" && state.pastedText.trim().length > 0 && !state.activeTaskId;
  const canSubmitFile = state.textMode === "file" && state.textFile && !state.activeTaskId;
  return `
    <section class="surface-card view-card">
      <div class="view-head">
        <div class="view-kicker">${view.eyebrow}</div>
        <h1>${escapeHtml(view.title)}</h1>
        <p>${escapeHtml(view.description)}</p>
      </div>
      <div class="mode-toggle">
        <button class="mode-pill ${state.textMode === "file" ? "is-active" : ""}" data-text-mode="file" ${isTaskRunning() ? "disabled" : ""}>上传文件</button>
        <button class="mode-pill ${state.textMode === "paste" ? "is-active" : ""}" data-text-mode="paste" ${isTaskRunning() ? "disabled" : ""}>直接粘贴</button>
      </div>
      ${state.textMode === "file" ? `
        <div class="single-column-form">
          <label class="upload-shell">
            <span class="upload-shell-label">文本文件</span>
            <input id="text-file-input" class="hidden-file-input" type="file" accept=".txt,.md,.docx,.srt,.vtt" ${isTaskRunning() ? "disabled" : ""} />
            <span class="upload-shell-value">${escapeHtml(state.textFileLabel)}</span>
          </label>
          <button class="wide-primary" data-action="submit-text-file" ${canSubmitFile ? "" : "disabled"}>开始执行</button>
        </div>
      ` : `
        <div class="single-column-form">
          <label class="field-stack">
            <span class="field-label">文本内容</span>
            <textarea id="paste-input" class="text-area-input" rows="14" placeholder="在此粘贴文本内容" ${isTaskRunning() ? "disabled" : ""}>${escapeHtml(state.pastedText)}</textarea>
          </label>
          <button class="wide-primary" data-action="submit-pasted-text" ${canSubmitPaste ? "" : "disabled"}>开始执行</button>
        </div>
      `}
    </section>
  `;
}

function renderRecoveryView() {
  const view = VIEW_CONTENT.recovery;
  return `
    <section class="surface-card view-card">
      <div class="view-head">
        <div class="view-kicker">${view.eyebrow}</div>
        <h1>${escapeHtml(view.title)}</h1>
        <p>上传项目目录后，直接恢复并继续处理。</p>
      </div>
      <section class="surface-card recovery-card recovery-card--single">
        <div class="share-link-section-head">
          <div class="share-link-section-kicker">上传恢复</div>
          <h2>上传目录恢复</h2>
        </div>
        <label class="upload-shell">
          <span class="upload-shell-label">项目目录</span>
          <input id="recovery-dir-input" class="hidden-file-input" type="file" webkitdirectory directory multiple ${isTaskRunning() ? "disabled" : ""} />
          <span class="upload-shell-value">${escapeHtml(state.recoveryDirLabel)}</span>
        </label>
        <button class="wide-primary" data-action="submit-recovery-upload" ${state.recoveryFiles.length && !state.activeTaskId ? "" : "disabled"}>开始恢复</button>
      </section>
    </section>
  `;
}

function renderHistoryWorkspace() {
  const run = getSelectedRun();
  if (!run) {
    return `
      <section class="surface-card project-hero">
        <div class="view-head">
          <div class="view-kicker">项目</div>
          <h1>暂未选中项目</h1>
          <p>从左侧项目列表中选择一个项目，即可查看它的进度和结果。</p>
        </div>
      </section>
    `;
  }

  const result = state.runPayloads[run.id];
  if (state.loadingRunId === run.id || !result) {
    return renderLoadingScreen("正在加载项目工作区...");
  }

  return `
    <section class="surface-card project-hero">
      <div class="view-head">
        <div class="view-kicker">项目</div>
        <h1>${escapeHtml(result.title)}</h1>
        <div class="project-meta-row">
          <span class="project-meta-path" title="${escapeAttribute(result.runDir || result.runName || "")}">${escapeHtml(result.runDir || result.runName || "")}</span>
          ${result.createdAt ? `<span class="project-meta-time">创建于 ${escapeHtml(result.createdAt)}</span>` : ""}
        </div>
      </div>
      ${renderHistoryWorkspaceBody(result)}
    </section>
  `;
}

function renderHistoryWorkspaceBody(result) {
  if (result.recoveryState === "transcript_only") {
    return renderTranscriptOnlyWorkspace(result);
  }
  return `
    ${renderFirstPassBlock(result)}
    ${renderSkillSection(result)}
  `;
}

function renderTranscriptOnlyWorkspace(result) {
  return `
    <section class="result-cluster is-featured">
      <div class="result-section-head">
        <div class="result-section-kicker">流程</div>
        <h3>已完成转录</h3>
        <p class="section-copy">当前项目已经完成转录，下一步是生成第一稿。</p>
      </div>
      ${renderTranscriptBlock(result)}
      <div class="result-inline-actions">
        <button class="wide-primary" data-action="resume-first-pass-inline" ${isActionDisabled("resume-first-pass-inline") ? "disabled" : ""}>生成第一稿</button>
      </div>
    </section>
  `;
}

function renderTranscriptBlock(result) {
  const transcript = result.transcriptSection;
  if (!transcript?.body) {
    return "";
  }
  return `
    <section class="result-cluster">
      <div class="result-section-head">
        <div class="result-section-kicker">原始材料</div>
        <h3>${escapeHtml(transcript.title ?? "原始转录稿")}</h3>
        <p class="section-copy">${escapeHtml(transcript.sourceName ?? "")}</p>
      </div>
      <div class="transcript-preview">${escapeHtml(transcript.body)}</div>
    </section>
  `;
}

function renderFirstPassBlock(result) {
  const firstPass = result.firstPass;
  const transcript = result.transcriptSection;
  if (!firstPass) {
    return "";
  }
  const rawTranscript = transcript?.timelineText || transcript?.body || firstPass.rawTranscriptReference || "";
  const ratingMeta = mapValueRating(firstPass.valueRating);
  const hasSupportBlocks = (firstPass.highValuePoints ?? []).length || (firstPass.objectiveContext ?? []).length;
  const draftParagraphs = Array.isArray(firstPass.draftParagraphs) ? firstPass.draftParagraphs : [];
  const firstPassBody = draftParagraphs.length
    ? `
      <div class="first-pass-prose">
        ${draftParagraphs
          .map(
            (item) => `
              <section class="first-pass-paragraph first-pass-paragraph--${escapeHtml(String(item.valueLevel || "normal").toLowerCase())}">
                <p>${escapeHtml(item.text ?? "")}</p>
              </section>
            `,
          )
          .join("")}
      </div>
    `
    : `<div class="transcript-preview transcript-preview--first-pass">${escapeHtml(firstPass.cleanedTranscript ?? "")}</div>`;
  return `
    <section class="result-cluster">
      <div class="first-pass-layout ${state.rawTranscriptOpen ? "is-raw-open" : ""}">
        <div class="content-block emphasis-block first-pass-main">
          <div class="first-pass-summary">
            <div class="content-block-head first-pass-heading-row">
              <div class="first-pass-heading-copy">
                <h3>整理初稿</h3>
                ${firstPass.oneLineVerdict ? `<p class="first-pass-summary-copy">${escapeHtml(firstPass.oneLineVerdict)}</p>` : ""}
              </div>
              <span class="value-chip is-${escapeHtml(ratingMeta.tone)}">${escapeHtml(ratingMeta.label)}</span>
            </div>
          </div>
          ${firstPassBody}
          ${hasSupportBlocks ? `
            <div class="double-panel first-pass-grid">
              <div class="content-block first-pass-subblock">
                <div class="content-block-head"><h3>高价值信息</h3></div>
                ${(firstPass.highValuePoints ?? []).length ? `<ul class="bullet-list">${(firstPass.highValuePoints ?? []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<p>当前没有可提取的重点。</p>`}
              </div>
              <div class="content-block first-pass-subblock">
                <div class="content-block-head"><h3>客观背景</h3></div>
                ${(firstPass.objectiveContext ?? []).length ? `<ul class="bullet-list">${(firstPass.objectiveContext ?? []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<p>当前没有额外背景补充。</p>`}
              </div>
            </div>
          ` : ""}
        </div>
        <div class="content-block raw-transcript-panel ${state.rawTranscriptOpen ? "is-open" : "is-collapsed"}">
          <div class="content-block-head raw-transcript-head">
            <h3>原稿</h3>
            <button
              class="progress-toggle-icon ${state.rawTranscriptOpen ? "is-open" : ""}"
              data-action="toggle-raw-transcript"
              aria-label="${state.rawTranscriptOpen ? "收起原稿" : "展开原稿"}"
              title="${state.rawTranscriptOpen ? "收起原稿" : "展开原稿"}"
            >
              <span class="progress-toggle-chevron" aria-hidden="true"></span>
            </button>
          </div>
          ${state.rawTranscriptOpen ? `<div class="transcript-preview transcript-preview--timeline">${escapeHtml(rawTranscript)}</div>` : ""}
        </div>
      </div>
    </section>
  `;
}

function renderSkillSection(result) {
  const options = result.skillOptions ?? [];
  const cards = result.skillResults ?? [];
  const selectedRecord = getSelectedTemplateRecord(cards);
  const activeTab = cards.length ? state.templatePanelTab : "catalog";
  return `
    <section class="result-cluster">
      <div class="result-section-head">
        <div class="result-section-kicker">二次深化</div>
        <h3>模板深化</h3>
      </div>
      <div class="section-tabs template-tabs">
        <button class="section-tab ${activeTab === "catalog" ? "is-active" : ""}" data-action="set-template-tab" data-template-tab="catalog">模板列表</button>
        <button class="section-tab ${activeTab === "records" ? "is-active" : ""}" data-action="set-template-tab" data-template-tab="records" ${cards.length ? "" : "disabled"}>生成记录</button>
      </div>
      ${activeTab === "records" && cards.length ? `
        <div class="template-record-layout">
          <div class="template-record-list">
            ${cards.map((item) => `
              <button
                class="mini-panel template-record-item ${selectedRecord?.id === item.id ? "is-selected" : ""}"
                data-action="select-template-record"
                data-template-id="${escapeHtml(item.id)}"
              >
                <div class="mini-panel-head">
                  <h3>${escapeHtml(item.title ?? "")}</h3>
                  <span>${escapeHtml(item.tag ?? "已生成")}</span>
                </div>
                ${item.overview ? `<p class="template-record-copy">${escapeHtml(item.overview)}</p>` : ""}
              </button>
            `).join("")}
          </div>
          ${selectedRecord ? renderTemplateResultDetail(selectedRecord, true) : ""}
        </div>
      ` : options.length ? `
        <div class="template-action-grid">
          ${options.map((item) => {
            const runState = getTemplateRunState(item.id);
            const generatedRecord = cards.find((record) => record.id === item.id) ?? null;
            return `
              <article class="mini-panel template-action-card ${item.completed ? "is-complete" : "is-waiting"} ${runState ? "is-running" : ""}">
                <div class="mini-panel-head">
                  <h3>${escapeHtml(item.name)}</h3>
                  <span class="template-state-chip ${item.completed ? "is-complete" : "is-waiting"}">${escapeHtml(getTemplateStatusLabel(item, runState))}</span>
                </div>
                <div class="template-action-copy">
                  ${item.description ? `<p>${escapeHtml(item.description)}</p>` : ""}
                  ${runState ? `<div class="template-task-inline"><div class="template-task-bar"><span style="width:${runState.percent}%"></span></div><strong>${escapeHtml(runState.label)}</strong></div>` : ""}
                </div>
                <div class="template-card-actions">
                  ${
                    item.completed
                      ? `
                        <button class="drawer-chip" data-action="view-template-record" data-template-id="${escapeHtml(item.id)}">查看记录</button>
                        <button class="drawer-chip" data-action="rerun-template" data-template-id="${escapeHtml(item.id)}" ${isActionDisabled("run-template") ? "disabled" : ""}>重复生成</button>
                      `
                      : `
                        <button class="drawer-chip drawer-chip--accent" data-action="run-template" data-template-id="${escapeHtml(item.id)}" ${isActionDisabled("run-template") ? "disabled" : ""}>开始生成</button>
                      `
                  }
                </div>
                ${generatedRecord ? `<div class="template-record-hint">已生成记录可在“生成记录”里反复查看。</div>` : ""}
              </article>
            `;
          }).join("")}
        </div>
      ` : `<div class="empty-copy">当前没有检测到可用模板。</div>`}
      ${activeTab === "catalog" && !cards.length ? `<div class="empty-copy">当前还没有模板结果，先从上面选择一个模板开始。</div>` : ""}
    </section>
  `;
}

function renderTemplateResultDetail(item, primary = false) {
  return `
    <div class="mini-panel template-result-card ${primary ? "is-primary" : ""}">
      <div class="mini-panel-head">
        <h3>${escapeHtml(item.title ?? "")}</h3>
        <span>${escapeHtml(item.tag ?? "已生成")}</span>
      </div>
      <div class="template-result-copy">
        ${item.overview ? `<p class="template-result-overview">${escapeHtml(item.overview)}</p>` : ""}
        ${item.keyPoints?.length ? `<ul class="bullet-list template-result-points">${item.keyPoints.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>` : ""}
      </div>
      ${item.sections?.length ? `
        <div class="skill-sections">
          ${item.sections.map((section) => `
            <div class="content-block skill-section-card">
              <div class="content-block-head skill-section-head"><h3>${escapeHtml(section.title ?? "")}</h3></div>
              ${section.summary ? `<p class="skill-section-summary">${escapeHtml(section.summary)}</p>` : ""}
              ${section.bullets?.length ? `<ul class="bullet-list skill-section-points">${section.bullets.map((bullet) => `<li>${escapeHtml(bullet)}</li>`).join("")}</ul>` : ""}
            </div>
          `).join("")}
        </div>
      ` : ""}
    </div>
  `;
}

function getSelectedRun() {
  return (state.bootstrap?.runs ?? []).find((item) => item.id === state.selectedHistoryRunId) ?? null;
}

function getProgressSource() {
  if (state.activeTaskStatus) {
    const phaseLabel = state.activeTaskStatus.phaseLabel ?? "处理中";
    const subtitle = state.activeTaskStatus.message ?? phaseLabel;
    const detailLines = [];
    if (state.activeTaskStatus.errorDetail) {
      detailLines.push(state.activeTaskStatus.errorDetail);
    }
    return {
      title: "当前进度",
      phaseLabel,
      subtitle,
      progressPercent: state.activeTaskStatus.progressPercent ?? 0,
      detailLines,
      history: Array.isArray(state.activeTaskStatus.history) ? state.activeTaskStatus.history : [],
    };
  }

  if (state.selectedHistoryRunId) {
    const runPayload = state.runPayloads[state.selectedHistoryRunId];
    if (runPayload?.progress) {
      return runPayload.progress;
    }
  }

  return TOOL_IDLE_PROGRESS[state.activeToolView] ?? TOOL_IDLE_PROGRESS[DEFAULT_VIEW];
}

function bindEvents() {
  app.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.activeToolView = button.getAttribute("data-view");
      state.selectedHistoryRunId = null;
      state.progressDetailsOpen = false;
      clearToast();
      window.location.hash = `#/${state.activeToolView}`;
      safeRenderApp();
      if (state.activeToolView === "share_link") {
        await refreshPlatformStatuses();
      }
    });
  });

  app.querySelectorAll("[data-history-select]").forEach((button) => {
    button.addEventListener("click", async () => {
      await openProject(button.getAttribute("data-history-select"));
    });
  });

  app.querySelectorAll("[data-text-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.textMode = button.getAttribute("data-text-mode");
      safeRenderApp();
    });
  });

  app.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      syncSettingsFormFromDom();
      await handleAction(button.getAttribute("data-action"), button.dataset);
    });
  });

  app.querySelectorAll(".start-page-shell--interactive").forEach((node) => {
    node.addEventListener("keydown", async (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        await handleAction("enter-workspace");
      }
    });
  });

  app.querySelectorAll("[data-setting]").forEach((input) => {
    input.addEventListener("input", (event) => {
      const value = normalizeSettingInput(input.dataset.setting, event.target.value);
      if (value !== event.target.value) {
        event.target.value = value;
      }
      state.settingsForm[input.dataset.setting] = value;
    });
  });

  const shareLinkInput = app.querySelector("#share-link-input");
  if (shareLinkInput) {
    shareLinkInput.addEventListener("input", (event) => {
      state.shareLink = event.target.value;
      safeRenderApp();
    });
  }

  const pasteInput = app.querySelector("#paste-input");
  if (pasteInput) {
    pasteInput.addEventListener("input", (event) => {
      state.pastedText = event.target.value;
    });
  }

  const localInput = app.querySelector("#local-media-input");
  if (localInput) {
    localInput.addEventListener("change", (event) => {
      const file = event.target.files?.[0] ?? null;
      state.localMediaFile = file;
      state.localMediaLabel = file?.name ?? "未选择文件";
      safeRenderApp();
    });
  }

  const textInput = app.querySelector("#text-file-input");
  if (textInput) {
    textInput.addEventListener("change", (event) => {
      const file = event.target.files?.[0] ?? null;
      state.textFile = file;
      state.textFileLabel = file?.name ?? "未选择文件";
      safeRenderApp();
    });
  }

  const recoveryInput = app.querySelector("#recovery-dir-input");
  if (recoveryInput) {
    recoveryInput.addEventListener("change", (event) => {
      const files = Array.from(event.target.files ?? []);
      state.recoveryFiles = files;
      state.recoveryDirLabel = files[0]?.webkitRelativePath?.split("/")[0] ?? files[0]?.name ?? "未选择目录";
      safeRenderApp();
    });
  }

  const runtimeResourceInput = app.querySelector("#runtime-resource-file-input");
  if (runtimeResourceInput) {
    runtimeResourceInput.addEventListener("change", async (event) => {
      const file = event.target.files?.[0] ?? null;
      const resourceId = event.target.dataset.resourceId;
      event.target.value = "";
      if (resourceId && file) {
        await uploadRuntimeResourceFile(resourceId, file);
      }
    });
  }

  const toast = app.querySelector("[data-toast-id]");
  if (toast) {
    toast.addEventListener("mouseenter", () => {
      toast.classList.add("is-paused");
      pauseToastTimer();
    });
    toast.addEventListener("mouseleave", () => {
      toast.classList.remove("is-paused");
      resumeToastTimer();
    });
  }
}

function syncSettingsFormFromDom() {
  app.querySelectorAll("[data-setting]").forEach((input) => {
    if (input.dataset.setting) {
      const value = normalizeSettingInput(input.dataset.setting, input.value);
      if (value !== input.value) {
        input.value = value;
      }
      state.settingsForm[input.dataset.setting] = value;
    }
  });
}

function normalizeSettingInput(setting, value) {
  const text = String(value ?? "");
  if (setting === "summaryApiKey") {
    return text.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)[0] ?? "";
  }
  return text.replace(/[\r\n]+/g, " ").trim();
}

async function handleAction(action, dataset = {}) {
  clearToast();
  if (isActionDisabled(action) && !["toggle-progress-details", "toggle-raw-transcript", "dismiss-toast", "enter-workspace", "retry-bootstrap"].includes(action)) {
    return;
  }
  try {
    switch (action) {
      case "enter-workspace":
        if (state.startPageTransitioning) {
          return;
        }
        state.startPageTransitioning = true;
        app.querySelector(".start-page-shell")?.classList.add("is-leaving");
        window.clearTimeout(startPageTransitionTimer);
        startPageTransitionTimer = window.setTimeout(() => {
          state.startPageEntered = true;
          state.startPageTransitioning = false;
          state.workspaceIntro = true;
          safeRenderApp();
          window.clearTimeout(workspaceIntroTimer);
          workspaceIntroTimer = window.setTimeout(() => {
            state.workspaceIntro = false;
            safeRenderApp();
          }, 420);
        }, 300);
        return;
      case "retry-bootstrap":
        await refreshBootstrap({ preserveSelection: true });
        safeRenderApp();
        return;
      case "toggle-history":
        state.leftDrawerOpen = !state.leftDrawerOpen;
        safeRenderApp();
        return;
      case "toggle-health":
        state.rightDrawerMode = state.rightDrawerMode === "health" ? null : "health";
        safeRenderApp();
        return;
      case "toggle-settings":
        state.rightDrawerMode = state.rightDrawerMode === "settings" ? null : "settings";
        safeRenderApp();
        return;
      case "set-theme":
        setThemePreference(dataset.theme);
        safeRenderApp();
        return;
      case "toggle-progress-details":
        state.progressDetailsOpen = !state.progressDetailsOpen;
        safeRenderApp();
        return;
      case "toggle-raw-transcript":
        state.rawTranscriptOpen = !state.rawTranscriptOpen;
        safeRenderApp();
        return;
      case "refresh-history":
        await refreshBootstrap({ preserveSelection: true });
        safeRenderApp();
        return;
      case "run-health-check":
        await runHealthCheck();
        return;
      case "save-settings":
        await saveSettings();
        return;
      case "test-connection":
        await runSettingsAction("test-connection", "/api/settings/test-connection", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildSettingsRequestPayload()),
        });
        return;
      case "load-models":
        await runSettingsAction("load-models", "/api/settings/models", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildSettingsRequestPayload()),
        });
        return;
      case "test-model":
        await runSettingsAction("test-model", "/api/settings/test-model", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...buildSettingsRequestPayload(),
            modelName: state.settingsForm.summaryApiModel,
          }),
        });
        return;
      case "submit-share-link":
        await submitShareLink();
        return;
      case "submit-local-media":
        await submitLocalMedia();
        return;
      case "submit-text-file":
        await submitTextFile();
        return;
      case "submit-pasted-text":
        await submitPastedText();
        return;
      case "submit-recovery-upload":
        await submitRecoveryUpload();
        return;
      case "open-resume-candidate":
        if (state.bootstrap?.resumeCandidate?.runId) {
          await openProject(state.bootstrap.resumeCandidate.runId);
        }
        return;
      case "open-auth":
        await runPlatformAction(dataset.platform, "open");
        return;
      case "check-auth":
        await runPlatformAction(dataset.platform, "status");
        return;
      case "download-runtime-resource":
        if (dataset.resourceId) {
          await downloadRuntimeResource(dataset.resourceId);
        }
        return;
      case "select-runtime-resource-file":
        if (dataset.resourceId) {
          selectRuntimeResourceFile(dataset.resourceId);
        }
        return;
      case "retry-runtime-resource":
        if (dataset.resourceId) {
          await retryRuntimeResource(dataset.resourceId);
        }
        return;
      case "dismiss-resource-prompt":
        dismissResourcePrompt();
        return;
      case "resume-first-pass-inline":
        await resumeFirstPassInline();
        return;
      case "run-template":
        if (dataset.templateId) {
          await runTemplateAction(dataset.templateId);
        }
        return;
      case "rerun-template":
        if (dataset.templateId) {
          await runTemplateAction(dataset.templateId);
        }
        return;
      case "view-template-record":
        if (dataset.templateId) {
          state.templatePanelTab = "records";
          state.selectedTemplateRecordId = dataset.templateId;
          safeRenderApp();
        }
        return;
      case "select-template-record":
        if (dataset.templateId) {
          state.selectedTemplateRecordId = dataset.templateId;
          safeRenderApp();
        }
        return;
      case "set-template-tab":
        state.templatePanelTab = dataset.templateTab === "records" ? "records" : "catalog";
        safeRenderApp();
        return;
      case "cancel-task":
        await cancelActiveTask();
        return;
      case "dismiss-toast":
        dismissToast();
        return;
      case "confirm-cpu-fallback":
        await confirmCpuFallbackAndContinue();
        return;
      case "retry-gpu-check":
        await retryGpuCheck();
        return;
      case "toggle-transcription-details":
        state.transcriptionDetailsOpen = !state.transcriptionDetailsOpen;
        safeRenderApp();
        return;
      case "dismiss-transcription-prompt":
        dismissTranscriptionPrompt();
        return;
      default:
        return;
    }
  } catch (error) {
    showToast(error.message ?? "请求执行失败。", "error");
    safeRenderApp();
  }
}

async function refreshBootstrap({ preserveSelection } = { preserveSelection: true }) {
  state.bootstrapping = true;
  safeRenderApp();
  try {
    const payload = await fetchJson("/api/bootstrap");
    state.bootstrap = payload;
    state.bootstrapError = "";
    if (!preserveSelection || !state.selectedHistoryRunId || !payload.runs.some((item) => item.id === state.selectedHistoryRunId)) {
      state.selectedHistoryRunId = null;
    }
    state.settingsForm = {
      summaryApiBaseUrl: payload.settings?.summaryApiBaseUrl ?? "",
      summaryApiKey: "",
      summaryApiModel: payload.settings?.summaryApiModel ?? "",
      transcribeBackend: payload.settings?.transcribeBackend ?? "auto",
    };
    state.activeToolView = parseViewFromHash() || payload.defaultToolView || DEFAULT_VIEW;
  } catch (error) {
    state.bootstrapError = error.message;
  } finally {
    state.bootstrapping = false;
  }
}

async function openProject(runId) {
  if (!runId) {
    return;
  }
  state.selectedHistoryRunId = runId;
  state.loadingRunId = runId;
  state.progressDetailsOpen = false;
  state.rawTranscriptOpen = false;
  safeRenderApp();
  try {
    state.runPayloads[runId] = await fetchJson(`/api/runs/${encodeURIComponent(runId)}`);
    const records = state.runPayloads[runId]?.skillResults ?? [];
    state.selectedTemplateRecordId = records[0]?.id ?? null;
    state.templatePanelTab = "catalog";
    state.activeToolView = null;
    state.leftDrawerOpen = true;
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.loadingRunId = null;
    safeRenderApp();
  }
}

async function runHealthCheck() {
  state.settingsBusyAction = "run-health-check";
  safeRenderApp();
  try {
    const payload = await fetchJson("/api/health/run", { method: "POST" });
    applyRuntimeStatusPayload(payload);
    showToast("健康自检已完成。");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.settingsBusyAction = null;
  }
  safeRenderApp();
}

function applyRuntimeStatusPayload(payload) {
  if (!state.bootstrap || !payload) {
    return;
  }
  if (payload.health) {
    state.bootstrap.health = payload.health;
  }
  if (payload.browserRuntime) {
    state.bootstrap.browserRuntime = payload.browserRuntime;
  }
  if (payload.transcription) {
    state.bootstrap.transcription = payload.transcription;
  }
  if (payload.runtimeResources) {
    state.bootstrap.runtimeResources = payload.runtimeResources;
  }
}

async function saveSettings() {
  state.settingsBusyAction = "save-settings";
  safeRenderApp();
  try {
    const payload = await fetchJson("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildSettingsRequestPayload()),
    });
    state.bootstrap.settings = payload;
    state.settingsResult = { ok: true, message: "系统设置已保存。" };
    showToast("系统设置已保存。");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.settingsBusyAction = null;
  }
  safeRenderApp();
}

function buildSettingsRequestPayload() {
  syncSettingsFormFromDom();
  return {
    ...state.settingsForm,
    keepExistingApiKey: !state.settingsForm.summaryApiKey?.trim(),
  };
}

async function runSettingsAction(action, url, options = {}) {
  state.settingsBusyAction = action;
  safeRenderApp();
  try {
    state.settingsResult = await fetchJson(url, options);
    showToast(state.settingsResult.message ?? "请求已完成。");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.settingsBusyAction = null;
  }
  safeRenderApp();
}

async function runPlatformAction(platform, mode) {
  if (mode === "open" && !(await ensureRuntimeResourcesReady(["browser_runtime"], "open-auth"))) {
    return;
  }
  try {
    const payload = await fetchJson(`/api/auth/${encodeURIComponent(platform)}/${mode === "open" ? "open" : "status"}`, {
      method: mode === "open" ? "POST" : "GET",
    });
    replacePlatformCard(payload);
    showToast(mode === "open" ? "授权窗口已启动。" : "平台状态已刷新。");
  } catch (error) {
    showToast(error.message, "error");
  }
  safeRenderApp();
}

function dismissResourcePrompt() {
  state.resourcePrompt = null;
  state.pendingResourceAction = null;
  safeRenderApp();
}

async function refreshRuntimeResources() {
  const payload = await fetchJson("/api/runtime/resources");
  state.bootstrap.runtimeResources = payload;
  return payload.resources ?? [];
}

async function ensureRuntimeResourcesReady(resourceIds, pendingAction) {
  const resources = await refreshRuntimeResources();
  const missing = resourceIds.map((id) => resources.find((item) => item.id === id)).find((item) => item && !item.ready);
  if (!missing) {
    state.resourcePrompt = null;
    state.pendingResourceAction = null;
    return true;
  }
  state.resourcePrompt = missing;
  state.pendingResourceAction = pendingAction;
  safeRenderApp();
  return false;
}

async function downloadRuntimeResource(resourceId) {
  state.resourceBusyId = resourceId;
  safeRenderApp();
  try {
    const status = await fetchJson(`/api/runtime/resources/${encodeURIComponent(resourceId)}/download`, { method: "POST" });
    await pollRuntimeResource(resourceId, status);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.resourceBusyId = null;
    safeRenderApp();
  }
}

async function pollRuntimeResource(resourceId, initialStatus = null) {
  let status = initialStatus;
  for (let attempt = 0; attempt < 240; attempt += 1) {
    if (!status || ["downloading", "installing"].includes(status.state)) {
      await wait(1000);
      status = await fetchJson(`/api/runtime/resources/${encodeURIComponent(resourceId)}/status`);
      const resource = findRuntimeResource(resourceId);
      if (resource && state.resourcePrompt?.id === resourceId) {
        state.resourcePrompt = { ...resource, ...status };
      }
      safeRenderApp();
    }
    if (status.ready || status.state === "ready") {
      await refreshRuntimeResources();
      showToast("运行资源已安装。");
      await continuePendingResourceAction();
      return;
    }
    if (status.state === "error" || status.state === "invalid") {
      await refreshRuntimeResources();
      showToast(status.error || status.detail || "资源安装失败。", "error");
      return;
    }
  }
  showToast("资源下载仍在进行，请稍后刷新状态。");
}

async function retryRuntimeResource(resourceId) {
  state.resourceBusyId = resourceId;
  safeRenderApp();
  try {
    await refreshRuntimeResources();
    const resource = findRuntimeResource(resourceId);
    state.resourcePrompt = resource?.ready ? null : resource;
    if (resource?.ready) {
      showToast("运行资源已可用。");
      await continuePendingResourceAction();
    }
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.resourceBusyId = null;
    safeRenderApp();
  }
}

function selectRuntimeResourceFile(resourceId) {
  const input = app.querySelector("#runtime-resource-file-input");
  if (!input) {
    return;
  }
  input.dataset.resourceId = resourceId;
  input.click();
}

async function uploadRuntimeResourceFile(resourceId, file) {
  if (!file) {
    return;
  }
  state.resourceBusyId = resourceId;
  safeRenderApp();
  try {
    const formData = new FormData();
    formData.append("file", file);
    const status = await fetchJson(`/api/runtime/resources/${encodeURIComponent(resourceId)}/upload`, {
      method: "POST",
      body: formData,
    });
    await refreshRuntimeResources();
    if (status.ready || status.state === "ready") {
      showToast("运行资源已安装。");
      await continuePendingResourceAction();
    } else {
      showToast(status.detail || "资源状态已更新。");
    }
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.resourceBusyId = null;
    safeRenderApp();
  }
}

async function continuePendingResourceAction() {
  const pending = state.pendingResourceAction;
  state.resourcePrompt = null;
  state.pendingResourceAction = null;
  if (pending === "submit-share-link") {
    await submitShareLink();
  } else if (pending === "submit-local-media") {
    await submitLocalMedia();
  } else if (pending === "open-auth") {
    showToast("授权运行时已可用，请重新点击打开授权。");
  }
}

function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function dismissTranscriptionPrompt() {
  state.transcriptionPrompt = null;
  state.transcriptionDetailsOpen = false;
  state.pendingTranscriptionAction = null;
  safeRenderApp();
}

async function refreshTranscriptionCapability() {
  const payload = await fetchJson("/api/runtime/transcription-capability");
  state.bootstrap.transcription = payload;
  return payload;
}

async function ensureTranscriptionReady(actionKind) {
  if (!(await ensureRuntimeResourcesReady(["model", "transcription_runtime"], actionKind))) {
    return false;
  }
  const capability = await refreshTranscriptionCapability();
  if (capability.gpuStatus === "ready" || (capability.cpuFallbackAvailable && capability.allowCpuFallback)) {
    state.transcriptionPrompt = null;
    state.transcriptionDetailsOpen = false;
    state.pendingTranscriptionAction = null;
    return true;
  }
  if (capability.cpuFallbackAvailable) {
    state.pendingTranscriptionAction = actionKind;
    state.transcriptionPrompt = capability;
    state.transcriptionDetailsOpen = true;
    safeRenderApp();
    return false;
  }
  throw new Error(capability.gpuReason || capability.cpuReason || "当前电脑无法执行本地转录。");
}

async function confirmCpuFallbackAndContinue() {
  const pending = state.pendingTranscriptionAction;
  if (!pending) {
    dismissTranscriptionPrompt();
    return;
  }
  state.transcriptionBusyAction = "confirm-cpu-fallback";
  safeRenderApp();
  try {
    const payload = await fetchJson("/api/runtime/transcription-preference", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ allowCpuFallback: true }),
    });
    state.bootstrap.transcription = payload;
    state.transcriptionPrompt = null;
    state.transcriptionDetailsOpen = false;
    state.pendingTranscriptionAction = null;
    showToast("已启用 CPU 兼容模式。");
    if (pending === "submit-share-link") {
      await submitShareLink(true);
    } else if (pending === "submit-local-media") {
      await submitLocalMedia(true);
    }
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.transcriptionBusyAction = null;
    safeRenderApp();
  }
}

async function retryGpuCheck() {
  state.transcriptionBusyAction = "retry-gpu-check";
  safeRenderApp();
  try {
    const payload = await refreshTranscriptionCapability();
    const pending = state.pendingTranscriptionAction;
    state.transcriptionPrompt = payload.gpuStatus === "ready" ? null : payload;
    state.transcriptionDetailsOpen = payload.gpuStatus !== "ready";
    if (payload.gpuStatus === "ready") {
      state.pendingTranscriptionAction = null;
      showToast("GPU 环境已恢复。");
      if (pending === "submit-share-link") {
        await submitShareLink(true);
      } else if (pending === "submit-local-media") {
        await submitLocalMedia(true);
      }
    } else {
      showToast(payload.gpuReason || "GPU 仍不可用。", "error");
    }
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.transcriptionBusyAction = null;
    safeRenderApp();
  }
}

async function submitShareLink(skipTranscriptionGate = false) {
  state.activeTemplateId = null;
  if (!skipTranscriptionGate && !(await ensureTranscriptionReady("submit-share-link"))) {
    return;
  }
  const task = await fetchJson("/api/tasks/share-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      shareUrl: state.shareLink,
      summaryModel: state.settingsForm.summaryApiModel,
      transcribeBackend: state.settingsForm.transcribeBackend,
    }),
  });
  beginTask(task.taskId);
}

async function submitLocalMedia(skipTranscriptionGate = false) {
  state.activeTemplateId = null;
  if (!skipTranscriptionGate && !(await ensureTranscriptionReady("submit-local-media"))) {
    return;
  }
  const formData = new FormData();
  formData.append("file", state.localMediaFile);
  formData.append("summaryModel", state.settingsForm.summaryApiModel);
  formData.append("transcribeBackend", state.settingsForm.transcribeBackend);
  const task = await fetchJson("/api/tasks/local-media", {
    method: "POST",
    body: formData,
  });
  beginTask(task.taskId);
}

async function submitTextFile() {
  state.activeTemplateId = null;
  const formData = new FormData();
  formData.append("file", state.textFile);
  formData.append("summaryModel", state.settingsForm.summaryApiModel);
  const task = await fetchJson("/api/tasks/text-file", {
    method: "POST",
    body: formData,
  });
  beginTask(task.taskId);
}

async function submitPastedText() {
  state.activeTemplateId = null;
  const task = await fetchJson("/api/tasks/pasted-text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: state.pastedText,
      summaryModel: state.settingsForm.summaryApiModel,
    }),
  });
  beginTask(task.taskId);
}

async function submitRecoveryUpload() {
  state.activeTemplateId = null;
  const formData = new FormData();
  state.recoveryFiles.forEach((file) => {
    formData.append("files", file, file.webkitRelativePath || file.name);
  });
  const task = await fetchJson("/api/tasks/recovery/uploaded-dir", {
    method: "POST",
    body: formData,
  });
  beginTask(task.taskId);
}

async function resumeFirstPassInline() {
  const run = getSelectedRun();
  if (!run) {
    return;
  }
  state.activeTemplateId = null;
  const task = await fetchJson(`/api/runs/${encodeURIComponent(run.id)}/resume-first-pass`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ modelName: state.settingsForm.summaryApiModel }),
  });
  beginTask(task.taskId);
}

async function runTemplateAction(templateId) {
  const run = getSelectedRun();
  if (!run) {
    return;
  }
  state.activeTemplateId = templateId;
  const task = await fetchJson(`/api/runs/${encodeURIComponent(run.id)}/templates/${encodeURIComponent(templateId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ summaryModel: state.settingsForm.summaryApiModel }),
  });
  beginTask(task.taskId);
}

async function cancelActiveTask() {
  if (!state.activeTaskId) {
    return;
  }
  const payload = await fetchJson(`/api/tasks/${encodeURIComponent(state.activeTaskId)}/cancel`, {
    method: "POST",
  });
  state.activeTaskStatus = payload;
  showToast("已发送中止请求。");
  safeRenderApp();
}

function beginTask(taskId) {
  state.activeTaskId = taskId;
  state.activeTaskStatus = {
    state: "running",
    phase: "input",
    phaseLabel: "已排队",
    progressPercent: 0,
    message: "任务已创建。",
    updatedAt: new Date().toISOString().slice(0, 16).replace("T", " "),
    history: [
      {
        label: "已排队",
        detail: "任务已创建。",
        updatedAt: new Date().toISOString().slice(0, 16).replace("T", " "),
        progressPercent: 0,
      },
    ],
  };
  state.progressDetailsOpen = false;
  state.rawTranscriptOpen = false;
  state.templatePanelTab = "catalog";
  clearToast();
  safeRenderApp();
  startTaskPolling(taskId);
}

function startTaskPolling(taskId) {
  stopTaskPolling();
  state.taskPollTimer = window.setInterval(async () => {
    try {
      const status = await fetchJson(`/api/tasks/${encodeURIComponent(taskId)}/status`);
      state.activeTaskStatus = status;
      safeRenderApp();
      if (status.state === "succeeded" || status.state === "failed") {
        stopTaskPolling();
        state.activeTaskId = null;
        state.activeTemplateId = null;
        if (status.state === "succeeded") {
          showToast("任务已完成。");
          await refreshBootstrap({ preserveSelection: true });
          if (status.runId) {
            await openProject(status.runId);
          } else {
            safeRenderApp();
          }
        } else {
          const cancelled = status.errorCode === "task.cancelled";
          state.activeTaskStatus = status;
          showToast(status.errorDetail || status.message || (cancelled ? "任务已中止。" : "任务执行失败。"), cancelled ? "success" : "error");
          safeRenderApp();
        }
      }
    } catch (error) {
      stopTaskPolling();
      state.activeTaskId = null;
      state.activeTemplateId = null;
      showToast(error.message, "error");
      safeRenderApp();
    }
  }, 1000);
}

function stopTaskPolling() {
  if (state.taskPollTimer) {
    window.clearInterval(state.taskPollTimer);
    state.taskPollTimer = null;
  }
}

function replacePlatformCard(payload) {
  const cards = state.bootstrap?.platforms ?? [];
  const index = cards.findIndex((item) => item.platform === payload.platform);
  if (index >= 0) {
    cards[index] = payload;
  }
}

function showToast(message, tone = "success", duration = 4200) {
  const normalized = String(message ?? "").trim();
  if (!normalized) {
    return;
  }
  dismissToast(false);
  state.toast = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    tone,
    message: normalized,
    duration,
    remaining: duration,
    paused: false,
  };
  startToastTimer(duration);
}

function startToastTimer(duration) {
  window.clearTimeout(toastTimer);
  toastStartedAt = Date.now();
  toastRemaining = duration;
  toastTimer = window.setTimeout(() => {
    dismissToast();
  }, duration);
}

function pauseToastTimer() {
  if (!state.toast || state.toast.paused) {
    return;
  }
  window.clearTimeout(toastTimer);
  toastRemaining = Math.max(0, toastRemaining - (Date.now() - toastStartedAt));
  state.toast.remaining = toastRemaining;
  state.toast.paused = true;
}

function resumeToastTimer() {
  if (!state.toast || !state.toast.paused) {
    return;
  }
  state.toast.paused = false;
  state.toast.remaining = toastRemaining;
  startToastTimer(Math.max(1200, toastRemaining));
}

function dismissToast(shouldRender = true) {
  window.clearTimeout(toastTimer);
  toastTimer = null;
  toastRemaining = 0;
  toastStartedAt = 0;
  state.toast = null;
  if (shouldRender) {
    safeRenderApp();
  }
}

function clearToast() {
  dismissToast(false);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail =
      typeof payload === "string"
        ? payload
        : payload?.detail || payload?.message || `请求失败，状态码 ${response.status}`;
    throw new Error(detail);
  }
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#96;");
}


