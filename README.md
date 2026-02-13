# Mail Check AI

複数のPOP3サーバーを監視し、登録済み顧客のメールをAI解析してGitea・Discordへ自動配信するシステム。
SMTP中継機能により送信メールも捕捉し、受信・送信を会話スレッドとして一元管理する。

## 主な機能

- **マルチPOP3監視**: 複数メールアカウントの同時監視
- **SMTP中継**: 送信メールをリレーし、AI分析・Git保存後に転送先SMTPサーバーへ中継
- **会話スレッド管理**: Message-ID / In-Reply-To / References ヘッダで受信・送信メールを自動紐づけ
- **ホワイトリスト方式**: 未登録アドレスのメールは無視
- **AI解析 (GPT-4)**: メール要約・Gitea Issue起票（受信）、要約・アクションアイテム抽出（送信）
- **Git証跡管理**: 顧客別Giteaリポジトリへ自動コミット・プッシュ
- **Discord通知**: Webhook経由でメール処理通知
- **添付ファイル解析**: PDF (OCR対応)、Word、Excel、CSV、テキストファイル
- **Web UI**: Bootstrap ベースの管理画面（顧客・メール・スレッド・SMTP設定）
- **セキュア構成**: Unix Domain Socket (DB) + Tailscale (外部アクセス)

## アーキテクチャ

```
                    ┌─────────────┐
                    │  POP3       │
                    │  Servers    │
                    └──────┬──────┘
                           │ 受信メール取得
                           ▼
┌────────────┐      ┌─────────────┐      ┌──────────────┐
│ Tailscale  │      │   Worker    │─────▶│  PostgreSQL  │
│ (VPN mesh) │      │  Container  │      │   (UDS)      │
└─────┬──────┘      └──────┬──────┘      └──────────────┘
      │                    │
      │                    ├─────▶ OpenAI API (GPT-4)
      │                    ├─────▶ Gitea (Git Push + Issue)
      │                    └─────▶ Discord (Webhook)
      │
      ├── API (port 8000)        ─── Web UI + REST API
      ├── SMTP Relay (port 587)  ─── 送信メール中継
      └── pgAdmin (port 5050)    ─── DB管理
                           ▲
                           │ 送信メール
                    ┌──────┴──────┐      ┌──────────────┐
                    │ メール      │      │ 転送先SMTP   │
                    │ クライアント │      │ サーバー     │
                    └─────────────┘      └──────────────┘
                                    中継 ──▶
```

### サービス構成

| サービス | 説明 | ネットワーク |
|----------|------|-------------|
| `db` | PostgreSQL 18 (Unix Domain Socket) | mail_network |
| `tailscale` | Tailscale VPNメッシュ | 独自 |
| `worker` | POP3メール処理ワーカー | mail_network |
| `smtp_relay` | SMTP中継サーバー (aiosmtpd) | Tailscale |
| `api` | FastAPI Web UI + REST API | Tailscale |
| `pgadmin` | pgAdmin 4 | Tailscale |
| `usage_notifier` | OpenAI使用量監視 | mail_network |

## セットアップ

### 1. 環境変数の設定

```bash
cp .env.example .env
nano .env
```

主要な設定:

| 変数名 | 必須 | デフォルト | 説明 |
|--------|------|-----------|------|
| `OPENAI_API_KEY` | Yes | - | OpenAI APIキー |
| `POSTGRES_PASSWORD` | Yes | changeme | DBパスワード |
| `DISCORD_WEBHOOK_URL` | No | - | Discord Webhook URL |
| `POLL_INTERVAL` | No | 60 | POP3ポーリング間隔(秒) |
| `OPENAI_MODEL` | No | gpt-4.1 | 使用するGPTモデル |
| `DEFAULT_GITEA_HOST` | No | - | デフォルトGiteaホスト |
| `DEFAULT_GITEA_TOKEN` | No | - | デフォルトGiteaトークン |
| `SMTP_RELAY_ENABLED` | No | false | SMTP中継の有効化 |
| `SMTP_RELAY_PORT` | No | 587 | SMTP中継ポート |
| `SMTP_RELAY_AUTH_USERNAME` | No | - | SMTP認証ユーザー名 |
| `SMTP_RELAY_AUTH_PASSWORD` | No | - | SMTP認証パスワード |
| `SMTP_RELAY_USE_STARTTLS` | No | false | STARTTLS使用 |

