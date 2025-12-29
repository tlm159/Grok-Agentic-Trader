const $ = (id) => document.getElementById(id);
const state = {
  lastSeries: [],
  lastHistorySignature: null,
  lastHistory: null,
};

function formatMoney(value, currency) {
  if (value === null || value === undefined) {
    return "-";
  }
  const number = Number(value);
  if (Number.isNaN(number)) {
    return "-";
  }
  return `${number.toFixed(2)} ${currency || "USD"}`;
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const number = Number(value);
  if (Number.isNaN(number)) {
    return "-";
  }
  return number.toFixed(4);
}

function formatTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function updatePositions(positions) {
  const container = $("positions");
  container.innerHTML = "";

  const header = document.createElement("div");
  header.className = "table-row header";
  header.innerHTML = "<div>Symbol</div><div>Qty</div><div>Price</div><div>Value</div><div>PnL</div><div>SL/TP</div>";
  container.appendChild(header);

  const entries = Object.entries(positions || {});
  if (!entries.length) {
    const row = document.createElement("div");
    row.className = "table-row";
    row.innerHTML = "<div>-</div><div>-</div><div>-</div><div>-</div>";
    container.appendChild(row);
    return;
  }

  entries.forEach(([symbol, info]) => {
    const row = document.createElement("div");
    row.className = "table-row";
    const qty = info && typeof info === "object" ? info.qty : info;
    const price = info && typeof info === "object" ? info.price : null;
    const value = info && typeof info === "object" ? info.value : null;
    const sl = info && typeof info === "object" ? info.sl : null;
    const tp = info && typeof info === "object" ? info.tp : null;
    const pnl = info && typeof info === "object" ? info.pnl : null;
    const pnlPct = info && typeof info === "object" ? info.pnl_pct : null;
    const sltp = sl || tp ? `${formatValue(sl)} / ${formatValue(tp)}` : "-";
    const pnlLabel = pnl === null || pnl === undefined ? "-" : `${pnl >= 0 ? "+" : ""}${formatValue(pnl)}`;
    const pnlClass = pnl === null || pnl === undefined ? "" : pnl >= 0 ? "good" : "bad";
    const pnlDetail = pnlPct === null || pnlPct === undefined ? "" : ` (${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%)`;
    row.innerHTML = `
      <div>${symbol}</div>
      <div>${formatValue(qty)}</div>
      <div>${formatValue(price)}</div>
      <div>${formatValue(value)}</div>
      <div class="${pnlClass}">${pnlLabel}${pnlDetail}</div>
      <div>${sltp}</div>
    `;
    container.appendChild(row);
  });
}

function updateTrade(trade) {
  const container = $("trade");
  container.innerHTML = "";

  const header = document.createElement("div");
  header.className = "table-row header";
  header.innerHTML = "<div>Action</div><div>Symbol</div><div>Qty</div><div>Price</div><div>Notional</div>";
  container.appendChild(header);

  if (!trade) {
    const row = document.createElement("div");
    row.className = "table-row";
    row.innerHTML = "<div>-</div><div>-</div><div>-</div><div>-</div><div>-</div>";
    container.appendChild(row);
    return;
  }

  const row = document.createElement("div");
  row.className = "table-row";
  row.innerHTML = `
    <div>${trade.action || "-"}</div>
    <div>${trade.symbol || "-"}</div>
    <div>${formatValue(trade.qty)}</div>
    <div>${formatValue(trade.price)}</div>
    <div>${formatValue(trade.notional)}</div>
  `;
  container.appendChild(row);
}

function updateHistory(history) {
  const container = $("history");
  if ((!history || !history.length) && state.lastHistory && state.lastHistory.length) {
    return;
  }
  const signature = JSON.stringify(
    (history || []).map((item) => [
      item.timestamp,
      item.action,
      item.symbol,
      item.notional,
      item.reason,
      item.reflection,
      item.positions_summary,
    ])
  );
  if (signature === state.lastHistorySignature) {
    return;
  }
  state.lastHistorySignature = signature;
  state.lastHistory = history;

  container.innerHTML = "";
  const scrollTop = container.scrollTop;

  if (!history || !history.length) {
    const empty = document.createElement("div");
    empty.className = "history-item";
    empty.textContent = "No decisions yet.";
    container.appendChild(empty);
    container.scrollTop = scrollTop;
    return;
  }

  history.slice().reverse().forEach((item) => {
    const card = document.createElement("div");
    card.className = "history-item";
    const action = item.action || "-";
    const symbol = item.symbol || "-";
    const notional = item.notional ? formatValue(item.notional) : "-";
    const confidence = item.confidence ?? "-";
    const when = formatTime(item.timestamp);
    const reason = item.reason || "No reason.";
    const reflection = item.reflection || "";
    const positionsSummary = item.positions_summary || "";
    const evidenceList = Array.isArray(item.evidence) ? item.evidence : [];
    const evidenceText = evidenceList.length ? `Evidence: ${evidenceList.join(" • ")}` : "";
    const sltp = item.sl_price || item.tp_price ? `SL ${formatValue(item.sl_price)} / TP ${formatValue(item.tp_price)}` : "SL/TP: -";

    card.innerHTML = `
      <div class="history-meta">${when}</div>
      <h4>${action} ${symbol}</h4>
      <div class="history-meta">Notional: ${notional} | Confidence: ${confidence}</div>
      <div class="history-meta">${sltp}</div>
      <p class="history-body">${reason}</p>
      <p class="history-body">${reflection}</p>
      <p class="history-body">${positionsSummary}</p>
      <p class="history-body">${evidenceText}</p>
    `;
    container.appendChild(card);
  });

  container.scrollTop = scrollTop;
}

