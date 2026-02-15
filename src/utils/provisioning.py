import re
import logging
import requests
from src.config import settings

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"


def _slugify(name: str) -> str:
    """顧客名をリポジトリ名/チャンネル名に使える形式に変換"""
    # 空白・全角スペースをハイフンに
    slug = re.sub(r'[\s　]+', '-', name.strip())
    # 連続ハイフンを1つに
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-').lower()


def create_gitea_repo(customer_name: str) -> str:
    """Giteaにプライベートリポジトリを作成し、clone URLを返す

    Raises:
        RuntimeError: 設定不足またはAPI呼び出し失敗時
    """
    if not settings.DEFAULT_GITEA_HOST or not settings.DEFAULT_GITEA_TOKEN:
        raise RuntimeError("DEFAULT_GITEA_HOST と DEFAULT_GITEA_TOKEN が必要です")

    repo_name = _slugify(customer_name)
    if not repo_name:
        raise RuntimeError("リポジトリ名を生成できませんでした")

    api_url = f"{settings.DEFAULT_GITEA_HOST.rstrip('/')}/api/v1/user/repos"
    resp = requests.post(
        api_url,
        headers={
            "Authorization": f"token {settings.DEFAULT_GITEA_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "name": repo_name,
            "private": True,
            "auto_init": True,
            "description": f"Mail Check AI - {customer_name}",
        },
        timeout=30,
    )

    if resp.status_code == 409:
        raise RuntimeError(f"リポジトリ '{repo_name}' は既に存在します")
    if not resp.ok:
        raise RuntimeError(f"Giteaリポジトリ作成に失敗: {resp.status_code} {resp.text}")

    data = resp.json()
    clone_url = data.get("clone_url") or data.get("html_url", "") + ".git"
    logger.info(f"Giteaリポジトリを作成しました: {clone_url}")
    return clone_url


def create_discord_channel_with_webhook(customer_name: str) -> str:
    """Discordの指定カテゴリにテキストチャンネルを作成し、Webhook URLを返す

    Raises:
        RuntimeError: 設定不足またはAPI呼び出し失敗時
    """
    if not settings.DISCORD_BOT_TOKEN or not settings.DISCORD_CATEGORY_ID:
        raise RuntimeError("DISCORD_BOT_TOKEN と DISCORD_CATEGORY_ID が必要です")

    headers = {
        "Authorization": f"Bot {settings.DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }

    # カテゴリチャンネルの情報を取得してguild_idを得る
    cat_resp = requests.get(
        f"{DISCORD_API_BASE}/channels/{settings.DISCORD_CATEGORY_ID}",
        headers=headers,
        timeout=15,
    )
    if not cat_resp.ok:
        raise RuntimeError(f"Discordカテゴリ情報の取得に失敗: {cat_resp.status_code} {cat_resp.text}")

    guild_id = cat_resp.json()["guild_id"]
    channel_name = _slugify(customer_name)
    if not channel_name:
        raise RuntimeError("チャンネル名を生成できませんでした")

    # テキストチャンネルを作成
    ch_resp = requests.post(
        f"{DISCORD_API_BASE}/guilds/{guild_id}/channels",
        headers=headers,
        json={
            "name": channel_name,
            "type": 0,
            "parent_id": settings.DISCORD_CATEGORY_ID,
        },
        timeout=15,
    )
    if not ch_resp.ok:
        raise RuntimeError(f"Discordチャンネル作成に失敗: {ch_resp.status_code} {ch_resp.text}")

    channel_id = ch_resp.json()["id"]
    logger.info(f"Discordチャンネルを作成しました: {channel_name} (ID: {channel_id})")

    # Webhookを作成
    wh_resp = requests.post(
        f"{DISCORD_API_BASE}/channels/{channel_id}/webhooks",
        headers=headers,
        json={"name": "Mail Check AI"},
        timeout=15,
    )
    if not wh_resp.ok:
        raise RuntimeError(f"Discord Webhook作成に失敗: {wh_resp.status_code} {wh_resp.text}")

    wh_data = wh_resp.json()
    webhook_url = f"https://discord.com/api/webhooks/{wh_data['id']}/{wh_data['token']}"
    logger.info(f"Discord Webhookを作成しました: チャンネル {channel_name}")
    return webhook_url
