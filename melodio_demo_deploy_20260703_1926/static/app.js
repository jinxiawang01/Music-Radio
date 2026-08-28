const EXAMPLES = [
  "适合深夜一个人开车的伤感华语歌",
  "和《乐队的夏天》里泸沽湖相似的歌曲",
  "jiaoanpu的歌曲",
  "像 Billie Eilish 那种暗黑流行风",
  "健身时让人热血的电子节奏",
  "许嵩什么时候生日",
  "换一首",
];

const DOMAIN_LABELS = {
  info_retrieval: "信息检索",
  content_reco: "内容推荐",
  function: "功能指令",
  creation: "创作/编辑",
  chitchat: "闲聊/兜底",
};

const INTENT_LABELS = {
  entity_search: "音乐实体·精搜",
  music_qa: "音乐百科",
  general_reco: "泛推荐",
  filtered_reco: "曲库限定推荐",
  similar_reco: "相似推荐",
  control: "操作指令",
  favorite: "收藏",
  implicit_feedback: "隐式反馈",
  music_gen: "音乐生成",
  lyrics: "歌词创作",
  continuation: "续写/变奏",
  adaptation: "参考/改编",
  vocal_separation: "人声分离",
  mixing: "混音/母带",
  chitchat: "闲聊",
  general_qa: "通用问答",
};

const form = document.querySelector("#form");
const queryInput = document.querySelector("#query");
const providerSelect = document.querySelector("#provider");
const providerStatus = document.querySelector("#providerStatus");
const heroNowPlaying = document.querySelector("#heroNowPlaying");
const radioLine = document.querySelector("#radioLine");
const heroTitle = document.querySelector(".now-panel h1");
const neteaseLoginBtn = document.querySelector("#neteaseLoginBtn");
const dispatchStatus = document.querySelector("#dispatchStatus");
const chips = document.querySelector("#chips");
const analysisEl = document.querySelector("#analysis");
const resultsEl = document.querySelector("#results");
const submitBtn = document.querySelector("#submitBtn");
const conversationEl = document.querySelector("#conversation");
const voiceBtn = document.querySelector("#voiceBtn");

const chatState = {
  sessionId: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
  history: [],
  lastGroups: [],
  lastMentionedSongs: [],
  currentSong: null,
  lastInteractionMode: "",
  messages: [],
  resultStore: {},
  latestResultId: "",
  autoplayNextResult: false,
  openingPlayed: false,
  favoriteSongs: new Set(),
};

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const voiceState = {
  recognition: null,
  listening: false,
  interimText: "",
  finalText: "",
  submitTimer: null,
  noSpeechTimer: null,
  manualStop: false,
  audioSnapshot: null,
  lastError: "",
  mode: "",
  mediaRecorder: null,
  mediaStream: null,
  mediaChunks: [],
  ws: null,
  audioContext: null,
  audioSource: null,
  audioProcessor: null,
  streamText: "",
  lastTranscriptAt: 0,
  stopRequested: false,
  submitted: false,
};
const VOICE_NO_SPEECH_HINT_MS = 8000;
const VOICE_MIC_PERMISSION_TIMEOUT_MS = 2500;
const VOICE_ASR_SAMPLE_RATE = 16000;
const VOICE_STREAM_BUFFER_SIZE = 2048;
let lockedScrollY = null;

const radioState = {
  timeline: [],
  index: 0,
  playing: false,
  loading: false,
  currentData: null,
  djAudio: new Audio(),
  musicAudio: new Audio(),
  musicAudioB: new Audio(),
  activeMusic: null,
  playToken: 0,
  fades: new Map(),
  watchdogTimer: null,
  activeRoot: null,
  hydratingQueue: false,
  continuingQueue: false,
  continuationPromise: null,
  continuationCount: 0,
  maxContinuations: 4,
  djGeneration: 0,
  autoplayUnlockPromise: null,
  debugEvents: [],
};

radioState.djAudio.preload = "auto";
radioState.musicAudio.preload = "auto";
radioState.musicAudioB.preload = "auto";
radioState.djAudio.volume = 1;
radioState.musicAudio.volume = 0;
radioState.musicAudioB.volume = 0;
radioState.activeMusic = radioState.musicAudio;

function configureManagedAudio(audio, kind = "music") {
  if (!audio) return;
  audio.preload = "auto";
  audio.playsInline = true;
  audio.setAttribute?.("playsinline", "");
  if (!audio.dataset) audio.dataset = {};
  audio.dataset.managedAudio = kind;
  if (kind === "music") {
    audio.autoplay = false;
    audio.defaultMuted = false;
    if (!audio.style) audio.style = {};
    audio.style.display = "none";
    if (document.body && !audio.isConnected) {
      document.body.appendChild(audio);
    }
  }
}

function configureManagedAudios() {
  configureManagedAudio(radioState.musicAudio, "music");
  configureManagedAudio(radioState.musicAudioB, "music");
  configureManagedAudio(radioState.djAudio, "dj");
}
configureManagedAudios();
document.addEventListener("DOMContentLoaded", configureManagedAudios);

const RADIO_VOLUME = {
  dj: 1,
  music: 0.58,
  ducked: 0.06,
  voiceListenMusic: 0.04,
  bed: 0.28,
  fadeMs: 1200,
  duckMs: 1400,
  voiceDuckMs: 180,
  restoreMs: 1800,
  restoreDelayMs: 250,
  introOverlapMs: 1500,
};

const AUTOPLAY_PRIMER_SRC = "data:audio/wav;base64,UklGRmQGAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YUAGAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";

const SILENT_AUDIO_SRC = "data:audio/mp3;base64,//uQZAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAACcQCAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg";

