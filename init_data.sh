#!/bin/bash
# 初期データ投入スクリプト（サンプル）

# 環境変数を読み込み
source .env

# PostgreSQLに接続して初期データを投入
docker-compose exec -T db psql -U ${POSTGRES_USER:-mailuser} -d ${POSTGRES_DB:-mail_check} << 'EOF'

-- サンプル顧客の登録
INSERT INTO customers (name, repo_url, gitea_token, discord_webhook) 
VALUES (
    'Example Corporation',
    'https://gitea.example.com/user/example-corp.git',
    'your-gitea-token-here',
    'https://discord.com/api/webhooks/your-webhook-url'
) ON CONFLICT DO NOTHING;

-- 顧客メールアドレスの登録（ホワイトリスト）
INSERT INTO email_addresses (email, customer_id) 
VALUES 
    ('customer@example.com', 1),
    ('support@example.com', 1)
ON CONFLICT DO NOTHING;

-- POP3アカウントの登録
INSERT INTO mail_accounts (host, port, username, password, use_ssl, enabled) 
VALUES (
    'mail.example.com',
    995,
    'support@yourcompany.com',
    'your-password-here',
    true,
    true
) ON CONFLICT DO NOTHING;

-- 登録確認
SELECT 'Customers:' as info;
SELECT id, name FROM customers;

SELECT 'Email Addresses:' as info;
SELECT email, customer_id FROM email_addresses;

SELECT 'Mail Accounts:' as info;
SELECT id, host, username, enabled FROM mail_accounts;

EOF

echo "✅ 初期データ投入完了"
