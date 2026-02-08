# 🚀 Universal AI Mail Processor

複数のPOP3サーバーを監視し、**登録済み顧客のメールのみ**をAI解析してGitea・Discord・下書きAPIへ自動配信するシステムです。

## ✨ 主な機能

- 📬 **マルチPOP3監視**: 複数のメールアカウントを同時監視
- 🛡️ **ホワイトリスト方式**: 未登録アドレスからのメールは完全無視
- 🔄 **重複排除**: `Message-ID`による確実な重複防止
- 📦 **Git証跡管理**: 顧客別Giteaリポジトリへ自動コミット・プッシュ
- 🤖 **AI解析 (GPT-4.1)**: メール要約・Issue生成・返信案作成
- 🎯 **自動配信**: Discord通知、Gitea Issue起票、下書きキュー保存
- 📄 **PDF対応**: PyMuPDFによる添付PDF解析
- 🔐 **セキュア構成**: Unix Domain Socket（DB）+ Tailscale（外部アクセス）

## 🏗️ アーキテクチャ

```
┌─────────────┐
│  POP3       │
│  Servers    │
└──────┬──────┘
       │
       ▼
┌─────────────┐      ┌──────────────┐
│   Worker    │─────▶│  PostgreSQL  │
│  Container  │      │      18      │
└──────┬──────┘      └──────────────┘
       │
       ├─────▶ Gitea (Git Push)
       ├─────▶ Discord (Webhook)
       ├─────▶ OpenAI API (GPT-4.1)
       └─────▶ Draft Queue (DB)
       
┌─────────────┐
│    API      │─────▶ HTTP REST API
│  Container  │       (下書き管理)
└─────────────┘
```

## 📊 データベース構造

### テーブル一覧

#### `customers` - 顧客マスタ
| カラム | 型 | 説明 |
|--------|-----|------|
| id | Integer (PK) | 顧客ID |
| name | String(255) | 顧客名 (ユニーク) |
| repo_url | Text | GiteaリポジトリURL |
| gitea_token | String(255) | Gitea APIトークン |
| discord_webhook | Text | 顧客専用Webhook URL |
| created_at | DateTime | 作成日時 |

#### `email_addresses` - 顧客メールアドレス（ホワイトリスト）
| カラム | 型 | 説明 |
|--------|-----|------|
| email | String(255) (PK) | メールアドレス |
| customer_id | Integer (FK) | 顧客ID |
| created_at | DateTime | 登録日時 |

#### `mail_accounts` - POP3アカウント設定
| カラム | 型 | 説明 |
|--------|-----|------|
| id | Integer (PK) | アカウントID |
| host | String(255) | POP3ホスト |
| port | Integer | ポート番号 |
| username | String(255) | ユーザー名 |
| password | String(255) | パスワード |
| use_ssl | Boolean | SSL使用フラグ |
| enabled | Boolean | 有効/無効 |

#### `processed_emails` - 処理済みメールID（重複排除）
| カラム | 型 | 説明 |
|--------|-----|------|
| message_id | String(512) (PK) | Message-ID |
| customer_id | Integer (FK) | 顧客ID |
| from_address | String(255) | 送信元 |
| subject | Text | 件名 |
| processed_at | DateTime | 処理日時 |

#### `draft_queue` - 返信下書きキュー
| カラム | 型 | 説明 |
|--------|-----|------|
| id | Integer (PK) | 下書きID |
| customer_id | Integer (FK) | 顧客ID |
| message_id | String(512) | 元メールのMessage-ID |
| reply_draft | Text | AI生成の返信案 |
| summary | Text | メール要約 |
| issue_title | String(500) | Issueタイトル |
| issue_url | Text | IssueのURL |
| status | String(50) | pending/sent/archived |
| created_at | DateTime | 作成日時 |
| completed_at | DateTime | 完了日時 |

## 🚀 セットアップ

### 1. 環境変数の設定

```bash
cp .env.example .env
nano .env
```

必須設定項目：
- `OPENAI_API_KEY`: OpenAI APIキー
- `DISCORD_WEBHOOK_URL`: Discord Webhook URL (オプション)
- `POSTGRES_PASSWORD`: データベースパスワード

