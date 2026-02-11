# OpenAI使用量監視

OpenAI APIの使用量を自動的に記録し、1ドルごとにDiscordへ通知する機能です。

## 仕組み

1. **自動記録**: 各OpenAI API呼び出しで使用したトークン数とコストを記録
2. **ローカル集計**: ログファイルから合計コストを計算
3. **定期チェック**: 1時間ごとに使用量を確認
4. **1ドルごとの通知**: 累積金額が1ドル単位で増えるたびにDiscord通知

> **注**: OpenAIのUser API Keyが廃止されたため、課金APIにアクセスできません。代わりに各API呼び出しのトークン使用量から自動でコストを計算します。

## 料金計算

現在サポートしているモデルの料金（$/1M tokens）:

| モデル | 入力 | 出力 |
|--------|------|------|
| gpt-4o | $2.50 | $10.00 |
| gpt-4o-mini | $0.150 | $0.600 |
| gpt-4 | $30.00 | $60.00 |
| gpt-3.5-turbo | $0.50 | $1.50 |

## 使い方

### 1. テスト実行

現在の使用量を確認:

```bash
# ホストから実行
python test_openai_usage.py

# またはコンテナ内から
docker compose exec worker python /app/test_openai_usage.py
```

出力例:
```
================================================================================
OpenAI使用量テスト（ローカル集計）
================================================================================

📊 使用量ログを読み込み中: /tmp/openai_usage.jsonl

✅ 集計完了!

📈 統計情報:
   API呼び出し回数: 42回
   合計トークン数: 125,432トークン
   合計コスト: $3.2145
   初回呼び出し: 2026-02-11 10:00:00
   最終呼び出し: 2026-02-11 15:30:00

💰 通知情報:
   現在の金額: $3.2145
   次の通知: $4.00
   あと: $0.7855
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

OpenAI APIの使用量が $5.1234 に達しました。

📊 統計:
- API呼び出し回数: 89回
- 合計トークン数: 234,567トークン
- 合計コスト: $5.1234
- 前回通知: $4.0000
- 初回呼び出し: 2026-02-01 09:15:30
- 最終呼び出し: 2026-02-11 16:45:22
```

## ファイル

- **使用量ログ**: `/tmp/openai_usage.jsonl` (コンテナ内) / `volumes/usage_state/openai_usage.jsonl` (ホスト)
  - 各API呼び出しの詳細を記録
  - JSONL形式（1行1レコード）
  
- **通知状態**: `/tmp/openai_usage_state.txt`
  - 最後に通知した金額を記録

## トラブルシューティング

### 使用量が記録されない

1. workerコンテナが正常に動作しているか確認
2. メールが処理されてOpenAI APIが呼び出されているか確認
3. ログファイルの権限を確認

```bash
# 使用量ログの確認
docker compose exec worker ls -la /tmp/openai_usage.jsonl
docker compose exec worker cat /tmp/openai_usage.jsonl | tail -5
```

### 通知が来ない

1. Discord Webhook URLが正しく設定されているか確認
2. usage_notifierサービスが起動しているか確認
3. ログでエラーを確認

```bash
docker compose ps usage_notifier
docker compose logs usage_notifier
```

### 使用量のリセット

ログファイルを削除すると使用量がリセットされます:

```bash
docker compose exec worker rm /tmp/openai_usage.jsonl
docker compose exec usage_notifier rm /tmp/openai_usage_state.txt
```
