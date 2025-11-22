#!/usr/bin/env python3
"""
weekly_events_update.py
- Google Drive 上の events.csv を取得し、OpenAI (GPT) でニュースのセンチメントを評価して
  events_scored.csv を Drive に再アップロードするスクリプト。

Usage:
  # 環境変数を設定して（推奨）
  export OPENAI_API_KEY=...
  export GOOGLE_SERVICE_ACCOUNT=/path/to/service-account.json    # optional (非対話)
  python3 weekly_events_update.py --dry-run

Notes:
 - Service account JSON を指定すれば自動化に向きます。指定がなければローカルの OAuth (pydrive) を使う対話フローになります。
 - 出力は JSON を想定してパースします。モデルの返答を厳密に検証し、不正な応答は安全に扱います。
"""
import os
import io
import time
import json
import argparse
import logging
from typing import Optional
from datetime import datetime
from pathlib import Path

import pandas as pd
import keyring
from market_data_fetch import fetch_market_data
import numpy as np
import math

# OpenAI: official client
from openai import OpenAI

# Google Drive: try service account via googleapiclient if available, else fall back to PyDrive
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    GOOGLE_API_AVAILABLE = True
except Exception:
    GOOGLE_API_AVAILABLE = False

try:
    from pydrive.auth import GoogleAuth
    from pydrive.drive import GoogleDrive
    PYDRIVE_AVAILABLE = True
except Exception:
    PYDRIVE_AVAILABLE = False

logger = logging.getLogger('weekly_events')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


DEFAULT_MODEL = os.environ.get('GPT_MODEL', 'gpt-4o-mini')

# Safety / risk limits (can be tuned)
MAX_LOT_MAP = {
    "JP225": 20.0,
    "SP500": 20.0,
    "NASDAQ_MINI": 20.0,
    "GOLD_SPOT": 10.0,
    "DE40": 20.0,
    "AAPL": 10.0,
    "MSFT": 10.0,
}
# Maximum percent of account that can be risked per trade (hard cap)
MAX_RISK_PCT = 5.0  # percent
# Maximum TP/SL width as fraction of entry price (e.g. 1.0 = 100%)
MAX_TP_SL_PCT = 1.0
# Maximum total risk exposure per run (daily exposure cap), JPY
MAX_DAILY_EXPOSURE_JPY = 200_000.0
# Absolute maximum loss allowed per trade (JPY)
MAX_ABSOLUTE_LOSS_JPY = 100_000.0


def detect_local_google_drive() -> Optional[str]:
    """Try to detect a locally-synced Google Drive folder.

    Returns the path to the first matching base folder (not the CFD3Pro subfolder).
    """
    # allow environment override
    env_drive = os.environ.get('LOCAL_GOOGLE_DRIVE')
    if env_drive and os.path.isdir(env_drive):
        logger.info('Detected LOCAL_GOOGLE_DRIVE environment variable: %s', env_drive)
        return env_drive

    candidates = [
        os.path.expanduser('~/Google ドライブ'),
        os.path.expanduser('~/Google Drive'),
        os.path.expanduser('~/My Drive'),
        '/Volumes/GoogleDrive',
        '/Volumes/Google Drive',
    ]

    for c in candidates:
        if os.path.isdir(c):
            logger.info('Detected local Google Drive folder: %s', c)
            return c

    logger.info('No local Google Drive folder detected among candidates: %s', candidates)
    return None


def load_openai_client():
    # try keyring first, then environment variable
    api_key = keyring.get_password('openai', 'default') or os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OpenAI API key not found. Set in Keychain (keyring) or OPENAI_API_KEY env var.')
    return OpenAI(api_key=api_key)


class DriveClient:
    def __init__(self, service_account_file: Optional[str] = None):
        self.sa = service_account_file
        # If a local Google Drive sync folder exists, prefer writing there and
        # avoid any interactive OAuth (pydrive) or service-account flows.
        local_drive_detected = detect_local_google_drive()
        if local_drive_detected:
            logger.info('Local Google Drive detected; using local save mode: %s', local_drive_detected)
            self.mode = 'local'
            # prefer a CFD3Pro subfolder inside detected path
            self.local_base = os.path.join(local_drive_detected, 'CFD3Pro')
            os.makedirs(self.local_base, exist_ok=True)
            return
        if self.sa and GOOGLE_API_AVAILABLE:
            logger.info('Using Google service account auth')
            scopes = ['https://www.googleapis.com/auth/drive']
            creds = service_account.Credentials.from_service_account_file(self.sa, scopes=scopes)
            self._svc = build('drive', 'v3', credentials=creds)
            self.mode = 'googleapiclient'
        elif PYDRIVE_AVAILABLE:
            logger.info('Using PyDrive local auth (interactive)')
            gauth = GoogleAuth()
            # LocalWebserverAuth will open a browser. For non-interactive, set up service account.
            gauth.LocalWebserverAuth()
            self._drv = GoogleDrive(gauth)
            self.mode = 'pydrive'
        else:
            # Do not fail hard here; allow caller to still write locally via other code paths.
            logger.warning('No Google Drive client available. PyDrive/google-api not configured. DriveClient will be unavailable for remote uploads.')
            self.mode = 'unavailable'

    def find_file_by_name(self, name: str):
        if self.mode == 'googleapiclient':
            q = f"name = '{name}' and trashed = false"
            res = self._svc.files().list(q=q, pageSize=10, fields='files(id, name)').execute()
            files = res.get('files', [])
            return files[0] if files else None
        elif self.mode == 'pydrive':
            files = self._drv.ListFile({'q': f"title='{name}' and trashed=false"}).GetList()
            return files[0] if files else None
        elif self.mode == 'local':
            # search in local_base for the given filename
            candidate = os.path.join(self.local_base, name)
            if os.path.isfile(candidate):
                return {'local_path': candidate, 'name': name}
            return None
        else:
            return None

    def download_file_content(self, file_meta):
        if self.mode == 'googleapiclient':
            fid = file_meta['id']
            request = self._svc.files().get_media(fileId=fid)
            fh = io.BytesIO()
            downloader = None
            from googleapiclient.http import MediaIoBaseDownload
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh.read().decode('utf-8')
        else:
            if self.mode == 'pydrive':
                return file_meta.GetContentString()
            if self.mode == 'local':
                path = file_meta.get('local_path')
                with open(path, 'r', encoding='utf-8') as fh:
                    return fh.read()
            raise RuntimeError('Drive client not available for download')

    def upload_csv(self, df: pd.DataFrame, title: str, existing_file=None):
        csv_str = df.to_csv(index=False)
        if self.mode == 'googleapiclient':
            media = MediaIoBaseUpload(io.BytesIO(csv_str.encode('utf-8')), mimetype='text/csv')
            try:
                if existing_file:
                    fid = existing_file['id']
                    self._svc.files().update(fileId=fid, media_body=media).execute()
                else:
                    meta = {'name': title}
                    self._svc.files().create(body=meta, media_body=media, fields='id').execute()
            except Exception as e:
                # If service account cannot create files (storage quota) or other Drive errors,
                # fall back to writing CSV locally so user can manually upload.
                try:
                    from googleapiclient.errors import HttpError
                except Exception:
                    HttpError = None
                msg = str(e)
                logger.warning('Drive upload failed: %s', msg)
                if HttpError and isinstance(e, HttpError) and 'storageQuotaExceeded' in msg:
                    logger.warning('Service account cannot create files (storage quota). Falling back to local save.')
                # ensure output dir
                # Prefer writing directly into a locally-synced Google Drive folder if available.
                possible_drive_paths = []
                # allow user override via env
                env_drive = os.environ.get('LOCAL_GOOGLE_DRIVE')
                if env_drive:
                    possible_drive_paths.append(env_drive)
                # common macOS user-visible paths (Japanese and English)
                possible_drive_paths.extend([
                    os.path.expanduser('~/Google ドライブ'),
                    os.path.expanduser('~/Google Drive'),
                    os.path.expanduser('~/My Drive'),
                    '/Volumes/GoogleDrive',
                ])

                written = None
                for base in possible_drive_paths:
                    try_path = os.path.join(base, 'CFD3Pro')
                    if os.path.isdir(try_path):
                        os.makedirs(try_path, exist_ok=True)
                        local_path = os.path.join(try_path, title)
                        with open(local_path, 'w', encoding='utf-8-sig') as fh:
                            fh.write(csv_str)
                        logger.info('Wrote CSV directly to local Google Drive folder: %s', local_path)
                        written = local_path
                        break

                if not written:
                    # ensure project output dir
                    out_dir = os.path.join(os.path.expanduser('~'), 'Desktop', 'CFD3_AutoSystem', 'output')
                    os.makedirs(out_dir, exist_ok=True)
                    local_path = os.path.join(out_dir, title)
                    with open(local_path, 'w', encoding='utf-8-sig') as fh:
                        fh.write(csv_str)
                    logger.info('Wrote CSV locally to %s. Please upload to Drive manually or adjust service account.', local_path)
                    written = local_path

                return {'local_path': written}
        else:
            if self.mode == 'pydrive':
                if existing_file:
                    f = existing_file
                    f.SetContentString(csv_str)
                    f.Upload()
                else:
                    newf = self._drv.CreateFile({'title': title})
                    newf.SetContentString(csv_str)
                    newf.Upload()
            elif self.mode == 'local':
                out_path = os.path.join(self.local_base, title)
                with open(out_path, 'w', encoding='utf-8-sig') as fh:
                    fh.write(csv_str)
                logger.info('Wrote CSV locally to %s (local drive mode)', out_path)
                return {'local_path': out_path}
            else:
                raise RuntimeError('No available Drive client to upload CSV')