function esc(value) {
  return String(value ?? "").replace(/[&<>"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  })[char]);
}

function selectorEsc(value) {
  if (window.CSS?.escape) return window.CSS.escape(String(value));
  return String(value).replace(/["\\]/g, "\\$&");
}

function mediaUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^(https?:|data:|blob:)/i.test(raw)) return raw;
  if (window.location.protocol === "file:") {
    return `http://127.0.0.1:7890${raw.startsWith("/") ? raw : `/${raw}`}`;
  }
  return new URL(raw, window.location.origin).href;
}

function apiUrl(path) {
  const raw = String(path || "");
  if (/^https?:\/\//i.test(raw)) return raw;
  if (window.location.protocol === "file:") {
    return `http://127.0.0.1:7890${raw.startsWith("/") ? raw : `/${raw}`}`;
  }
  return raw;
}

function proxiedMusicUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (!/^https?:\/\//i.test(raw)) return raw;
  return apiUrl(`/audio-proxy?url=${encodeURIComponent(raw)}`);
}

function intentText(analysis) {
  if (!analysis) return "";
  const domain = DOMAIN_LABELS[analysis.domain] || analysis.domain || "";
  const intent = INTENT_LABELS[analysis.intent] || analysis.intent || "";
  return `${domain} · ${intent}`;
}

function renderProviders(data) {
  providerSelect.innerHTML = data.providers.map((provider) => (
    `<option value="${esc(provider.id)}" ${provider.id === data.default ? "selected" : ""}>
      ${esc(provider.label)}${provider.configured ? "" : "（未配置）"}
    </option>`
  )).join("");
  providerStatus.textContent = "";
}

function setDispatchStatus(text, { active = true } = {}) {
  if (!dispatchStatus) return;
  dispatchStatus.textContent = text || "Ready";
  const isActive = active && text !== "Ready";
  if (typeof dispatchStatus.classList?.toggle === "function") {
    dispatchStatus.classList.toggle("is-active", isActive);
  } else if (isActive) {
    dispatchStatus.classList?.add?.("is-active");
  } else {
    dispatchStatus.classList?.remove?.("is-active");
  }
}

function showNeteaseLoginModal({ qrimg, key }) {
  const existing = document.querySelector(".netease-login-modal");
  if (existing) existing.remove();
  const modal = document.createElement("div");
  modal.className = "netease-login-modal";
  modal.innerHTML = `
    <div class="netease-login-card">
      <button class="netease-login-close" type="button" aria-label="关闭">×</button>
      <h2>登录网易云音乐</h2>
      <p>用网易云音乐 App 扫码登录。登录态只保存在本机 demo 的 state 目录里。</p>
      ${qrimg ? `<img src="${esc(qrimg)}" alt="网易云登录二维码" />` : ""}
      <div class="netease-login-status">等待扫码...</div>
    </div>
  `;
  document.body.appendChild(modal);
  const status = modal.querySelector(".netease-login-status");
  modal.querySelector(".netease-login-close")?.addEventListener("click", () => modal.remove());
  pollNeteaseLogin(key, status, modal);
}

async function pollNeteaseLogin(key, statusEl, modal) {
  let stopped = false;
  modal.querySelector(".netease-login-close")?.addEventListener("click", () => { stopped = true; });
  for (let i = 0; i < 90 && !stopped && document.body.contains(modal); i += 1) {
    try {
      const response = await fetch(apiUrl(`/netease-login/check?key=${encodeURIComponent(key)}`));
      const data = await response.json();
      if (data.code === 800) {
        statusEl.textContent = "二维码已过期，请重新打开登录。";
        return;
      }
      if (data.code === 801) {
        statusEl.textContent = "等待扫码...";
      } else if (data.code === 802) {
        statusEl.textContent = "已扫码，请在手机上确认登录。";
      } else if (data.code === 803) {
        statusEl.textContent = data.cookie_saved ? "登录成功，已保存网易云登录态。" : "登录成功，但未拿到 Cookie。";
        neteaseLoginBtn.textContent = "网易云已登录";
        window.setTimeout(() => modal.remove(), 900);
        return;
      } else if (data.error) {
        statusEl.textContent = `登录检查失败：${data.error}`;
      }
    } catch (error) {
      statusEl.textContent = `登录检查失败：${error.message}`;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 2000));
  }
}

async function startNeteaseLogin() {
  neteaseLoginBtn.disabled = true;
  neteaseLoginBtn.textContent = "生成二维码...";
  try {
    const response = await fetch(apiUrl("/netease-login/qr"), { method: "POST" });
    const data = await response.json();
    if (data.error || !data.key) {
      throw new Error(data.error || "二维码生成失败");
    }
    showNeteaseLoginModal(data);
  } catch (error) {
    alert(`网易云登录失败：${error.message}`);
  } finally {
    neteaseLoginBtn.disabled = false;
    if (neteaseLoginBtn.textContent === "生成二维码...") {
      neteaseLoginBtn.textContent = "登录网易云";
    }
  }
}

async function refreshNeteaseLoginState() {
  if (!neteaseLoginBtn) return;
  try {
    const response = await fetch(apiUrl("/netease-auth-status"));
    const data = await response.json();
    if (data.cookie_configured && data.stream_ok) {
      neteaseLoginBtn.textContent = "网易云已登录";
      neteaseLoginBtn.classList.add("is-logged-in");
      neteaseLoginBtn.title = "网易云登录态有效";
    } else if (data.cookie_configured) {
      neteaseLoginBtn.textContent = "网易云需刷新";
      neteaseLoginBtn.classList.remove("is-logged-in");
      neteaseLoginBtn.title = data.error || "已配置 Cookie，但当前测试歌曲不可播";
    } else {
      neteaseLoginBtn.textContent = "登录网易云";
      neteaseLoginBtn.classList.remove("is-logged-in");
      neteaseLoginBtn.title = "未检测到网易云登录态";
    }
  } catch (error) {
    neteaseLoginBtn.textContent = "登录网易云";
    neteaseLoginBtn.classList.remove("is-logged-in");
    neteaseLoginBtn.title = `网易云状态检查失败：${error.message}`;
  }
}

function flattenSongs(groups) {
  const songs = [];
  (groups || []).forEach((group) => {
    (group.songs || []).forEach((song) => {
      songs.push({
        ...song,
        title: song.title || "",
        artist: song.artist || "",
        image_url: song.image_url || song.cover_url || song.album_image_url || "",
        cover_url: song.cover_url || song.image_url || song.album_image_url || "",
        group: group.title || "",
      });
    });
  });
  return songs.filter((song) => song.title && song.artist);
}

function songKey(song) {
  return `${String(song?.title || "").trim().toLowerCase()}|||${String(song?.artist || "").trim().toLowerCase()}`;
}

function dedupeSongs(songs) {
  const seen = new Set();
  return (songs || []).filter((song) => {
    const key = songKey(song);
    if (!song?.title || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function queryHasAny(query, words) {
  return words.some((word) => query.includes(word));
}

function isExplicitNewMusicRequest(query) {
  const q = String(query || "").trim();
  if (!q) return false;
  if (/《[^》]+》/.test(q) || /[-—–]/.test(q)) return true;
  const hasMusicAction = queryHasAny(q, ["播放", "放", "播", "来", "听", "推荐", "找", "挑", "搜"]);
  const hasMusicTarget = queryHasAny(q, ["的歌", "歌曲", "作品", "歌手", "专辑"]);
  if (hasMusicAction && hasMusicTarget) return true;
  if (/([一二两三四五六七八九十1-9]\s*(首|支|个|段)).*(的歌|歌曲|作品)/.test(q)) return true;
  return false;
}

function localControlTypeForQuery(query) {
  const q = String(query || "").trim();
  if (!q) return "";
  const lower = q.toLowerCase();
  const hasContext = Boolean(chatState.currentSong?.title || chatState.lastGroups?.length || chatState.lastMentionedSongs?.length || radioState.currentData);
  if (queryHasAny(q, ["这首", "这首歌", "当前", "现在这首", "刚才那首", "刚刚那首", "它", "这歌"])
    && queryHasAny(q, ["播放", "放一下", "放这", "来这", "起播"])) {
    return "";
  }
  if ((queryHasAny(q, ["播放", "放一下", "开始播放"]) && queryHasAny(q, ["的歌", "歌曲", "专辑", "歌手"]))
    || /^(播放|放一下|开始播放|放)\s*[\u4e00-\u9fffA-Za-z0-9· ._-]{2,30}(的|[-—–])[\u4e00-\u9fffA-Za-z0-9· ._-]{1,30}/.test(q)
    || /《[^》]+》/.test(q)
    || /\S+\s*[-—–]\s*\S+/.test(q)) {
    return "";
  }
  const recommendationSignals = [
    "推荐", "来点", "来些", "想听", "听点", "听些", "适合", "类似", "相似", "像",
    "一批", "一组", "几首", "歌单", "风格", "更欢快", "更伤感", "更燃", "换一批",
  ];
  const explicitTransport = queryHasAny(q, [
    "下一首", "上一首", "换一首", "换首", "换歌", "切歌", "跳过",
    "不要这首", "这首不好听", "不好听", "回到上一首", "切回上一首",
  ]);
  if (!explicitTransport && (queryHasAny(q, recommendationSignals) || queryHasAny(lower, ["similar", "recommend"]))) {
    return "";
  }
  if (queryHasAny(q, ["现在这首歌叫啥", "现在这首歌叫什么", "当前播放", "现在放的", "正在放的", "这首歌叫什么", "这首叫什么", "还有多久"])) {
    return hasContext ? "status" : "";
  }
  if (queryHasAny(q, ["音量大", "声音大", "调大", "大声点", "再大声", "太小声"])) return "volume_up";
  if (queryHasAny(q, ["音量小", "声音小", "调小", "小声点", "再小声", "太大声"])) return "volume_down";
  if (/换\s*[二两三四五六七八九十2-9]\s*首/.test(q) || /跳过\s*[二两三四五六七八九十2-9]\s*首/.test(q)) return hasContext ? "next" : "";
  if (queryHasAny(q, ["上一首", "回到上一首", "切回上一首"])) return hasContext ? "previous" : "";
  if (queryHasAny(q, ["下一首", "换一首", "换首", "换歌", "切歌", "跳过", "不要这首", "这首不好听", "不好听"])) return hasContext ? "next" : "";
  if (queryHasAny(q, ["暂停", "停一下", "暂停播放"]) || q === "停") return hasContext ? "pause" : "";
  if (queryHasAny(q, ["继续", "接着放", "继续播放", "恢复播放", "开始播放"])) return hasContext ? "resume" : "";
  return "";
}

function controlStepCountForQuery(query) {
  const q = String(query || "");
  const match = q.match(/(?:换|跳过|切|下)\s*([二两三四五六七八九十2-9])\s*首/);
  if (!match) return 1;
  const raw = match[1];
  const value = {
    二: 2,
    两: 2,
    三: 3,
    四: 4,
    五: 5,
    六: 6,
    七: 7,
    八: 8,
    九: 9,
    十: 10,
  }[raw] || Number(raw);
  return Number.isFinite(value) ? Math.max(1, Math.min(10, value)) : 1;
}

function localControlAnswer(controlType) {
  const current = chatState.currentSong || {};
  if (controlType === "status") {
    if (current.title) {
      return `现在在放《${current.title}》${current.artist ? `，${current.artist}` : ""}。`;
    }
    return "现在还没有正在播放的歌曲。";
  }
  return {
    next: "好的，现在为你切到下一首。",
    previous: "好的，现在为你切回上一首。",
    pause: "好的，现在为你暂停播放。",
    resume: "好的，现在继续为你播放。",
    volume_up: "好的，现在为你调大音量。",
    volume_down: "好的，现在为你调小音量。",
  }[controlType] || "好的，已收到你的播放控制指令。";
}

function localControlPayload(query, controlType) {
  const answer = localControlAnswer(controlType);
  const count = controlType === "next" || controlType === "previous" ? controlStepCountForQuery(query) : 1;
  return {
    query,
    analysis: {
      domain: "function",
      intent: "control",
      entity_type: "unknown",
      action: controlType === "status" ? "query_status" : "control",
      identified: true,
      reference: query,
      traits: ["播控指令"],
      target_entity: {},
    },
    answer,
    groups: [],
    entities: [],
    control: controlType === "status" ? null : { type: controlType, song: {}, count },
    dj: {
      program_title: "Melodio 播控",
      speech: answer,
      segments: [
        {
          type: "quick_touch",
          should_speak: true,
          speech_text: answer,
          text: answer,
          position: "before",
          trackIndex: 0,
        },
      ],
    },
  };
}

function openingDjPayload() {
  const text = "欢迎来到 Melodio。我在这里陪你听歌，你可以告诉我现在的心情、场景，或者直接说想听哪首歌。";
  return {
    query: "__opening__",
    provider: providerSelect?.value || "local",
    analysis: {
      domain: "chitchat",
      intent: "chitchat",
      entity_type: "unknown",
      action: "answer",
      identified: true,
      reference: "开机问候",
      target_entity: { name: "", artist: "", album: "" },
      traits: ["DJ opening"],
    },
    answer: text,
    groups: [],
    entities: [],
    dj: {
      program_title: "Melodio",
      speech: text,
      segments: [
        {
          type: "quick_touch",
          should_speak: true,
          speech_text: text,
          text,
          position: "immediate",
          trackIndex: 0,
        },
      ],
    },
  };
}

function classifyInteractionMode(query) {
  const q = String(query || "").trim();
  const lower = q.toLowerCase();
  const hasContext = Boolean(chatState.currentSong?.title || chatState.lastGroups?.length || chatState.lastMentionedSongs?.length);
  if (isExplicitNewMusicRequest(q)) {
    return "exact_search";
  }
  const playbackWords = [
    "下一首", "上一首", "换一首", "切歌", "跳过", "暂停", "继续", "接着放", "恢复播放",
    "换首", "换歌", "不要这首", "这首不好听", "不好听", "回到上一首", "播刚才",
    "收藏", "红心", "这首", "当前", "现在这首", "刚才那首", "刚刚那首",
    "第1首", "第2首", "第3首", "第一首", "第二首", "第三首",
    "换一批", "换点", "更", "不要", "别", "类似", "相似",
  ];
  if (hasContext && queryHasAny(q, playbackWords)) {
    return "playback_dialogue";
  }
  if (/第\s*[一二三四五六七八九十\d]+\s*(首|个|条)/.test(q)) {
    return "playback_dialogue";
  }
  if (/《[^》]+》/.test(q) || /[-—–]/.test(q) || queryHasAny(q, ["播放", "放一下", "起播"])) {
    return "exact_search";
  }
  if (queryHasAny(lower, ["similar", "dream pop", "r&b", "kpop"]) || queryHasAny(q, [
    "推荐", "来点", "想听", "听点", "听些", "适合", "场景", "睡前", "生日",
    "下雨", "开车", "浪漫", "伤感", "开心", "热血", "暗黑", "像", "类似",
  ])) {
    return "fuzzy_query";
  }
  if (queryHasAny(q, ["的歌", "歌曲", "专辑", "歌手"]) || /^[A-Za-z0-9\s,'().!-]{2,}$/.test(q)) {
    return "exact_search";
  }
  return "fuzzy_query";
}

function contextPayload(query = "") {
  const interactionMode = classifyInteractionMode(query);
  const isNewMusicTask = isExplicitNewMusicRequest(query);
  const activeMusic = radioState.activeMusic;
  const playbackActive = Boolean(radioState.playing && activeMusic && !activeMusic.paused && !activeMusic.ended);
  return {
    session_id: chatState.sessionId,
    interaction_mode: interactionMode,
    playback_active: playbackActive,
    playback_status: playbackActive ? "playing" : (radioState.playing ? "active" : "idle"),
    history: chatState.history.slice(-6).map((item) => ({
      role: String(item.role || ""),
      content: String(item.content || "").slice(0, 600),
    })),
    last_groups: isNewMusicTask ? [] : sanitizeGroupsForApi(chatState.lastGroups),
    mentioned_songs: isNewMusicTask ? [] : sanitizeSongsForApi(chatState.lastMentionedSongs),
    current_song: isNewMusicTask ? {} : sanitizeSongForApi(chatState.currentSong),
  };
}

function sanitizeSongForApi(song) {
  if (!song || typeof song !== "object") return {};
  return {
    title: String(song.title || "").slice(0, 120),
    artist: String(song.artist || "").slice(0, 120),
    image_url: String(song.image_url || song.cover_url || "").slice(0, 500),
    group: String(song.group || "").slice(0, 120),
    reason: String(song.reason || "").slice(0, 240),
  };
}

function sanitizeGroupsForApi(groups) {
  return (groups || []).slice(0, 5).map((group) => ({
    title: String(group?.title || "").slice(0, 120),
    songs: (group?.songs || []).slice(0, 8).map(sanitizeSongForApi).filter((song) => song.title && song.artist),
  })).filter((group) => group.songs.length);
}

function sanitizeSongsForApi(songs) {
  return (songs || []).slice(0, 5).map(sanitizeSongForApi).filter((song) => song.title && song.artist);
}

function rememberTurn(query, data) {
  chatState.history.push({ role: "user", content: query });
  const intent = data?.analysis ? intentText(data.analysis) : "";
  const answer = data?.answer || "";
  const songs = flattenSongs(data?.groups || []);
  const summary = answer || (songs.length ? `返回 ${songs.length} 首歌：${songs.slice(0, 3).map((song) => `${song.title} - ${song.artist}`).join("；")}` : intent);
  chatState.history.push({ role: "assistant", content: summary });
  chatState.history = chatState.history.slice(-8);
  chatState.lastInteractionMode = classifyInteractionMode(query);
  if (data?.groups?.length) {
    chatState.lastGroups = data.groups;
  }
  if (Array.isArray(data?.mentioned_songs) && data.mentioned_songs.length) {
    chatState.lastMentionedSongs = data.mentioned_songs;
  } else if (songs.length) {
    chatState.lastMentionedSongs = songs.slice(0, 5);
  }
}

function scrollConversation() {
  if (!document.body?.classList?.contains("debug-ui")) return;
  requestAnimationFrame(() => {
    const composerHeight = document.querySelector(".composer")?.offsetHeight || 0;
    const target = Math.max(0, conversationEl.getBoundingClientRect().bottom + window.scrollY - window.innerHeight + composerHeight + 28);
    window.scrollTo({ top: target, behavior: "smooth" });
  });
}

function lockViewportPosition() {
  lockedScrollY = window.scrollY;
}

function restoreViewportPosition() {
  if (lockedScrollY === null) return;
  const target = lockedScrollY;
  requestAnimationFrame(() => {
    window.scrollTo({ top: target, behavior: "auto" });
  });
}

function unlockViewportPosition() {
  restoreViewportPosition();
  window.setTimeout(() => {
    lockedScrollY = null;
  }, 250);
}

function messageArticleHtml(item) {
  return `
    <article data-message-id="${esc(item.id)}" class="message ${item.role === "user" ? "user-message" : "assistant-message"} ${item.pending ? "pending-message" : ""}">
      <span>${item.role === "user" ? "你" : "Melodio"}</span>
      <div class="message-body">${item.html}</div>
    </article>
  `;
}

function renderMessageIncrementally(item, { scroll = true } = {}) {
  if (typeof conversationEl.insertAdjacentHTML !== "function") {
    renderConversation();
    return;
  }
  if (chatState.messages.length === 1) {
    conversationEl.innerHTML = "";
  }
  conversationEl.insertAdjacentHTML("beforeend", messageArticleHtml(item));
  bindDjAudioErrors(conversationEl);
  if (scroll) scrollConversation();
}

function addMessage(role, html, { pending = false, scroll = true } = {}) {
  const id = `msg-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const message = { id, role, html, pending };
  chatState.messages.push(message);
  renderMessageIncrementally(message, { scroll });
  return id;
}

function updateMessage(id, html, { pending = false, scroll = true } = {}) {
  const message = chatState.messages.find((item) => item.id === id);
  if (!message) return;
  message.html = html;
  message.pending = pending;
  const article = conversationEl.querySelector(`[data-message-id="${selectorEsc(id)}"]`);
  if (!article) {
    renderConversation();
    return;
  }
  article.className = `message ${message.role === "user" ? "user-message" : "assistant-message"} ${message.pending ? "pending-message" : ""}`;
  const body = article.querySelector(".message-body");
  if (body) body.innerHTML = html;
  bindDjAudioErrors(article);
  if (scroll) scrollConversation();
}

function bindDjAudioErrors(root = document) {
  root.querySelectorAll(".dj-audio").forEach((audio) => {
    if (!audio.dataset.radioBound) {
      audio.dataset.radioBound = "true";
      audio.addEventListener("play", () => {
        if (audio.dataset.nativePreview === "true") return;
        audio.pause();
        audio.currentTime = 0;
        startRadioFromDjAudio(audio);
      });
    }
    audio.addEventListener("error", () => {
      const parent = audio.closest(".dj-segment") || audio.parentElement;
      if (!parent || parent.querySelector(".dj-audio-error")) return;
      const note = document.createElement("div");
      note.className = "dj-audio-note dj-audio-error";
      note.textContent = "DJ 语音加载失败，请用 http://127.0.0.1:7890 打开 demo，并确认本地服务正在运行。";
      parent.appendChild(note);
    }, { once: true });
  });
}

function renderConversation() {
  if (!chatState.messages.length) {
    conversationEl.innerHTML = `
      <div class="welcome">
        <strong>Melodio 已就绪</strong>
        <span>直接说“周杰伦的歌”，接着说“播放第二首”或“换一批更欢快的”。</span>
      </div>
    `;
    return;
  }
  conversationEl.innerHTML = chatState.messages.map(messageArticleHtml).join("");
  bindDjAudioErrors(conversationEl);
}

function analysisHtml(analysis, answer) {
  if (!analysis) return "";
  const traits = (analysis.traits || []).map((trait) => `<span class="trait">${esc(trait)}</span>`).join("");
  const entity = analysis.entity_type && analysis.entity_type !== "unknown"
    ? `<span class="intent secondary">${esc(analysis.entity_type)} · ${esc(analysis.action || "")}</span>`
    : "";
  return `
    <div class="analysis-top">
      <span class="intent">${esc(intentText(analysis))}</span>
      ${entity}
      ${analysis.reference ? `<span class="reference">${esc(analysis.reference)}</span>` : ""}
    </div>
    ${traits ? `<div class="traits">${traits}</div>` : ""}
    ${answer ? `<p class="reason">${esc(answer)}</p>` : ""}
  `;
}

function djHtml(dj) {
  const segments = (dj?.segments || []).filter((segment) => (
    segment && (segment.speech_text || segment.text || segment.audio || segment.reason || segment.route)
  ));
  if (!dj || (!dj.speech && !dj.audio_url && !dj.program_title && !segments.length)) return "";
  const labelFor = (segment) => ({
    cold_open: "开场",
    bridge: "串场",
    quick_touch: "短句",
    back_announce: "收束",
    silence: "留白",
  }[segment.type] || segment.tag || "DJ");
  const segmentHtml = segments.length
    ? `<div class="dj-segments">${segments.map((segment, index) => {
      const speechText = segment.speech_text || segment.text || "";
      const spoken = Boolean(segment.should_speak && speechText);
      const audioSrc = mediaUrl(segment.audio);
      const playbackKey = segmentPlaybackKey(segment);
      const audio = segment.audio
        ? `<audio class="dj-audio" controls preload="metadata" src="${esc(audioSrc)}" data-segment-index="${index}" data-segment-key="${esc(playbackKey)}"></audio>`
        : "";
      const ttsNote = segment.tts_error
        ? `<div class="dj-audio-note">TTS 生成失败：${esc(segment.tts_error)}</div>`
        : segment.tts_skipped
          ? `<div class="dj-audio-note">这段未生成语音：${esc(segment.tts_skipped)}</div>`
          : "";
      const route = segment.route ? `<div class="dj-route">${esc(segment.route)}</div>` : "";
      const text = spoken
        ? `<p>${esc(speechText)}</p>`
        : `<p class="dj-silence">这一拍不说话，让两首歌直接接上${segment.reason ? `：${esc(segment.reason)}` : ""}</p>`;
      return `
        <article class="dj-segment ${spoken ? "" : "silent"}" data-segment-index="${index}" data-segment-key="${esc(playbackKey)}">
          <div class="dj-segment-tag">${esc(labelFor(segment))}</div>
          ${route}
          ${text}
          ${audio}
          ${ttsNote}
        </article>
      `;
    }).join("")}</div>`
    : "";
  const fallbackAudio = !segments.length && dj.audio_url
    ? `<audio class="dj-audio" controls preload="metadata" src="${esc(mediaUrl(dj.audio_url))}"></audio>`
    : "";
  return `
    <section class="dj-panel">
      <div class="dj-label">${esc(dj.program_title || "Melodio DJ")}</div>
      ${!segments.length && dj.speech ? `<p>${esc(dj.speech)}</p>` : ""}
      ${fallbackAudio}
      ${segmentHtml}
    </section>
  `;
}

function spokenSegments(dj) {
  return (dj?.segments || []).filter((segment) => (
    segment && segment.type !== "silence" && segment.audio && (segment.speech_text || segment.text)
  ));
}

function segmentsFor(dj, position, matcher) {
  return (dj?.segments || []).filter((segment) => (
    segment && segment.position === position && matcher(segment)
  ));
}

function segmentTrackIndex(segment) {
  return Number(segment?.trackIndex ?? 0);
}

function segmentPlaybackKey(segment) {
  if (!segment) return "";
  return [
    segment.type || "",
    segment.position || "",
    Number.isInteger(segment.trackIndex) ? segment.trackIndex : "",
    Number.isInteger(segment.afterTrackIndex) ? segment.afterTrackIndex : "",
    Number.isInteger(segment.beforeTrackIndex) ? segment.beforeTrackIndex : "",
    segment.audio || "",
    segment.speech_text || segment.text || "",
  ].join("|");
}

function buildRadioTimeline(data, tracks) {
  const dj = data?.dj || {};
  const originalSongs = flattenSongs(data.groups || []);
  const timelineDj = (dj.pending || dj.async_overlay) ? { ...dj, segments: [] } : dj;
  const djSegments = timelineDj.segments || [];
  const timeline = [];
  const playableByIndex = new Map();
  tracks.forEach((track, fallbackIndex) => {
    if (!track?.ok || !track.stream_url) return;
    const requestedIndex = Number.isInteger(track.requested_index) ? track.requested_index : fallbackIndex;
    playableByIndex.set(requestedIndex, track);
  });
  const tracksForTimeline = originalSongs
    .map((song, idx) => {
      const track = playableByIndex.get(idx);
      if (!track) return null;
      return {
        ...track,
        original_index: idx,
        display_title: song.title,
        display_artist: song.artist,
        display_image_url: song.image_url || song.cover_url || track.image_url || track.cover_url || "",
      };
    })
    .filter(Boolean);
  if (!tracksForTimeline.length) {
    return timeline;
  }

  tracksForTimeline.forEach((track, idx) => {
    const originalIndex = Number.isInteger(track.original_index) ? track.original_index : idx;
    const beforeSegments = segmentsFor(timelineDj, "before_track", (segment) => segmentTrackIndex(segment) === originalIndex);
    beforeSegments.forEach((segment) => {
      if (segment.type !== "silence" && segment.audio) {
        timeline.push({
          kind: "voice",
          segment,
          segmentIndex: djSegments.indexOf(segment),
          segmentKey: segmentPlaybackKey(segment),
          label: segment.speech_text || segment.text || "DJ",
        });
      }
    });
    timeline.push({ kind: "music", track, label: `${track.display_title || track.requested_title || track.title} - ${track.display_artist || track.requested_artist || track.artist}` });
      const afterSegments = segmentsFor(timelineDj, "after_track", (segment) => segmentTrackIndex(segment) === originalIndex);
    afterSegments.forEach((segment) => {
      if (segment.type !== "silence" && segment.audio) {
        timeline.push({
          kind: "voice",
          segment,
          segmentIndex: djSegments.indexOf(segment),
          segmentKey: segmentPlaybackKey(segment),
          label: segment.speech_text || segment.text || "DJ",
        });
      }
    });
    if (idx < tracksForTimeline.length - 1) {
      const nextTrack = tracksForTimeline[idx + 1];
      const nextOriginalIndex = Number.isInteger(nextTrack.original_index) ? nextTrack.original_index : idx + 1;
      const betweenSegments = segmentsFor(timelineDj, "between_tracks", (segment) => (
        Number(segment.afterTrackIndex) === originalIndex && Number(segment.beforeTrackIndex) === nextOriginalIndex
      ));
      betweenSegments.forEach((segment) => {
        if (segment.type !== "silence" && segment.audio) {
          timeline.push({
            kind: "voice",
            segment,
            segmentIndex: djSegments.indexOf(segment),
            segmentKey: segmentPlaybackKey(segment),
            label: segment.speech_text || segment.text || "DJ",
          });
        }
      });
    }
  });
  return timeline;
}

function playableTrackIndexes(tracks) {
  const indexes = new Set();
  (tracks || []).forEach((track, fallbackIndex) => {
    if (!track?.ok || !track.stream_url) return;
    indexes.add(Number.isInteger(track.requested_index) ? track.requested_index : fallbackIndex);
  });
  return indexes;
}

function segmentMatchesPlayable(segment, playableIndexes) {
  if (!segment || !playableIndexes.size) return false;
  if (segment.position === "before_track" || segment.position === "after_track") {
    return playableIndexes.has(segmentTrackIndex(segment));
  }
  if (segment.position === "between_tracks") {
    return playableIndexes.has(Number(segment.afterTrackIndex)) && playableIndexes.has(Number(segment.beforeTrackIndex));
  }
  return true;
}

function alignDjToPlayableTracks(data, tracks) {
  const playableIndexes = playableTrackIndexes(tracks);
  if (!data?.dj?.segments || !playableIndexes.size) return data;
  const segments = data.dj.segments.filter((segment) => (
    segment.type === "silence" || segmentMatchesPlayable(segment, playableIndexes)
  ));
  const speech = segments.map((segment) => segment.speech_text || segment.text || "").filter(Boolean).join(" ");
  return {
    ...data,
    dj: {
      ...data.dj,
      segments,
      speech,
      display_text: speech,
      tts_text: speech,
      play: (data.dj.play || []).filter((_, index) => playableIndexes.has(index)),
    },
  };
}

function playableGroupsFromTracks(groups, tracks) {
  const playableIndexes = playableTrackIndexes(tracks);
  if (!playableIndexes.size) return groups || [];
  const nextGroups = [];
  let songIndex = 0;
  (groups || []).forEach((group) => {
    const songs = [];
    (group.songs || []).forEach((song) => {
      if (playableIndexes.has(songIndex)) songs.push(song);
      songIndex += 1;
    });
    if (songs.length) {
      nextGroups.push({ ...group, songs });
    }
  });
  return nextGroups;
}

function reorderGroupsByPlayable(groups, tracks) {
  const playableIndexes = playableTrackIndexes(tracks);
  if (!playableIndexes.size) return groups || [];
  const playableGroups = playableGroupsFromTracks(groups, tracks);
  const playableKeys = new Set(flattenSongs(playableGroups).map((song) => `${song.title}|||${song.artist}`));
  const fallbackGroups = [];
  (groups || []).forEach((group) => {
    const songs = (group.songs || []).filter((song) => !playableKeys.has(`${song.title}|||${song.artist}`));
    if (songs.length) fallbackGroups.push({ ...group, songs });
  });
  return [...playableGroups, ...fallbackGroups].slice(0, 3);
}

function sourceGroupsForPlayback(data) {
  if (!data) return [];
  if (!data._sourceGroups) {
    data._sourceGroups = data.groups || [];
  }
  return data._sourceGroups;
}

function alignResultToPlayableQueue(data, tracks, root) {
  const playableGroups = playableGroupsFromTracks(sourceGroupsForPlayback(data), tracks);
  if (playableGroups.length) {
    data.groups = playableGroups;
    const resultId = root?.dataset?.resultId || "";
    if (resultId && chatState.resultStore[resultId]) {
      chatState.resultStore[resultId].groups = data.groups;
    }
  }
  return alignDjToPlayableTracks(data, tracks);
}

function mergeContinuationGroups(data, nextGroups) {
  if (!data || !nextGroups?.length) return [];
  if (!data._sourceGroups) data._sourceGroups = data.groups || [];
  const existingKeys = new Set(flattenSongs(data._sourceGroups).map(songKey));
  const acceptedGroups = [];
  nextGroups.forEach((group) => {
    const songs = [];
    (group.songs || []).forEach((song) => {
      const key = songKey(song);
      if (!song?.title || existingKeys.has(key)) return;
      existingKeys.add(key);
      songs.push(song);
    });
    if (songs.length) acceptedGroups.push({ ...group, songs });
  });
  if (!acceptedGroups.length) return [];
  data._sourceGroups = [...data._sourceGroups, ...acceptedGroups];
  data.groups = data._sourceGroups;
  return acceptedGroups;
}

function musicItemsRemaining() {
  return radioState.timeline.slice(radioState.index + 1).filter((item) => item?.kind === "music").length;
}

function shouldPrepareContinuation() {
  return musicItemsRemaining() <= 2;
}

function playbackExcludeSongs(data) {
  const fromSource = flattenSongs(sourceGroupsForPlayback(data));
  const fromTimeline = radioState.timeline
    .filter((item) => item?.kind === "music")
    .map((item) => ({
      title: item.track?.display_title || item.track?.requested_title || item.track?.title || "",
      artist: item.track?.display_artist || item.track?.requested_artist || item.track?.artist || "",
    }));
  return dedupeSongs([...fromSource, ...fromTimeline]).slice(0, 30);
}

function refreshDjPanel(root, dj) {
  const current = root?.querySelector(".dj-panel");
  const html = djHtml(dj);
  if (current && html) {
    current.outerHTML = html;
    bindDjAudioErrors(root);
  } else if (current && !html) {
    current.remove();
  }
}

async function hydrateDjTts(data, root) {
  const segments = (data?.dj?.segments || []).filter((segment) => (
    segment && segment.type !== "silence" && (segment.speech_text || segment.text)
  ));
  if (!segments.length) return;
  if (segments.some((segment) => segment.audio)) {
    if (!flattenSongs(data.groups || []).length) {
      playSpeechOnlyDj(data, root);
    } else {
      queueOrPlayAsyncDj(data, root);
    }
    return;
  }
  const token = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const generation = radioState.djGeneration;
  root.dataset.ttsToken = token;
  try {
    radioDebugEvent("dj_tts_request", `segments=${segments.length}`, root);
    const response = await fetch(apiUrl("/dj/tts"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dj: data.dj }),
    });
    const payload = await response.json();
    if (generation !== radioState.djGeneration || root.dataset.ttsToken !== token || !payload.dj) return;
    data.dj = { ...payload.dj, async_overlay: Boolean(data.dj?.async_overlay) };
    data.dj.pending = false;
    radioDebugEvent("dj_tts_done", `audio=${(firstPlayableDjSegment(data.dj)?.audio || "none").slice(0, 80)}`, root);
    refreshDjPanel(root, data.dj);
    if (!flattenSongs(data.groups || []).length && playSpeechOnlyDj(data, root)) {
      return;
    }
    queueOrPlayAsyncDj(data, root);
  } catch (error) {
    radioDebugEvent("dj_tts_error", error.message || String(error), root);
    updateRadioStatus(`DJ 语音生成失败：${error.message || "可先直接播放歌曲"}`, root);
  }
}

async function hydrateDjProgram(data, root) {
  if (!data?.dj?.pending || !root) return;
  if (flattenSongs(data.groups || []).length && !data.dj._playableQueueReady) {
    radioDebugEvent("dj_build_wait_playable_queue", "skip until playable tracks are known", root);
    return;
  }
  data.dj.async_overlay = true;
  const token = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const generation = radioState.djGeneration;
  root.dataset.djToken = token;
  try {
    const response = await fetch(apiUrl("/dj/build"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: data.query || "",
        provider: data.provider || "local",
        analysis: data.analysis || {},
        groups: sanitizeGroupsForApi(data.groups || []),
        answer: data.answer || "",
        context: contextPayload(data.query || ""),
      }),
    });
    const payload = await response.json();
    if (generation !== radioState.djGeneration || root.dataset.djToken !== token || !payload.dj) return;
    data.dj = { ...payload.dj, async_overlay: true };
    radioDebugEvent("dj_build_done", `segments=${(data.dj.segments || []).length}`, root);
    refreshDjPanel(root, data.dj);
    hydrateDjTts(data, root);
  } catch (error) {
    data.dj._buildStarted = false;
    radioDebugEvent("dj_build_error", error.message || String(error), root);
    updateRadioStatus(`DJ 串场生成失败：${error.message || "歌曲可以先播"}`, root);
  }
}

async function prefetchRadioStreams(data) {
  const songs = flattenSongs(data?.groups || []).slice(0, 5).map((song) => ({ title: song.title, artist: song.artist }));
  if (!songs.length) return;
  try {
    await fetch(apiUrl("/music-streams"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ songs }),
    });
  } catch (error) {
    // Playback will surface the actual error when the user starts the radio.
  }
}

async function prefetchSingleSongStream(song, index = 0) {
  if (!song?.title) return;
  try {
    await fetch(apiUrl("/music-streams"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ songs: [{ title: song.title, artist: song.artist || "" }], offset: index }),
    });
  } catch (error) {
    // The radio start path will retry and surface errors if needed.
  }
}

function cancelFade(audio) {
  const frame = radioState.fades.get(audio);
  if (frame) cancelAnimationFrame(frame);
  radioState.fades.delete(audio);
}

function fadeVolume(audio, target, duration = RADIO_VOLUME.fadeMs) {
  cancelFade(audio);
  const startVolume = Number.isFinite(audio.volume) ? audio.volume : 1;
  const targetVolume = Math.max(0, Math.min(1, target));
  const startedAt = performance.now();
  let lastFrameAt = -1;
  return new Promise((resolve) => {
    function step(now) {
      const progress = duration <= 0 ? 1 : Math.min(1, (now - startedAt) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      audio.volume = startVolume + (targetVolume - startVolume) * eased;
      if (progress < 1) {
        if (now === lastFrameAt) {
          const timeoutToken = { type: "timeout" };
          radioState.fades.set(audio, timeoutToken);
          timeoutToken.id = window.setTimeout(() => {
            if (radioState.fades.get(audio) !== timeoutToken) return;
            step(performance.now());
          }, 16);
        } else {
          lastFrameAt = now;
          radioState.fades.set(audio, requestAnimationFrame(step));
        }
      } else {
        audio.volume = targetVolume;
        radioState.fades.delete(audio);
        resolve();
      }
    }
    radioState.fades.set(audio, requestAnimationFrame(step));
  });
}

function makeMusicAudioAudible(audio, startVolume = 0.04) {
  if (!audio) return;
  audio.muted = false;
  audio.defaultMuted = false;
  audio.autoplay = false;
  audio.loop = false;
  const safeVolume = Math.max(0.02, Math.min(1, Number.isFinite(startVolume) ? startVolume : 0.04));
  audio.volume = safeVolume;
}

function duckMusic() {
  const audio = radioState.activeMusic;
  if (audio && !audio.paused && !audio.ended) {
    fadeVolume(audio, RADIO_VOLUME.ducked, RADIO_VOLUME.duckMs);
    return true;
  }
  return false;
}

function restoreMusic({ delay = RADIO_VOLUME.restoreDelayMs, duration = RADIO_VOLUME.restoreMs } = {}) {
  const audio = radioState.activeMusic;
  if (!audio || audio.paused || audio.ended) return;
  const token = radioState.playToken;
  window.setTimeout(() => {
    if (token !== radioState.playToken || !radioState.playing || audio.paused || audio.ended) return;
    radioDebugEvent("music_restore", audioDebugState(audio));
    fadeVolume(audio, RADIO_VOLUME.music, duration);
  }, Math.max(0, delay));
}

function isDjAudioActive() {
  return Boolean(radioState.djAudio && !radioState.djAudio.paused && !radioState.djAudio.ended);
}

function activeAudiosForVoiceInput() {
  return [radioState.musicAudio, radioState.musicAudioB, radioState.djAudio].filter((audio) => (
    audio && !audio.paused && !audio.ended
  ));
}

function enterVoiceListeningMode() {
  if (voiceState.audioSnapshot) return;
  const activeAudios = activeAudiosForVoiceInput();
  voiceState.audioSnapshot = activeAudios.map((audio) => ({
    audio,
    volume: Number.isFinite(audio.volume) ? audio.volume : 1,
    muted: Boolean(audio.muted),
    isDj: audio === radioState.djAudio,
  }));
  voiceState.audioSnapshot.forEach(({ audio, isDj }) => {
    cancelFade(audio);
    audio.muted = false;
    if (isDj) {
      fadeVolume(audio, 0, RADIO_VOLUME.voiceDuckMs);
    } else {
      fadeVolume(audio, RADIO_VOLUME.voiceListenMusic, RADIO_VOLUME.voiceDuckMs);
    }
  });
  if (radioState.activeRoot && activeAudios.length) {
    updateRadioStatus("正在听你说，背景音乐已降低。", radioState.activeRoot);
  }
}

function exitVoiceListeningMode({ restore = true } = {}) {
  const snapshot = voiceState.audioSnapshot || [];
  voiceState.audioSnapshot = null;
  if (!restore) return;
  snapshot.forEach(({ audio, volume, muted, isDj }) => {
    if (!audio || audio.paused || audio.ended) return;
    cancelFade(audio);
    audio.muted = muted;
    fadeVolume(audio, volume, RADIO_VOLUME.voiceDuckMs);
  });
  if (radioState.activeRoot && snapshot.some((item) => item.audio && !item.audio.paused && !item.audio.ended && !item.isDj)) {
    updateRadioStatus(`正在播放：${currentSongDisplayName()}`, radioState.activeRoot);
  }
}

function invalidateAsyncDj({ preserveActiveAudio = false } = {}) {
  radioState.djGeneration += 1;
  const data = radioState.currentData;
  if (data?.dj) {
    data.dj.pending = false;
    data.dj.overlay_pending = false;
    data.dj._buildStarted = false;
    (data.dj.segments || []).forEach((segment) => {
      delete segment._overlayStarted;
    });
  }
  if (!preserveActiveAudio) {
    cancelFade(radioState.djAudio);
    radioState.djAudio.pause();
    radioState.djAudio.removeAttribute("src");
    radioState.djAudio.load();
    restoreMusic();
  }
}

function firstPlayableDjSegment(dj) {
  return (dj?.segments || []).find((segment) => (
    segment
    && segment.type !== "silence"
    && segment.audio
    && (segment.speech_text || segment.text)
    && !segment._overlayStarted
  ));
}

function shouldKeepMusicAsBed(data = radioState.currentData) {
  return Boolean(data?.dj?.pending || data?.dj?.overlay_pending);
}

function playAsyncDjOverlay(data, root) {
  const segment = firstPlayableDjSegment(data?.dj);
  if (!segment || !radioState.playing) return false;
  const music = radioState.activeMusic;
  if (!music || music.paused || music.ended) return false;
  const token = radioState.playToken;
  const audio = radioState.djAudio;
  radioDebugEvent("dj_overlay_attempt", `music=${audioDebugState(music)} dj=${audioDebugState(audio)}`, root);
  segment._overlayStarted = true;
  if (data?.dj) {
    data.dj.overlay_pending = false;
  }
  prepareDjAudioForPlayback(audio, segment.audio);
  radioDebugEvent("dj_audio_prepared", audioDebugState(audio), root);
  updateRadioStatus(`DJ 插播：${segment.speech_text || segment.text || "Melodio"}`, root);
  radioDebugEvent("music_duck", audioDebugState(music), root);
  fadeVolume(music, RADIO_VOLUME.ducked, RADIO_VOLUME.duckMs);
  audio.onended = () => {
    if (token !== radioState.playToken) return;
    radioDebugEvent("dj_overlay_ended", audioDebugState(audio), root);
    restoreMusic();
    updateRadioStatus(`正在播放：${currentSongDisplayName()}`, root);
  };
  audio.onerror = () => {
    if (token !== radioState.playToken) return;
    radioDebugEvent("dj_overlay_error", audioDebugState(audio), root);
    restoreMusic();
    updateRadioStatus("DJ 语音加载失败，音乐继续播放。", root);
  };
  audio.play().then(() => {
    radioDebugEvent("dj_overlay_playing", audioDebugState(audio), root);
  }).catch((error) => {
    if (token !== radioState.playToken) return;
    radioDebugEvent("dj_overlay_play_blocked", `${error.message || error} ${audioDebugState(audio)}`, root);
    restoreMusic();
    updateRadioStatus(`DJ 语音播放失败：${error.message || "浏览器限制了音频启动"}`, root);
  });
  return true;
}

function playAsyncDjSolo(data, root) {
  const segment = firstPlayableDjSegment(data?.dj);
  if (!segment) return false;
  const token = radioState.djGeneration;
  const audio = radioState.djAudio;
  segment._overlayStarted = true;
  if (data?.dj) {
    data.dj.overlay_pending = false;
  }
  prepareDjAudioForPlayback(audio, segment.audio);
  radioDebugEvent("dj_solo_attempt", audioDebugState(audio), root);
  updateRadioStatus(`DJ：${segment.speech_text || segment.text || "Melodio"}`, root);
  audio.onended = () => {
    if (token !== radioState.djGeneration) return;
    radioDebugEvent("dj_solo_ended", audioDebugState(audio), root);
    restoreMusic({ delay: 0 });
    if (!radioState.playing) updateRadioStatus("Melodio 已回应", root);
  };
  audio.onerror = () => {
    if (token !== radioState.djGeneration) return;
    radioDebugEvent("dj_solo_error", audioDebugState(audio), root);
    restoreMusic({ delay: 0 });
    updateRadioStatus("DJ 语音加载失败，音乐会继续准备。", root);
  };
  audio.play().then(() => {
    radioDebugEvent("dj_solo_playing", audioDebugState(audio), root);
    const music = radioState.activeMusic;
    if (music && !music.paused && !music.ended) {
      fadeVolume(music, RADIO_VOLUME.bed, RADIO_VOLUME.duckMs);
    }
  }).catch((error) => {
    if (token !== radioState.djGeneration) return;
    segment._overlayStarted = false;
    if (data?.dj) data.dj.overlay_pending = true;
    radioDebugEvent("dj_solo_play_blocked", `${error.message || error} ${audioDebugState(audio)}`, root);
    updateRadioStatus("DJ 语音已就绪，会在音乐进入后自动插播。", root);
  });
  return true;
}

function activeMusicIsPlaying() {
  const music = radioState.activeMusic;
  return Boolean(music && !music.paused && !music.ended && !isSilentPrimedAudio(music));
}

function ensureMusicBedForDj(data, root) {
  if (activeMusicIsPlaying()) return true;
  const indexes = musicTimelineIndexes();
  const firstIndex = indexes.find((index) => radioState.timeline[index]?.track?.stream_url);
  const item = Number.isInteger(firstIndex) ? radioState.timeline[firstIndex] : null;
  if (item?.kind === "music" && item.track?.stream_url) {
    if (!radioState.playing) {
      radioState.playing = true;
      radioState.activeRoot = radioState.activeRoot || root || null;
      radioState.currentData = radioState.currentData || data || null;
      syncHeroTransport();
    }
    startMusicUnderVoice(item.track, root, firstIndex);
    return true;
  }
  if (data && root && flattenSongs(data.groups || []).length && !radioState.loading) {
    window.setTimeout(() => startRadio(data, root, { forceStart: true }), 0);
  }
  return false;
}

function queueOrPlayAsyncDj(data, root) {
  if (!data?.dj) return false;
  radioState.currentData = data;
  radioState.activeRoot = radioState.activeRoot || root || null;
  data.dj.overlay_pending = true;
  const played = maybePlayQueuedDjOverlay(root);
  if (played) return true;
  if (flattenSongs(data.groups || []).length && ensureMusicBedForDj(data, root)) {
    maybePlayQueuedDjOverlay(root);
    return true;
  }
  if (!played) {
    radioDebugEvent("dj_overlay_queued", "waiting for active music", root);
    updateRadioStatus("DJ 语音已就绪，会在音乐进入后自动插播。", root);
  }
  return played;
}

function playSpeechOnlyDj(data, root) {
  const segment = firstPlayableDjSegment(data?.dj);
  if (!segment) return false;
  if (radioState.playing && radioState.activeMusic && !radioState.activeMusic.paused && !radioState.activeMusic.ended) {
    return playAsyncDjOverlay(data, root);
  }
  const token = radioState.playToken + 1;
  radioState.playToken = token;
  const audio = radioState.djAudio;
  segment._overlayStarted = true;
  prepareDjAudioForPlayback(audio, segment.audio);
  radioState.playing = true;
  radioState.activeRoot = root;
  updateRadioStatus(`DJ：${segment.speech_text || segment.text || "Melodio"}`, root);
  syncHeroTransport();
  audio.onended = () => {
    if (token !== radioState.playToken) return;
    radioState.playing = false;
    updateRadioStatus("Melodio 已回应", root);
    syncHeroTransport();
  };
  audio.onerror = () => {
    if (token !== radioState.playToken) return;
    radioState.playing = false;
    updateRadioStatus("DJ 语音加载失败。", root);
    syncHeroTransport();
  };
  audio.play().catch((error) => {
    if (token !== radioState.playToken) return;
    radioState.playing = false;
    updateRadioStatus(`DJ 语音播放失败：${error.message || "浏览器限制了音频启动"}`, root);
    syncHeroTransport();
  });
  return true;
}

function queueAsyncDjOverlay(data, root) {
  if (!data?.dj) return false;
  return queueOrPlayAsyncDj(data, root);
}

function maybePlayQueuedDjOverlay(root) {
  const data = radioState.currentData;
  if (!data?.dj?.overlay_pending) return false;
  radioDebugEvent("dj_overlay_retry", `active=${audioDebugState(radioState.activeMusic)}`, root);
  return playAsyncDjOverlay(data, root);
}

function beginAsyncDjIfNeeded(data, root) {
  if (!data?.dj?.pending || !root || data.dj._buildStarted) return;
  data.dj._buildStarted = true;
  radioDebugEvent("dj_build_request", `provider=${data.provider || ""}`, root);
  const hasSongs = Boolean(flattenSongs(data.groups || []).length);
  updateRadioStatus(hasSongs ? "音乐已开始，DJ 正在根据可播歌曲编排。" : "DJ 正在组织这次回应。", root);
  hydrateDjProgram(data, root);
}

async function fadeOutAndPause(audio, duration = RADIO_VOLUME.fadeMs) {
  if (audio.paused) return;
  await fadeVolume(audio, 0, duration);
  audio.pause();
}

function nextMusicAudio() {
  return radioState.activeMusic === radioState.musicAudio ? radioState.musicAudioB : radioState.musicAudio;
}

function isSilentPrimedAudio(audio) {
  return audio?.datasetUnlocked === "true" && String(audio.src || "").startsWith("data:audio/");
}

function rememberCurrentTrack(track) {
  const title = track?.display_title || track?.requested_title || track?.title || "";
  const artist = track?.display_artist || track?.requested_artist || track?.artist || "";
  const imageUrl = track?.display_image_url || track?.image_url || track?.cover_url || "";
  if (title) {
    chatState.currentSong = { title, artist, image_url: imageUrl };
    updateHeroTrack({ title, artist, image_url: imageUrl });
  }
}

function updateNowPlayingFromTrack(track, root = null, prefix = "正在播放") {
  if (!track) return false;
  const title = track.display_title || track.requested_title || track.title || "";
  const artist = track.display_artist || track.requested_artist || track.artist || "";
  const imageUrl = track.display_image_url || track.image_url || track.cover_url || "";
  if (!title) return false;
  updateHeroTrack({ title, artist, image_url: imageUrl });
  const status = root?.querySelector(".radio-playback-status");
  if (status) status.textContent = `${prefix}：${title}${artist ? ` - ${artist}` : ""}`;
  syncHeroTransport();
  return true;
}

function clearRadioWatchdog() {
  if (radioState.watchdogTimer) {
    window.clearInterval(radioState.watchdogTimer);
    radioState.watchdogTimer = null;
  }
}

function startRadioWatchdog(root, item, audio, token, finishItem) {
  clearRadioWatchdog();
  let lastTime = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
  let resumeAttempts = 0;
  let stuckTicks = 0;
  radioState.watchdogTimer = window.setInterval(() => {
    if (!radioState.playing || token !== radioState.playToken) {
      clearRadioWatchdog();
      return;
    }
    const currentItem = radioState.timeline[radioState.index];
    if (currentItem !== item) {
      clearRadioWatchdog();
      return;
    }
    updateRadioDebug(root, item, audio, "watch");
    if (audio.ended) {
      finishItem();
      return;
    }
    if (item.kind === "music" && Number.isFinite(audio.duration) && audio.duration > 0 && audio.currentTime >= audio.duration - 0.35) {
      finishItem();
      return;
    }
    if (audio.paused) {
      if (resumeAttempts < 2) {
        resumeAttempts += 1;
        audio.play().catch(() => {
          if (resumeAttempts >= 2) finishItem();
        });
      } else {
        finishItem();
      }
      return;
    }
    const currentTime = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    if (Math.abs(currentTime - lastTime) < 0.05) {
      stuckTicks += 1;
    } else {
      stuckTicks = 0;
      lastTime = currentTime;
    }
    if (stuckTicks >= 12 && item.kind === "voice") {
      updateRadioStatus("DJ 语音可能卡住，继续播放队列", root);
      finishItem();
    }
  }, 1000);
}

async function unlockAudioElement(audio, { keepAlive = false } = {}) {
  const previousSrc = audio.src;
  const previousVolume = audio.volume;
  try {
    if (keepAlive && audio.datasetUnlocked === "true" && !audio.paused && !audio.ended) {
      return true;
    }
    audio.src = AUTOPLAY_PRIMER_SRC;
    audio.volume = 0;
    audio.muted = Boolean(keepAlive);
    audio.defaultMuted = Boolean(keepAlive);
    audio.autoplay = Boolean(keepAlive);
    audio.loop = Boolean(keepAlive);
    await audio.play();
    if (!keepAlive) {
      audio.pause();
      audio.currentTime = 0;
      audio.removeAttribute("src");
      audio.load();
      audio.loop = false;
      audio.autoplay = false;
      audio.muted = false;
      audio.defaultMuted = false;
    }
    audio.volume = previousVolume;
    audio.datasetUnlocked = "true";
    return true;
  } catch (error) {
    console.warn(`radio audio unlock failed keepAlive=${keepAlive} message=${error?.message || String(error)} muted=${audio.muted} defaultMuted=${audio.defaultMuted} paused=${audio.paused} readyState=${audio.readyState}`);
    audio.loop = false;
    audio.volume = previousVolume;
    if (!keepAlive) {
      audio.muted = false;
      audio.defaultMuted = false;
    }
    if (previousSrc) audio.src = previousSrc;
    return false;
  }
}

async function unlockRadioAudio(root) {
  const results = await Promise.all([
    unlockAudioElement(radioState.djAudio, { keepAlive: true }),
    unlockAudioElement(radioState.musicAudio, { keepAlive: true }),
    unlockAudioElement(radioState.musicAudioB, { keepAlive: true }),
  ]);
  if (!results.every(Boolean)) {
    updateRadioStatus("浏览器可能限制多音频自动播放；如果开场垫乐没响，请再点一次开始。", root);
  }
  return results;
}

function ensureRadioAutoplayUnlocked(root) {
  const needsUnlock = [radioState.djAudio, radioState.musicAudio, radioState.musicAudioB].some((audio) => (
    !audio || audio.datasetUnlocked !== "true" || audio.paused || audio.ended
  ));
  if (!radioState.autoplayUnlockPromise || needsUnlock) {
    radioState.autoplayUnlockPromise = unlockRadioAudio(root).catch(() => [false, false, false]);
  }
  return radioState.autoplayUnlockPromise;
}

function primeRadioAutoplay(root = null) {
  if (radioState.playing) return;
  if (hasRealPlaybackToResume()) return;
  ensureRadioAutoplayUnlocked(root);
}

function bindAutoplayPrimer(target) {
  if (!target) return;
  ["pointerdown", "mousedown", "touchstart"].forEach((eventName) => {
    target.addEventListener(eventName, () => primeRadioAutoplay(), { passive: true });
  });
}

function resumePreparedRadio(root) {
  if (!radioState.timeline.length || radioState.playing) return false;
  const item = radioState.timeline[radioState.index];
  if (!item) return false;
  const audio = item.kind === "voice"
    ? radioState.djAudio
    : (radioState.activeMusic || radioState.musicAudio);
  if (!audio?.src) return false;
  if (item.kind === "music") {
    audio.muted = false;
    audio.defaultMuted = false;
    if (!Number.isFinite(audio.volume) || audio.volume <= 0) {
      audio.volume = 0.05;
    }
  }
  radioState.playing = true;
  syncHeroTransport();
  audio.play?.().then(() => {
    updateRadioStatus(item.kind === "voice" ? `DJ：${item.label}` : `正在播放：${item.label}`, root);
    if (item.kind === "music") {
      fadeVolume(audio, RADIO_VOLUME.music, RADIO_VOLUME.restoreMs || RADIO_VOLUME.fadeMs);
    }
    maybePlayQueuedDjOverlay(root);
  }).catch((error) => {
    radioState.playing = false;
    updateRadioStatus(`需要再次点击播放：${error.message || "浏览器限制了音频启动"}`, root);
  });
  return true;
}

function isPrestartedTrack(track) {
  return track?._startedAudio
    && track._startedToken === radioState.playToken
    && !track._startedAudio.paused
    && !track._startedAudio.ended;
}

function clearPrestartedTrack(track) {
  if (!track) return;
  delete track._startedAudio;
  delete track._startedToken;
  delete track._timelineIndex;
  delete track._prestartEnded;
  delete track._prestartError;
  delete track._wasPrestarted;
}

function resetAudioHandlers(audio) {
  if (!audio) return;
  audio.onended = null;
  audio.onerror = null;
  audio.ontimeupdate = null;
}

function prepareDjAudioForPlayback(audio, src) {
  cancelFade(audio);
  resetAudioHandlers(audio);
  audio.pause();
  audio.loop = false;
  audio.autoplay = false;
  audio.muted = false;
  audio.defaultMuted = false;
  audio.volume = RADIO_VOLUME.dj;
  audio.src = mediaUrl(src);
  audio.currentTime = 0;
  audio.load?.();
}

function startMusicUnderVoice(track, root, timelineIndex = -1) {
  if (!track?.stream_url || !radioState.playing) return;
  const token = radioState.playToken;
  rememberCurrentTrack(track);
  if (isPrestartedTrack(track)) {
    track._timelineIndex = timelineIndex;
    fadeVolume(track._startedAudio, RADIO_VOLUME.ducked, RADIO_VOLUME.duckMs);
    return;
  }
  const previous = radioState.activeMusic;
  const audio = previous && !previous.paused && !previous.ended && !isSilentPrimedAudio(previous)
    ? nextMusicAudio()
    : (previous || radioState.musicAudio);
  if (previous && previous !== audio && !previous.paused) {
    fadeOutAndPause(previous, RADIO_VOLUME.fadeMs);
  }
  radioState.activeMusic = audio;
  resetAudioHandlers(audio);
  audio.src = proxiedMusicUrl(track.stream_url);
  audio.loop = false;
  audio.currentTime = 0;
  makeMusicAudioAudible(audio, RADIO_VOLUME.ducked);
  track._startedAudio = audio;
  track._startedToken = token;
  track._timelineIndex = timelineIndex;
  track._prestartEnded = false;
  track._prestartError = false;
  track._wasPrestarted = true;
  audio.onended = () => {
    if (token !== radioState.playToken) return;
    track._prestartEnded = true;
    updateRadioStatus("开场垫乐已结束，进入正式队列时会重新播放", root);
  };
  audio.onerror = () => {
    if (token !== radioState.playToken) return;
    track._prestartError = true;
    updateRadioStatus("开场垫乐加载失败，进入正式队列时会重新播放", root);
  };
  audio.play().then(() => {
    updateNowPlayingFromTrack(track, root, "正在播放");
    fadeVolume(audio, RADIO_VOLUME.ducked, RADIO_VOLUME.duckMs);
    maybePlayQueuedDjOverlay(root);
  }).catch((error) => {
    if (token !== radioState.playToken) return;
    track._prestartError = true;
    updateRadioStatus(`开场垫乐启动失败：${error.message || "浏览器阻止了音乐自动播放"}`, root);
  });
}

function stopRadio() {
  radioState.playing = false;
  radioState.playToken += 1;
  radioState.activeRoot = null;
  clearRadioWatchdog();
  cancelFade(radioState.djAudio);
  cancelFade(radioState.musicAudio);
  cancelFade(radioState.musicAudioB);
  radioState.djAudio.pause();
  radioState.musicAudio.pause();
  radioState.musicAudioB.pause();
  radioState.djAudio.muted = false;
  radioState.musicAudio.muted = false;
  radioState.musicAudioB.muted = false;
  radioState.djAudio.removeAttribute("src");
  radioState.musicAudio.removeAttribute("src");
  radioState.musicAudioB.removeAttribute("src");
  radioState.djAudio.load();
  radioState.musicAudio.load();
  radioState.musicAudioB.load();
  radioState.djAudio.volume = RADIO_VOLUME.dj;
  radioState.musicAudio.volume = 0;
  radioState.musicAudioB.volume = 0;
  radioState.activeMusic = radioState.musicAudio;
  radioState.autoplayUnlockPromise = null;
  if (heroTitle && !chatState.currentSong?.title) {
    heroTitle.textContent = "Melodio";
    updateHeroCover("");
  }
  syncHeroTransport();
}

function stopMusicForTakeover() {
  clearRadioWatchdog();
  [radioState.musicAudio, radioState.musicAudioB].forEach((audio) => {
    cancelFade(audio);
    audio.pause();
    audio.muted = false;
    audio.removeAttribute("src");
    audio.load();
    audio.volume = 0;
  });
  radioState.timeline.forEach((item) => {
    if (item?.kind === "music") clearPrestartedTrack(item.track);
  });
  radioState.activeMusic = radioState.musicAudio;
}

function syncHeroTransport() {
  const heroPlay = document.querySelector('.hero-control[data-control="play"]');
  if (heroPlay) {
    heroPlay.textContent = radioState.playing ? "Ⅱ" : "▶";
    heroPlay.dataset.state = radioState.playing ? "pause" : "play";
  }
  syncHeroFavorite();
}

function songFavoriteKey(song = chatState.currentSong) {
  const title = String(song?.title || "").trim().toLowerCase();
  const artist = String(song?.artist || "").trim().toLowerCase();
  return title ? `${title}|||${artist}` : "";
}

function syncHeroFavorite() {
  const favoriteButton = document.querySelector('.hero-control[data-control="favorite"]');
  if (!favoriteButton) return;
  const key = songFavoriteKey();
  const active = Boolean(key && chatState.favoriteSongs.has(key));
  if (typeof favoriteButton.classList?.toggle === "function") {
    favoriteButton.classList.toggle("is-favorited", active);
  } else if (active) {
    favoriteButton.classList?.add?.("is-favorited");
  } else {
    favoriteButton.classList?.remove?.("is-favorited");
  }
  favoriteButton.dataset.state = active ? "favorited" : "";
  favoriteButton.setAttribute?.("aria-pressed", active ? "true" : "false");
  favoriteButton.title = active ? "已收藏" : "收藏当前歌曲";
  favoriteButton.textContent = active ? "♥" : "♡";
}

function toggleHeroFavorite(root = currentPlaybackRoot()) {
  const key = songFavoriteKey();
  if (!key) {
    updateRadioStatus("当前还没有可收藏的歌曲", root);
    return false;
  }
  if (chatState.favoriteSongs.has(key)) {
    chatState.favoriteSongs.delete(key);
    updateRadioStatus(`已取消收藏：${currentSongDisplayName()}`, root);
  } else {
    chatState.favoriteSongs.add(key);
    updateRadioStatus(`已收藏：${currentSongDisplayName()}`, root);
  }
  syncHeroFavorite();
  return true;
}

function splitSongLabel(label) {
  const raw = String(label || "").trim();
  const parts = raw.split(/\s+-\s+/);
  if (parts.length >= 2) {
    return {
      title: parts.slice(0, -1).join(" - ").trim(),
      artist: parts[parts.length - 1].trim(),
    };
  }
  return { title: raw, artist: "" };
}

function activeTrackInfoFromStatus(text) {
  const raw = String(text || "");
  const musicText = raw
    .replace(/^正在播放：/, "")
    .replace(/^正在启动：/, "")
    .replace(/^DJ 开场 \+ 音乐同步进入：/, "")
    .replace(/^DJ 串场 \+ 音乐同步进入：/, "")
    .replace(/^DJ 开场 \+ 音乐渐入：/, "")
    .replace(/^DJ 串场 \+ 音乐渐入：/, "")
    .trim();
  if (
    !musicText
    || /^DJ/.test(musicText)
    || /^已(?:取消)?收藏：/.test(musicText)
    || /浏览器|限制|拦截|解析|准备|失败|暂停|继续|已经|没有|暂时|可控播放|开场垫乐|权限|麦克风|语音|收藏/.test(musicText)
    || !/\s+-\s+/.test(musicText)
  ) {
    return null;
  }
  return splitSongLabel(musicText);
}

function updateHeroCover(imageUrl) {
  const cover = document.querySelector(".cover-art");
  if (!cover) return;
  const image = cover.querySelector?.(".cover-image");
  if (!cover.style) cover.style = {};
  const src = String(imageUrl || "").trim();
  if (src) {
    if (image) {
      image.onload = () => {
        const width = image.naturalWidth || 1;
        const height = image.naturalHeight || 1;
        cover.style.aspectRatio = `${width} / ${height}`;
      };
      image.src = src;
      if (image.complete && image.naturalWidth && image.naturalHeight) {
        cover.style.aspectRatio = `${image.naturalWidth} / ${image.naturalHeight}`;
      }
    }
    cover.style.backgroundImage = "";
    cover.classList.add("has-cover");
  } else {
    if (image) image.removeAttribute?.("src");
    cover.style.aspectRatio = "";
    cover.style.backgroundImage = "";
    cover.classList.remove("has-cover");
  }
}

function updateHeroTrack(trackInfo) {
  if (!trackInfo?.title) return false;
  if (heroTitle) heroTitle.textContent = trackInfo.title;
  if (heroNowPlaying) heroNowPlaying.textContent = trackInfo.artist || "";
  if (providerStatus) providerStatus.textContent = "";
  if (radioLine) radioLine.textContent = "Now playing";
  const imageUrl = trackInfo.image_url || trackInfo.cover_url || chatState.currentSong?.image_url || "";
  if (imageUrl) updateHeroCover(imageUrl);
  chatState.currentSong = { title: trackInfo.title, artist: trackInfo.artist || "", image_url: imageUrl };
  syncHeroFavorite();
  return true;
}

function updateRadioStatus(text, root) {
  const status = root?.querySelector(".radio-playback-status");
  if (status) status.textContent = text;
  if (text) setDispatchStatus(text);
  syncHeroTransport();
  if (heroNowPlaying && text) {
    const trackInfo = activeTrackInfoFromStatus(text);
    if (trackInfo?.title) updateHeroTrack(trackInfo);
  }
}

function audioDebugState(audio) {
  if (!audio) return "audio=none";
  return [
    `src=${String(audio.src || "").slice(0, 80)}`,
    `paused=${audio.paused}`,
    `muted=${audio.muted}`,
    `loop=${audio.loop}`,
    `vol=${Number.isFinite(audio.volume) ? audio.volume.toFixed(2) : "-"}`,
    `ready=${audio.readyState}`,
    `network=${audio.networkState}`,
    `t=${Number.isFinite(audio.currentTime) ? audio.currentTime.toFixed(1) : "0.0"}`,
  ].join(" ");
}

function radioDebugEvent(name, detail = "", root = radioState.activeRoot) {
  const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  radioState.debugEvents.push(`[${time}] ${name}${detail ? ` · ${detail}` : ""}`);
  radioState.debugEvents = radioState.debugEvents.slice(-12);
  if (root) updateRadioDebug(root, null, null, "event");
}

function currentPlaybackRoot() {
  return radioState.activeRoot || latestAssistantRoot() || null;
}

function currentPlaybackData() {
  return radioState.currentData || latestResultData() || null;
}

function hasRealPlaybackToResume() {
  const active = radioState.activeMusic || radioState.musicAudio;
  return Boolean(
    radioState.timeline.length
    || currentPlaybackData()
    || (active?.src && !isSilentPrimedAudio(active))
  );
}

function pauseHeroPlayback(root = currentPlaybackRoot()) {
  invalidateAsyncDj();
  clearRadioWatchdog();
  [radioState.djAudio, radioState.musicAudio, radioState.musicAudioB].forEach((audio) => {
    cancelFade(audio);
    audio.pause();
  });
  radioState.playing = false;
  updateRadioStatus("已暂停", root);
  syncHeroTransport();
  return true;
}

async function resumeHeroPlayback(root = currentPlaybackRoot()) {
  if (resumePreparedRadio(root)) return true;
  const active = radioState.activeMusic || radioState.musicAudio;
  if (active?.src && !isSilentPrimedAudio(active)) {
    try {
      radioState.playing = true;
      syncHeroTransport();
      await active.play();
      updateRadioStatus(`正在播放：${currentSongDisplayName()}`, root);
      if (active === radioState.activeMusic) {
        fadeVolume(active, RADIO_VOLUME.music, RADIO_VOLUME.restoreMs || RADIO_VOLUME.fadeMs);
      }
      maybePlayQueuedDjOverlay(root);
      return true;
    } catch (error) {
      radioState.playing = false;
      syncHeroTransport();
      updateRadioStatus(`需要再次点击播放：${error.message || "浏览器限制了音频启动"}`, root);
      return false;
    }
  }
  const data = currentPlaybackData();
  if (data && root) {
    startRadio(data, root, { forceStart: true });
    return true;
  }
  return false;
}

function updateRadioDebug(root, item, audio, note = "") {
  const target = root?.querySelector(".radio-debug");
  if (!target) return;
  const current = Number.isFinite(audio?.currentTime) ? audio.currentTime.toFixed(1) : "0.0";
  const duration = Number.isFinite(audio?.duration) ? audio.duration.toFixed(1) : "?";
  const currentLine = [
    `index=${radioState.index}/${radioState.timeline.length}`,
    `kind=${item?.kind || "-"}`,
    `playing=${radioState.playing}`,
    `paused=${audio?.paused}`,
    `ended=${audio?.ended}`,
    `t=${current}/${duration}`,
    `vol=${Number.isFinite(audio?.volume) ? audio.volume.toFixed(2) : "-"}`,
    note,
  ].filter(Boolean).join(" · ");
  target.textContent = [currentLine, ...radioState.debugEvents].filter(Boolean).join("\n");
}

function musicExternalUrl(track) {
  if (!track) return "";
  return track.song_url || track.search_url || "";
}

function trackDisplayName(track) {
  return `${track?.requested_title || track?.display_title || track?.title || "未知歌曲"}${track?.requested_artist || track?.display_artist || track?.artist ? ` - ${track.requested_artist || track.display_artist || track.artist}` : ""}`;
}

function appleMusicSearchUrl(title, artist = "") {
  return `https://music.apple.com/search?term=${encodeURIComponent(`${title || ""} ${artist || ""}`.trim())}`;
}

function currentSongDisplayName() {
  const song = chatState.currentSong || {};
  return `${song.title || "当前歌曲"}${song.artist ? ` - ${song.artist}` : ""}`;
}

function renderRadioFallbacks(tracks, root) {
  const target = root?.querySelector(".radio-fallbacks");
  if (!target) return;
  const unavailable = (tracks || []).filter((track) => !track?.ok || !track.stream_url);
  if (!unavailable.length) {
    target.hidden = true;
    target.innerHTML = "";
    return;
  }
  target.hidden = false;
  target.innerHTML = `
    <div class="radio-fallback-title">以下歌曲暂时拿不到可控播放直链，已从电台流跳过</div>
    <div class="radio-fallback-list">
      ${unavailable.map((track) => {
        const url = musicExternalUrl(track);
        return `
          <div class="radio-fallback-item">
            <span>${esc(trackDisplayName(track))}</span>
            ${track.error ? `<em>${esc(track.error)}</em>` : ""}
            ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">外部播放</a>` : ""}
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function shouldOverlapVoiceWithMusic(item) {
  return item?.kind === "voice";
}

function voiceMusicOverlapDelay(item) {
  if (item?.segment?.position === "before_track") return 0;
  return item?.segment?.type === "cold_open" ? 0 : RADIO_VOLUME.introOverlapMs;
}

function nextPlayableMusicItem(fromIndex) {
  for (let i = fromIndex + 1; i < radioState.timeline.length; i += 1) {
    const candidate = radioState.timeline[i];
    if (candidate?.kind === "music" && candidate.track?.stream_url) {
      return candidate;
    }
    if (candidate?.kind === "music") return null;
  }
  return null;
}

function firstPlayableMusicItem() {
  return radioState.timeline.find((item) => item?.kind === "music" && item.track?.stream_url) || null;
}

async function playTimelineItem(root) {
  if (!radioState.playing) return;
  const token = radioState.playToken;
  if (radioState.index >= radioState.timeline.length) {
    if (radioState.continuationPromise) {
      updateRadioStatus("正在补充后续歌曲...", root);
      if (await continueRadioQueueIfNeeded(root, { force: true })) return;
    } else if (await continueRadioQueueIfNeeded(root, { force: true })) {
      return;
    }
    updateRadioStatus("节目已播完", root);
    radioState.playing = false;
    const button = root?.querySelector(".radio-start");
    if (button) button.textContent = "重新播放电台";
    return;
  }
  const item = radioState.timeline[radioState.index];
  if (item.kind === "music") {
    rememberCurrentTrack(item.track);
  }
  updateRadioStatus(item.kind === "voice" ? `DJ 准备播放：${item.label}` : `正在启动：${item.label}`, root);
  const prestartedMusic = item.kind === "music"
    && isPrestartedTrack(item.track);
  const audio = item.kind === "voice" ? radioState.djAudio : (prestartedMusic ? item.track._startedAudio : nextMusicAudio());
  const other = radioState.djAudio;
  const nextMusicItem = item.kind === "voice" && shouldOverlapVoiceWithMusic(item)
    ? nextPlayableMusicItem(radioState.index)
    : null;
  let overlappedMusic = false;
  let itemSettled = false;
  const finishItem = () => {
    if (itemSettled || token !== radioState.playToken) return;
    itemSettled = true;
    clearRadioWatchdog();
    updateRadioDebug(root, item, audio, "finish");
    if (item.kind === "voice") {
      restoreMusic();
      radioState.index += 1;
    } else {
      clearPrestartedTrack(item.track);
      radioState.index += 1;
    }
    playTimelineItem(root);
  };
  if (item.kind === "voice") {
    duckMusic();
  } else {
    if (!isDjAudioActive()) {
      await fadeOutAndPause(other, 500);
    }
    if (!prestartedMusic && radioState.activeMusic && radioState.activeMusic !== audio && !radioState.activeMusic.paused) {
      fadeOutAndPause(radioState.activeMusic, RADIO_VOLUME.fadeMs);
    }
    radioState.activeMusic = audio;
    if (!prestartedMusic) makeMusicAudioAudible(audio, shouldKeepMusicAsBed() || isDjAudioActive() ? RADIO_VOLUME.bed : 0.04);
  }
  resetAudioHandlers(audio);
  if (!prestartedMusic) {
    if (item.kind === "voice") {
      prepareDjAudioForPlayback(audio, item.segment.audio);
    } else {
      audio.src = proxiedMusicUrl(item.track.stream_url);
      audio.loop = false;
      audio.currentTime = 0;
    }
    if (item.kind === "music") {
      item.track._startedAudio = audio;
      item.track._startedToken = token;
      item.track._timelineIndex = radioState.index;
    }
  } else {
    item.track._prestartEnded = false;
    item.track._prestartError = false;
  }
  audio.onended = () => {
    finishItem();
  };
  audio.ontimeupdate = () => {
    if (item.kind !== "music" || itemSettled || token !== radioState.playToken) return;
    if (Number.isFinite(audio.duration) && audio.duration > 0 && audio.currentTime >= audio.duration - 0.35) {
      finishItem();
    } else {
      updateRadioDebug(root, item, audio);
    }
  };
  audio.onerror = () => {
    if (item.kind === "voice") {
      updateRadioStatus("DJ 语音加载失败，继续播放队列", root);
      finishItem();
      return;
    }
    finishItem();
  };
  startRadioWatchdog(root, item, audio, token, finishItem);
  if (item.kind === "voice" && nextMusicItem && voiceMusicOverlapDelay(item) <= 0) {
    updateRadioStatus(`${item.segment?.type === "cold_open" ? "DJ 开场" : "DJ 串场"} + 音乐同步进入：${nextMusicItem.label}`, root);
    updateNowPlayingFromTrack(nextMusicItem.track, root, "正在播放");
    startMusicUnderVoice(nextMusicItem.track, root, radioState.timeline.indexOf(nextMusicItem));
  }
  if (prestartedMusic) {
    updateRadioDebug(root, item, audio, "takeover");
    if (item.kind === "music") {
      updateNowPlayingFromTrack(item.track, root, "正在播放");
    } else {
      updateRadioStatus(`DJ：${item.label}`, root);
    }
    radioDebugEvent("timeline_takeover", `${item.kind} ${audioDebugState(audio)}`, root);
    makeMusicAudioAudible(audio, Math.max(0.04, Number.isFinite(audio.volume) ? audio.volume : RADIO_VOLUME.ducked));
    fadeVolume(audio, RADIO_VOLUME.music, RADIO_VOLUME.restoreMs);
    maybePlayQueuedDjOverlay(root);
    return;
  }
  updateRadioDebug(root, item, audio, "starting");
  audio.play().then(() => {
    updateRadioDebug(root, item, audio, "playing");
    if (item.kind === "music") {
      updateNowPlayingFromTrack(item.track, root, "正在播放");
    } else {
      updateRadioStatus(`DJ：${item.label}`, root);
    }
    radioDebugEvent("timeline_playing", `${item.kind} ${audioDebugState(audio)}`, root);
    if (item.kind === "music") {
      const targetVolume = (shouldKeepMusicAsBed() || isDjAudioActive()) ? RADIO_VOLUME.bed : RADIO_VOLUME.music;
      fadeVolume(audio, targetVolume, prestartedMusic ? RADIO_VOLUME.duckMs : RADIO_VOLUME.fadeMs);
      if (shouldPrepareContinuation()) continueRadioQueueIfNeeded(root);
      window.setTimeout(() => {
        if (token === radioState.playToken && radioState.playing && radioState.timeline[radioState.index] === item) {
          maybePlayQueuedDjOverlay(root);
        }
      }, 0);
    } else if (nextMusicItem && voiceMusicOverlapDelay(item) > 0) {
      window.setTimeout(() => {
        if (token === radioState.playToken && radioState.playing && !radioState.djAudio.paused && radioState.timeline[radioState.index] === item) {
          overlappedMusic = true;
          updateRadioStatus(`${item.segment?.type === "cold_open" ? "DJ 开场" : "DJ 串场"} + 音乐渐入：${nextMusicItem.label}`, root);
          startMusicUnderVoice(nextMusicItem.track, root, radioState.timeline.indexOf(nextMusicItem));
        }
      }, voiceMusicOverlapDelay(item));
    }
  }).catch((error) => {
    if (item.kind === "voice") {
      radioDebugEvent("timeline_voice_play_blocked", `${error.message || error} ${audioDebugState(audio)}`, root);
      updateRadioStatus(`DJ 语音播放失败：${error.message}`, root);
      finishItem();
      return;
    }
    radioDebugEvent("timeline_music_play_blocked", `${error.message || error} ${audioDebugState(audio)}`, root);
    updateRadioStatus(`浏览器拦截了自动起播，请点顶部播放键继续。`, root);
    updateRadioDebug(root, item, audio, "play blocked");
    radioState.playing = false;
    radioState.loading = false;
    const button = root?.querySelector(".radio-start");
    if (button) button.textContent = "继续播放";
    syncHeroTransport();
  });
}

async function prepareRadioTimeline(data, root) {
  updateRadioStatus("正在解析歌曲音频...", root);
  await ensureRadioAutoplayUnlocked(root);
  const songs = flattenSongs(data.groups || []).slice(0, 5).map((song) => ({ title: song.title, artist: song.artist }));
  const response = await fetch(apiUrl("/music-streams"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ songs }),
  });
  const streamData = await response.json();
  const tracks = streamData.tracks || [];
  renderRadioFallbacks(tracks, root);
  const playbackData = alignDjToPlayableTracks(data, tracks);
  refreshDjPanel(root, playbackData.dj);
  const timeline = buildRadioTimeline(playbackData, tracks);
  const playableCount = tracks.filter((track) => track?.ok && track.stream_url).length;
  return { playbackData, tracks, timeline, playableCount, unavailableCount: tracks.length - playableCount };
}

async function prepareInitialRadioTimeline(data, root) {
  updateRadioStatus("正在解析前几首音频...", root);
  await ensureRadioAutoplayUnlocked(root);
  const songs = flattenSongs(data.groups || []).slice(0, 5).map((song) => ({ title: song.title, artist: song.artist }));
  const response = await fetch(apiUrl("/music-streams"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ songs, offset: 0 }),
  });
  const streamData = await response.json();
  const tracks = streamData.tracks || [];
  renderRadioFallbacks(tracks, root);
  const playbackData = alignDjToPlayableTracks(data, tracks);
  refreshDjPanel(root, playbackData.dj);
  const timeline = buildRadioTimeline(playbackData, tracks);
  const playableCount = tracks.filter((track) => track?.ok && track.stream_url).length;
  return { playbackData, tracks, timeline, playableCount, unavailableCount: tracks.length - playableCount, songs };
}

async function hydrateRemainingRadioTimeline(data, root, initialTracks, songs, token) {
  const startOffset = Math.max(0, initialTracks?.length || 0);
  if (!songs || songs.length <= startOffset) return;
  radioState.hydratingQueue = true;
  try {
    const response = await fetch(apiUrl("/music-streams"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ songs: songs.slice(startOffset), offset: startOffset }),
    });
    const streamData = await response.json();
    const tracks = [...(initialTracks || []), ...(streamData.tracks || [])].sort((left, right) => (
      Number(left.requested_index || 0) - Number(right.requested_index || 0)
    ));
    if (token !== radioState.playToken || root !== radioState.activeRoot) return;
    renderRadioFallbacks(tracks, root);
    const playbackData = alignResultToPlayableQueue(data, tracks, root);
    if (data.dj) data.dj._playableQueueReady = true;
    refreshDjPanel(root, playbackData.dj);
    const nextTimeline = buildRadioTimeline(playbackData, tracks);
    const currentItem = radioState.timeline[radioState.index];
    const currentKey = currentItem?.kind === "voice"
      ? `voice:${currentItem.segmentKey}`
      : currentItem?.kind === "music"
        ? `music:${currentItem.track?.original_index ?? currentItem.track?.requested_index}`
        : "";
    radioState.timeline = nextTimeline;
    const newIndex = currentKey
      ? nextTimeline.findIndex((item) => (
        item.kind === "voice"
          ? `voice:${item.segmentKey}` === currentKey
          : `music:${item.track?.original_index ?? item.track?.requested_index}` === currentKey
      ))
      : -1;
    if (newIndex >= 0) radioState.index = newIndex;
    if (radioState.playing && currentItem?.kind === "music" && radioState.activeMusic?.ended) {
      radioState.index = Math.min(radioState.index + 1, radioState.timeline.length);
      playTimelineItem(root);
    }
    const playableCount = tracks.filter((track) => track?.ok && track.stream_url).length;
    const unavailableCount = tracks.length - playableCount;
    if (unavailableCount > 0) {
      updateRadioStatus(`可控播放 ${playableCount} 首，${unavailableCount} 首需外部播放；后续队列已补齐。`, root);
    }
  } catch (error) {
    if (token === radioState.playToken && root === radioState.activeRoot) {
      updateRadioStatus("后续歌曲音频仍在准备中，当前歌曲会继续播放。", root);
    }
  } finally {
    if (token === radioState.playToken && root === radioState.activeRoot) {
      radioState.hydratingQueue = false;
    }
  }
}

async function continueRadioQueueIfNeeded(root, { force = false } = {}) {
  const data = radioState.currentData;
  const playbackRoot = radioState.activeRoot || root;
  if (!data || !radioState.playing) return false;
  if (radioState.continuationPromise) {
    return force ? await radioState.continuationPromise : false;
  }
  if (!force && !shouldPrepareContinuation()) return false;
  if (radioState.continuationCount >= radioState.maxContinuations) return false;
  radioState.continuationPromise = continueRadioQueue(playbackRoot, data, { force });
  try {
    return await radioState.continuationPromise;
  } finally {
    radioState.continuationPromise = null;
  }
}

async function continueRadioQueue(playbackRoot, data, { force = false } = {}) {
  const token = radioState.playToken;
  radioState.continuingQueue = true;
  radioState.continuationCount += 1;
  try {
    updateRadioStatus(force ? "正在补充后续歌曲..." : "后续歌曲正在后台准备。", playbackRoot);
    const response = await fetch(apiUrl("/radio/continue"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: data.query || "",
        provider: data.provider || providerSelect?.value || "local",
        analysis: data.analysis || {},
        groups: sourceGroupsForPlayback(data),
        context: contextPayload(data.query || ""),
        exclude: playbackExcludeSongs(data),
        n: 8,
      }),
    });
    const payload = await response.json();
    if (token !== radioState.playToken || playbackRoot !== radioState.activeRoot) return false;
    const acceptedGroups = mergeContinuationGroups(data, payload.groups || []);
    const newSongs = flattenSongs(acceptedGroups).map((song) => ({ title: song.title, artist: song.artist || "" }));
    if (!newSongs.length) {
      updateRadioStatus("这组歌已经播完，暂时没有新的可续播歌曲。", playbackRoot);
      return false;
    }
    const startOffset = Math.max(0, flattenSongs(sourceGroupsForPlayback(data)).length - newSongs.length);
    const streamResponse = await fetch(apiUrl("/music-streams"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ songs: newSongs, offset: startOffset }),
    });
    const streamData = await streamResponse.json();
    if (token !== radioState.playToken || playbackRoot !== radioState.activeRoot) return false;
    const nextTimeline = buildRadioTimeline(data, streamData.tracks || []);
    const existingKeys = new Set(radioState.timeline.map((item) => (
      item.kind === "voice"
        ? `voice:${item.segmentKey}`
        : `music:${item.track?.original_index ?? item.track?.requested_index}:${songKey({
          title: item.track?.display_title || item.track?.requested_title || item.track?.title || "",
          artist: item.track?.display_artist || item.track?.requested_artist || item.track?.artist || "",
        })}`
    )));
    const additions = nextTimeline.filter((item) => {
      const key = item.kind === "voice"
        ? `voice:${item.segmentKey}`
        : `music:${item.track?.original_index ?? item.track?.requested_index}:${songKey({
          title: item.track?.display_title || item.track?.requested_title || item.track?.title || "",
          artist: item.track?.display_artist || item.track?.requested_artist || item.track?.artist || "",
        })}`;
      return !existingKeys.has(key);
    });
    if (!additions.length) {
      updateRadioStatus("已尝试补充队列，但新增歌曲暂时不可播。", playbackRoot);
      return false;
    }
    const insertionIndex = radioState.timeline.length;
    radioState.timeline.push(...additions);
    renderRadioFallbacks(streamData.tracks || [], playbackRoot);
    updateRadioStatus(`已续上 ${additions.filter((item) => item.kind === "music").length} 首歌。`, playbackRoot);
    if (radioState.playing && radioState.index >= insertionIndex) {
      radioState.index = insertionIndex;
      await playTimelineItem(playbackRoot);
    }
    return true;
  } catch (error) {
    if (token === radioState.playToken && playbackRoot === radioState.activeRoot) {
      updateRadioStatus("续播歌曲还没准备好，当前播放不受影响。", playbackRoot);
    }
    return false;
  } finally {
    if (token === radioState.playToken) {
      radioState.continuingQueue = false;
    }
  }
}

