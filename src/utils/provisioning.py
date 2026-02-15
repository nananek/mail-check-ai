import re
import logging
from typing import List
import requests
from src.config import settings

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"


def validate_slug(slug: str) -> str:
    """スラッグをバリデーションし正規化する

    英数字・ハイフン・アンダースコアのみ許可。

    Raises:
        RuntimeError: 不正な形式の場合
    """
    slug = slug.strip().lower()
    if not slug:
        raise RuntimeError("ローマ字名が空です")
    if not re.match(r'^[a-z0-9][a-z0-9_-]*$', slug):
        raise RuntimeError(f"ローマ字名 '{slug}' に使用できない文字が含まれています（英小文字・数字・ハイフン・アンダースコアのみ）")
    return slug


def _gitea_headers() -> dict:
    return {
        "Authorization": f"token {settings.DEFAULT_GITEA_TOKEN}",
        "Content-Type": "application/json",
    }


def _discord_headers() -> dict:
    return {
        "Authorization": f"Bot {settings.DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }


def preflight_check(slug: str) -> None:
    """Gitea・Discord両方で名前の重複がないか事前確認する

    問題がある場合はすべてまとめてRuntimeErrorで報告する。

    Raises:
        RuntimeError: 重複や設定不足がある場合
    """
    slug = validate_slug(slug)
    errors: List[str] = []

    # Giteaリポジトリの存在チェック
    if not settings.DEFAULT_GITEA_HOST or not settings.DEFAULT_GITEA_TOKEN:
        errors.append("DEFAULT_GITEA_HOST と DEFAULT_GITEA_TOKEN が必要です")
    else:
        try:
            # GET /api/v1/repos/{owner}/{repo} — 認証ユーザーのリポジトリを確認
            # まず認証ユーザー名を取得
            user_resp = requests.get(
                f"{settings.DEFAULT_GITEA_HOST.rstrip('/')}/api/v1/user",
                headers=_gitea_headers(),
                timeout=15,
            )
            if not user_resp.ok:
                errors.append(f"Giteaユーザー情報の取得に失敗: {user_resp.status_code}")
            else:
                username = user_resp.json()["login"]
                repo_resp = requests.get(
                    f"{settings.DEFAULT_GITEA_HOST.rstrip('/')}/api/v1/repos/{username}/{slug}",
                    headers=_gitea_headers(),
                    timeout=15,
                )
                if repo_resp.status_code == 200:
                    errors.append(f"Giteaリポジトリ '{slug}' は既に存在します")
                elif repo_resp.status_code != 404:
                    errors.append(f"Giteaリポジトリの確認に失敗: {repo_resp.status_code}")
        except requests.RequestException as e:
            errors.append(f"Gitea接続エラー: {e}")

    # Discordチャンネルの存在チェック
    if not settings.DISCORD_BOT_TOKEN or not settings.DISCORD_CATEGORY_ID:
        errors.append("DISCORD_BOT_TOKEN と DISCORD_CATEGORY_ID が必要です")
    else:
        try:
            cat_resp = requests.get(
                f"{DISCORD_API_BASE}/channels/{settings.DISCORD_CATEGORY_ID}",
                headers=_discord_headers(),
                timeout=15,
            )
            if not cat_resp.ok:
                errors.append(f"Discordカテゴリ情報の取得に失敗: {cat_resp.status_code}")
            else:
                guild_id = cat_resp.json()["guild_id"]
                # ギルド内の全チャンネルを取得してカテゴリ配下に同名がないか確認
                ch_list_resp = requests.get(
                    f"{DISCORD_API_BASE}/guilds/{guild_id}/channels",
                    headers=_discord_headers(),
                    timeout=15,
                )
                if not ch_list_resp.ok:
                    errors.append(f"Discordチャンネル一覧の取得に失敗: {ch_list_resp.status_code}")
                else:
                    for ch in ch_list_resp.json():
                        if (ch.get("parent_id") == settings.DISCORD_CATEGORY_ID
                                and ch.get("name") == slug):
                            errors.append(f"Discordチャンネル '{slug}' は既に存在します")
                            break
        except requests.RequestException as e:
            errors.append(f"Discord接続エラー: {e}")

    if errors:
        raise RuntimeError(" / ".join(errors))


def create_gitea_repo(slug: str, customer_name: str) -> str:
    """Giteaにプライベートリポジトリを作成し、clone URLを返す

    Args:
        slug: リポジトリ名（英数字・ハイフン）
        customer_name: 顧客表示名（descriptionに使用）

    Raises:
        RuntimeError: API呼び出し失敗時
    """
    repo_name = validate_slug(slug)

    api_url = f"{settings.DEFAULT_GITEA_HOST.rstrip('/')}/api/v1/user/repos"
    resp = requests.post(
        api_url,
        headers=_gitea_headers(),
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


def create_discord_channel_with_webhook(slug: str) -> str:
    """Discordの指定カテゴリにテキストチャンネルを作成し、Webhook URLを返す

    Args:
        slug: チャンネル名（英数字・ハイフン）

    Raises:
        RuntimeError: API呼び出し失敗時
    """
    channel_name = validate_slug(slug)
    headers = _discord_headers()

    # カテゴリチャンネルの情報を取得してguild_idを得る
    cat_resp = requests.get(
        f"{DISCORD_API_BASE}/channels/{settings.DISCORD_CATEGORY_ID}",
        headers=headers,
        timeout=15,
    )
    if not cat_resp.ok:
        raise RuntimeError(f"Discordカテゴリ情報の取得に失敗: {cat_resp.status_code} {cat_resp.text}")

    guild_id = cat_resp.json()["guild_id"]

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