#### 2. Tailscaleのセットアップ（外部アクセス用）

このシステムはセキュリティのため、APIとpgAdminは`127.0.0.1`でのみリッスンします。
外部からアクセスするにはTailscaleを使用してください。

```bash
# Tailscaleのインストール（Ubuntu/Debian）
curl -fsSL https://tailscale.com/install.sh | sh

# Tailscaleの起動
sudo tailscale up

# TailscaleのIPアドレスを確認
tailscale ip -4
# 例: 100.x.x.x
```

これで、Tailscaleネットワーク内の他のデバイスから以下でアクセス可能：
- **Web UI**: `http://100.x.x.x:8000/` ← **推奨**
- REST API: `http://100.x.x.x:8000/api`
- API ドキュメント: `http://100.x.x.x:8000/docs`
- pgAdmin: `http://100.x.x.x:5050`

#### 3. Docker起動

#### 3. Docker起動

```bash
docker-compose up -d
```

これにより以下のサービスが起動します：
- **db**: PostgreSQL 18（Unix Domain Socket使用）
- **worker**: メール処理ワーカー
- **api**: REST API（127.0.0.1:8000でリッスン）
- *# 4. データベース初期化

マイグレーションは自動実行されますが、手動で確認する場合：

```bash
docker-compose exec worker alembic upgrade head
```

#### 5

### 4. 初期データ投入

**推奨: Web UIから登録**

Tailscale経由でWeb UIにアクセスして設定を行います：

```bash
# TailscaleのIPアドレス確認
docker compose exec tailscale tailscale ip -4

# ブラウザでアクセス
# http://100.x.x.x:8000/
```

Web UIから以下を順番に設定：
1. **顧客管理** → 顧客を追加（Giteaリポジトリ、APIトークン、Discord Webhook）
2. **メールアドレス管理** → ホワイトリスト用メールアドレスを追加
3. **POP3アカウント管理** → メールアカウントを追加・有効化

**SQL直接投入（上級者向け）**

PostgreSQLに接続して直接登録することも可能：

```sql
-- 顧客登録
INSERT INTO customers (name, repo_url, gitea_token, discord_webhook) 
VALUES (
    'Example Corp',
    'https://gitea.example.com/user/example-corp.git',
    'your-gitea-token-here',
    'https://discord.com/api/webhooks/...'
);

-- 顧客メールアドレス登録（ホワイトリスト）
INSERT INTO email_addresses (email, customer_id) 
VALUES ('customer@example.com', 1);

-- POP3アカウント登録
INSERT INTO mail_accounts (host, port, username, password, use_ssl, enabled) 
VALUES ('mail.example.com', 995, 'support@yourcompany.com', 'password', true, true);
```

## 🌐 Web UI（設定管理画面）

### アクセス方法

Web UIはTailscale経由でアクセスします：

```bash
# TailscaleのIPアドレスを確認
docker compose exec tailscale tailscale ip -4
# 例: 100.x.x.x
```

ブラウザで以下にアクセス：
```
http://100.x.x.x:8000/
```

### 利用可能な管理画面

#### 📊 ダッシュボード (`/`)
- 顧客数、登録メールアドレス数、アクティブアカウント数、保留中下書き数の統計表示
- 最近処理されたメール一覧
- 最新の保留中下書き一覧
- システム情報（ポーリング間隔など）

#### 👥 顧客管理 (`/customers`)
**できること：**
- 顧客の新規登録（顧客名、Giteaリポジトリ、APIトークン、Discord Webhook）
- 顧客情報の編集
- 顧客の削除（関連データも削除されます）

**画面情報：**
- 顧客ID、顧客名、リポジトリURL
- 登録メールアドレス数
- Discord Webhook設定状況
- 登録日時

#### 📧 メールアドレス管理 (`/email-addresses`)
**できること：**
- ホワイトリスト用メールアドレスの追加
- 顧客別フィルタリング
- メールアドレスの削除

**機能：**
- このリストに登録されたアドレスからのメール**のみ**が処理されます
- 未登録アドレスからのメールは自動的に無視されます