function markRadioStarted(root) {
  radioState.activeRoot = root || null;
  radioState.currentData = root?.dataset?.resultId ? chatState.resultStore[root.dataset.resultId] : radioState.currentData;
  radioState.playing = true;
  radioState.playToken += 1;
  radioState.continuingQueue = false;
  radioState.continuationCount = 0;
  const button = root?.querySelector(".radio-start");
  if (button) {
    button.textContent = "暂停电台播放";
    button.disabled = false;
  }
}

async function startRadio(data, root, { forceStart = false, preserveDj = false } = {}) {
  if (radioState.playing) {
    const previousRoot = radioState.activeRoot;
    const sameRoot = previousRoot && root && previousRoot === root;
    if (preserveDj && radioState.djAudio && !radioState.djAudio.paused && !radioState.djAudio.ended) {
      stopMusicForTakeover();
      radioState.playing = false;
      radioState.activeRoot = null;
    } else {
      stopRadio();
    }
    const previousButton = previousRoot?.querySelector?.(".radio-start");
    if (previousButton) previousButton.textContent = "开始电台播放";
    if (sameRoot && !forceStart) {
      updateRadioStatus("已暂停", root);
      const button = root?.querySelector(".radio-start");
      if (button) button.textContent = "开始电台播放";
      return;
    }
  }
  if (radioState.loading) return;
  radioState.loading = true;
  const button = root?.querySelector(".radio-start");
  if (button) button.disabled = true;
  try {
    let prepared = await prepareInitialRadioTimeline(data, root);
    if (!prepared.timeline.length) {
      updateRadioStatus("第一首暂时不可播，正在查找下一首可播歌曲...", root);
      prepared = await prepareRadioTimeline(data, root);
    }
    const { timeline, tracks, playableCount, unavailableCount, songs } = prepared;
    radioState.timeline = timeline;
    radioState.index = 0;
    if (!radioState.timeline.length) {
      const fallback = tracks.find((track) => track.search_url || track.song_url);
      updateRadioStatus(fallback ? "暂时拿不到可控音频，请使用下方外部播放入口。" : "没有可播放音频。", root);
      return;
    }
    const hasPlayableMusic = radioState.timeline.some((item) => item.kind === "music");
    if (!hasPlayableMusic) {
      updateRadioStatus("将播放 DJ 开场；歌曲暂时只能使用外部播放器。", root);
    } else if (unavailableCount > 0) {
      updateRadioStatus(`可控播放 ${playableCount} 首，${unavailableCount} 首需外部播放；电台将自动播放可控歌曲。`, root);
    }
    alignResultToPlayableQueue(data, tracks, root);
    if (data.dj) data.dj._playableQueueReady = true;
    radioState.currentData = data;
    markRadioStarted(root);
    playTimelineItem(root);
    window.setTimeout(() => beginAsyncDjIfNeeded(data, root), 0);
    hydrateRemainingRadioTimeline(data, root, tracks, songs, radioState.playToken);
  } catch (error) {
    updateRadioStatus(`电台播放启动失败：${error.message}`, root);
  } finally {
    radioState.loading = false;
    if (button) button.disabled = false;
  }
}