### 2. Tailscaleセットアップ

API、SMTP中継、pgAdminはTailscaleネットワーク経由でのみアクセス可能。

```bash
# 初回起動時にTailscaleコンテナの認証が必要
docker compose up tailscale
docker compose exec tailscale tailscale up

# IPアドレス確認
docker compose exec tailscale tailscale ip -4
# 例: 100.x.x.x
```

アクセス先:
- **Web UI**: `http://100.x.x.x:8000/`
- **SMTP中継**: `100.x.x.x:587`
- **pgAdmin**: `http://100.x.x.x:5050`
- **API ドキュメント**: `http://100.x.x.x:8000/api/docs`

### 3. Docker起動

```bash
docker compose up -d
```

### 4. 初期設定 (Web UI)

ブラウザで `http://100.x.x.x:8000/` にアクセスし、以下を順に設定:

1. **顧客管理** - 顧客を追加（Giteaリポジトリ、APIトークン、Discord Webhook）
2. **メールアドレス** - ホワイトリスト用メールアドレスを登録
3. **メールアカウント** - POP3アカウントを追加・有効化
4. **SMTP中継** - 転送先SMTPサーバーを設定（送信メール中継を使う場合）

## SMTP中継の使い方

メールクライアントの送信サーバー(SMTP)設定を以下に変更:

| 設定項目 | 値 |
|----------|-----|
| サーバー | TailscaleのIP (100.x.x.x) |
| ポート | 587 (デフォルト) |
| ユーザー名 | `SMTP_RELAY_AUTH_USERNAME`で設定した値 |
| パスワード | `SMTP_RELAY_AUTH_PASSWORD`で設定した値 |

メール送信の流れ:
1. メールクライアントがSMTP中継にメールを送信
2. システムが受取人のメールアドレスから顧客を特定
3. AI分析（要約・アクションアイテム抽出）
4. Giteaリポジトリにアーカイブ
5. 会話スレッドに紐づけ
6. Web UIの転送先SMTPサーバー設定に基づいて本来のSMTPサーバーに転送

## 会話スレッド

受信・送信メールは以下の優先順位で自動的にスレッドに紐づけられる:

1. **In-Reply-To** ヘッダ - 返信先メールのMessage-IDでマッチ
2. **References** ヘッダ - 参照チェーン内のMessage-IDでマッチ
3. **件名** フォールバック - Re:/Fwd:/返信:/転送: を除去した正規化件名 + 顧客IDでマッチ

Web UIの「会話スレッド」画面でタイムライン表示（受信=青、送信=緑）を確認できる。

## データベース構造

### テーブル一覧

| テーブル | 説明 |
|----------|------|
| `customers` | 顧客マスタ（名前、Gitea設定、Discord Webhook） |
| `email_addresses` | 顧客メールアドレス（ホワイトリスト） |
| `mail_accounts` | POP3アカウント設定 |
| `processed_emails` | 処理済みメール（重複排除、方向・スレッド紐づけ） |
| `conversation_threads` | 会話スレッド |
| `thread_emails` | スレッド内の個別メール（方向、ヘッダ情報、AI要約） |
| `smtp_relay_config` | 転送先SMTPサーバー設定 |
| `system_settings` | システム設定（タイムゾーン等） |

マイグレーション:
```bash
docker compose exec worker alembic upgrade head
```

## Web UI