#### 📮 POP3アカウント管理 (`/mail-accounts`)
**できること：**
- POP3メールアカウントの追加（ホスト、ポート、認証情報、SSL設定）
- アカウント情報の編集
- アカウントの有効化/無効化
- アカウントの削除

**画面情報：**
- サーバー情報（ホスト、ポート）
- SSL/TLS使用状況
- アカウント状態（有効/無効）
- ワンクリックでアカウントの有効化/無効化切り替え

#### 📝 下書き管理 (`/drafts`)
**できること：**
- AI生成された返信下書きの閲覧
- 顧客別フィルタリング
- ステータス別フィルタリング（保留中/送信済み/アーカイブ）
- 下書きのステータス更新（送信完了マーク、アーカイブ化）
- 返信テキストのクリップボードへコピー
- 下書きの削除

**表示情報：**
- メール要約
- AI生成返信案
- 作成されたGitea Issueへのリンク
- Message-ID
- 作成日時

### UI機能一覧

| 機能 | 新規追加 | 編集 | 削除 | フィルタ | その他 |
|------|---------|------|------|---------|--------|
| 顧客管理 | ✅ | ✅ | ✅ | - | Discord Webhook設定 |
| メールアドレス | ✅ | - | ✅ | ✅ 顧客別 | ホワイトリスト管理 |
| POP3アカウント | ✅ | ✅ | ✅ | - | 有効化/無効化トグル |
| 下書き | - | - | ✅ | ✅ 顧客別・ステータス別 | ステータス更新、コピー |

### 技術スタック

- **フロントエンド**: Bootstrap 5.3.0 + Bootstrap Icons
- **テンプレートエンジン**: Jinja2
- **バックエンド**: FastAPI (HTMLResponse + Form handling)
- **AJAX**: Fetch API (Vanilla JavaScript)

## 📡 REST API エンドポイント

### ヘルスチェック

#### `GET /api/health`
サービス状態確認

**レスポンス例：**
```json
{
  "status": "ok",
  "service": "Mail Check AI API",
  "version": "1.0.0"
}
```

### 下書き管理

#### `GET /drafts?status=pending`
全顧客の下書き一覧取得

**クエリパラメータ：**
- `status`: フィルタするステータス（`pending` / `sent` / `archived`）

#### `GET /drafts/{customer_id}?status=pending`
特定顧客の下書き取得

#### `PATCH /drafts/{draft_id}/complete`
下書きを完了済みとしてマーク

**レスポンス例：**
```json
{
  "status": "success",
  "message": "Draft marked as sent"
}
```

#### `PATCH /drafts/{draft_id}`
下書きステータス更新

**リクエストボディ：**
```json
{
  "status": "sent"  // pending / sent / archived
}
```

#### `DELETE /drafts/{draft_id}`
下書き削除

#### `GET /api/drafts/{draft_id}/text`
下書きテキスト取得（コピー機能用）

### 顧客管理

#### `GET /customers`
顧客一覧取得

#### `GET /api/customers/{customer_id}`
顧客詳細取得

#### `DELETE /api/customers/{customer_id}`
顧客削除（関連データも削除）

### メールアドレス管理

#### `DELETE /api/email-addresses/{email}`
メールアドレス削除

### POP3アカウント管理

#### `GET /api/mail-accounts/{account_id}`
アカウント詳細取得

#### `PATCH /api/mail-accounts/{account_id}/toggle`
アカウント有効化/無効化

**リクエストボディ：**
```json
{
  "enabled": true
}
```

#### `DELETE /api/mail-accounts/{account_id}`
アカウント削除

## 🔧 設定項目

### 環境変数

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `POLL_INTERVAL` | 60 | POP3ポーリング間隔（秒） |
| `OPENAI_MODEL` | gpt-4.1 | 使用するGPTモデル |
| `GIT_REPOS_PATH` | /tmp/git_repos | Gitリポジトリ保存先 |
| `DEBUG` | false | デバッグモード |

### ネットワーク構成

- **データベース接続**: Unix Domain Socket（`/var/run/postgresql`）を使用
- **API/pgAdmin**: `127.0.0.1`でのみリッスン
- **外部アクセス**: Tailscale経由で安全にアクセス

### セキュリティ設計