async function startRadioFromDjAudio(audio) {
  const root = audio?.closest(".assistant-result");
  const resultId = root?.dataset.resultId || "";
  const data = chatState.resultStore[resultId];
  if (!data || !root || radioState.loading) return;
  const segmentKey = audio?.dataset?.segmentKey || "";
  const segmentIndex = Number(audio?.dataset?.segmentIndex);
  if (radioState.playing) {
    stopRadio();
  }
  radioState.loading = true;
  const button = root.querySelector(".radio-start");
  if (button) button.disabled = true;
  try {
    let prepared = await prepareInitialRadioTimeline(data, root);
    if (!prepared.timeline.length) {
      prepared = await prepareRadioTimeline(data, root);
    }
    const { timeline, tracks, songs } = prepared;
    radioState.timeline = timeline;
    const targetIndex = timeline.findIndex((item) => (
      item?.kind === "voice"
      && (
        (segmentKey && item.segmentKey === segmentKey)
        || (Number.isInteger(segmentIndex) && item.segmentIndex === segmentIndex)
      )
    ));
    radioState.index = Math.max(0, targetIndex);
    if (!radioState.timeline.length) {
      updateRadioStatus("没有可播放音频。", root);
      return;
    }
    alignResultToPlayableQueue(data, tracks, root);
    if (data.dj) data.dj._playableQueueReady = true;
    radioState.currentData = data;
    markRadioStarted(root);
    playTimelineItem(root);
    hydrateRemainingRadioTimeline(data, root, tracks, songs, radioState.playToken);
  } catch (error) {
    updateRadioStatus(`电台播放启动失败：${error.message}`, root);
  } finally {
    radioState.loading = false;
    if (button) button.disabled = false;
  }
  if (!segmentKey && !Number.isInteger(segmentIndex)) {
    hydrateDjTts(data, root);
  }
}