| 画面 | パス | 機能 |
|------|------|------|
| ダッシュボード | `/` | 統計（顧客数、メール数、スレッド数）、最近の処理メール |
| 顧客管理 | `/customers` | 顧客CRUD、Gitea/Discord設定 |
| メールアドレス | `/email-addresses` | ホワイトリスト管理、顧客別フィルタ |
| メールアカウント | `/mail-accounts` | POP3アカウントCRUD、有効/無効切替 |
| 会話スレッド | `/threads` | スレッド一覧・詳細、タイムライン表示 |
| SMTP中継 | `/smtp-relay` | 転送先SMTPサーバーCRUD、ステータス表示 |
| 設定 | `/settings` | タイムゾーン、Giteaデフォルト設定 |

## 対応添付ファイル形式

| 形式 | 拡張子 | 備考 |
|------|--------|------|
| PDF | `.pdf` | テキスト抽出 + OCR (Tesseract 日本語/英語) |
| Word | `.docx` | python-docx |
| Excel | `.xlsx` | openpyxl (全シート) |
| CSV | `.csv` | 文字コード自動判定 |
| テキスト | `.txt`, `.log`, `.md`, `.json`, `.xml`, `.html` | 文字コード自動判定 |

制限: 1ファイル最大10,000文字、表形式最大500行、GPT送信は添付全体で最大8,000文字

## プロジェクト構造

```
mail-check-ai/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── 001_initial_migration.py
│       ├── 002_add_system_settings.py
│       ├── 003_add_smtp_relay_and_threads.py
│       └── 004_remove_draft_queue.py
├── volumes/
│   ├── postgres_data/
│   ├── postgres_socket/
│   ├── git_repos/
│   └── usage_state/
└── src/
    ├── config.py              # 環境変数設定
    ├── models.py              # SQLAlchemyモデル
    ├── database.py            # DB接続管理
    ├── worker.py              # POP3メール処理ワーカー
    ├── smtp_relay.py          # SMTP中継サーバー (aiosmtpd)
    ├── api.py                 # FastAPI REST API + Web UI
    ├── usage_notifier.py      # OpenAI使用量監視
    ├── templates/
    │   ├── base.html
    │   ├── dashboard.html
    │   ├── customers.html
    │   ├── email_addresses.html
    │   ├── mail_accounts.html
    │   ├── threads.html
    │   ├── thread_detail.html
    │   ├── smtp_relay.html
    │   └── settings.html
    └── utils/
        ├── git_handler.py     # Git操作・Giteaプッシュ
        ├── openai_client.py   # OpenAI API連携
        ├── pdf_parser.py      # PDF/添付ファイル解析
        └── thread_manager.py  # 会話スレッド管理
```

## GHCR デプロイ

GitHub Actionsでイメージを自動ビルド・GHCR公開:

```bash
# mainへのプッシュで自動ビルド
git push origin main

# タグプッシュでバージョニング
git tag v1.0.0 && git push origin v1.0.0
```

本番デプロイ:
```bash
# .envにGITHUB_REPOSITORYを設定
GITHUB_REPOSITORY=yourname/mail-check-ai

# パブリックイメージの場合
docker pull ghcr.io/yourname/mail-check-ai:latest
docker compose up -d

# プライベートイメージの場合
echo $GHCR_TOKEN | docker login ghcr.io -u $GITHUB_USERNAME --password-stdin
docker pull ghcr.io/$GITHUB_REPOSITORY:latest
docker compose up -d
```

## トラブルシューティング

```bash
# ログ確認
docker compose logs -f worker
docker compose logs -f api
docker compose logs -f smtp_relay

# TailscaleのIP確認
docker compose exec tailscale tailscale ip -4

# マイグレーション手動実行
docker compose exec worker alembic upgrade head

# DB接続確認 (Unix Domain Socket)
docker compose exec worker psql -h /var/run/postgresql -U mailuser -d mail_check
```

## セキュリティ設計

- **Unix Domain Socket**: PostgreSQLはネットワークポート非公開
- **Tailscale**: API・SMTP中継・pgAdminはVPNメッシュ内のみ公開
- **ホワイトリスト**: 登録済みアドレスのメールのみ処理
- **POP3非削除**: RETR後もサーバーからメールを削除しない（Message-IDで重複排除）

## ライセンス

MIT License