1. **Unix Domain Socket**: PostgreSQLはネットワークポートを公開せず、ソケット通信のみ
2. **ローカルバインド**: APIとpgAdminは127.0.0.1に限定
3. **Tailscale**: 暗号化されたメッシュネットワークで外部アクセス
4. **ホワイトリスト**: 未登録メールアドレスは自動無視

## 📁 プロジェクト構造

```
mail-check-ai/
├── docker-compose.yml          # Docker構成（開発・本番）
├── docker-compose.prod.yml     # 本番環境用構成
├── Dockerfile                  # コンテナイメージ定義
├── requirements.txt            # Python依存パッケージ
├── alembic.ini                # Alembic設定
├── volumes/                   # データ永続化ディレクトリ
│   ├── postgres_data/         # PostgreSQLデータ
│   ├── postgres_socket/       # Unix Domain Socket
│   └── git_repos/             # Gitリポジトリキャッシュ
├── alembic/
│   ├── env.py                 # Alembic環境設定
│   └── versions/              # マイグレーションファイル
│       └── 001_initial_migration.py
├── src/
    ├── __init__.py
    ├── config.py              # 設定管理
    ├── models.py              # SQLAlchemyモデル
    ├── database.py            # DB接続管理
    ├── worker.py              # メール処理ワーカー
    ├── api.py                 # FastAPI REST API + Web UI
    ├── templates/             # Jinja2テンプレート
    │   ├── base.html          # ベーステンプレート
    │   ├── dashboard.html     # ダッシュボード
    │   ├── customers.html     # 顧客管理
    │   ├── email_addresses.html  # メールアドレス管理
    │   ├── mail_accounts.html    # POP3アカウント管理
    │   └── drafts.html        # 下書き管理
    └── utils/
        ├── git_handler.py     # Git操作
        ├── pdf_parser.py      # PDF解析
        └── openai_client.py   # OpenAI API連携
```

## 🔐 セキュリティ設計

### ホワイトリスト方式
- `email_addresses`テーブルに登録されたアドレス**のみ**を処理
- 未登録アドレスからのメールは`processed_emails`にマークして以降無視

### POP3削除ポリシー
- `RETR`後もサーバーから削除**しない**設計
- `Message-ID`ベースの重複排除により安全なステート管理

### 認証情報管理
- 環境変数による機密情報管理
- Giteaトークンはデータベース内で顧客ごとに管理

## 🛠️ トラブルシューティング

### Tailscaleで接続できない

```bash
# Tailscaleの状態確認
sudo tailscale status

# IPアドレスを確認
tailscale ip -4

# 再起動
sudo tailscale down
sudo tailscale up
```

他のデバイスからアクセス：
```bash
# Web UIヘルスチェック
curl http://100.x.x.x:8000/api/health

# Web UIはブラウザで
http://100.x.x.x:8000/

# API ドキュメント
http://100.x.x.x:8000/docs

# pgAdminはブラウザで
http://100.x.x.x:5050/
```

### Web UIにアクセスできない

```bash
# APIコンテナの状態確認
docker compose ps api

# APIログ確認
docker compose logs api

# jinja2がインストールされているか確認
docker compose exec api python -c "import jinja2; print(jinja2.__version__)"
```

jinja2がない場合：
```bash
# requirements.txtを確認
grep jinja2 requirements.txt

# イメージを再ビルド
docker compose build api
docker compose up -d api
```

### Workerが起動しない
```bash
docker compose logs worker
```
マイグレーションエラーの場合：
```bash
docker compose exec worker alembic upgrade head
```

### データベース接続エラー

Unix Domain Socketの確認：
```bash
# ソケットファイルの存在確認
ls -la ./volumes/postgres_socket/

# PostgreSQL接続テスト
docker compose exec worker psql -h /var/run/postgresql -U mailuser -d mail_check
```

### Git Push失敗
- Giteaトークンの権限を確認（Read/Write権限が必要）
- リポジトリURLが正しいか確認（`.git`で終わる必要あり）

### POP3接続エラー
- `mail_accounts`の設定を確認
- SSL/TLSポート（通常995）とプレーンテキストポート（通常110）を確認

### OpenAI APIエラー
- APIキーの有効性を確認
- レート制限に達していないか確認
- モデル名が正しいか確認（`gpt-4.1`）