function radioPlayerHtml(data) {
  const songs = flattenSongs(data.groups || []);
  const hasDjAudio = spokenSegments(data.dj).length > 0;
  if (!songs.length) return "";
  return `
    <section class="radio-playback">
      <div>
        <strong>电台播放流</strong>
        <span class="radio-playback-status">${hasDjAudio ? "DJ 语音已就绪，点击后自动交替播放。" : "DJ 语音未就绪，将尝试直接播放歌曲。"}</span>
      </div>
      <button class="radio-start" type="button">开始电台播放</button>
      <div class="radio-fallbacks" hidden></div>
    </section>
  `;
}

function renderAnalysis(analysis, answer) {
  analysisEl.hidden = true;
  analysisEl.innerHTML = analysisHtml(analysis, answer);
}

function entityCard(entity) {
  const tracks = (entity.tracks || []).slice(0, 12).map((track) => `<span class="track">${esc(track)}</span>`).join("");
  const label = {
    album: "专辑",
    artist: "歌手",
    song: "单曲",
    playlist: "歌单",
  }[entity.type] || "实体";
  return `
    <article class="card entity-card">
      <div class="song-head">
        <div>
          <p class="entity-type">${esc(label)}</p>
          <h2 class="song-title">${esc(entity.title)}</h2>
          ${entity.artist ? `<p class="artist">${esc(entity.artist)}</p>` : ""}
        </div>
        <span class="badge">实体</span>
      </div>
      ${entity.reason ? `<p class="reason">${esc(entity.reason)}</p>` : ""}
      ${tracks ? `<div class="tracks">${tracks}</div>` : ""}
      <div class="links">
        <a class="play-link" href="${esc(entity.url || appleMusicSearchUrl(entity.title, entity.artist))}" target="_blank" rel="noopener">Apple Music</a>
        <a class="play-link" href="${esc(entity.spotify_search)}" target="_blank" rel="noopener">Spotify 搜索</a>
      </div>
    </article>
  `;
}