function drawChart(series, baseline) {
  const canvas = $("equityChart");
  const ctx = canvas.getContext("2d");
  const width = canvas.clientWidth;
  const height = canvas.height;
  if (!width || !height) {
    return;
  }
  canvas.width = width;
  ctx.clearRect(0, 0, width, height);

  const values = (series || []).map((point) => Number(point.equity)).filter((v) => !Number.isNaN(v));
  if (values.length < 2) {
    ctx.strokeStyle = "rgba(94, 228, 255, 0.2)";
    ctx.beginPath();
    ctx.moveTo(0, height / 2);
    ctx.lineTo(width, height / 2);
    ctx.stroke();
    if (baseline !== null && baseline !== undefined) {
      ctx.strokeStyle = "rgba(255, 230, 109, 0.5)";
      ctx.setLineDash([6, 6]);
      ctx.beginPath();
      ctx.moveTo(0, height / 2);
      ctx.lineTo(width, height / 2);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    return;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const padding = (max - min) * 0.1 || 1;
  const range = max - min + padding * 2;

  ctx.strokeStyle = "rgba(94, 228, 255, 0.85)";
  ctx.lineWidth = 2;
  ctx.beginPath();

  values.forEach((value, index) => {
    const x = (index / (values.length - 1)) * width;
    const y = height - ((value - min + padding) / range) * height;
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();

  if (baseline !== null && baseline !== undefined) {
    const y = height - ((baseline - min + padding) / range) * height;
    ctx.strokeStyle = "rgba(255, 230, 109, 0.6)";
    ctx.setLineDash([6, 6]);
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

function updateUI(data) {
  $("model").textContent = data.model || "-";
  $("timestamp").textContent = formatTime(data.timestamp);
  $("budget").textContent = formatMoney(data.starting_cash, data.currency);
  if (data.next_check_minutes !== null && data.next_check_minutes !== undefined) {
    $("nextCheck").textContent = `${Number(data.next_check_minutes).toFixed(2)} min`;
  } else {
    $("nextCheck").textContent = "-";
  }
  $("equity").textContent = formatMoney(data.equity, data.currency);
  $("cash").textContent = formatMoney(data.cash, data.currency);
  $("positionsValue").textContent = `Positions value: ${formatMoney(data.positions_value, data.currency)}`;
  const openPnlEl = $("openPnl");
  if (data.open_pnl !== null && data.open_pnl !== undefined) {
    const openPnl = Number(data.open_pnl);
    const prefix = openPnl >= 0 ? "+" : "";
    openPnlEl.textContent = `Open PnL: ${prefix}${openPnl.toFixed(2)} ${data.currency || "USD"}`;
    openPnlEl.classList.remove("good", "bad");
    openPnlEl.classList.add(openPnl >= 0 ? "good" : "bad");
  } else {
    openPnlEl.textContent = "Open PnL: -";
    openPnlEl.classList.remove("good", "bad");
  }
  if (data.leverage !== null && data.leverage !== undefined) {
    $("leverage").textContent = `Leverage: ${Number(data.leverage).toFixed(2)}x`;
  } else {
    $("leverage").textContent = "Leverage: -";
  }
  if (data.cash_ratio !== null && data.cash_ratio !== undefined) {
    $("cashRatio").textContent = `Cash ratio: ${(Number(data.cash_ratio) * 100).toFixed(1)}%`;
  } else {
    $("cashRatio").textContent = "Cash ratio: -";
  }

  const deltaEl = $("equityDelta");
  deltaEl.classList.remove("good", "bad");
  if (data.equity_delta === null || data.equity_delta === undefined) {
    deltaEl.textContent = "Delta: -";
  } else {
    const delta = Number(data.equity_delta);
    const prefix = delta >= 0 ? "+" : "";
    deltaEl.textContent = `Delta: ${prefix}${delta.toFixed(2)} ${data.currency || "USD"}`;
    deltaEl.classList.add(delta >= 0 ? "good" : "bad");
  }

  const pnlEl = $("pnl");
  pnlEl.classList.remove("good", "bad");
  if (data.starting_cash !== null && data.starting_cash !== undefined && data.equity !== null) {
    const pnl = Number(data.equity) - Number(data.starting_cash);
    const prefix = pnl >= 0 ? "+" : "";
    pnlEl.textContent = `PnL: ${prefix}${pnl.toFixed(2)} ${data.currency || "USD"}`;
    pnlEl.classList.add(pnl >= 0 ? "good" : "bad");
  } else {
    pnlEl.textContent = "PnL: -";
  }

  const decision = data.decision || {};
  $("action").textContent = decision.action || "-";
  $("symbol").textContent = decision.symbol || "-";
  $("notional").textContent = decision.notional ? formatValue(decision.notional) : "-";
  $("confidence").textContent = decision.confidence ?? "-";
  $("reflection").textContent = decision.reflection || "No reflection yet.";

  updatePositions(data.positions || {});
  updateTrade(data.trade || null);
  updateHistory(data.decision_history || []);
  drawChart(data.equity_series || [], data.starting_cash);

  const promptEl = $("lastPrompt");
  const rawEl = $("lastRaw");
  if (promptEl) {
    if (data.prompt) {
      promptEl.textContent = JSON.stringify(data.prompt, null, 2);
    } else {
      promptEl.textContent = "-";
    }
  }
  if (rawEl) {
    rawEl.textContent = data.raw ? data.raw : "-";
  }
}

async function refresh() {
  const status = $("status");
  try {
    const response = await fetch("/data/dashboard.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    updateUI(data);
    status.textContent = data.error ? `Error: ${data.error}` : "Live";
  } catch (error) {
    status.textContent = "Waiting for data";
  }
}

refresh();
setInterval(refresh, 3000);
