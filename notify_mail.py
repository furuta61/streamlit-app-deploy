#!/usr/bin/env python3
import argparse, os, time, datetime, yagmail

OUTPUT_DIR = "./output"

def load_creds():
    # support multiple env var names used across configs (.env uses ALERT_EMAIL_USER)
    user = os.environ.get("EMAIL_USER") or os.environ.get("GMAIL_USER") or os.environ.get("ALERT_EMAIL_USER")
    pwd  = os.environ.get("EMAIL_PASS") or os.environ.get("GMAIL_APP_PASSWORD") or os.environ.get("ALERT_EMAIL_PASS")
    return user, pwd

def send_email(recipient: str, subject: str, body: str, attachments: list[str], retries=3, sleep_s=2):
    user, pwd = load_creds()
    for i in range(1, retries+1):
        try:
            if user and pwd:
                yag = yagmail.SMTP(user=user, password=pwd)     # 環境変数で送信
            elif user and not pwd:
                yag = yagmail.SMTP(user)                        # keyring（yagmail.register 済み）
            else:
                yag = yagmail.SMTP()                            # 送信元はkeyringの既定を使用
            yag.send(to=recipient, subject=subject, contents=body, attachments=attachments)
            print(f"📧 メール送信完了: {recipient}")
            return True
        except Exception as e:
            print(f"⚠️ 送信失敗({i}/{retries}): {e}")
            if i < retries: time.sleep(sleep_s)
    return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="本番送信を実行")
    # recipient fallback: RECIPIENT > EMAIL_USER > ALERT_EMAIL_TO > ALERT_EMAIL_USER
    default_recipient = os.environ.get("RECIPIENT") or os.environ.get("EMAIL_USER") or os.environ.get("ALERT_EMAIL_TO") or os.environ.get("ALERT_EMAIL_USER")
    parser.add_argument("--recipient", default=default_recipient,
                        help="送信先メール。未指定時は RECIPIENT/EMAIL_USER/ALERT_EMAIL_TO を順に使用")
    parser.add_argument("--dry-run", action="store_true", help="送信せず内容を表示")
    args = parser.parse_args()

    json_path = os.path.join(OUTPUT_DIR, "ifd_proposals.json")
    md_path   = os.path.join(OUTPUT_DIR, "ifd_proposals.md")
    if not (os.path.exists(json_path) and os.path.exists(md_path)):
        print("❌ IFD提案ファイルが見つかりません。"); return

    with open(md_path, "r", encoding="utf-8") as f:
        summary = f.read()

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"[CFD3 AutoSystem] IFD提案生成完了 ({now})"
    body = f"✅ IFD提案を生成しました。\n\n---\n{summary}\n\n出力: {os.path.abspath(OUTPUT_DIR)}"

    print(f"送信先: {args.recipient}")
    print(f"添付: {json_path}, {md_path}")

    if args.dry_run or not args.send:
        print("🧪 ドライラン: 送信しません。件名/本文プレビュー↓\n", subject, "\n", body[:400], "...")
        return

    if not args.recipient:
        print("❌ 送信先が未設定です（--recipient か EMAIL_USER/RECIPIENT を設定）"); return

    ok = send_email(args.recipient, subject, body, [json_path, md_path])
    if not ok: raise SystemExit(1)

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
notify_mail.py
- IFD 提案（./output/ifd_proposals.json, .md）を Gmail 経由で送信する簡易スクリプト
- 動作条件: 環境変数 EMAIL_USER と EMAIL_PASS を設定すること（Gmail のアプリパスワード推奨）
- 依存: yagmail (pip install yagmail)

Usage:
  export EMAIL_USER="you@gmail.com"
  export EMAIL_PASS="your_app_password"
  python3 notify_mail.py

