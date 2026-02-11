# OpenAI使用量監視

OpenAI APIの使用量を定期的に照会し、1ドルごとにDiscordへ通知する機能です。

## 機能

- **定期的な使用量チェック**: 1時間ごとにOpenAI APIの使用量を照会
- **1ドルごとの通知**: 使用量が1ドル単位で増えるたびにDiscord通知
- **サブスクリプション情報**: 上限金額なども確認可能

## 使い方

### 1. テスト実行

使用量照会が正常に動作するか確認:

```bash
docker compose exec usage_notifier python /app/test_openai_usage.py
```

または、コンテナ外から:

```bash
python test_openai_usage.py
```

### 2. サービス起動

```bash
# 使用量監視サービスのみ起動
docker compose up -d usage_notifier

# すべてのサービスと一緒に起動
docker compose up -d
```

### 3. ログ確認

```bash
docker compose logs -f usage_notifier
```

## 設定

### 環境変数

- `OPENAI_API_KEY`: OpenAI APIキー（必須）
- `DISCORD_WEBHOOK_URL`: Discord Webhook URL（必須）

### チェック間隔の変更

[src/usage_notifier.py](src/usage_notifier.py)の`check_interval`を変更:

```python
self.check_interval = 3600  # 秒単位（デフォルト: 1時間）
```

### 通知しきい値の変更

1ドル以外のしきい値にしたい場合は、`notification_threshold`を変更:

```python
self.notification_threshold = 1.0  # ドル単位（デフォルト: $1）
```

## 通知例

Discord通知の内容:

```
💰 OpenAI使用量通知

OpenAI APIの使用量が $5.00 に達しました。

📊 今月の使用状況:
- 開始日: 2026-02-01
- 現在: $5.00
- 前回通知: $4.00
- 上限: $100.00
```

## トラブルシューティング

### API認証エラー

```
OpenAI API key is invalid
```

環境変数`OPENAI_API_KEY`が正しく設定されているか確認してください。

### 使用量情報が取得できない

OpenAI APIのダッシュボードにアクセスできるAPIキーを使用しているか確認してください。
プロジェクトAPIキーではなく、ユーザーAPIキーが必要な場合があります。

## 状態ファイル

最後に通知した金額は `/tmp/openai_usage_state.txt` に保存されます（コンテナ内では`/tmp`、ホストでは`volumes/usage_state/`にマウント）。
