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

### 2. Docker起動

```bash
docker-compose up -d
```

これにより以下のサービスが起動します：
- **db**: PostgreSQL 18
- **worker**: メール処理ワーカー
- **api**: REST API (port 8000)
- **pgadmin**: データベース管理UI (port 5050)

### 3. データベース初期化

マイグレーションは自動実行されますが、手動で確認する場合：

```bash
docker-compose exec worker alembic upgrade head
```

### 4. 初期データ投入

PostgreSQLに接続して顧客・メールアドレス・POP3アカウントを登録：

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

## 📡 API エンドポイント

### `GET /`
ヘルスチェック

### `GET /drafts?status=pending`
全顧客の下書き一覧取得

### `GET /drafts/{customer_id}?status=pending`
特定顧客の下書き取得

### `PATCH /drafts/{draft_id}/complete`
下書きを完了済みとしてマーク

### `PATCH /drafts/{draft_id}`
下書きステータス更新
```json
{
  "status": "sent"  // pending / sent / archived
}
```

### `DELETE /drafts/{draft_id}`
下書き削除

### `GET /customers`
顧客一覧取得

## 🔧 設定項目

### 環境変数

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `POLL_INTERVAL` | 60 | POP3ポーリング間隔（秒） |
| `OPENAI_MODEL` | gpt-4.1 | 使用するGPTモデル |
| `GIT_REPOS_PATH` | /tmp/git_repos | Gitリポジトリ保存先 |
| `DEBUG` | false | デバッグモード |

## 📁 プロジェクト構造

```
mail-check-ai/
├── docker-compose.yml          # Docker構成
├── Dockerfile                  # コンテナイメージ定義
├── requirements.txt            # Python依存パッケージ
├── alembic.ini                # Alembic設定
├── alembic/
│   ├── env.py                 # Alembic環境設定
│   └── versions/              # マイグレーションファイル
│       └── 001_initial_migration.py
└── src/
    ├── __init__.py
    ├── config.py              # 設定管理
    ├── models.py              # SQLAlchemyモデル
    ├── database.py            # DB接続管理
    ├── worker.py              # メール処理ワーカー
    ├── api.py                 # FastAPI REST API
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

### Workerが起動しない
```bash
docker-compose logs worker
```
マイグレーションエラーの場合：
```bash
docker-compose exec worker alembic upgrade head
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
- [ ] 管理画面UI（フロントエンド）
- [ ] マルチテナント対応
- [ ] S3へのバックアップ
- [ ] Prometheusメトリクス

## 📄 ライセンス

MIT License

## 🙏 サポート

問題が発生した場合は、以下をご確認ください：
1. Docker・Docker Composeのバージョン
2. エラーログ全文
3. 環境変数設定内容（機密情報を除く）

---

**Built with ❤️ using Python, FastAPI, PostgreSQL, and OpenAI GPT-4.1**
