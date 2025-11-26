'use strict';

// Markdown → HTMLに変換（必要箇所のみで使用）
function renderMarkdown(md) {
  if (!md) return "";
  const html = marked.parse(md);
  return `<div class="markdown-body">${html}</div>`;
}

// 初期化（Ver.106: スクショ機能は未対応のためUIを無効化）
document.addEventListener('DOMContentLoaded', () => {
  // 画像アップロードUIは現在無効化
  const fileInput = document.getElementById('fileInput');
  const sendBtn = document.getElementById('sendBtn');
  const preview = document.getElementById('preview');
  if (fileInput) fileInput.disabled = true;
  if (sendBtn) {
    sendBtn.disabled = true;
    sendBtn.title = 'Ver.106ではスクショ解析は無効です';
  }
  if (preview) preview.innerHTML = '<p style="color:#888;">※ 現在、この環境ではスクショ解析は未対応です</p>';

  // WebSocket接続（ライブ更新）
  try {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${location.host}/ws/live`);
    ws.onopen = () => {
      const el = document.getElementById('result');
      if (el) el.insertAdjacentHTML('afterbegin', '<div style="color:#b8ff5c;">🔌 WebSocket 接続: LIVE更新を開始</div>');
    };
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        const r = data.result || {};
        const fd = (r.final_direction || r['最終方向'] || '').toString().toUpperCase();
        const color = fd === 'BUY' ? '#b8ff5c' : fd === 'SELL' ? '#ef4444' : '#888';
        const msg = `
          <div style="border:1px dashed #444;padding:8px;margin:8px 0;border-radius:6px;background:#0a0a0a;">
            <strong style="color:#4cc9f0;">${r.symbol || data.symbol || 'N/A'}</strong>
            <span style="background:${color};color:#000;padding:2px 8px;border-radius:6px;margin-left:8px;">${fd || 'N/A'}</span>
            <span style="color:#aaa;margin-left:8px;">conf:${r.final_confidence ?? r.confidence ?? r['信頼度'] ?? '-'} / win:${r.win_rate !== undefined ? Math.round(r.win_rate*100) + '%' : '-'}</span>
          </div>`;
        const el = document.getElementById('result');
        if (el) el.insertAdjacentHTML('afterbegin', msg);
      } catch { /* ignore */ }
    };
  } catch { /* ignore */ }
});

// 画像プレビュー（無効化済み）
document.getElementById('fileInput').addEventListener('change', () => {});
document.getElementById('sendBtn').addEventListener('click', () => {
  alert('現在この環境ではスクショ解析は無効です');
});

// AI自動解析ボタン（Ver.106仕様）
document.getElementById('aiAutoBtn').addEventListener('click', async () => {
  const btn = document.getElementById('aiAutoBtn');
  btn.disabled = true;
  btn.textContent = '解析中...';

  try {
    const res = await fetch('/analyze/swing_multi', { method: 'POST' });
    const json = await res.json();

    let output = `<h3>🤖 AI自動解析（${json.count || 0}銘柄）</h3>`;
    if (Array.isArray(json.results)) {
      json.results.forEach(r => {
        const fd = (r.final_direction || r['最終方向'] || '').toString().toUpperCase();
        const color = fd === 'BUY' ? '#b8ff5c' : fd === 'SELL' ? '#ef4444' : '#888';
        const win = r.win_rate !== undefined ? Math.round(r.win_rate * 100) + '%' : '-';
        const sent = r.sentiment?.summary || '';

        output += `
          <div style="border:1px solid #444;padding:16px;margin:12px 0;border-radius:8px;background:#0a0a0a;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
              <h4 style="color:#4cc9f0;margin:0;">${r.symbol}</h4>
              <span style="background:${color};color:#000;padding:4px 10px;border-radius:6px;font-weight:bold;">${fd || 'N/A'}</span>
            </div>
            <div style="display:grid;grid-template-columns:repeat(2, minmax(0,1fr));gap:8px;font-size:14px;">
              <p><strong>confidence:</strong> ${r.confidence ?? r['信頼度'] ?? '-'} → <strong>final:</strong> ${r.final_confidence ?? '-'}</p>
              <p><strong>win rate:</strong> ${win}</p>
              <p><strong>ATR:</strong> ${r.atr ?? '-'}</p>
              <p><strong>comment:</strong> ${r.comment || r['コメント'] || ''}</p>
            </div>
            ${sent ? `<details style="margin-top:8px;"><summary style="cursor:pointer;color:#b8ff5c;">📰 Sentiment</summary><div style="margin-top:6px;color:#ccc;">${sent}</div></details>` : ''}
            <details style="margin-top:8px;">
              <summary style="cursor:pointer;color:#999;">📋 Raw</summary>
              <pre>${JSON.stringify(r, null, 2)}</pre>
            </details>
          </div>`;
      });
    }

    output += `<details style="margin-top:12px;"><summary style="cursor:pointer;color:#999;">📦 Full JSON</summary><pre>${JSON.stringify(json, null, 2)}</pre></details>`;
    document.getElementById('result').innerHTML = output;
  } catch (e) {
    document.getElementById('result').textContent = 'エラー: ' + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'AI自動解析を実行';
  }
});