## 📝 ログ確認

```bash
# Worker ログ
docker-compose logs -f worker

# API ログ
docker-compose logs -f api

# DB ログ
docker-compose logs -f db
```

## 🔄 アップデート

```bash
# コードを更新
git pull

# コンテナ再ビルド・再起動
docker-compose up -d --build

# マイグレーション実行
docker-compose exec worker alembic upgrade head
```

## 🎯 今後の拡張案

- [ ] IMAP対応
- [ ] メール送信機能（SMTP連携）
- [ ] Slackインテグレーション
- [x] ~~管理画面UI（フロントエンド）~~ ✅ Bootstrap Web UI実装済み
- [ ] マルチテナント対応
- [ ] S3へのバックアップ
- [ ] Prometheusメトリクス
- [ ] Web UIからの下書き編集機能
- [ ] メール処理履歴の詳細表示

## � GitHub Container Registry (GHCR) デプロイ

### GitHub Actions自動ビルド（トークン不要）

コードをGitHubにプッシュするだけで、**GitHub Actionsが自動的に**Dockerイメージをビルド・GHCRにプッシュします。

💡 **GitHub Actionsでのビルド・プッシュには設定不要** — `GITHUB_TOKEN`が自動提供されます

#### 1. リポジトリをGitHubにプッシュ

```bash
git push origin main
```

**GitHub Actionsが自動実行**され、以下のイメージタグが作成されます：
- `ghcr.io/yourname/mail-check-ai:latest` (mainブランチ)
- `ghcr.io/yourname/mail-check-ai:main` (ブランチ名)
- `ghcr.io/yourname/mail-check-ai:v1.0.0` (タグをプッシュした場合)
- `ghcr.io/yourname/mail-check-ai:main-a1b2c3d` (コミットSHA)

#### 2. イメージの公開設定

**デフォルトはプライベート**です。パブリックにする場合：

1. GitHub → リポジトリ → Packages
2. 該当イメージ → Package settings
3. "Change visibility" → **Public**

✅ **パブリックイメージなら本番環境でもトークン不要**

#### 3. 本番環境デプロイ（パブリックイメージの場合）

```bash
# .envにGITHUB_REPOSITORYのみ設定
GITHUB_REPOSITORY=yourname/mail-check-ai

# デプロイ（ログイン不要）
docker pull ghcr.io/yourname/mail-check-ai:latest
docker-compose -f docker-compose.prod.yml up -d
```

#### 4. 本番環境デプロイ（プライベートイメージの場合）

**Personal Access Token (PAT) の作成:**
1. GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
2. "Generate new token (classic)"
3. スコープ: `read:packages` を選択
4. トークンをコピー

**本番サーバーの.env設定:**


**本番サーバーの.env設定:**

```bash
GITHUB_REPOSITORY=yourname/mail-check-ai
GITHUB_USERNAME=yourname
GHCR_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**デプロイ実行:**

```bash
# デプロイスクリプトを使用
./deploy-ghcr.sh

# または手動で
echo $GHCR_TOKEN | docker login ghcr.io -u $GITHUB_USERNAME --password-stdin
docker pull ghcr.io/$GITHUB_REPOSITORY:latest
docker-compose -f docker-compose.prod.yml up -d
```

#### 5. マルチアーキテクチャサポート

GitHub Actionsは以下のプラットフォーム用にビルドします：
- `linux/amd64` (x86_64)
- `linux/arm64` (ARM/Apple Silicon)

### バージョン管理

```bash
# セマンティックバージョニング
git tag v1.0.0
git push origin v1.0.0

# 自動的に以下が作成されます:
# - ghcr.io/yourname/mail-check-ai:v1.0.0
# - ghcr.io/yourname/mail-check-ai:1.0
# - ghcr.io/yourname/mail-check-ai:1
```

## �📄 ライセンス

MIT License

## 🙏 サポート

問題が発生した場合は、以下をご確認ください：
1. Docker・Docker Composeのバージョン
2. エラーログ全文
3. 環境変数設定内容（機密情報を除く）

---

**Built with ❤️ using Python, FastAPI, PostgreSQL, and OpenAI GPT-4.1**
