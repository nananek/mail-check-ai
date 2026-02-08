#!/bin/bash
# GHCRから本番環境へデプロイ

set -e

echo "🚀 Mail Check AI - GHCR デプロイメント"
echo ""

# 環境変数チェック
if [ ! -f .env ]; then
    echo "❌ .env ファイルが見つかりません"
    echo "📝 .env.example をコピーして設定してください"
    exit 1
fi

source .env

if [ -z "$GITHUB_REPOSITORY" ]; then
    echo "❌ GITHUB_REPOSITORY が設定されていません"
    echo "📝 .env に GITHUB_REPOSITORY=owner/repo を追加してください"
    exit 1
fi

# GHCRログイン（プライベートイメージの場合のみ必要）
if [ -n "$GHCR_TOKEN" ]; then
    echo "🔐 プライベートイメージのためGHCRにログイン中..."
    echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GITHUB_USERNAME}" --password-stdin
else
    echo "ℹ️  GHCR_TOKEN未設定 - パブリックイメージとして処理します"
    echo "   プライベートイメージの場合は .env に GHCR_TOKEN を設定してください"
fi

# 最新イメージをプル
echo "📦 最新イメージをプル中: ghcr.io/${GITHUB_REPOSITORY}:latest"
docker pull ghcr.io/${GITHUB_REPOSITORY}:latest

# サービス起動
echo "🚀 本番環境を起動中..."
docker-compose -f docker-compose.prod.yml up -d

echo ""
echo "✅ デプロイ完了!"
echo ""
echo "📊 サービスステータス:"
docker-compose -f docker-compose.prod.yml ps

echo ""
echo "📝 ログ確認コマンド:"
echo "  docker-compose -f docker-compose.prod.yml logs -f worker"
echo "  docker-compose -f docker-compose.prod.yml logs -f api"
