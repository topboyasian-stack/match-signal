const DATA_BASE = "https://raw.githubusercontent.com/topboyasian-stack/match-signal/main/data/";
const SITE_URL = "https://topboyasian-stack.github.io/match-signal/";

async function telegram(env, method, body) {
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.description || `Telegram ${method} failed`);
  return data.result;
}

async function loadJson(name) {
  const response = await fetch(`${DATA_BASE}${name}`, { cf: { cacheTtl: 60 } });
  if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
  return response.json();
}

function pct(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function predictionLine(p) {
  const pick = p.pick === "p1" ? p.player_1 : p.pick === "p2" ? p.player_2 : p.pick;
  const confidence = pct(p.confidence);
  if (p.sport === "tennis") {
    return `🎾 <b>${escapeHtml(p.player_1)} vs ${escapeHtml(p.player_2)}</b>\nPick: <b>${escapeHtml(pick)}</b> — ${confidence}`;
  }
  const probs = p.probabilities || {};
  return `⚽ <b>${escapeHtml(p.home_team || p.team_1 || "Home")} vs ${escapeHtml(p.away_team || p.team_2 || "Away")}</b>\nPick: <b>${escapeHtml(pick)}</b> — ${confidence} · 1X2 ${pct(probs.home)} / ${pct(probs.draw)} / ${pct(probs.away)}`;
}

async function buildTodayMessage() {
  const [predictions, basketball] = await Promise.all([
    loadJson("predictions.json").catch(() => []),
    loadJson("basketball_predictions.json").catch(() => []),
  ]);
  const all = [...(Array.isArray(predictions) ? predictions : []), ...(Array.isArray(basketball) ? basketball : [])];
  const now = Date.now();
  const upcoming = all.filter((p) => {
    const t = Date.parse(p.start_time || p.commence_time || "");
    return Number.isFinite(t) && t >= now - 6 * 3600_000 && t <= now + 36 * 3600_000;
  });
  upcoming.sort((a, b) => Date.parse(a.start_time || a.commence_time) - Date.parse(b.start_time || b.commence_time));
  const qualified = upcoming.filter((p) => Number(p.confidence || 0) >= 0.55 || p.qualified_signal === true);
  const selected = (qualified.length ? qualified : upcoming).slice(0, 10);
  if (!selected.length) return `📡 <b>Match Signal</b>\n\nNo upcoming model signals found right now.\n\n<a href="${SITE_URL}">Open dashboard</a>`;
  return `📡 <b>MATCH SIGNAL — TODAY</b>\n\n${selected.map(predictionLine).join("\n\n")}\n\n<a href="${SITE_URL}">Open full dashboard →</a>`;
}

async function handleCommand(chatId, text, env) {
  const command = text.trim().split(/\s+/)[0].toLowerCase().split("@")[0];
  if (command === "/start" || command === "/help") {
    return telegram(env, "sendMessage", {
      chat_id: chatId,
      text: `📡 <b>Match Signal AI</b>\n\nYour automated football, tennis and basketball prediction assistant.\n\n/today — current signals\n/football — football signals\n/tennis — tennis signals\n/basketball — basketball signals\n/performance — model performance\n\n<a href="${SITE_URL}">Open Match Signal</a>`,
      parse_mode: "HTML",
      disable_web_page_preview: true,
    });
  }
  if (command === "/today") return telegram(env, "sendMessage", { chat_id: chatId, text: await buildTodayMessage(), parse_mode: "HTML", disable_web_page_preview: true });
  if (["/football", "/tennis", "/basketball"].includes(command)) {
    const file = command === "/basketball" ? "basketball_predictions.json" : "predictions.json";
    const sport = command.slice(1);
    const data = await loadJson(file).catch(() => []);
    const rows = (Array.isArray(data) ? data : []).filter((p) => p.sport === sport || (sport === "basketball" && p.sport === "basketball"));
    const qualified = rows.filter((p) => Number(p.confidence || 0) >= 0.55 || p.qualified_signal === true).slice(0, 10);
    const body = qualified.length ? qualified.map(predictionLine).join("\n\n") : `No qualified ${sport} signals right now.`;
    return telegram(env, "sendMessage", { chat_id: chatId, text: `📡 <b>${sport.toUpperCase()}</b>\n\n${body}\n\n<a href="${SITE_URL}">Open dashboard →</a>`, parse_mode: "HTML", disable_web_page_preview: true });
  }
  if (command === "/performance") {
    const [football, basketball] = await Promise.all([
      loadJson("accuracy.json").catch(() => ({})),
      loadJson("basketball_accuracy.json").catch(() => ({})),
    ]);
    const accuracy = football.accuracy ?? football.overall_accuracy ?? football.hit_rate ?? null;
    const bAccuracy = basketball.accuracy ?? basketball.overall_accuracy ?? basketball.hit_rate ?? null;
    return telegram(env, "sendMessage", {
      chat_id: chatId,
      text: `📈 <b>MATCH SIGNAL PERFORMANCE</b>\n\nFootball/Tennis: <b>${accuracy == null ? "Pending settlement" : pct(accuracy)}</b>\nBasketball: <b>${bAccuracy == null ? "Pending settlement" : pct(bAccuracy)}</b>\n\n<a href="${SITE_URL}performance.html">View full performance →</a>`,
      parse_mode: "HTML",
      disable_web_page_preview: true,
    });
  }
  return telegram(env, "sendMessage", { chat_id: chatId, text: "Use /today, /football, /tennis, /basketball or /performance." });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET") return new Response("Match Signal Telegram Worker is online.", { status: 200 });
    if (request.method !== "POST" || url.pathname !== "/telegram/webhook") return new Response("Not found", { status: 404 });
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TELEGRAM_WEBHOOK_SECRET) return new Response("Unauthorized", { status: 401 });
    try {
      const update = await request.json();
      const message = update.message;
      if (message?.chat?.id && message.text?.startsWith("/")) await handleCommand(message.chat.id, message.text, env);
      if (update.channel_post?.chat?.id) console.log(`Channel post received from ${update.channel_post.chat.id}`);
      return new Response("ok");
    } catch (error) {
      console.error(error);
      return new Response("ok");
    }
  },
};