def safe_call_gpt(client: OpenAI, model: str, prompt: str, retries=3, backoff=2):
    last_exc = None
    for i in range(1, retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            return resp
        except Exception as e:
            logger.warning('OpenAI call failed (%d/%d): %s', i, retries, e)
            last_exc = e
            time.sleep(backoff * i)
    raise last_exc


def build_prompt_for_row(row: dict) -> str:
    # Build a clear instruction requesting JSON output
    # Accept multiple possible columns (some CSVs use event_type for the text)
    text = (
        row.get('text')
        or row.get('headline')
        or row.get('description')
        or row.get('event_type')
        or ''
    )
    prompt = (
        "あなたは金融市場のアナリストです。次のニュース/イベントのテキストを読み、"
        "市場センチメントを 'Bullish'、'Bearish'、'Neutral' のいずれかで判定し、"
        "その理由を短く（最大3点）書いてください。出力は必ず厳密な JSON のみを返してください。"
        "  絶対に他の説明や注釈、コードブロックを追加しないでください。"
        "\n出力 JSON スキーマ（例）:\n{\n  \"sentiment\": \"Bullish|Bearish|Neutral\",\n  \"confidence\": 0.00,\n  \"reasons\": [\"理由1\", \"理由2\"]\n}\n"
        "例: ニュースが明確に買いの場合 -> {\"sentiment\":\"Bullish\",\"confidence\":0.92,\"reasons\":[\"好決算\",\"楽観的ガイダンス\"]}"
        "\n厳守: confidence は 0.0 から 1.0 の数値、小数点で出力してください。reasons は最大3個の短い文字列にしてください。"
        f"\nニュース/イベント:\n{text}"
    )
    return prompt


def parse_sentiment_response(resp) -> dict:
    # Try to extract JSON from model response
    try:
        content = resp.choices[0].message.content
    except Exception:
        content = str(resp)
    # Find first JSON-looking substring
    start = content.find('{')
    end = content.rfind('}')
    if start >= 0 and end >= 0 and end > start:
        js = content[start:end+1]
        try:
            data = json.loads(js)
            return data
        except Exception:
            logger.warning('モデル応答の JSON パース失敗 (json.loads): %s', js[:200])
            # try literal_eval as fallback (handles single quotes)
            try:
                import ast
                data = ast.literal_eval(js)
                return data
            except Exception:
                logger.warning('モデル応答の JSON パース失敗 (ast.literal_eval)')
    # Fallback: do a simple text map
    c = content.lower()
    # try to extract sentiment words and a float confidence via regex
    try:
        import re
        m_conf = re.search(r"\b([0]?\.?\d(?:\.\d+)?)\b", content)
        conf = float(m_conf.group(1)) if m_conf else 0.5
    except Exception:
        conf = 0.5
    if 'bull' in c or 'buy' in c:
        return {'sentiment': 'Bullish', 'confidence': min(max(conf, 0.0), 1.0), 'reasons': [content[:200]]}
    if 'bear' in c or 'sell' in c:
        return {'sentiment': 'Bearish', 'confidence': min(max(conf, 0.0), 1.0), 'reasons': [content[:200]]}
    return {'sentiment': 'Neutral', 'confidence': min(max(conf, 0.0), 1.0), 'reasons': [content[:200]]}


def sentiment_to_numeric(s: str) -> int:
    return 1 if s.lower() == 'bullish' else (-1 if s.lower() == 'bearish' else 0)


def main(dry_run=False, target_file='events.csv', model=DEFAULT_MODEL, service_account_file=None, market_days: int = 30, local_file: Optional[str] = None, out_path: Optional[str] = None, tolerance: Optional[str] = None, output_mode: str = 'internal', lenient: bool = False, atr_period: int = 14, sma_period: int = 20, momentum_window: int = 5, rsi_buy: float = 45.0, rsi_sell: float = 55.0, relax_score_threshold: float = 0.9):
    # Mark run start so that launchd logs show clear run boundaries
    ts = datetime.now().isoformat()
    print(f'RUN START {ts}', flush=True)
    client = load_openai_client()

    # If a local file is provided, read it directly (useful for testing).
    if local_file:
        local_file = os.path.expanduser(local_file)
        if not os.path.isfile(local_file):
            logger.error('Local file not found: %s', local_file)
            return
        logger.info('Using local events file: %s', local_file)
        df = pd.read_csv(local_file)
    else:
        drive = DriveClient(service_account_file=service_account_file)

        f = drive.find_file_by_name(target_file)
        if not f:
            logger.error('%s が Drive に見つかりません。', target_file)
            return

        csv_text = drive.download_file_content(f)
        df = pd.read_csv(io.StringIO(csv_text))

    # --- Fetch and merge market data (nearest-backward join) ---
    try:
        # normalize event time column to 'date' (parse as UTC then make naive)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], utc=True)
        elif 'datetime' in df.columns:
            df['date'] = pd.to_datetime(df['datetime'], utc=True)
        elif 'time' in df.columns:
            df['date'] = pd.to_datetime(df['time'], utc=True)
        else:
            logger.warning('No date/datetime/time column found in events CSV — creating date=now')
            df['date'] = pd.to_datetime('now', utc=True)
        # convert tz-aware to naive (both sides should have same dtype)
        try:
            df['date'] = df['date'].dt.tz_convert(None)
        except Exception:
            # if already naive or conversion fails, leave as-is
            pass

        market_df = fetch_market_data(days=market_days, use_cache=True)
        # compute a crude volatility estimate (rolling std of pct_change * price) for JP225
        try:
            if 'JP225' in market_df.columns:
                vol = market_df['JP225'].pct_change().rolling(14, min_periods=3).std()
                market_df['volatility'] = (vol * market_df['JP225']).abs()
            else:
                market_df['volatility'] = 0.0
        except Exception:
            market_df['volatility'] = 0.0
        # drop tzinfo to make datetimes naive for merge_asof
        market_df["date"] = pd.to_datetime(market_df["date"])
        # handle both tz-aware and tz-naive series robustly
        try:
            market_df["date"] = market_df["date"].dt.tz_convert(None)
        except Exception:
            try:
                market_df["date"] = market_df["date"].dt.tz_localize(None)
            except Exception:
                # leave as-is if conversion/localize fails
                pass
        market_df = market_df.sort_values('date')
        # apply optional tolerance for merge_asof (e.g. '1h', '30min')
        if tolerance:
            try:
                tol = pd.to_timedelta(tolerance)
            except Exception:
                logger.warning('Invalid tolerance value %s; ignoring', tolerance)
                tol = None
        else:
            tol = None
        if tol is not None:
            df = pd.merge_asof(df.sort_values('date'), market_df.sort_values('date'), on='date', direction='backward', tolerance=tol)
        else:
            df = pd.merge_asof(df.sort_values('date'), market_df.sort_values('date'), on='date', direction='backward')
        logger.info('Merged market data into events; added columns: %s', ','.join([c for c in market_df.columns if c != 'date']))
        # Debug: optionally print shapes/columns to help trace empty-output issues
        if os.environ.get('DEBUG_VERBOSE') == '1':
            try:
                logger.debug('DEBUG: merged df.shape=%s; market_df.shape=%s', getattr(df, 'shape', None), getattr(market_df, 'shape', None))
                logger.debug('DEBUG: merged df.columns=%s', list(df.columns))
            except Exception:
                pass
    except Exception as e:
        logger.warning('Failed to fetch/merge market data: %s', e)

    # === Exclude instruments that should not be traded (configurable via env) ===
    # Example: MONITOR_EXCLUDE_SYMBOLS=USDJPY,TOPIX
    exclude_symbols_env = os.environ.get('MONITOR_EXCLUDE_SYMBOLS') or os.environ.get('EXCLUDE_SYMBOLS')
    if exclude_symbols_env:
        try:
            exclude_set = set([s.strip().upper() for s in exclude_symbols_env.split(',') if s.strip()])
        except Exception:
            exclude_set = set()
    else:
        # Per user request, by default exclude USDJPY from trade proposals
        exclude_set = {'USDJPY'}

    # keep a copy of original df so we can recover if excludes remove all rows
    df_original_before_exclude = df.copy()

    if exclude_set:
        # Build a boolean mask for rows to drop
        drop_mask = pd.Series(False, index=df.index)
        # If market column with symbol exists, drop rows where it's non-null
        for sym in list(exclude_set):
            if sym in df.columns:
                try:
                    drop_mask = drop_mask | (~df[sym].isna())
                except Exception:
                    pass
        # If instrument or entry_source columns exist, drop matching rows
        for colname in ['instrument', 'entry_source', 'instrument_name']:
            if colname in df.columns:
                try:
                    drop_mask = drop_mask | (df[colname].astype(str).str.upper().isin(exclude_set))
                except Exception:
                    pass
        # Log and filter
        n_before = len(df)
        df = df.loc[~drop_mask].reset_index(drop=True)
        n_after = len(df)
        if n_before != n_after:
            logger.info('Excluded %d rows matching exclude symbols: %s', n_before - n_after, ','.join(exclude_set))
        # If exclusions removed all rows, revert exclusions (safe-fail) and warn
        if n_after == 0:
            logger.warning('Exclude filter removed all rows (n_before=%d). Reverting exclude for this run to avoid empty outputs.', n_before)
            print(f"⚠️ Exclude filter would remove all rows (removed {n_before}). Skipping excludes for this run.")
            df = df_original_before_exclude.copy()

    # === Data quality gate: ensure required market columns are present and non-empty ===
    # ユーザー指定の優先監視銘柄に合わせて必須列を更新
    # NOTE: User requested that only JP225, NASDAQ_MINI, GOLD_SPOT are strictly required
    required_markets = ['JP225', 'NASDAQ_MINI', 'GOLD_SPOT']
    missing = []
    try:
        for mkt in required_markets:
            if mkt not in market_df.columns or market_df[mkt].dropna().empty:
                missing.append(mkt)
    except Exception:
        missing = required_markets

    if missing:
        logger.error('Market data quality check failed; missing or empty columns: %s', ','.join(missing))
        print(f"❌ Market data incomplete: missing or empty columns: {', '.join(missing)}. Aborting run for safety.")
        return

    # Ensure columns
    if 'event_type' not in df.columns and 'text' not in df.columns:
        logger.error('CSV に event_type または text カラムが必要です。見つかりません。')
        return

    results = []
    for idx, row in df.iterrows():
        prompt = build_prompt_for_row(row)
        # idx may be a datetime-like index (string); use %s to avoid formatting TypeError
        logger.info('Row %s -> calling GPT (len prompt=%d)', idx, len(prompt))
        if dry_run:
            # Show sample of prompt
            logger.info('DRY RUN prompt preview: %s', prompt[:400])
            parsed = {'sentiment': 'Neutral', 'confidence': 0.5, 'reasons': ['dry-run']}
            raw_resp_text = 'DRY_RUN'
        else:
            resp = safe_call_gpt(client, model, prompt)
            # capture raw model output for auditing
            try:
                raw_resp_text = ''
                # OpenAI client response compatibility
                raw_resp_text = resp.choices[0].message.content
            except Exception:
                raw_resp_text = str(resp)
            parsed = parse_sentiment_response(resp)

        # --- raw model output logging (append per-run) ---
        try:
            logs_dir = Path.home() / "Desktop" / "CFD3_AutoSystem" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            raw_log = logs_dir / f"raw_model_responses_{datetime.now().strftime('%Y%m%d')}.jsonl"
            with open(raw_log, 'a', encoding='utf-8') as rf:
                entry = {'index': int(idx), 'text': (row.get('text') or row.get('headline') or ''), 'prompt': prompt, 'response': raw_resp_text, 'ts': datetime.now().isoformat()}
                rf.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            logger.warning('raw model output logging failed')

        numeric = sentiment_to_numeric(parsed.get('sentiment', 'Neutral'))
        results.append({
            'sentiment': parsed.get('sentiment', 'Neutral'),
            'confidence': parsed.get('confidence', 0.5),
            'reasons': '; '.join(parsed.get('reasons', [])),
            'numeric': numeric
        })

    scored = pd.concat([df.reset_index(drop=True), pd.DataFrame(results)], axis=1)
    # Preserve existing combined_score if present in input; otherwise compute from impact/numeric
    if 'combined_score' not in scored.columns:
        if 'impact' in scored.columns:
            scored['impact'] = scored['impact'].fillna(0.5)
            scored['combined_score'] = scored['impact'] * scored['numeric']
        else:
            scored['combined_score'] = scored['numeric']
    else:
        # try to coerce to float and fill NaN if necessary
        try:
            scored['combined_score'] = pd.to_numeric(scored['combined_score'], errors='coerce')
        except Exception:
            pass

    # Preserve a copy of the full scored DataFrame for internal outputs before any filtering
    full_scored = scored.copy()

    # === IFD提案ロジック ===
    # 市場列の正規化（マージによる _x / _y サフィックスを優先順で解決）
    market_cols = ["JP225", "NASDAQ", "GOLD"]
    # When merge_asof runs and the input CSV already contained market columns,
    # pandas will produce e.g. JP225_x (input) and JP225_y (from market_df).
    # Previously we stripped _x/_y which could hide which value was used.
    # Here we explicitly prefer the merged market value (suffix _y) when present,
    # otherwise fall back to the input value (_x) or any existing column.
    cols = list(scored.columns)
    resolved = {}
    for col in cols:
        # skip temporary suffixed columns; we'll add resolved names later
        if col.endswith('_x') or col.endswith('_y'):
            base = col[:-2]
            resolved.setdefault(base, []).append(col)
        else:
            # keep as-is if not a suffixed column and not already tracked
            if col not in resolved:
                resolved[col] = [col]

    # Build new column order choosing _y over _x when both exist
    new_cols = []
    for base, variants in resolved.items():
        chosen = None
        # prefer exact base if present in original (non-suffixed)
        if base in cols and base not in [v for lst in resolved.values() for v in lst if v!=base]:
            chosen = base
        else:
            # prefer _y (market), then _x (input), then first available
            y = base + '_y'
            x = base + '_x'
            if y in variants:
                chosen = y
            elif x in variants:
                chosen = x
            else:
                chosen = variants[0]
        new_cols.append((base, chosen))

    # Rebuild DataFrame with resolved column names (base names)
    reordered = {}
    for base, chosen in new_cols:
        reordered[base] = scored[chosen]
    scored = pd.DataFrame(reordered)

    # IFD提案ロジック (優先銘柄をユーザー指定の順に固定)
    # ユーザー要望: ドイツ40, 米国S500, Microsoft, Apple, JP225, 金スポット, ナスダックミニ
    priority_cols = ["DE40", "SP500", "MSFT", "AAPL", "JP225", "GOLD_SPOT", "NASDAQ_MINI"]

    # === 全銘柄を同時にIFD検討するため、各イベントを銘柄ごとに展開 ===
    # ユーザー要望: すべての銘柄を同時に検討
    expanded_rows = []
    for idx, row in scored.iterrows():
        for symbol in priority_cols:
            # 銘柄データが存在する場合のみ展開
            if symbol in row.index and not pd.isna(row[symbol]):
                new_row = row.copy()
                # この銘柄を優先的に選択させるため、他の銘柄をNaNに設定
                for other_symbol in priority_cols:
                    if other_symbol != symbol:
                        new_row[other_symbol] = np.nan
                # イベント名に銘柄を追加して識別しやすくする
                if pd.notna(new_row.get('text')):
                    new_row['text'] = f"{new_row['text']} [{symbol}]"
                expanded_rows.append(new_row)
    
    # 展開されたデータフレームを使用
    if expanded_rows:
        scored = pd.DataFrame(expanded_rows).reset_index(drop=True)
        print(f"✅ 全銘柄展開: {len(expanded_rows)}件のIFD候補を生成しました")

    # Auto-TP/SL parameters (configurable via CLI)
    ATR_PERIOD = int(atr_period)
    SMA_PERIOD = int(sma_period)
    MOM_WINDOW = int(momentum_window)
    RSI_BUY = float(rsi_buy)
    RSI_SELL = float(rsi_sell)
    RELAX_SCORE = float(relax_score_threshold)

    def detect_entry_source(row):
        for col in priority_cols:
            if col in row.index:
                val = row.get(col, np.nan)
                # handle array-like values (due to duplicate column names after merge)
                if isinstance(val, (pd.Series, list, tuple, np.ndarray)):
                    found = False
                    for v in list(val):
                        if not pd.isna(v):
                            found = True
                            break
                    if found:
                        return col
                    else:
                        continue
                if not pd.isna(val):
                    return col
        return np.nan

    def compute_ifd(row):
        src = detect_entry_source(row)
        val = row.get(src, np.nan) if isinstance(src, str) else np.nan
        # if val is array-like, take first non-NA element
        if isinstance(val, (pd.Series, list, tuple, np.ndarray)):
            picked = np.nan
            for v in list(val):
                if not pd.isna(v):
                    picked = v
                    break
            val = picked
        score = row.get("combined_score", 0)
        if pd.isna(val):
            # For missing entry, ensure full return shape (12 values) with NaNs
            return pd.Series(["HOLD", np.nan, np.nan, np.nan, src, np.nan, np.nan, np.nan, True, "no entry", False, ""])
        # しきい値によるシグナル分類
        if score >= 0.7:
            signal = "BUY"
        elif score <= -0.7:
            signal = "SELL"
        else:
            signal = "HOLD"

        # === GO / STRONG_GO ルールベースの TP/SL と lot_size 設定 ===
        # デフォルト: HOLD は取引無し
        trade_type = np.nan
        # initialize
        TP = np.nan
        SL = np.nan
        lot_size = np.nan
        # if HOLD, return NaNs for trade fields
        if signal == 'HOLD':
            # return same-length series as the main path: keep sanity_pass True but no lot
            return pd.Series([signal, np.nan, np.nan, np.nan, src, trade_type, 0.0, 0.0, True, 'HOLD', False, ''])

        # Determine GO type based on combined_score
        # Strong threshold
        strong_thresh = 0.85
        # デイトレ向け設定: STRONG_GO -> 3000円固定利確、GO -> 1000円固定利確
        # Use per-lot JPY targets and convert to price points via point value (pv)
        if score >= strong_thresh:
            trade_type = 'STRONG_GO'
            lot_override = 6.0  # default lots for STRONG_GO
            per_lot_tp_jpy = 3000.0  # デイトレ向け3000円固定利確
        else:
            trade_type = 'GO'
            lot_override = 4.0  # default lots for GO
            per_lot_tp_jpy = 1000.0  # デイトレ向け1000円固定利確

        # Convert per-lot TP in JPY to price points using point value (pv)
        try:
            pv = float(point_value_map.get(src, 1.0))
        except Exception:
            pv = 1.0
        
        # デイトレ向け：全シンボルでポイントベース計算（個別株は除外済み）
        try:
            entry_price = float(val)
        except Exception:
            entry_price = float(val) if not pd.isna(val) else np.nan
        
        # 全て指数として扱う（AAPL/MSFTはevents.csvで0に設定済み）
        # 指数：固定ポイントで計算
        try:
            tp_distance = float(per_lot_tp_jpy) / pv
        except Exception:
            tp_distance = float(per_lot_tp_jpy)
        # SL default: デイトレ向けにTPの1/3に縮小（損失を抑える）
        sl_distance = tp_distance / 3.0
        
        # BUY/SELL influence TP/SL direction (apply as absolute price offsets)
        if signal == 'BUY':
            TP = entry_price + tp_distance
            SL = entry_price - sl_distance
        else:
            TP = entry_price - tp_distance
            SL = entry_price + sl_distance
        # --- STRONG_GO: 自動利確モニタリング (ATR/RSI/SMA を参照して TP/SL を上書きする場合) ---
        # flags to record whether auto TP/SL was applied and reason
        auto_tp_applied = False
        auto_tp_reason = ''

        try:
            if trade_type == 'STRONG_GO':
                # 対応する market_df の列名を探す（候補を順に試す）
                market_col = None
                candidates = [src, src.replace('_SPOT', ''), src.replace('_MINI', ''), src.replace('NASDAQ_MINI', 'NASDAQ'), 'GOLD_SPOT', 'GOLD']
                for c in candidates:
                    if c in market_df.columns:
                        market_col = c
                        break
                if market_col is None:
                    # 部分一致も試す
                    for c in market_df.columns:
                        if src.split('_')[0] in str(c):
                            market_col = c
                            break

                if market_col is not None:
                    series = market_df[market_col].dropna().astype(float)
                    # 必要な履歴が揃っているか（最低20本）
                    if len(series) >= 20:
                        prices = series.tail(60)
                        # ATR の簡易代理指標: 指定されたATR期間の絶対リターン移動平均 × 平均価格
                        try:
                            atr = prices.pct_change().abs().rolling(ATR_PERIOD).mean().iloc[-1] * prices.mean()
                            if pd.isna(atr) or atr == 0:
                                atr = tp_distance * 0.5
                        except Exception:
                            atr = tp_distance * 0.5

                        # SMA
                        try:
                            sma20 = prices.rolling(SMA_PERIOD).mean().iloc[-1]
                        except Exception:
                            sma20 = float('nan')

                        # RSI (期間は14で計算)
                        try:
                            delta = prices.diff().dropna()
                            up = delta.clip(lower=0).rolling(14).mean()
                            down = -delta.clip(upper=0).rolling(14).mean()
                            rs = (up / down).replace([np.inf, -np.inf], np.nan)
                            rsi = 100 - (100 / (1 + rs))
                            rsi = float(rsi.iloc[-1]) if not rsi.empty else 50.0
                        except Exception:
                            rsi = 50.0

                        # 短期モメンタム（指定ウィンドウ）
                        try:
                            momentum = prices.pct_change(periods=MOM_WINDOW).iloc[-1]
                            momentum = float(momentum)
                        except Exception:
                            momentum = 0.0

                        # momentum 閾値は combined_score が高い場合に緩める
                        momentum_thresh = -0.01
                        if score and float(score) > RELAX_SCORE:
                            momentum_thresh = -0.003

                        trigger = False
                        if signal == 'BUY':
                            if (momentum < momentum_thresh) or (not pd.isna(sma20) and prices.iloc[-1] < sma20) or (rsi < RSI_BUY):
                                trigger = True
                        else:
                            # SELL の場合は逆シグナルで判定
                            if (momentum > abs(momentum_thresh)) or (not pd.isna(sma20) and prices.iloc[-1] > sma20) or (rsi > RSI_SELL):
                                trigger = True

                        if trigger:
                            # SL を ATR*3 に設定し、TP を ATR*2 に設定（リスクリワード比 1:0.67）
                            sl_val = float(atr) * 3.0
                            tp_val = float(atr) * 2.0
                            if signal == 'BUY':
                                SL = entry_price - sl_val
                                TP = entry_price + tp_val  # 買いの場合は上に利確
                            else:
                                SL = entry_price + sl_val
                                TP = entry_price - tp_val  # 売りの場合は下に利確
                            auto_tp_applied = True
                            auto_tp_reason = f"atr={float(atr):.4f}, rsi={float(rsi):.2f}, mom={float(momentum):.4f}"
                            logger.info('STRONG_GO 自動利確適用: %s (market_col=%s, %s) -> TP=%s, SL=%s', src, market_col, auto_tp_reason, TP, SL)
        except Exception as e:
            logger.warning('Auto TP evaluation failed for %s: %s', src, e)
        # 丸め単位適用（JP225 / SP500 / DE40 / AAPL / MSFT は整数）
        if src in ["JP225", "SP500", "DE40", "AAPL", "MSFT"]:
            val, TP, SL = round(val, 0), round(TP, 0), round(SL, 0)
        elif src == "NASDAQ_MINI":
            val, TP, SL = round(val, 2), round(TP, 2), round(SL, 2)
        elif src == "GOLD_SPOT":
            val, TP, SL = round(val, 2), round(TP, 2), round(SL, 2)
        # === lot_size / risk_amount の計算 ===
        # 要件: 口座残高=1,000,000 JPY, 許容リスク=1% => risk_target=10,000 JPY
        # JP225 の 1ポイントあたりの価値: 100 JPY（要件）
        # === lot_size / risk_amount の計算 (ユーザー指定のロジックに更新) ===
        # 各シンボルの1ポイントあたり価値（JPY換算）
        # 各シンボルの1ポイントあたり価値（JPY換算）
        # 値は想定（ブローカーによって異なるため運用時に調整してください）
        point_value_map = {
            "JP225": 100,        # 日経225
            "NASDAQ_MINI": 20,   # ナスダックミニ
            "SP500": 50,         # S&P500（概算）
            "GOLD_SPOT": 100,    # GOLD
            "DE40": 100,         # DAX（概算）
            "AAPL": 100,         # 個株（概算）
            "MSFT": 100,         # 個株（概算）
        }
        try:
            balance = 1_000_000
            risk_pct = 1.0  # percent
            risk_amount = balance * (risk_pct / 100.0)
            pv = point_value_map.get(src, 1.0)
            price_diff = None
            try:
                price_diff = abs(float(val) - float(SL))
            except Exception:
                price_diff = None

            # If GO rules set fixed lot_override, use it; otherwise compute lot based on risk
            if 'lot_override' in locals() and lot_override is not None:
                lot_size = float(lot_override)
            else:
                if price_diff and price_diff != 0:
                    lot_size = risk_amount / (price_diff * pv)
                else:
                    lot_size = 0.0

            # ブローカーの最小ロット単位で丸め
            min_lot_map = {
                "JP225": 0.1,
                "NASDAQ_MINI": 0.1,
                "SP500": 0.1,
                "GOLD_SPOT": 0.01,
                "DE40": 0.1,
                "AAPL": 0.01,
                "MSFT": 0.01,
            }
            min_lot = min_lot_map.get(src, 0.01)
            try:
                if lot_size and lot_size > 0:
                    floored = math.floor(lot_size / min_lot) * min_lot
                    # ユーザーの指定に合わせ最小単位以上に調整
                    lot_size = max(min_lot, floored)
                else:
                    lot_size = 0.0
            except Exception:
                pass

            try:
                lot_size = round(float(lot_size), 4)
                risk_amount = round(float(risk_amount), 2)
            except Exception:
                pass
        except Exception:
            lot_size = 0.0
            risk_amount = round(1_000_000 * (1.0 / 100.0), 2)

        # ユーザー仕様に合わせ、HOLD の行でも risk_amount は残すが lot_size は 0 にする運用にする場合は
        # 下記のように上書きできます。現在は上のロジックに従っています。

        # Compute risk_amount based on loss per lot (price diff * pv * lot_size)
        try:
            loss_per_lot = (abs(entry_price - SL) if not pd.isna(SL) else 0.0) * pv
            risk_amount = loss_per_lot * float(lot_size) if lot_size else round(balance * (risk_pct / 100.0), 2)
        except Exception:
            risk_amount = round(balance * (risk_pct / 100.0), 2)

        # Ensure numeric rounding
        # Ensure numeric rounding
        try:
            lot_size = round(float(lot_size), 4)
        except Exception:
            pass
        try:
            risk_amount = round(float(risk_amount), 2)
        except Exception:
            pass

        # --- Safety caps and sanity checks ---
        sanity_pass = True
        sanity_reason = ''
        try:
            # TP/SL width check
            if not pd.isna(entry_price) and not pd.isna(TP) and not pd.isna(SL):
                width = abs(TP - SL)
                if entry_price > 0 and (width / float(entry_price)) > MAX_TP_SL_PCT:
                    sanity_pass = False
                    sanity_reason = 'TP/SL width too large'
            # price_diff check
            if price_diff is None or price_diff <= 0:
                sanity_pass = False
                sanity_reason = (sanity_reason + '; price diff invalid').strip('; ')
        except Exception:
            pass

        # cap lot_size by per-symbol max and max risk percent
        try:
            max_lot = MAX_LOT_MAP.get(src, None)
            if max_lot is not None and not pd.isna(lot_size):
                if float(lot_size) > float(max_lot):
                    lot_size = float(max_lot)
            # cap risk amount to MAX_RISK_PCT of balance
            try:
                balance = float(balance)
            except Exception:
                balance = 1_000_000
            max_risk_amount = balance * (MAX_RISK_PCT / 100.0)
            if risk_amount and float(risk_amount) > float(max_risk_amount):
                risk_amount = round(float(max_risk_amount), 2)
        except Exception:
            pass

        # If sanity failed, set lot to 0 and mark trade as HOLD-like for safety
        if not sanity_pass:
            lot_size = 0.0
            risk_amount = 0.0

        # Ensure auto_tp flags exist (may have been set in STRONG_GO branch)
        try:
            _applied = auto_tp_applied
            _reason = auto_tp_reason
        except Exception:
            _applied = False
            _reason = ''

        return pd.Series([signal, val, TP, SL, src, trade_type, lot_size, risk_amount, sanity_pass, sanity_reason, _applied, _reason])

    # compute_ifd now returns: signal, entry, TP, SL, entry_source, type, lot_size, risk_amount, sanity_pass, sanity_reason, auto_tp_applied, auto_tp_reason
    # Apply compute_ifd row-wise but be robust to mis-sized returns (pad/trim as needed)
    try:
        # Debug: show scored shape before compute_ifd to detect empty inputs
        if os.environ.get('DEBUG_VERBOSE') == '1':
            try:
                logger.debug('DEBUG: scored.shape before compute_ifd = %s', getattr(scored, 'shape', None))
                if not scored.empty:
                    logger.debug('\n%s', scored.head(5).to_string())
            except Exception:
                pass

        # compute per-row, but handle malformed or variable-length returns robustly
        res = scored.apply(compute_ifd, axis=1)
        cols = ["signal", "entry", "TP", "SL", "entry_source", "type", "lot_size", "risk_amount", "sanity_pass", "sanity_reason", "auto_tp_applied", "auto_tp_reason"]
        rows = []
        for item in res:
            if isinstance(item, pd.Series):
                arr = item.tolist()
            elif isinstance(item, (list, tuple)):
                arr = list(item)
            else:
                arr = [item]
            # pad or trim to length of cols
            if len(arr) < len(cols):
                arr = arr + [pd.NA] * (len(cols) - len(arr))
            elif len(arr) > len(cols):
                arr = arr[:len(cols)]
            rows.append(arr)

        # Build DataFrame from rows safely
        try:
            df_ifd = pd.DataFrame(rows, columns=cols)
        except Exception:
            # fallback: create with no columns and fill with NaNs
            df_ifd = pd.DataFrame(rows)

        # Ensure df_ifd has at least as many rows as scored; if shorter, pad with NaNs
        if len(df_ifd) < len(scored):
            pad_n = len(scored) - len(df_ifd)
            pad_rows = [[pd.NA] * len(cols) for _ in range(pad_n)]
            df_ifd = pd.concat([df_ifd, pd.DataFrame(pad_rows, columns=df_ifd.columns)], ignore_index=True)

        # Assign columns into scored in a robust way
        for c in cols:
            if c in df_ifd.columns:
                try:
                    # align by position
                    scored[c] = df_ifd[c].values[:len(scored)]
                except Exception:
                    scored[c] = pd.Series([pd.NA] * len(scored))
            else:
                scored[c] = pd.Series([pd.NA] * len(scored))

        print("✅ IFD提案列を追加しました（signal / entry / TP / SL / entry_source）")
    except Exception as e:
        # Fallback: create empty columns to avoid crash
        print('⚠️ IFD列の作成中に例外が発生しました:', e)
        scored['signal'] = pd.NA
        scored['entry'] = pd.NA
        scored['TP'] = pd.NA
        scored['SL'] = pd.NA
        scored['entry_source'] = pd.NA
        scored['type'] = pd.NA
        scored['lot_size'] = pd.NA
        scored['risk_amount'] = pd.NA
        scored['sanity_pass'] = pd.NA
        scored['sanity_reason'] = pd.NA
        scored['auto_tp_applied'] = pd.NA
        scored['auto_tp_reason'] = pd.NA
    # Add lot_size calculation notice with fixed account params per requirements
    print("✅ lot_size計算を追加しました（残高=1000000JPY, リスク=1%）")
    # === Balanced 運用ルール: action 列を追加して TRADE/WATCH/IGNORE に分類します ===
    try:
        # normalize combined_score
        scored['combined_score'] = pd.to_numeric(scored['combined_score'], errors='coerce').fillna(0.0)
        # default
        scored['action'] = 'IGNORE'
        scored['action_reason'] = ''

        # Balanced rule (recommended):
        # - TRADE if STRONG_GO and combined_score >= 0.80 and sanity_pass == True
        # - TRADE if GO and combined_score >= 0.85 and sanity_pass == True (rare)
        # - WATCH if 0.65 <= combined_score < 0.80 and sentiment != 'Bearish'
        # - otherwise IGNORE
        def decide_action(row):
            try:
                score = float(row.get('combined_score', 0.0))
            except Exception:
                score = 0.0
            sentiment = str(row.get('sentiment', '') or '').lower()
            sanity = bool(row.get('sanity_pass', False))
            typ = str(row.get('type', '') or '')
            # If lenient mode is enabled, base decision only on score (ignore type/sentiment/sanity)
            if lenient:
                # Lenient thresholds: TRADE >=0.65, WATCH >=0.50
                if score >= 0.65:
                    return ('TRADE', f'lenient: score>={score:.2f} >=0.65')
                if score >= 0.50:
                    return ('WATCH', f'lenient: score>={score:.2f} >=0.50')
                return ('IGNORE', f'lenient: score<{score:.2f} <0.50')

            # TRADE rules (default Balanced behavior)
            if typ == 'STRONG_GO' and score >= 0.80 and sanity:
                return ('TRADE', 'STRONG_GO and score>=0.80 and sanity_pass')
            if typ == 'GO' and score >= 0.85 and sanity:
                return ('TRADE', 'GO and score>=0.85 and sanity_pass')
            # WATCH rules
            if 0.65 <= score < 0.80 and sentiment != 'bearish':
                return ('WATCH', 'score between 0.65 and 0.80 and sentiment not Bearish')
            # default
            return ('IGNORE', 'does not meet trade/watch thresholds')

        acts = scored.apply(lambda r: decide_action(r), axis=1)
        scored['action'] = [a[0] for a in acts]
        scored['action_reason'] = [a[1] for a in acts]

        # Filter for subsequent production output: only TRADE rows become production candidates
        filtered = scored.loc[scored['action'] == 'TRADE'].copy()
        if filtered.empty:
            print('ℹ️ Balanced ルールの結果: TRADE 対象はありませんでした（出力は空です）。')
        else:
            print(f"✅ Balanced ルールで TRADE を採用しました（件数={len(filtered)}）")
        scored = filtered
    except Exception as e:
        logger.warning('Balanced rule processing failed: %s', e)
    # Prepare a cleaned_df (minimal canonical schema) so logs and public/internal CSVs can be generated
    # Add an explicit instrument column based on entry_source so outputs don't mis-label TOPIX as JP225 etc.
    scored['instrument'] = scored['entry_source']

    desired = ['text', 'date', 'combined_score', 'signal', 'type', 'instrument', 'entry', 'TP', 'SL', 'entry_source', 'lot_size', 'risk_amount', 'sanity_pass', 'sanity_reason', 'auto_tp_applied', 'auto_tp_reason']
    for d in desired:
        if d not in scored.columns:
            scored[d] = pd.NA
    cleaned_df = scored[desired].copy()
    # === Ensure required output columns have safe defaults to prevent downstream failures ===
    # Default policy:
    # - signal/type: 'HOLD'
    # - entry/TP/SL/entry_source: empty string for public-friendly CSV
    # - lot_size/risk_amount: 0.0
    # - sanity_pass: False
    try:
        cleaned_df['signal'] = cleaned_df['signal'].fillna('HOLD')
    except Exception:
        cleaned_df['signal'] = cleaned_df['signal'].apply(lambda x: 'HOLD' if pd.isna(x) else x)
    if 'type' in cleaned_df.columns:
        cleaned_df['type'] = cleaned_df['type'].fillna('HOLD')
    for col in ['entry', 'TP', 'SL', 'entry_source']:
        if col in cleaned_df.columns:
            cleaned_df[col] = cleaned_df[col].fillna('')
    # numeric defaults
    for ncol in ['lot_size', 'risk_amount']:
        if ncol in cleaned_df.columns:
            try:
                cleaned_df[ncol] = pd.to_numeric(cleaned_df[ncol], errors='coerce').fillna(0.0)
            except Exception:
                cleaned_df[ncol] = cleaned_df[ncol].apply(lambda x: 0.0 if pd.isna(x) else x)
    if 'sanity_pass' in cleaned_df.columns:
        cleaned_df['sanity_pass'] = cleaned_df['sanity_pass'].fillna(False)
    # 表示の改善: 主要列をターミナルで整形表示します。
    # === 自動ログ出力 & CSVサマリー保存（launchd対応） ===
    print("\n==== RUN START ({}) ====\n".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    try:
        # --- 整形テーブル表示（既存のTabulate出力を利用） ---
        from tabulate import tabulate
        cols_to_show = ["text", "signal", "type", "entry_source", "lot_size", "risk_amount", "entry", "TP", "SL", "combined_score"]
        # do not show the DataFrame index in the table
        table_str = tabulate(scored[cols_to_show].head(20), headers=cols_to_show, tablefmt="github", floatfmt=".2f", showindex=False)
        print("\n📊 出力サマリー（主要列）:")
        print(table_str)
    except Exception as e:
        print("⚠️ 表形式の出力中にエラー:", e)
        table_str = scored.head(10).to_string(index=False)

    # === ログ/CSV 保存処理 ===
    try:
        # ディレクトリの作成
        logs_dir = Path.home() / "Desktop" / "CFD3_AutoSystem" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # ファイル名（日時付き）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = logs_dir / f"ifd_summary_{timestamp}.log"
        csv_path = logs_dir / f"ifd_summary_{timestamp}.csv"

        # テキストログ保存
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("==== IFD SUMMARY LOG ====\n")
            f.write(f"Generated: {datetime.now()}\n")
            f.write("\n" + table_str + "\n")
            f.write("\n==== END LOG ====\n")

        # CSV保存
        scored.to_csv(csv_path, index=False)
        print(f"\n✅ ログ保存完了: {log_path}")
        print(f"✅ CSV保存完了: {csv_path}")

    except Exception as e:
        print("⚠️ ログ保存でエラー:", e)

    # --- 公開用 / 内部用 CSV の出力（ドライブ保存） ---
    try:
        # prepare two variants: internal (rich) and public (minimal, nicely rounded)
        # include lot_size and risk_amount after entry_source per requirement
        # >>> PATCH START: keep stronger side per symbol for public/summary <<<
        def _type_rank(v: str) -> int:
            # 小さいほど優先
            order = {'STRONG_GO': 0, 'GO': 1, 'HOLD': 2}
            return order.get(str(v).upper(), 9)

        def _prepare_for_filter(df: pd.DataFrame) -> pd.DataFrame:
            out = df.copy()
            # 安全な型変換
            if 'combined_score' in out.columns:
                out['__abs_score__'] = out['combined_score'].astype(float).abs()
            else:
                out['__abs_score__'] = 0.0
            if 'type' in out.columns:
                out['__type_rank__'] = out['type'].map(_type_rank)
            else:
                out['__type_rank__'] = 9
            if 'date' in out.columns:
                out['__date__'] = pd.to_datetime(out['date'], errors='coerce')
            else:
                out['__date__'] = pd.NaT
            return out

        def keep_stronger_side_per_symbol(df: pd.DataFrame) -> pd.DataFrame:
            """同一 entry_source で片側のみ残す。abs(score) 降順、date 降順、type優先度 昇順。"""
            if 'entry_source' not in df.columns:
                return df
            tmp = _prepare_for_filter(df)
            tmp = tmp.sort_values(
                by=['entry_source', '__abs_score__', '__date__', '__type_rank__'],
                ascending=[True, False, False, True]
            )
            kept = tmp.drop_duplicates(subset=['entry_source'], keep='first').drop(columns=['__abs_score__','__date__','__type_rank__'])
            return kept

        # --- create internal (full) and public (filtered) views ---
        public_cols = ["text", "signal", "type", "entry_source", "lot_size", "risk_amount", "entry", "TP", "SL", "combined_score"]
        # internal: keep full scored rows (pre-filter)
        internal_df = full_scored.copy()
        # public: start from cleaned minimal schema but apply stronger-side filter
        public_df = cleaned_df.copy()
        # Ensure numeric columns exist on public_df
        for c in ["entry", "TP", "SL", "combined_score"]:
            if c not in public_df.columns:
                public_df[c] = np.nan
        public_view = keep_stronger_side_per_symbol(public_df)
        print(f"🧹 同一シンボルの強い方だけを採用（同点は最新→type優先）: {len(public_view)} / {len(public_df)} 行")
        # >>> PATCH END <<<

        def format_row_for_public(r):
            # operate on a plain dict to avoid assigning into a Series with numeric dtype
            out = dict(r)
            src = out.get('entry_source')
            e = out.get('entry')
            tp = out.get('TP')
            sl = out.get('SL')
            # apply rounding rules
            try:
                if pd.isna(e):
                    out['entry'] = ''
                    out['TP'] = ''
                    out['SL'] = ''
                else:
                    if src in ["JP225", "SP500", "DE40", "AAPL", "MSFT"]:
                        out['entry'] = int(round(float(e)))
                        out['TP'] = int(round(float(tp))) if not pd.isna(tp) else ''
                        out['SL'] = int(round(float(sl))) if not pd.isna(sl) else ''
                    elif src == 'NASDAQ_MINI':
                        out['entry'] = round(float(e), 2)
                        out['TP'] = round(float(tp), 2) if not pd.isna(tp) else ''
                        out['SL'] = round(float(sl), 2) if not pd.isna(sl) else ''
                    elif src == 'GOLD_SPOT':
                        out['entry'] = round(float(e), 2)
                        out['TP'] = round(float(tp), 2) if not pd.isna(tp) else ''
                        out['SL'] = round(float(sl), 2) if not pd.isna(sl) else ''
                    elif src == 'USDJPY':
                        out['entry'] = round(float(e), 2)
                        out['TP'] = round(float(tp), 2) if not pd.isna(tp) else ''
                        out['SL'] = round(float(sl), 2) if not pd.isna(sl) else ''
                    else:
                        # default: 2 decimals for floats
                        out['entry'] = round(float(e), 2)
                        out['TP'] = round(float(tp), 2) if not pd.isna(tp) else ''
                        out['SL'] = round(float(sl), 2) if not pd.isna(sl) else ''
            except Exception:
                # leave as-is on any error
                pass
            # combined_score to 2 decimals
            try:
                if 'combined_score' in out and not pd.isna(out['combined_score']):
                    out['combined_score'] = round(float(out['combined_score']), 2)
            except Exception:
                pass
            # Ensure auto_tp fields are present and human-friendly for public view
            try:
                # auto_tp_applied: convert truthy to 'TRUE' else blank
                if 'auto_tp_applied' in out and not pd.isna(out.get('auto_tp_applied')):
                    out['auto_tp_applied'] = 'TRUE' if bool(out.get('auto_tp_applied')) else ''
                else:
                    out['auto_tp_applied'] = ''
            except Exception:
                out['auto_tp_applied'] = ''
            try:
                if 'auto_tp_reason' in out and not pd.isna(out.get('auto_tp_reason')):
                    # truncate long reasons for public CSV
                    reason = str(out.get('auto_tp_reason') or '')
                    out['auto_tp_reason'] = (reason[:120] + '...') if len(reason) > 120 else reason
                else:
                    out['auto_tp_reason'] = ''
            except Exception:
                out['auto_tp_reason'] = ''
            return pd.Series(out)

        # Ensure entry/TP/SL and combined_score can safely hold empty strings without dtype warnings
        for _col in ['entry', 'TP', 'SL', 'combined_score']:
            # create column as empty string if missing so dtype becomes object
            if _col not in public_view.columns:
                public_view[_col] = ''
            try:
                public_view[_col] = public_view[_col].astype(object)
            except Exception:
                # fallback: ensure elements are objects
                public_view[_col] = public_view[_col].apply(lambda x: x)

        import warnings
        warnings.filterwarnings('ignore', category=FutureWarning)
        public_view = public_view.apply(format_row_for_public, axis=1)
    # Note: we intentionally suppress the specific FutureWarning here because
    # format_row_for_public constructs new Series objects and the prior pandas
    # behavior emits a deprecation warning when assigning '' into float columns.
    # The suppression is local and minimal; consider removing after upstream fix.

        # choose filenames
        timestamp2 = datetime.now().strftime('%Y%m%d_%H%M')
        internal_name = f"events_scored_{timestamp2}_internal.csv"
        public_name = f"events_scored_{timestamp2}_public.csv"

        # write into drive_sync_path (determined below in normal upload flow) — for dry-run, also write into logs_dir
        # We will save public/internal into the logs dir as well for record
        try:
            public_save_path = logs_dir / public_name
            internal_save_path = logs_dir / internal_name
            # Finalize public_view: cast key numeric columns to formatted strings
            def _to_str_num(v):
                try:
                    if v == '' or pd.isna(v):
                        return ''
                    f = float(v)
                    if float(f).is_integer():
                        return str(int(f))
                    return f"{f:.2f}"
                except Exception:
                    return '' if v == '' else str(v)

            for _c in ['entry', 'TP', 'SL']:
                if _c in public_view.columns:
                    public_view[_c] = public_view[_c].apply(_to_str_num)

            if 'combined_score' in public_view.columns:
                public_view['combined_score'] = public_view['combined_score'].apply(lambda v: '' if v == '' or pd.isna(v) else f"{float(v):.2f}")

            # Save the filtered public_view (stronger side per symbol) and internal full copy
            public_view.to_csv(public_save_path, index=False, encoding='utf-8-sig')
            internal_df.to_csv(internal_save_path, index=False, encoding='utf-8-sig')
            logger.info('Saved public/internal CSV to logs: %s, %s', public_save_path, internal_save_path)
            print(f"✅ 公開用CSV保存: {public_save_path}")
            print(f"✅ 内部用CSV保存: {internal_save_path}")
        except Exception:
            # non-fatal
            logger.warning('Could not save public/internal CSV into logs folder')


        print(f"\n✅ ログ保存完了: {log_path}")
        print(f"✅ CSV保存完了: {csv_path}")

    except Exception as e:
        print("⚠️ ログ保存でエラー:", e)

    # --- 追加: 最新の internal CSV を fancy_grid で毎回表示する ---
    try:
        from tabulate import tabulate
        import glob
        files = sorted(glob.glob(str(logs_dir / "events_scored_*_internal.csv")), key=os.path.getmtime)
        if files:
            latest_internal = files[-1]
            print(f"\n📊 最新のIFD結果（{latest_internal}）\n")
            df_latest = pd.read_csv(latest_internal)
            cols_show = ["signal", "type", "entry_source", "entry", "TP", "SL", "lot_size", "combined_score"]
            present = [c for c in cols_show if c in df_latest.columns]
            print(tabulate(df_latest[present], headers="keys", tablefmt="fancy_grid", showindex=False, floatfmt=".2f"))
        else:
            print("❌ internal CSV が見つかりませんでした。")
    except Exception as e:
        logger.warning('最新IFD表示に失敗しました: %s', e)

    print("==== RUN END ({}) ====\n".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    out_name = 'events_scored.csv'
    if dry_run:
        logger.info('DRY RUN: would upload %s (rows=%d)', out_name, len(scored))
        print(scored.head().to_string())
    else:
        # Instead of attempting to upload via the Drive API (which may fail for
        # service accounts without quota), write directly to a local Google Drive
        # sync folder (e.g. "/Users/otomi/Google ドライブ/CFD3Pro"). This follows
        # the recommended quick workflow described in the instructions.
        try:
            base = detect_local_google_drive() or os.environ.get('LOCAL_GOOGLE_DRIVE')
            # determine output destination: CLI --out takes precedence
            if out_path:
                outp = os.path.expanduser(out_path)
                # if outp is a directory, create file inside
                if os.path.isdir(outp):
                    drive_sync_path = outp
                else:
                    # if parent dir exists or can be created, use containing dir
                    parent = os.path.dirname(outp) or os.path.expanduser('~')
                    os.makedirs(parent, exist_ok=True)
                    drive_sync_path = parent
                    # use provided filename
                    output_filename = os.path.basename(outp)
            else:
                base = detect_local_google_drive() or os.environ.get('LOCAL_GOOGLE_DRIVE')
                if base:
                    drive_sync_path = os.path.join(base, 'CFD3Pro')
                else:
                    # fallback to user's Desktop project output
                    drive_sync_path = os.path.join(os.path.expanduser('~'), 'Desktop', 'CFD3_AutoSystem', 'output')

            os.makedirs(drive_sync_path, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            if 'output_filename' not in locals():
                output_filename = f"events_scored_{timestamp}.csv"
            output_path = os.path.join(drive_sync_path, output_filename)
            # --- 出力クリーンアップ ---
            # Remove duplicated columns (e.g. *_x, *_y) already normalized earlier.
            # Keep only the requested columns in specific order.
            def pick_column(df, base):
                # return the first matching column name for base (exact match preferred)
                if base in df.columns:
                    return base
                # try variations with suffixes
                for c in df.columns:
                    if c.split('.')[0] == base or c.startswith(base + '_') or c.endswith('_' + base) or base in c:
                        return c
                return None

            desired = ['text', 'date', 'combined_score', 'signal', 'entry', 'TP', 'SL', 'entry_source', 'lot_size', 'risk_amount', 'auto_tp_applied', 'auto_tp_reason']
            cleaned_cols = []
            for d in desired:
                col = pick_column(scored, d)
                if col:
                    cleaned_cols.append(col)
                else:
                    # if missing, create a column with NaNs to keep schema
                    scored[d] = np.nan
                    cleaned_cols.append(d)

            cleaned_df = scored[cleaned_cols].copy()
            # rename columns to canonical names if needed
            rename_map = {col: name for col, name in zip(cleaned_cols, desired) if col != name}
            if rename_map:
                cleaned_df = cleaned_df.rename(columns=rename_map)

            # Save cleaned CSV
            cleaned_df.to_csv(output_path, index=False, encoding='utf-8-sig')
            logger.info('Wrote cleaned scored CSV to %s', output_path)
            print("✅ 出力クリーンアップ完了")
            print(f"✅ Driveフォルダに保存完了: {output_path}")
            # mark run end for launchd logs
            ts_end = datetime.now().isoformat()
            print(f'RUN END {ts_end}', flush=True)
        except Exception as e:
            logger.exception('Failed to write scored CSV locally: %s', e)
            # As a last resort, attempt to use the Drive client (existing fallback)
            try:
                drive.upload_csv(scored, out_name, existing_file=None)
                logger.info('✅ %s をDriveに保存しました。', out_name)
            except Exception:
                logger.exception('Drive upload also failed; check logs and service account settings.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--file', default='events.csv')
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--service-account', help='サービスアカウント JSON のパス（自動化向け）')
    parser.add_argument('--local-file', help='ローカルの events CSV を直接指定して読み込む（テスト用）')
    parser.add_argument('--out', help='出力先ディレクトリまたはファイル名（例: /path/to/dir or /path/to/file.csv）')
    parser.add_argument('--tolerance', help="merge_asof の許容時間（例: '1h', '30min'）。指定がなければ無制限。")
    parser.add_argument('--output-mode', choices=['internal', 'public'], default='internal', help='出力 CSV のモード: internal (詳細) または public (公開用に整形)')
    # Default behavior: lenient (より多くのチャンスを出力)
    parser.add_argument('--strict', action='store_true', help='厳格モード: Balanced ルールを適用（--strict を指定すると lenient ではなくなります）')
    # Auto-TP/SL tuning parameters
    parser.add_argument('--atr-period', type=int, default=14, help='ATR proxy の計算に使う期間（デフォルト: 14）')
    parser.add_argument('--sma-period', type=int, default=20, help='SMA の期間（デフォルト: 20）')
    parser.add_argument('--momentum-window', type=int, default=5, help='モメンタム計算の期間（デフォルト: 5）')
    parser.add_argument('--rsi-buy', type=float, default=45.0, help='BUY に対する RSI トリガー閾値（デフォルト: 45）')
    parser.add_argument('--rsi-sell', type=float, default=55.0, help='SELL に対する RSI トリガー閾値（デフォルト: 55）')
    parser.add_argument('--relax-score-threshold', type=float, default=0.9, help='combined_score がこれを超えると閾値を緩める（デフォルト: 0.9）')
    args = parser.parse_args()
    main(dry_run=args.dry_run, target_file=args.file, model=args.model, service_account_file=args.service_account, local_file=args.local_file, out_path=args.out, tolerance=args.tolerance, output_mode=args.output_mode, lenient=(not args.strict), atr_period=args.atr_period, sma_period=args.sma_period, momentum_window=args.momentum_window, rsi_buy=args.rsi_buy, rsi_sell=args.rsi_sell, relax_score_threshold=args.relax_score_threshold)