function songKey(song) {
  return `${song.title || ""}|||${song.artist || ""}`;
}

function songCard(song) {
  const key = esc(songKey(song));
  const reason = song.reason ? `<p class="reason">${esc(song.reason)}</p>` : "";
  return `
    <article class="song-row" data-title="${esc(song.title)}" data-artist="${esc(song.artist)}">
      <div class="song-main">
        <div class="song-index"></div>
        <div class="mini-eq" aria-hidden="true"><i></i><i></i><i></i></div>
        <div class="song-copy">
          <div class="song-line">
            <h2 class="song-title">${esc(song.title)}</h2>
            <span class="artist">${esc(song.artist)}</span>
          </div>
          ${reason}
        </div>
        <div class="song-actions">
          <button class="load-player" type="button">播放</button>
          <a class="play-link compact-link" href="${esc(song.url || appleMusicSearchUrl(song.title, song.artist))}" target="_blank" rel="noopener">Apple</a>
          <a class="play-link compact-link" href="${esc(song.spotify_search)}" target="_blank" rel="noopener">Spotify</a>
        </div>
      </div>
      <div class="inline-player" data-preview-key="${key}"></div>
    </article>
  `;
}

async function hydratePlayers() {
  const players = Array.from(document.querySelectorAll(".inline-player[data-autoload='true']"));
  await Promise.all(players.map(async (player) => {
    const loadToken = player.dataset.loadToken || "";
    const card = player.closest(".song-row");
    const title = card?.dataset.title || "";
    const artist = card?.dataset.artist || "";
    if (!title) {
      player.innerHTML = `<div class="player-unavailable">暂无播放信息</div>`;
      return;
    }
    try {
      const response = await fetch(apiUrl("/music-player"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, artist }),
      });
      const data = await response.json();
      if (player.dataset.loadToken !== loadToken || player.dataset.autoload !== "true") {
        return;
      }
      if (!data.ok || !data.player_url) {
        const providerName = data.provider === "apple_music" ? "Apple Music" : (data.provider === "spotify" ? "Spotify" : "网易云");
        player.innerHTML = `
          <div class="player-unavailable">
            暂无${providerName}内嵌播放器
            ${data.search_url ? `<a href="${esc(data.search_url)}" target="_blank" rel="noopener">去${providerName}搜索</a>` : ""}
          </div>
        `;
        return;
      }
      const songUrl = data.song_url || data.search_url || "#";
      if (data.provider === "apple_music" && data.preview_url) {
        player.innerHTML = `
          <div class="apple-preview-player">
            ${data.image_url ? `<img src="${esc(data.image_url)}" alt="${esc(data.title || title)} 封面" />` : ""}
            <div>
              <strong>${esc(data.title || title)}${data.artist ? ` · ${esc(data.artist)}` : ""}</strong>
              ${data.album ? `<span>${esc(data.album)}</span>` : ""}
              <audio controls preload="metadata" src="${esc(mediaUrl(data.preview_url))}"></audio>
              <a href="${esc(songUrl)}" target="_blank" rel="noopener">Apple Music</a>
            </div>
          </div>
        `;
        return;
      }
      const isSpotify = data.provider === "spotify";
      const providerName = isSpotify ? "Spotify" : "网易云";
      player.innerHTML = `
        <details class="music-details ${isSpotify ? "spotify-details" : "netease-details"}" open>
          <summary>
            <span>${providerName}</span>
            <strong>${esc(data.title || title)}${data.artist ? ` · ${esc(data.artist)}` : ""}</strong>
          </summary>
          <iframe
            class="${isSpotify ? "spotify-frame" : "netease-frame"}"
            title="${esc(data.title || title)} - ${esc(data.artist || artist)}"
            src="${esc(data.player_url)}"
            loading="lazy"
            frameborder="0"
            allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
            marginwidth="0"
            marginheight="0"
            width="100%"
            height="${isSpotify ? "152" : "86"}"
          ></iframe>
        </details>
        <div class="player-meta compact">
          <span>${isSpotify ? "如需完整播放，请在 Spotify 中登录账号" : "内嵌播放器空白时，请使用外部播放"}</span>
          <a href="${esc(songUrl)}" target="_blank" rel="noopener">
            打开${providerName}播放
          </a>
        </div>
      `;
    } catch (error) {
      if (player.dataset.loadToken !== loadToken || player.dataset.autoload !== "true") {
        return;
      }
      player.innerHTML = `<div class="player-unavailable">播放器加载失败</div>`;
    }
  }));
}

function resultsHtml(groups, answer, entities = []) {
  const entityHtml = entities && entities.length ? `
    <section class="group">
      <div class="group-title">
        <span>实体结果</span>
        <span class="count">${entities.length} 个</span>
      </div>
      <div class="cards entity-cards">${entities.map(entityCard).join("")}</div>
    </section>
  ` : "";

  if ((!groups || !groups.length) && !entityHtml) {
    return answer ? "" : `<div class="empty inline-empty">当前意图只做分类，不返回歌曲。</div>`;
  }

  const groupHtml = (groups || []).map((group) => `
    <section class="group">
      <div class="group-title">
        <span>${esc(group.title)}</span>
        <span class="count">${group.songs.length} 首</span>
      </div>
      <div class="song-list">${group.songs.map(songCard).join("")}</div>
    </section>
  `).join("");
  return entityHtml + groupHtml;
}

function assistantResponseHtml(data) {
  const resultId = `result-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  data._resultId = resultId;
  chatState.resultStore[resultId] = data;
  if (flattenSongs(data.groups || []).length) {
    chatState.latestResultId = resultId;
  }
  return `
    <div class="assistant-result" data-result-id="${esc(resultId)}">
      ${radioPlayerHtml(data)}
      ${djHtml(data.dj)}
      ${analysisHtml(data.analysis, data.answer)}
      ${resultsHtml(data.groups, data.answer, data.entities)}
    </div>
  `;
}

function isControlPlaySong(data) {
  return data?.analysis?.intent === "control" && data?.control?.type === "play_song";
}

function controlSongData(data) {
  const song = data?.control?.song || flattenSongs(data?.groups || [])[0];
  if (!song?.title) return null;
  return {
    ...data,
    analysis: {
      ...(data.analysis || {}),
      domain: "info_retrieval",
      intent: "entity_search",
      entity_type: "song",
      action: "play",
    },
    answer: "",
    groups: [
      {
        title: "播控目标",
        songs: [
          {
            title: song.title,
            artist: song.artist || "",
            reason: "根据你的播控指令直接起播这首歌。",
            spotify_search: song.spotify_search || `https://open.spotify.com/search/${encodeURIComponent(`${song.title} ${song.artist || ""}`)}`,
          },
        ],
      },
    ],
  };
}

function stopActiveAudioForSkip() {
  clearRadioWatchdog();
  radioState.timeline.forEach((item) => {
    if (item?.kind === "music") {
      clearPrestartedTrack(item.track);
    }
  });
  [radioState.djAudio, radioState.musicAudio, radioState.musicAudioB].forEach((audio) => {
    cancelFade(audio);
    audio.pause();
  });
}

function musicTimelineIndexes() {
  return radioState.timeline
    .map((item, index) => (item?.kind === "music" ? index : -1))
    .filter((index) => index >= 0);
}

function musicTimelineIndexByOriginalIndex(originalIndex) {
  if (!Number.isInteger(originalIndex)) return -1;
  return radioState.timeline.findIndex((item) => (
    item?.kind === "music"
    && (item.track?.original_index ?? item.track?.requested_index) === originalIndex
  ));
}

function activeMusicTimelinePosition(indexes) {
  const active = radioState.activeMusic;
  if (active && !active.paused && !active.ended) {
    const prestartedIndex = indexes.findIndex((index) => {
      const item = radioState.timeline[index];
      return item?.track?._startedAudio === active;
    });
    if (prestartedIndex >= 0) return prestartedIndex;
  }
  const current = radioState.index;
  const exact = indexes.findIndex((index) => index === current);
  if (exact >= 0) return exact;
  for (let i = indexes.length - 1; i >= 0; i -= 1) {
    if (indexes[i] < current) return i;
  }
  return -1;
}

function currentMusicOriginalIndex() {
  const active = radioState.activeMusic;
  const activeTrack = radioState.timeline.find((item) => (
    item?.kind === "music" && item.track?._startedAudio === active
  ))?.track;
  const src = String(active?.src || "");
  const srcTrack = activeTrack ? null : radioState.timeline.find((item) => (
    item?.kind === "music"
    && item.track?.stream_url
    && src.includes(encodeURIComponent(item.track.stream_url))
  ))?.track;
  const track = activeTrack || srcTrack || (radioState.timeline[radioState.index]?.kind === "music" ? radioState.timeline[radioState.index].track : null);
  const index = track?.original_index ?? track?.requested_index;
  return Number.isInteger(index) ? index : -1;
}

async function resolveOneTrack(song, index) {
  if (!song?.title) return null;
  const response = await fetch(apiUrl("/music-streams"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      songs: [{ title: song.title, artist: song.artist || "" }],
      offset: index,
    }),
  });
  const data = await response.json();
  const track = (data.tracks || []).find((item) => item?.ok && item.stream_url);
  if (!track) return null;
  return {
    ...track,
    original_index: index,
    requested_index: index,
    display_title: song.title,
    display_artist: song.artist || "",
    display_image_url: song.image_url || song.cover_url || track.image_url || track.cover_url || "",
  };
}

async function playResolvedTrackForSkip(track, root, data) {
  if (!track?.stream_url) return false;
  const playbackRoot = radioState.activeRoot || root;
  stopActiveAudioForSkip();
  const timelineIndex = musicTimelineIndexByOriginalIndex(track.original_index ?? track.requested_index);
  const timelineItem = timelineIndex >= 0 ? radioState.timeline[timelineIndex] : null;
  const playbackTrack = timelineItem?.track ? { ...timelineItem.track, ...track } : track;
  if (timelineItem) {
    timelineItem.track = playbackTrack;
    timelineItem.label = `${playbackTrack.display_title || playbackTrack.requested_title || playbackTrack.title} - ${playbackTrack.display_artist || playbackTrack.requested_artist || playbackTrack.artist || ""}`;
  }
  radioState.playing = true;
  radioState.currentData = data || radioState.currentData;
  radioState.activeRoot = playbackRoot;
  if (timelineItem) {
    radioState.index = timelineIndex;
  } else {
    radioState.timeline = [{ kind: "music", track: playbackTrack, label: `${playbackTrack.display_title} - ${playbackTrack.display_artist}` }];
    radioState.index = 0;
  }
  markRadioStarted(playbackRoot);
  const token = radioState.playToken;
  const audio = nextMusicAudio();
  radioState.activeMusic = audio;
  resetAudioHandlers(audio);
  cancelFade(audio);
  audio.src = proxiedMusicUrl(playbackTrack.stream_url);
  audio.loop = false;
  audio.currentTime = 0;
  makeMusicAudioAudible(audio, 0.06);
  playbackTrack._startedAudio = audio;
  playbackTrack._startedToken = token;
  playbackTrack._timelineIndex = radioState.index;
  updateNowPlayingFromTrack(playbackTrack, playbackRoot, "正在切到");
  updateRadioDebug(playbackRoot, radioState.timeline[radioState.index], audio, "skip starting");
  try {
    await audio.play();
  } catch (error) {
    if (token !== radioState.playToken) return false;
    radioDebugEvent("skip_play_failed", `${error.message || error} ${audioDebugState(audio)}`, playbackRoot);
    resetAudioHandlers(audio);
    audio.pause();
    audio.removeAttribute("src");
    audio.load?.();
    radioState.playing = false;
    syncHeroTransport();
    return false;
  }
  if (token !== radioState.playToken) return false;
  fadeVolume(audio, RADIO_VOLUME.music, RADIO_VOLUME.fadeMs);
  audio.onended = () => {
    if (token !== radioState.playToken) return;
    radioState.index += 1;
    playTimelineItem(playbackRoot);
  };
  audio.onerror = () => {
    if (token !== radioState.playToken) return;
    radioDebugEvent("skip_audio_error", audioDebugState(audio), playbackRoot);
    radioState.playing = false;
    updateRadioStatus("这首歌播放失败，请再试一次切歌。", playbackRoot);
    syncHeroTransport();
  };
  audio.ontimeupdate = () => updateRadioDebug(playbackRoot, radioState.timeline[radioState.index], audio, "skip playing");
  updateNowPlayingFromTrack(playbackTrack, playbackRoot, "正在播放");
  radioDebugEvent("skip_playing", audioDebugState(audio), playbackRoot);
  syncHeroTransport();
  maybePlayQueuedDjOverlay(playbackRoot);
  if (timelineIndex >= 0 && token === radioState.playToken && !audio.ended) {
    radioState.index = timelineIndex;
  }
  return true;
}

async function skipBySongList(direction, root) {
  const data = radioState.currentData || latestResultData();
  const playbackRoot = radioState.activeRoot || root;
  const songs = flattenSongs(sourceGroupsForPlayback(data)).slice(0, 5);
  if (!songs.length) return false;
  const currentIndex = currentMusicOriginalIndex();
  const step = direction === "previous" ? -1 : 1;
  let targetIndex = currentIndex >= 0 ? currentIndex + step : (direction === "previous" ? 0 : 1);
  if (targetIndex < 0 || targetIndex >= songs.length) {
    updateRadioStatus(direction === "previous" ? "已经是第一首" : "已经是最后一首", playbackRoot);
    return true;
  }
  updateRadioStatus(direction === "previous" ? "正在切到上一首..." : "正在切到下一首...", playbackRoot);
  for (; targetIndex >= 0 && targetIndex < songs.length; targetIndex += step) {
    const track = await resolveOneTrack(songs[targetIndex], targetIndex);
    if (!track) continue;
    const played = await playResolvedTrackForSkip(track, playbackRoot, data);
    if (played) return true;
    updateRadioStatus(direction === "previous" ? "上一首播放失败，继续找可播歌曲..." : "下一首播放失败，继续找可播歌曲...", playbackRoot);
  }
  updateRadioStatus(direction === "previous" ? "上一首暂时不可播" : "下一首暂时不可播", playbackRoot);
  return true;
}

async function skipToTimelineMusic(direction, root) {
  const playbackRoot = radioState.activeRoot || root;
  const indexes = musicTimelineIndexes();
  if (!indexes.length) {
    return await skipBySongList(direction, playbackRoot);
  }
  const activePosition = activeMusicTimelinePosition(indexes);
  const nextPosition = direction === "previous"
    ? Math.max(0, activePosition <= 0 ? 0 : activePosition - 1)
    : Math.min(indexes.length - 1, activePosition + 1);
  if (nextPosition === activePosition && radioState.timeline[radioState.index]?.kind === "music") {
    if (radioState.hydratingQueue && direction === "next") {
      return await skipBySongList(direction, playbackRoot);
    }
    updateRadioStatus(direction === "previous" ? "已经是第一首" : "已经是最后一首", playbackRoot);
    return true;
  }
  const item = radioState.timeline[indexes[nextPosition]];
  if (item?.kind === "music" && item.track?.stream_url) {
    const played = await playResolvedTrackForSkip(item.track, playbackRoot, radioState.currentData || latestResultData());
    if (played) return true;
    return await skipBySongList(direction, playbackRoot);
  }
  return await skipBySongList(direction, playbackRoot);
}

async function executeControl(data, root, startFn = startRadio) {
  const controlType = data?.control?.type || "";
  if (!controlType) return false;
  const playbackRoot = radioState.activeRoot || latestAssistantRoot() || root;
  const playbackData = radioState.currentData || latestResultData();
  const speakControl = () => {
    if (root && data?.dj) window.setTimeout(() => hydrateDjTts(data, root), 0);
  };
  if (controlType === "play_song") {
    const playableData = controlSongData(data);
    if (!playableData) return false;
    invalidateAsyncDj({ preserveActiveAudio: true });
    window.setTimeout(() => {
      startFn(playableData, root, { forceStart: true, preserveDj: true });
      speakControl();
    }, 0);
    return true;
  }
  if (controlType === "status") {
    if (data?.answer) updateRadioStatus(data.answer, playbackRoot);
    speakControl();
    return true;
  }
  if (controlType === "pause") {
    pauseHeroPlayback(playbackRoot);
    speakControl();
    return true;
  }
  if (controlType === "next" || controlType === "previous") {
    invalidateAsyncDj();
    if (playbackData) radioState.currentData = playbackData;
    const count = Math.max(1, Math.min(10, Number(data?.control?.count || 1) || 1));
    let handled = false;
    for (let step = 0; step < count; step += 1) {
      handled = await skipToTimelineMusic(controlType, playbackRoot);
      if (!handled) break;
      const atEnd = /已经是(第一|最后)首/.test(playbackRoot?.querySelector?.(".radio-playback-status")?.textContent || "");
      if (atEnd) break;
    }
    speakControl();
    return handled;
  }
  if (controlType === "resume") {
    const active = radioState.activeMusic || radioState.musicAudio;
    active.play?.().then(() => {
      radioState.playing = true;
      updateRadioStatus("继续播放中", playbackRoot);
      speakControl();
    }).catch(() => updateRadioStatus("浏览器需要你点一下播放才能继续", playbackRoot));
    return true;
  }
  if (controlType === "volume_up" || controlType === "volume_down") {
    const delta = controlType === "volume_up" ? 0.12 : -0.12;
    [radioState.djAudio, radioState.musicAudio, radioState.musicAudioB].forEach((audio) => {
      audio.volume = Math.max(0, Math.min(1, (Number.isFinite(audio.volume) ? audio.volume : 0.5) + delta));
    });
    updateRadioStatus(controlType === "volume_up" ? "已调大音量" : "已调小音量", playbackRoot);
    speakControl();
    return true;
  }
  return false;
}

function latestAssistantRoot() {
  if (!chatState.latestResultId) return null;
  return conversationEl.querySelector(`[data-result-id="${selectorEsc(chatState.latestResultId)}"]`);
}

function latestResultData() {
  return chatState.latestResultId ? chatState.resultStore[chatState.latestResultId] : null;
}

function playOpeningDj() {
  if (chatState.openingPlayed) return false;
  chatState.openingPlayed = true;
  const data = openingDjPayload();
  const pendingId = addMessage("assistant", assistantResponseHtml(data), { scroll: false });
  const root = conversationEl.querySelector(`[data-message-id="${selectorEsc(pendingId)}"] .assistant-result`);
  if (root) {
    hydrateDjTts(data, root);
    return true;
  }
  chatState.openingPlayed = false;
  return false;
}

function scheduleOpeningDjAutoplay() {
  window.setTimeout(() => {
    playOpeningDj();
  }, 250);
}

async function handleHeroControl(type) {
  const root = currentPlaybackRoot();
  const data = currentPlaybackData();
  if (type === "play") {
    if (radioState.playing) {
      pauseHeroPlayback(root);
      return;
    }
    if (hasRealPlaybackToResume()) {
      if (await resumeHeroPlayback(root)) {
        return;
      }
    }
    unlockRadioAudio(root);
    const query = queryInput.value.trim();
    if (query && !submitBtn.disabled) {
      chatState.autoplayNextResult = true;
      recommend(query);
      return;
    }
    if (playOpeningDj()) {
      return;
    }
    return;
  }
  if (!root) {
    updateRadioStatus("先发送一个请求，Melodio 会生成可播放队列。", null);
    return;
  }
  if (type === "next" || type === "previous") {
    if (data) radioState.currentData = data;
    await executeControl({ control: { type }, analysis: { intent: "control" } }, root);
    return;
  }
  if (type === "favorite") {
    toggleHeroFavorite(root);
  }
}

