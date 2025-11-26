// ==== タブ切替 ====
const tabs = document.querySelectorAll(".tabs button");
const panels = document.querySelectorAll(".panel");
tabs.forEach((tab, i) => {
  tab.addEventListener("click", () => {
    tabs.forEach(t => t.classList.remove("active"));
    panels.forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    panels[i].classList.add("active");
  });
});

// ==== 手動IFD ====
document.getElementById("imageForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const formData = new FormData(e.target);
  const res = await fetch("/analyze/image", { method: "POST", body: formData });
  const data = await res.json();
  let output = '';
  if (data.table_markdown) {
    output += '📊 トレードテーブル:\n\n' + data.table_markdown + '\n\n';
  }
  output += '📋 詳細JSON:\n' + JSON.stringify(data, null, 2);
  document.getElementById("manualResult").textContent = output;
});

// ==== AIスイング ====
document.getElementById("runAI").addEventListener("click", async () => {
  document.getElementById("aiResult").textContent = "AI解析中...";
  const res = await fetch("/analyze/swing_multi", { method: "POST" });
  const data = await res.json();
  let output = '';
  if (data.markdown) {
    output += '📊 トレードテーブル (DAY6H形式):\n\n' + data.markdown + '\n\n';
  }
  output += '📋 詳細JSON:\n' + JSON.stringify(data, null, 2);
  document.getElementById("aiResult").textContent = output;
  updateCharts(data);
});

// ==== WebSocketでリアルタイム結果更新 ====
(function initWS() {
  try {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${location.host}/ws/live`);
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      const pre = document.getElementById("aiResult");
      pre.textContent = "🔔リアルタイム更新:\n\n" + JSON.stringify(msg, null, 2);
      updateCharts(msg);
    };
  } catch (e) {
    console.warn('WS init failed', e);
  }
})();

// ==== グラフ初期化 ====
let sentimentChart, confidenceChart;

function initCharts() {
  const ctx1 = document.getElementById("sentimentChart").getContext("2d");
  const ctx2 = document.getElementById("confidenceChart").getContext("2d");

  sentimentChart = new Chart(ctx1, {
    type: "doughnut",
    data: {
      labels: ["Positive", "Neutral", "Negative"],
      datasets: [{
        label: "Sentiment",
        data: [0, 0, 0],
        backgroundColor: ["#22c55e", "#94a3b8", "#ef4444"]
      }]
    },
    options: { plugins: { legend: { labels: { color: "#f1f5f9" } } } }
  });

  confidenceChart = new Chart(ctx2, {
    type: "bar",
    data: {
      labels: ["JP225", "NAS100", "GER40", "XAUUSD"],
      datasets: [{
        label: "Confidence",
        data: [0, 0, 0, 0],
        backgroundColor: "#38bdf8"
      }]
    },
    options: {
      scales: {
        y: { min: 0, max: 100, ticks: { color: "#f1f5f9" } },
        x: { ticks: { color: "#f1f5f9" } }
      },
      plugins: { legend: { labels: { color: "#f1f5f9" } } }
    }
  });
}

// ==== グラフ更新 ====
function updateCharts(data) {
  if (!data || !data.results) return;

  // 感情スコア（POST応答にはバッチのsentimentが無いので各要素から平均をとる）
  let pos = 0, neu = 0, neg = 0, count = 0;
  data.results.forEach(r => {
    if (r.sentiment) {
      pos += r.sentiment.positive || 0;
      neu += r.sentiment.neutral || 0;
      neg += r.sentiment.negative || 0;
      count += 1;
    }
  });
  if (count > 0) {
    sentimentChart.data.datasets[0].data = [pos / count, neu / count, neg / count];
    sentimentChart.update();
  }

  // 信頼度バー（英語/日本語キー対応）
  const labels = [];
  const confs = [];
  data.results.forEach(r => {
    labels.push(r.symbol || "?");
    const conf = r.confidence ?? r.final_confidence ?? r["信頼度"] ?? 0;
    confs.push(Number(conf) || 0);
  });
  confidenceChart.data.labels = labels;
  confidenceChart.data.datasets[0].data = confs;
  confidenceChart.update();
}

// 初期化
initCharts();
