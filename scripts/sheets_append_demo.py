#!/usr/bin/env python3
import os
import sys
import json
import argparse
from datetime import datetime

try:
    from googleapiclient.discovery import build
    from google.oauth2 import service_account
except Exception as e:
    print("❌ google-api-python-client / google-auth が未インストールです。requirements.txt を反映してください。", file=sys.stderr)
    raise


def load_service_account_creds() -> dict:
    """環境変数からサービスアカウントJSONを読み込む。
    - GOOGLE_CREDENTIALS_JSON: JSON全文
    - GOOGLE_CREDENTIALS_JSON_FILE: JSONファイルパス
    いずれも無ければ ValueError。
    """
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    creds_file = os.getenv("GOOGLE_CREDENTIALS_JSON_FILE")

    if creds_json:
        try:
            return json.loads(creds_json)
        except Exception as e:
            raise ValueError(f"GOOGLE_CREDENTIALS_JSON のJSONパースに失敗: {e}")

    if creds_file:
        if not os.path.exists(creds_file):
            raise ValueError(f"GOOGLE_CREDENTIALS_JSON_FILE が見つかりません: {creds_file}")
        try:
            with open(creds_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            raise ValueError(f"GOOGLE_CREDENTIALS_JSON_FILE の読み込み/パースに失敗: {e}")

    raise ValueError("環境変数 GOOGLE_CREDENTIALS_JSON か GOOGLE_CREDENTIALS_JSON_FILE を設定してください")


def build_sheets_service(creds_info: dict):
    creds = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds)


def append_record(service, sheet_id: str, record: dict, sheet_range: str = "Logs!A1"):
    # バックエンドと同一の列順を採用
    ordered_keys = [
        "timestamp", "symbol", "direction", "entry", "tp", "sl", "signal", "confidence", "comment"
    ]
    row = [record.get(k, "") for k in ordered_keys]
    body = {"values": [row]}
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=sheet_range,
        valueInputOption="USER_ENTERED",
        body=body,
    ).execute()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Append a demo IFD analysis row to Google Sheets")
    p.add_argument("--sheet-id", default=os.getenv("SHEET_ID"), help="Google Sheet ID (env SHEET_ID)")
    p.add_argument("--sheet-range", default="Logs!A1", help="Append range, default: Logs!A1")
    p.add_argument("--symbol", default="TEST_JP225")
    p.add_argument("--direction", default="buy", choices=["buy", "sell"])
    p.add_argument("--entry", type=float, default=49000)
    p.add_argument("--tp", type=float, default=49100)
    p.add_argument("--sl", type=float, default=48900)
    p.add_argument("--signal", default="GO")
    p.add_argument("--confidence", type=int, default=99)
    p.add_argument("--comment", default="テスト書き込み")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not args.sheet_id:
        raise ValueError("環境変数 SHEET_ID または --sheet-id を設定してください")

    creds_info = load_service_account_creds()
    service = build_sheets_service(creds_info)

    record = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": args.symbol,
        "direction": args.direction,
        "entry": args.entry,
        "tp": args.tp,
        "sl": args.sl,
        "signal": args.signal,
        "confidence": args.confidence,
        "comment": args.comment,
    }

    append_record(service, args.sheet_id, record, args.sheet_range)
    print("✅ Google Sheets 書き込み成功:", json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("❌ Error:", str(e), file=sys.stderr)
        sys.exit(1)