function renderResults(groups, answer, entities = []) {
  resultsEl.hidden = true;
  resultsEl.innerHTML = resultsHtml(groups, answer, entities);
}

function renderLoading(text) {
  return `<p class="loading-text">${esc(text)}</p>`;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function renderAsyncSkeleton(data, note = "线上模型正在生成推荐，歌曲稍后自动补齐。") {
  return `
    <div class="assistant-result async-skeleton">
      ${analysisHtml(data.analysis, data.answer || note)}
      <p class="loading-text">${esc(note)}</p>
    </div>
  `;
}

function setVoiceButtonState(state, label) {
  if (!voiceBtn) return;
  voiceBtn.dataset.state = state;
  voiceBtn.textContent = label;
  voiceBtn.classList.toggle("is-listening", state === "listening");
  if (state === "listening") setDispatchStatus("正在听你说话...");
}

function clearVoiceTimers() {
  if (voiceState.submitTimer) {
    window.clearTimeout(voiceState.submitTimer);
    voiceState.submitTimer = null;
  }
  if (voiceState.noSpeechTimer) {
    window.clearTimeout(voiceState.noSpeechTimer);
    voiceState.noSpeechTimer = null;
  }
}

function browserNavigator() {
  if (typeof window !== "undefined" && window.navigator) return window.navigator;
  if (typeof navigator !== "undefined") return navigator;
  return null;
}

function microphoneApiAvailable() {
  const nav = browserNavigator();
  return Boolean(nav?.mediaDevices?.getUserMedia);
}

function mediaRecorderAvailable() {
  return microphoneApiAvailable() && typeof window.MediaRecorder !== "undefined";
}

function webAudioAvailable() {
  return microphoneApiAvailable() && Boolean(window.AudioContext || window.webkitAudioContext) && typeof window.WebSocket !== "undefined";
}

function preferRecordedVoiceInput() {
  const location = window.location || {};
  const hostname = String(location.hostname || "");
  return hostname.endsWith(".vercel.app");
}

function voiceUnavailableReason() {
  if (!microphoneApiAvailable()) {
    return "当前浏览器无法访问麦克风，请用 Chrome 打开 http://127.0.0.1:7890/";
  }
  if (!webAudioAvailable() && !SpeechRecognition && !mediaRecorderAvailable()) {
    return "当前浏览器不支持实时语音输入，请用 Chrome 打开 http://127.0.0.1:7890/";
  }
  return "";
}

function setVoiceUnavailable(reason) {
  if (!voiceBtn) return;
  voiceBtn.disabled = true;
  voiceBtn.textContent = "不可用";
  voiceBtn.title = reason;
  if (queryInput) queryInput.placeholder = reason;
}

function microphoneErrorMessage(error) {
  const name = error?.name || "";
  if (name === "NotAllowedError" || name === "PermissionDeniedError") {
    return "麦克风权限被浏览器拦截，请在地址栏权限里允许麦克风后刷新";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "没有检测到可用麦克风";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "麦克风正在被其他应用占用，请关闭后重试";
  }
  return `麦克风启动失败：${error?.message || name || "未知错误"}`;
}

async function requestMicrophoneAccess() {
  const nav = browserNavigator();
  if (!nav?.mediaDevices?.getUserMedia) {
    return { ok: false, error: "当前浏览器无法访问麦克风，请用 Chrome 打开 http://127.0.0.1:7890/" };
  }
  try {
    const stream = await Promise.race([
      nav.mediaDevices.getUserMedia({ audio: true }),
      new Promise((_, reject) => {
        window.setTimeout(() => reject(new Error("mic-permission-timeout")), VOICE_MIC_PERMISSION_TIMEOUT_MS);
      }),
    ]);
    stream.getTracks().forEach((track) => track.stop());
    return { ok: true, error: "" };
  } catch (error) {
    if (error?.message === "mic-permission-timeout") {
      return { ok: false, error: "正在等待麦克风权限，请在浏览器弹窗或地址栏权限里选择允许" };
    }
    return { ok: false, error: microphoneErrorMessage(error) };
  }
}

const VOICE_CORRECTIONS = [
  [/张\s*[轩璇玄萱悬]/g, "张悬"],
  [/焦\s*安\s*[普浦谱铺]/g, "焦安溥"],
  [/焦安普/g, "焦安溥"],
  [/娇安普/g, "焦安溥"],
  [/jiao\s*an\s*pu/gi, "焦安溥"],
  [/曹东没有派对/g, "草东没有派对"],
  [/曹东/g, "草东"],
  [/草东没派对/g, "草东没有派对"],
  [/比利\s*艾利什/g, "Billie Eilish"],
  [/碧梨/g, "Billie Eilish"],
  [/比莉\s*艾利什/g, "Billie Eilish"],
  [/billie\s*eilish/gi, "Billie Eilish"],
  [/陆\s*谷\s*湖/g, "泸沽湖"],
  [/泸\s*姑\s*湖/g, "泸沽湖"],
  [/卢\s*沟\s*湖/g, "泸沽湖"],
  [/乐队的夏添/g, "乐队的夏天"],
  [/周杰论/g, "周杰伦"],
  [/周洁伦/g, "周杰伦"],
  [/周杰轮/g, "周杰伦"],
  [/许song/gi, "许嵩"],
  [/许松/g, "许嵩"],
  [/陶哲/g, "陶喆"],
  [/薛之千/g, "薛之谦"],
  [/林有嘉/g, "林宥嘉"],
  [/邓子琪/g, "邓紫棋"],
  [/王非/g, "王菲"],
  [/万能青年旅社/g, "万能青年旅店"],
  [/黑怕/g, "hiphop"],
  [/嘻哈/g, "hiphop"],
  [/hip\s*hop/gi, "hiphop"],
  [/c\s*d\s*c/gi, "CDC"],
  [/西\s*地\s*西/g, "CDC"],
  [/成都\s*c\s*d\s*c/gi, "成都CDC"],
  [/(?<!中国)新\s*说\s*唱/g, "中国新说唱"],
  [/中国新说唱/g, "中国新说唱"],
  [/说唱新时代/g, "说唱新世代"],
  [/说唱新世代/g, "说唱新世代"],
  [/乐夏/g, "乐队的夏天"],
  [/乐队的夏添/g, "乐队的夏天"],
  [/海尔兄弟/g, "Higher Brothers"],
  [/higher\s*brothers/gi, "Higher Brothers"],
  [/马思维/g, "马思唯"],
  [/马师傅/g, "马思唯"],
  [/谢老板/g, "谢帝"],
  [/g\s*a\s*i/gi, "GAI"],
  [/盖周延/g, "GAI周延"],
  [/王以太/g, "王以太"],
  [/王乙太/g, "王以太"],
  [/艾热/g, "艾热"],
  [/姜云生/g, "姜云升"],
  [/小青龙/g, "小青龙"],
  [/kafe\s*hu/gi, "Kafe.Hu"],
  [/咖啡壶/g, "Kafe.Hu"],
];

const VOICE_MUSIC_TERMS = [
  "播放", "放", "听", "推荐", "歌曲", "音乐", "歌手", "专辑", "第", "首",
  "张悬", "焦安溥", "草东", "Billie Eilish", "泸沽湖", "周杰伦", "许嵩", "陶喆",
  "薛之谦", "林宥嘉", "邓紫棋", "王菲", "万能青年旅店",
  "hiphop", "说唱", "中文说唱", "CDC", "成都说唱", "云南说唱", "中国新说唱",
  "说唱新世代", "乐队的夏天", "Higher Brothers", "马思唯", "谢帝", "GAI",
  "王以太", "艾热", "姜云升", "小青龙", "Kafe.Hu", "云南", "昆明", "成都",
];

const VOICE_STATIC_ENTITIES = [
  "张悬", "焦安溥", "草东没有派对", "草东", "Billie Eilish", "泸沽湖", "周杰伦",
  "许嵩", "陶喆", "薛之谦", "林宥嘉", "邓紫棋", "王菲", "万能青年旅店",
  "Kanye West", "Kanye", "Taylor Swift", "陈奕迅", "孙燕姿", "蔡依林", "王力宏",
  "Higher Brothers", "马思唯", "谢帝", "GAI", "王以太", "艾热", "姜云升",
  "小青龙", "Kafe.Hu", "CDC", "中国新说唱", "说唱新世代", "乐队的夏天",
];

function normalizeVoiceTranscript(text, alternatives = []) {
  const candidates = [text, ...alternatives].map((item) => String(item || "").trim()).filter(Boolean);
  if (!candidates.length) return "";
  return candidates
    .map((candidate, index) => {
      const normalized = applyVoiceEntityCorrections(applyVoiceCorrections(candidate));
      return {
        text: normalized,
        score: voiceCandidateScore(normalized) - index * 0.01,
      };
    })
    .sort((left, right) => right.score - left.score)[0].text;
}

function applyVoiceCorrections(text) {
  let normalized = String(text || "").trim();
  VOICE_CORRECTIONS.forEach(([pattern, value]) => {
    normalized = normalized.replace(pattern, value);
  });
  normalized = normalized
    .replace(/(第?\s*[一二三四五六七八九十\d]+)\s*[手艘收]/g, "$1首")
    .replace(/下一[手艘收]/g, "下一首")
    .replace(/上一[手艘收]/g, "上一首")
    .replace(/换一[手艘收]/g, "换一首")
    .replace(/切[手艘收]/g, "切歌");
  return normalized.replace(/\s+/g, " ").trim();
}

function voiceEntitiesFromContext() {
  const entities = new Set(VOICE_STATIC_ENTITIES);
  const add = (value) => {
    const text = String(value || "").trim();
    if (text.length >= 2) entities.add(text);
  };
  add(chatState.currentSong?.title);
  add(chatState.currentSong?.artist);
  flattenSongs(chatState.lastGroups || []).forEach((song) => {
    add(song.title);
    add(song.artist);
  });
  chatState.history.forEach((item) => {
    const content = String(item?.content || "");
    VOICE_STATIC_ENTITIES.forEach((entity) => {
      if (content.includes(entity)) add(entity);
    });
  });
  return Array.from(entities).sort((left, right) => right.length - left.length);
}

function voiceEntityAliases(entity) {
  const aliases = new Set([entity]);
  const compact = entity.replace(/\s+/g, "");
  if (compact !== entity) aliases.add(compact);
  if (/^[A-Za-z\s]+$/.test(entity)) {
    aliases.add(entity.toLowerCase());
  }
  const manual = {
    张悬: ["张轩", "张璇", "张玄", "张萱"],
    焦安溥: ["焦安普", "焦安谱", "娇安普", "jiaoanpu"],
    草东没有派对: ["曹东没有派对", "草东没派对"],
    草东: ["曹东"],
    周杰伦: ["周洁伦", "周杰论", "周杰轮"],
    许嵩: ["许松", "许song"],
    陶喆: ["陶哲"],
    薛之谦: ["薛之千"],
    林宥嘉: ["林有嘉"],
    邓紫棋: ["邓子琪"],
    王菲: ["王非"],
    万能青年旅店: ["万能青年旅社"],
    泸沽湖: ["陆谷湖", "泸姑湖", "卢沟湖"],
    "Billie Eilish": ["比利艾利什", "比莉艾利什", "碧梨", "billieeilish"],
    "Higher Brothers": ["海尔兄弟", "higherbrothers"],
    马思唯: ["马思维", "马师傅", "masiwei"],
    谢帝: ["谢老板"],
    GAI: ["盖", "gai"],
    王以太: ["王乙太"],
    姜云升: ["姜云生"],
    "Kafe.Hu": ["咖啡壶", "kafehu"],
    中国新说唱: ["新说唱"],
    乐队的夏天: ["乐夏", "乐队的夏添"],
    Kanye: ["侃爷", "坎耶"],
    "Kanye West": ["侃爷", "坎耶韦斯特"],
  };
  (manual[entity] || []).forEach((alias) => aliases.add(alias));
  return Array.from(aliases).filter((alias) => alias && alias !== entity);
}

function shouldApplyVoiceEntityCorrection(text) {
  return /播放|放|听|推荐|来点|想听|歌曲|音乐|歌手|专辑|第.+首|类似|相似/.test(text);
}

function applyVoiceEntityCorrections(text) {
  let normalized = String(text || "");
  if (!shouldApplyVoiceEntityCorrection(normalized)) return normalized;
  voiceEntitiesFromContext().forEach((entity) => {
    voiceEntityAliases(entity).forEach((alias) => {
      if (!alias || alias === entity || !normalized.includes(alias)) return;
      if (normalized.includes(entity) && entity.includes(alias)) return;
      normalized = normalized.split(alias).join(entity);
    });
  });
  return normalized;
}

function voiceCandidateScore(text) {
  let score = 0;
  [...VOICE_MUSIC_TERMS, ...voiceEntitiesFromContext()].forEach((term) => {
    if (text.includes(term)) score += term.length > 2 ? 2 : 1;
  });
  if (/第\s*[一二三四五六七八九十\d]+\s*首/.test(text)) score += 4;
  if (/播放|放一下|听|推荐|来点|想听/.test(text)) score += 2;
  return score;
}

function asrWebSocketUrl() {
  const path = "/asr/stream";
  if (window.location.protocol === "file:") return "ws://127.0.0.1:7890/asr/stream";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
}

function resampleFloat32(input, sourceRate, targetRate) {
  if (!input?.length) return new Float32Array();
  if (sourceRate === targetRate) return input;
  const ratio = sourceRate / targetRate;
  const length = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    const position = i * ratio;
    const left = Math.floor(position);
    const right = Math.min(input.length - 1, left + 1);
    const weight = position - left;
    output[i] = input[left] * (1 - weight) + input[right] * weight;
  }
  return output;
}

function floatTo16BitPcm(input) {
  const buffer = new ArrayBuffer(input.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < input.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, input[i]));
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return buffer;
}

function sendVoicePcmChunk(input) {
  const ws = voiceState.ws;
  const context = voiceState.audioContext;
  if (!ws || ws.readyState !== WebSocket.OPEN || !context || !input?.length) return;
  const downsampled = resampleFloat32(input, context.sampleRate || 48000, VOICE_ASR_SAMPLE_RATE);
  if (!downsampled.length) return;
  ws.send(floatTo16BitPcm(downsampled));
}

function cleanupStreamVoiceInput() {
  if (voiceState.audioProcessor) {
    try {
      voiceState.audioProcessor.disconnect();
    } catch (_) {}
    voiceState.audioProcessor.onaudioprocess = null;
    voiceState.audioProcessor = null;
  }
  if (voiceState.audioSource) {
    try {
      voiceState.audioSource.disconnect();
    } catch (_) {}
    voiceState.audioSource = null;
  }
  if (voiceState.audioContext) {
    try {
      voiceState.audioContext.close();
    } catch (_) {}
    voiceState.audioContext = null;
  }
  stopRecorderTracks();
}

function currentVoiceTranscript() {
  const candidates = [voiceState.streamText, voiceState.finalText, queryInput.value]
    .map((item) => normalizeVoiceTranscript(String(item || "").trim()))
    .filter(Boolean);
  if (!candidates.length) return "";
  return candidates.sort((left, right) => right.length - left.length)[0];
}

function handleStreamAsrMessage(data) {
  if (!data || typeof data !== "object") return;
  if (data.event === "ready") {
    queryInput.placeholder = "正在听，边说边识别...";
    return;
  }
  if (data.event === "error") {
    const message = data.error || "豆包 ASR 识别失败";
    voiceState.lastError = message;
    voiceBtn.title = message;
    queryInput.placeholder = message;
    stopStreamVoiceInput({ submit: false });
    setVoiceButtonState("idle", "🎙 语音");
    return;
  }
  const text = normalizeVoiceTranscript(String(data.text || "").trim());
  if (!text) return;
  voiceState.streamText = text;
  if (data.event === "final") voiceState.finalText = text;
  queryInput.value = currentVoiceTranscript() || text;
  voiceState.lastTranscriptAt = Date.now();
  if (voiceState.noSpeechTimer) {
    window.clearTimeout(voiceState.noSpeechTimer);
    voiceState.noSpeechTimer = null;
  }
}

async function startStreamVoiceInput() {
  const micAccess = await requestMicrophoneAccess();
  if (!micAccess.ok) {
    voiceState.lastError = micAccess.error;
    voiceBtn.title = micAccess.error;
    setVoiceButtonState("idle", "需授权");
    queryInput.placeholder = micAccess.error;
    return;
  }
  const nav = browserNavigator();
  const stream = await nav.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  const audioContext = new AudioContextCtor();
  if (audioContext.state === "suspended") {
    await audioContext.resume();
  }
  const source = audioContext.createMediaStreamSource(stream);
  const processor = audioContext.createScriptProcessor(VOICE_STREAM_BUFFER_SIZE, 1, 1);
  const ws = new WebSocket(asrWebSocketUrl());
  ws.binaryType = "arraybuffer";

  voiceState.mode = "stream";
  voiceState.listening = true;
  voiceState.mediaStream = stream;
  voiceState.audioContext = audioContext;
  voiceState.audioSource = source;
  voiceState.audioProcessor = processor;
  voiceState.ws = ws;
  voiceState.streamText = "";
  voiceState.finalText = "";
  voiceState.interimText = "";
  voiceState.lastError = "";
  voiceState.stopRequested = false;
  voiceState.submitted = false;
  queryInput.value = "";
  queryInput.placeholder = "正在连接豆包实时语音...";
  voiceBtn.title = "正在实时识别，说完后会自动发送；再点一次停止";
  setVoiceButtonState("listening", "停止");
  enterVoiceListeningMode();
  clearVoiceTimers();

  voiceState.noSpeechTimer = window.setTimeout(() => {
    if (!voiceState.listening || voiceState.streamText || voiceState.finalText) return;
    queryInput.placeholder = "还没有听到声音，请靠近一点再说";
    voiceBtn.title = "还没有听到声音，请靠近一点再说";
  }, VOICE_NO_SPEECH_HINT_MS);

  processor.onaudioprocess = (event) => {
    if (!voiceState.listening || voiceState.ws !== ws) return;
    const input = event.inputBuffer.getChannelData(0);
    sendVoicePcmChunk(input);
  };

  ws.addEventListener("open", () => {
    ws.send(JSON.stringify({ event: "config", format: "pcm", sample_rate: VOICE_ASR_SAMPLE_RATE }));
    queryInput.placeholder = "正在听，边说边识别...";
    try {
      source.connect(processor);
      processor.connect(audioContext.destination);
    } catch (error) {
      handleStreamAsrMessage({ event: "error", error: `麦克风音频链路启动失败：${error.message}` });
    }
  });
  ws.addEventListener("message", (event) => {
    try {
      handleStreamAsrMessage(JSON.parse(event.data));
    } catch (_) {}
  });
  ws.addEventListener("error", () => {
    handleStreamAsrMessage({ event: "error", error: "豆包 ASR 连接失败，请确认后端服务和 ASR key。" });
  });
  ws.addEventListener("close", () => {
    cleanupStreamVoiceInput();
    if (!voiceState.listening) return;
    voiceState.listening = false;
    exitVoiceListeningMode();
    setVoiceButtonState("idle", voiceState.lastError ? "需授权" : "🎙 语音");
    queryInput.placeholder = voiceState.lastError || "告诉 Melodio 你现在想听什么";
  });
}

function stopStreamVoiceInput({ submit = true } = {}) {
  const text = currentVoiceTranscript();
  clearVoiceTimers();
  voiceState.listening = false;
  voiceState.stopRequested = true;
  const ws = voiceState.ws;
  voiceState.ws = null;
  cleanupStreamVoiceInput();
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify({ event: "stop" }));
    } catch (_) {}
    window.setTimeout(() => {
      try {
        ws.close();
      } catch (_) {}
    }, 250);
  } else if (ws) {
    try {
      ws.close();
    } catch (_) {}
  }
  setVoiceButtonState("idle", "🎙 语音");
  queryInput.placeholder = "告诉 Melodio 你现在想听什么";
  exitVoiceListeningMode();
  if (submit && text && !submitBtn.disabled) {
    queryInput.value = text;
    primeRadioAutoplay();
    chatState.autoplayNextResult = true;
    recommend(text);
  }
}