安全メモ:
- 推奨は Gmail のアプリパスワードを使うこと（2段階認証を有効にして発行）。
- 直接パスワードをファイルに書き込まないでください。
"""
import os
import sys
import datetime
import argparse
import keyring

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
JSON_NAME = 'ifd_proposals.json'
MD_NAME = 'ifd_proposals.md'

# 認証情報は環境変数から取得（CLI で上書き可）、Keyring をフォールバックで利用
# resolve EMAIL_USER / ALERT_EMAIL_USER fallbacks
EMAIL_USER = os.environ.get('EMAIL_USER') or os.environ.get('GMAIL_USER') or os.environ.get('ALERT_EMAIL_USER')
# EMAIL_PASS は環境変数か Keyring('gmail', EMAIL_USER) を参照
ENV_PASS = os.environ.get('EMAIL_PASS') or os.environ.get('GMAIL_PASS') or os.environ.get('GMAIL_APP_PASSWORD') or os.environ.get('ALERT_EMAIL_PASS')
EMAIL_PASS = ENV_PASS
if not EMAIL_PASS and EMAIL_USER:
    try:
        EMAIL_PASS = keyring.get_password('gmail', EMAIL_USER)
    except Exception:
        EMAIL_PASS = ENV_PASS
# recipient fallback: RECIPIENT > ALERT_EMAIL_TO > EMAIL_USER
ENV_RECIPIENT = os.environ.get('RECIPIENT') or os.environ.get('ALERT_EMAIL_TO') or EMAIL_USER


def send_notification(dry_run=False, recipient=None):
    json_path = os.path.join(OUTPUT_DIR, JSON_NAME)
    md_path = os.path.join(OUTPUT_DIR, MD_NAME)

    json_exists = os.path.exists(json_path)
    md_exists = os.path.exists(md_path)

    if not json_exists and not dry_run:
        print('❌ IFD提案ファイルが見つかりません:', json_path)
        sys.exit(2)
    if not md_exists:
        print('⚠️ Markdown 要約ファイルが見つかりません, 送信は続行します:', md_path)

    # resolve recipient (CLI > ENV > EMAIL_USER)
    recipient = recipient or ENV_RECIPIENT

    # prepare message
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    subject = f"[CFD3 AutoSystem] IFD提案生成完了 ({now})"
    body_intro = f"✅ IFD提案を生成しました。出力フォルダ: {os.path.abspath(OUTPUT_DIR)}\n"

    summary = ''
    try:
        if md_exists:
            with open(md_path, 'r', encoding='utf-8') as f:
                summary = f.read()
    except Exception as e:
        summary = f"(Markdown 読込エラー: {e})"

    contents = body_intro + '\n---\n' + summary

    # If dry-run: just print what would be sent and return
    attachments = []
    if json_exists:
        attachments.append(json_path)
    if md_exists:
        attachments.append(md_path)

    if dry_run:
        print('--- DRY RUN ---')
        print('送信先:', recipient)
        print('件名:', subject)
        print('添付ファイル:')
        if attachments:
            for p in attachments:
                print(' -', p)
        else:
            print(' (なし)')
        print('\n本文プレビュー:\n')
        print(contents[:1000])
        print('--- END DRY RUN ---')
        return

    # 認証チェック
    if not EMAIL_USER:
        print('❌ 環境変数 EMAIL_USER が設定されていません。\n例: export EMAIL_USER=you@gmail.com')
        sys.exit(3)

    # lazy import yagmail with helpful error
    try:
        import yagmail
    except Exception as e:
        print('❌ yagmail をインポートできません。インストールしてください: pip install yagmail')
        print('詳細:', e)
        sys.exit(4)

    # connect and send
    try:
        if EMAIL_PASS:
            yag = yagmail.SMTP(EMAIL_USER, EMAIL_PASS)
        else:
            # if no pass, rely on keyring configuration (yagmail will try)
            yag = yagmail.SMTP(EMAIL_USER)
    except Exception as e:
        print('❌ Gmail へ接続できません。認証情報を確認してください。')
        print('詳細:', e)
        sys.exit(5)

    try:
        yag.send(to=recipient, subject=subject, contents=contents, attachments=attachments)
        print(f'📧 メール送信完了: {recipient}')
    except Exception as e:
        print('❌ メール送信に失敗しました。')
        print('詳細:', e)
        sys.exit(6)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='IFD 提案を Gmail で送信します。--dry-run オプションで実際の送信を行わずに確認できます。')
    parser.add_argument('--dry-run', action='store_true', help='添付や認証が無くても送信内容を表示するドライラン')
    parser.add_argument('--recipient', '-r', help='送信先メールアドレス（環境変数 RECIPIENT を上書き）')
    args = parser.parse_args()
    try:
        send_notification(dry_run=args.dry_run, recipient=args.recipient)
    except SystemExit:
        raise
    except Exception as e:
        print('予期せぬエラーが発生しました:', e)
        sys.exit(99)