function preferredAudioMimeType() {
  if (typeof window.MediaRecorder === "undefined") return "";
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ];
  return candidates.find((type) => window.MediaRecorder.isTypeSupported?.(type)) || "";
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const value = String(reader.result || "");
      resolve(value.includes(",") ? value.split(",").pop() : value);
    };
    reader.onerror = () => reject(reader.error || new Error("音频读取失败"));
    reader.readAsDataURL(blob);
  });
}

async function transcribeRecordedAudio(blob) {
  const audioBase64 = await blobToBase64(blob);
  const response = await fetch(apiUrl("/asr/transcribe"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      audio_base64: audioBase64,
      mime_type: blob.type || "audio/webm",
    }),
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok || !payload.text) {
    throw new Error(payload.error || "语音识别失败");
  }
  return normalizeVoiceTranscript(String(payload.text || "").trim());
}

function stopRecorderTracks() {
  if (voiceState.mediaStream) {
    voiceState.mediaStream.getTracks().forEach((track) => track.stop());
    voiceState.mediaStream = null;
  }
}

async function startRecorderVoiceInput() {
  const micAccess = await requestMicrophoneAccess();
  if (!micAccess.ok) {
    voiceState.lastError = micAccess.error;
    voiceBtn.title = micAccess.error;
    setVoiceButtonState("idle", "需授权");
    queryInput.placeholder = micAccess.error;
    return;
  }
  const nav = browserNavigator();
  const stream = await nav.mediaDevices.getUserMedia({ audio: true });
  const mimeType = preferredAudioMimeType();
  const recorder = new window.MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  voiceState.mode = "recorder";
  voiceState.listening = true;
  voiceState.mediaStream = stream;
  voiceState.mediaRecorder = recorder;
  voiceState.mediaChunks = [];
  voiceState.lastError = "";
  queryInput.value = "";
  queryInput.placeholder = "正在录音，说完再点一次麦克风";
  voiceBtn.title = "正在录音，说完再点一次停止识别";
  setVoiceButtonState("listening", "停止");
  enterVoiceListeningMode();
  clearVoiceTimers();
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) voiceState.mediaChunks.push(event.data);
  });
  recorder.addEventListener("stop", async () => {
    const chunks = voiceState.mediaChunks.slice();
    const type = recorder.mimeType || mimeType || "audio/webm";
    stopRecorderTracks();
    clearVoiceTimers();
    voiceState.listening = false;
    voiceState.mediaRecorder = null;
    exitVoiceListeningMode();
    if (!chunks.length) {
      queryInput.placeholder = "没有录到声音，请再试一次";
      setVoiceButtonState("idle", "🎙 语音");
      return;
    }
    setVoiceButtonState("checking", "识别中");
    queryInput.placeholder = "正在识别语音...";
    try {
      const text = await transcribeRecordedAudio(new Blob(chunks, { type }));
      if (!text) throw new Error("没有识别到文本");
      queryInput.value = text;
      setVoiceButtonState("idle", "🎙 语音");
      queryInput.placeholder = "告诉 Melodio 你现在想听什么";
      if (!submitBtn.disabled) {
        primeRadioAutoplay();
        chatState.autoplayNextResult = true;
        recommend(text);
      }
    } catch (error) {
      const message = error.message || "语音识别失败";
      voiceState.lastError = message;
      voiceBtn.title = message;
      queryInput.placeholder = message;
      setVoiceButtonState("idle", "🎙 语音");
    }
  });
  recorder.start();
}

function stopRecorderVoiceInput() {
  const recorder = voiceState.mediaRecorder;
  if (recorder && recorder.state !== "inactive") {
    recorder.stop();
  } else {
    stopRecorderTracks();
    voiceState.listening = false;
    setVoiceButtonState("idle", "🎙 语音");
    exitVoiceListeningMode();
  }
}

function initVoiceInput() {
  if (!voiceBtn) return;
  const unavailable = voiceUnavailableReason();
  if (unavailable) {
    setVoiceUnavailable(unavailable);
    return;
  }
  if (!preferRecordedVoiceInput() && webAudioAvailable()) {
    voiceState.mode = "stream";
    voiceBtn.title = "语音输入：点击开始实时识别，说完自动发送";
    return;
  }
  if (mediaRecorderAvailable()) {
    voiceState.mode = "recorder";
    voiceBtn.title = "语音输入：点击开始，再点一次停止并识别";
    return;
  }
  if (!SpeechRecognition) {
    voiceState.mode = "recorder";
    return;
  }
  const recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 5;
  voiceState.recognition = recognition;

  recognition.addEventListener("start", () => {
    voiceState.listening = true;
    voiceState.interimText = "";
    voiceState.finalText = "";
    voiceState.manualStop = false;
    voiceState.lastError = "";
    queryInput.value = "";
    enterVoiceListeningMode();
    clearVoiceTimers();
    voiceState.noSpeechTimer = window.setTimeout(() => {
      if (!voiceState.listening || voiceState.finalText || voiceState.interimText) return;
      queryInput.placeholder = "还没有听到声音，请确认麦克风权限或靠近一点再说";
      voiceBtn.title = "还没有听到声音，请确认麦克风权限或靠近一点再说";
    }, VOICE_NO_SPEECH_HINT_MS);
    queryInput.placeholder = "正在听...";
    setVoiceButtonState("listening", "停止");
  });

  recognition.addEventListener("result", (event) => {
    let finalText = "";
    let interimText = "";
    const alternatives = [];
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const transcript = event.results[i][0]?.transcript || "";
      for (let altIndex = 1; altIndex < event.results[i].length; altIndex += 1) {
        const alternative = event.results[i][altIndex]?.transcript || "";
        if (alternative) alternatives.push(alternative);
      }
      if (event.results[i].isFinal) {
        finalText += transcript;
      } else {
        interimText += transcript;
      }
    }
    if (finalText.trim()) {
      voiceState.finalText = `${voiceState.finalText}${finalText}`.trim();
    }
    const text = normalizeVoiceTranscript((voiceState.finalText || interimText).trim(), alternatives);
    if (text) {
      voiceState.interimText = text;
      queryInput.value = text;
      if (voiceState.noSpeechTimer) {
        window.clearTimeout(voiceState.noSpeechTimer);
        voiceState.noSpeechTimer = null;
      }
    }
  });

  recognition.addEventListener("error", (event) => {
    const errorLabel = {
      "not-allowed": "麦克风权限被浏览器拦截，请允许麦克风后再试",
      "service-not-allowed": "当前浏览器不允许使用语音识别",
      "audio-capture": "没有检测到可用麦克风",
      "no-speech": "没有听到声音，请再说一次",
      network: "语音识别网络异常，请稍后重试",
    }[event.error] || `语音输入失败：${event.error || "未知错误"}`;
    voiceState.lastError = errorLabel;
    voiceBtn.title = errorLabel;
    clearVoiceTimers();
    setVoiceButtonState("idle", event.error === "not-allowed" ? "需授权" : "🎙 语音");
    queryInput.placeholder = errorLabel;
    voiceState.listening = false;
    exitVoiceListeningMode();
  });

  recognition.addEventListener("end", () => {
    clearVoiceTimers();
    setVoiceButtonState("idle", voiceState.lastError ? "需授权" : "🎙 语音");
    queryInput.placeholder = voiceState.lastError || "输入想听的音乐，例如：适合深夜一个人开车的伤感华语歌";
    voiceState.listening = false;
    exitVoiceListeningMode();
  });
}

async function toggleVoiceInput() {
  if (voiceState.listening) {
    if (voiceState.mode === "stream") {
      stopStreamVoiceInput({ submit: true });
      return;
    }
    if (voiceState.mode === "recorder") {
      stopRecorderVoiceInput();
      return;
    }
    const query = normalizeVoiceTranscript((voiceState.finalText || queryInput.value || "").trim());
    voiceState.manualStop = true;
    voiceState.recognition.stop();
    exitVoiceListeningMode();
    if (query && !submitBtn.disabled) {
      primeRadioAutoplay();
      queryInput.value = query;
      chatState.autoplayNextResult = true;
      recommend(query);
    }
    return;
  }
  if (!preferRecordedVoiceInput() && webAudioAvailable()) {
    try {
      await startStreamVoiceInput();
    } catch (error) {
      const message = error.message || "实时语音输入启动失败";
      voiceState.lastError = message;
      voiceBtn.title = message;
      queryInput.placeholder = message;
      setVoiceButtonState("idle", "🎙 语音");
      exitVoiceListeningMode();
      cleanupStreamVoiceInput();
    }
    return;
  }
  if (mediaRecorderAvailable()) {
    await startRecorderVoiceInput();
    return;
  }
  if (!voiceState.recognition) return;
  voiceState.lastError = "";
  setVoiceButtonState("checking", "授权中");
  queryInput.placeholder = "正在请求麦克风权限...";
  const micAccess = await requestMicrophoneAccess();
  if (!micAccess.ok) {
    voiceState.lastError = micAccess.error;
    voiceBtn.title = micAccess.error;
    setVoiceButtonState("idle", "需授权");
    queryInput.placeholder = micAccess.error;
    return;
  }
  try {
    voiceState.recognition.start();
  } catch (error) {
    voiceBtn.title = `语音输入启动失败：${error.message}`;
  }
}

async function recommend(query) {
  lockViewportPosition();
  submitBtn.disabled = true;
  submitBtn.textContent = "发送中";
  setDispatchStatus("正在理解你的请求...");
  addMessage("user", `<p>${esc(query)}</p>`, { scroll: false });
  const controlType = localControlTypeForQuery(query);
  const pendingId = addMessage(
    "assistant",
    renderLoading(controlType ? "正在执行。" : "正在识别并生成结果。"),
    { pending: true, scroll: false },
  );
  try {
    if (controlType) {
      setDispatchStatus("识别为播控指令，正在执行...");
      const data = localControlPayload(query, controlType);
      updateMessage(pendingId, assistantResponseHtml(data), { scroll: false });
      const root = conversationEl.querySelector(`[data-result-id="${data._resultId || ""}"]`);
      chatState.autoplayNextResult = false;
      if (controlType === "status") {
        if (root) hydrateDjTts(data, root);
      } else if (root) {
        await executeControl(data, currentPlaybackRoot() || root);
      }
      rememberTurn(query, data);
      return;
    }
    primeRadioAutoplay();
    const provider = providerSelect.value || "local";
    setDispatchStatus(`正在调用 ${provider === "local" ? "本地" : provider} 模型...`);
    if (providerStatus && !chatState.currentSong?.title) {
      providerStatus.textContent = "DJ Radio";
    }

    const data = await fetchAsyncRecommendationPayload(query, provider, pendingId);
    if (data) {
      await handleFinalRecommendation(query, data, pendingId);
    }
  } catch (error) {
    chatState.autoplayNextResult = false;
    setDispatchStatus("调度失败，请重试", { active: false });
    updateMessage(pendingId, `<p class="error-text">${esc(error.message)}</p>`, { scroll: false });
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "发送";
    if (!radioState.playing) setDispatchStatus("Ready", { active: false });
    unlockViewportPosition();
  }
}

async function readSseResponse(response, onEvent) {
  if (!response.body) throw new Error("当前浏览器不支持流式响应。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    chunks.forEach((chunk) => {
      const line = chunk.split("\n").find((item) => item.startsWith("data:"));
      if (!line) return;
      const raw = line.slice(5).trim();
      if (!raw) return;
      onEvent(JSON.parse(raw));
    });
  }
  if (buffer.trim()) {
    const line = buffer.split("\n").find((item) => item.startsWith("data:"));
    if (line) onEvent(JSON.parse(line.slice(5).trim()));
  }
}

async function fetchRecommendationPayload(query, provider, pendingId) {
  const payload = {
    query,
    n: 12,
    provider,
    context: contextPayload(query),
  };
  let finalData = null;
  let streamedSongs = 0;
  const response = await fetch(apiUrl("/recommend/stream"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("流式推荐接口不可用");
  let streamError = null;
  await readSseResponse(response, (event) => {
    if (event.type === "start") {
      setDispatchStatus("已进入流式推荐，正在选歌...");
      updateMessage(pendingId, renderLoading("正在选歌。"), { pending: true, scroll: false });
    } else if (event.type === "song" && event.song) {
      streamedSongs += 1;
      setDispatchStatus(`已选到 ${streamedSongs} 首，正在整理队列...`);
      if (streamedSongs === 1) {
        prefetchSingleSongStream(event.song, event.index || 0);
      }
      updateMessage(
        pendingId,
        renderLoading(`已选到 ${streamedSongs} 首，正在整理播放队列。`),
        { pending: true, scroll: false },
      );
    } else if (event.type === "final" && event.result) {
      finalData = event.result;
    } else if (event.type === "error") {
      streamError = event.error || "流式推荐失败";
    }
  });
  if (streamError) throw new Error(streamError);
  if (!finalData) throw new Error("流式推荐未返回完整结果");
  return finalData;
}

async function handleFinalRecommendation(query, data, pendingId) {
  setDispatchStatus("已拿到推荐，正在准备播放队列...");
  updateMessage(pendingId, assistantResponseHtml(data), { scroll: false });
  const root = conversationEl.querySelector(`[data-result-id="${data._resultId || ""}"]`);
  const hasGroups = Boolean((data.groups || []).length);
  if (root && await executeControl(data, root)) {
    chatState.autoplayNextResult = false;
    rememberTurn(query, data);
    return;
  }
  prefetchRadioStreams(data);
  if (root && chatState.autoplayNextResult && hasGroups) {
    chatState.autoplayNextResult = false;
    setDispatchStatus("正在解析音源并自动起播...");
    await startRadio(data, root, { forceStart: true });
  } else if (root && chatState.autoplayNextResult && data.dj && !hasGroups) {
    chatState.autoplayNextResult = false;
    hydrateDjTts(data, root);
  } else if (root && data.dj?.pending && !hasGroups) {
    beginAsyncDjIfNeeded(data, root);
  } else if (root && data.dj && !data.dj.pending && !hasGroups) {
    hydrateDjTts(data, root);
  }
  rememberTurn(query, data);
}

async function pollRecommendationJob(jobId, pendingId, startedAt, skeleton = null) {
  const maxWaitMs = 90000;
  let attempt = 0;
  while (Date.now() - startedAt < maxWaitMs) {
    await sleep(Math.min(1200 + attempt * 300, 3000));
    attempt += 1;
    const response = await fetch(apiUrl(`/recommend/status/${encodeURIComponent(jobId)}`));
    const data = await response.json();
    if (data.status === "done" && data.result) {
      setDispatchStatus("模型返回完成，正在整理结果...");
      return data.result;
    }
    if (data.status === "error") {
      throw new Error(data.error || "线上模型生成失败");
    }
    const note = `线上模型仍在生成推荐结果，已等待 ${Math.round((Date.now() - startedAt) / 1000)} 秒。`;
    setDispatchStatus(note);
    updateMessage(pendingId, skeleton ? renderAsyncSkeleton(skeleton, note) : renderLoading(note), { pending: true, scroll: false });
  }
  throw new Error("线上模型生成超时，请稍后重试。");
}

async function fetchAsyncRecommendationPayload(query, provider, pendingId) {
  const payload = {
    query,
    n: 12,
    provider,
    context: contextPayload(query),
  };
  try {
    const response = await fetch(apiUrl("/recommend/start"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    setDispatchStatus("已完成意图识别，正在分发任务...");
    if (!response.ok || data.error) {
      throw new Error(data.error || "异步推荐启动失败");
    }
    if (data.mode === "sync") {
      setDispatchStatus("命中同步调度，正在整理结果...");
      return data.result;
    }
    if (data.mode === "error") {
      throw new Error(data.error || "异步推荐启动失败");
    }
    if (data.mode === "async" && data.job_id) {
      if (data.skeleton) {
        setDispatchStatus("已识别意图，线上模型正在生成歌曲...");
        updateMessage(
          pendingId,
          renderAsyncSkeleton(data.skeleton, "已识别意图，线上模型正在生成歌曲列表。"),
          { pending: true, scroll: false },
        );
      }
      return await pollRecommendationJob(data.job_id, pendingId, Date.now(), data.skeleton || null);
    }
    throw new Error("异步推荐接口返回异常");
  } catch (error) {
    setDispatchStatus("异步调度不可用，切换备用链路...");
    updateMessage(pendingId, renderLoading("异步推荐不可用，切换普通推荐。"), { pending: true, scroll: false });
    try {
      return await fetchRecommendationPayload(query, provider, pendingId);
    } catch (streamError) {
      setDispatchStatus("流式链路不可用，切换普通推荐...");
      updateMessage(pendingId, renderLoading("流式返回不可用，切换普通推荐。"), { pending: true, scroll: false });
      const response = await fetch(apiUrl("/recommend"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok || data.error) {
        throw new Error(data.error || streamError.message || error.message || "推荐失败");
      }
      return data;
    }
  }
}

EXAMPLES.forEach((example) => {
  const button = document.createElement("button");
  button.className = "chip";
  button.type = "button";
  button.textContent = example;
  bindAutoplayPrimer(button);
  button.addEventListener("click", () => {
    primeRadioAutoplay();
    queryInput.value = example;
    chatState.autoplayNextResult = true;
    recommend(example);
  });
  chips.appendChild(button);
});

bindAutoplayPrimer(submitBtn);
document.querySelectorAll(".hero-control").forEach(bindAutoplayPrimer);

document.addEventListener("click", (event) => {
  if (
    event.target.closest("#submitBtn")
    || event.target.closest(".chip")
    || event.target.closest(".hero-control")
    || event.target.closest(".radio-start")
  ) {
    primeRadioAutoplay();
  }
}, { capture: true });

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  if (query) {
    primeRadioAutoplay();
    queryInput.value = "";
    chatState.autoplayNextResult = true;
    recommend(query);
  }
});

document.addEventListener("click", (event) => {
  const heroButton = event.target.closest(".hero-control");
  if (heroButton) {
    handleHeroControl(heroButton.dataset.control || "play").catch((error) => {
      updateRadioStatus(`操作失败：${error.message || "请稍后重试"}`, radioState.activeRoot || latestAssistantRoot());
    });
    return;
  }

  const radioButton = event.target.closest(".radio-start");
  if (radioButton) {
    const root = radioButton.closest(".assistant-result");
    const resultId = root?.dataset.resultId || "";
    const data = chatState.resultStore[resultId];
    if (data) startRadio(data, root);
    return;
  }

  const playerButton = event.target.closest(".load-player");
  if (playerButton) {
    const card = playerButton.closest(".song-row");
    const player = card?.querySelector(".inline-player");
    if (card?.dataset.title) {
      chatState.currentSong = { title: card.dataset.title, artist: card.dataset.artist || "" };
    }
    if (!player) return;
    document.querySelectorAll(".song-row.is-playing").forEach((row) => {
      if (row !== card) row.classList.remove("is-playing");
    });
    document.querySelectorAll(".inline-player").forEach((item) => {
      if (item !== player) {
        item.innerHTML = "";
        item.removeAttribute("data-autoload");
        item.removeAttribute("data-load-token");
      }
    });
    player.dataset.autoload = "true";
    player.dataset.loadToken = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    card.classList.add("is-playing");
    player.innerHTML = `<div class="player-loading">正在加载播放器</div>`;
    hydratePlayers();
    return;
  }
});

neteaseLoginBtn?.addEventListener("click", startNeteaseLogin);
voiceBtn?.addEventListener("click", toggleVoiceInput);
initVoiceInput();
refreshNeteaseLoginState();

fetch(apiUrl("/providers"))
  .then((response) => response.json())
  .then(renderProviders)
  .then(() => {
    renderConversation();
    scheduleOpeningDjAutoplay();
  })
  .catch(() => {
    providerStatus.textContent = "本地复刻";
    providerSelect.innerHTML = `<option value="local">本地复刻模型</option>`;
    renderConversation();
    scheduleOpeningDjAutoplay();
  });
