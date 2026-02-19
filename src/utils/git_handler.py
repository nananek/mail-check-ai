import os
import shutil
import hashlib
from pathlib import Path
from typing import List, Tuple
from datetime import datetime
from git import Repo, GitCommandError
from src.config import settings
import logging

logger = logging.getLogger(__name__)


class GitHandler:
    """Giteaリポジトリとの連携を管理するクラス"""
    
    def __init__(self, repo_url: str, gitea_token: str, customer_name: str):
        self.repo_url = repo_url
        self.gitea_token = gitea_token
        self.customer_name = customer_name
        self.local_path = Path(settings.GIT_REPOS_PATH) / customer_name.replace(" ", "_")
        
    def _get_authenticated_url(self) -> str:
        """認証トークンを含むURLを生成"""
        for scheme in ("https://", "http://"):
            if self.repo_url.startswith(scheme):
                rest = self.repo_url[len(scheme):]
                return f"{scheme}{self.gitea_token}@{rest}"
        return self.repo_url
    
    def sync_repository(self) -> Repo:
        """リポジトリを同期（clone または pull）"""
        auth_url = self._get_authenticated_url()
        
        if self.local_path.exists():
            logger.info(f"Pulling latest changes for {self.customer_name}")
            try:
                repo = Repo(self.local_path)
                origin = repo.remotes.origin
                origin.pull()
                return repo
            except GitCommandError as e:
                logger.warning(f"Pull failed, re-cloning: {e}")
                shutil.rmtree(self.local_path)
        
        logger.info(f"Cloning repository for {self.customer_name}")
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        repo = Repo.clone_from(auth_url, self.local_path)
        return repo
    
    def save_email_archive(
        self,
        message_id: str,
        email_content: str,
        attachments: List[Tuple[str, bytes]],
        subject: str,
        from_address: str,
        received_date: str,
        direction: str = "received"
    ) -> Tuple[str, str]:
        """
        メールと添付ファイルをリポジトリに保存

        Args:
            direction: "received" (受信) or "sent" (送信)

        Returns:
            (コミットハッシュ, アーカイブディレクトリの相対パス)
        """
        repo = self.sync_repository()

        # received_dateをパース
        try:
            # RFC 2822形式をパース
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(received_date)
        except:
            # パース失敗時は現在時刻を使用
            dt = datetime.utcnow()

        # アーカイブディレクトリ構造: archive/yyyy-mm-dd/hhmmss-{recv|sent}-subject-hash/
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H%M%S")

        # サブジェクトとメッセージIDからハッシュを生成
        hash_input = f"{subject}{message_id}".encode('utf-8')
        hash_suffix = hashlib.md5(hash_input).hexdigest()[:8]

        # サブジェクトをファイル名に使える形式に変換（最大30文字）
        safe_subject = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in subject)
        safe_subject = safe_subject.strip()[:30].replace(' ', '-')

        dir_prefix = "sent" if direction == "sent" else "recv"
        dir_name = f"{time_str}-{dir_prefix}-{safe_subject}-{hash_suffix}"
        archive_dir = self.local_path / "archive" / date_str / dir_name
        archive_dir.mkdir(parents=True, exist_ok=True)

        # メール本文を保存
        email_file = archive_dir / "email.txt"
        with open(email_file, "w", encoding="utf-8") as f:
            if direction == "sent":
                f.write(f"To: {from_address}\n")
            else:
                f.write(f"From: {from_address}\n")
            f.write(f"Subject: {subject}\n")
            f.write(f"Date: {received_date}\n")
            f.write(f"Message-ID: {message_id}\n")
            f.write("\n" + "="*80 + "\n\n")
            f.write(email_content)

        # 添付ファイルを保存
        for filename, content in attachments:
            attachment_path = archive_dir / filename
            with open(attachment_path, "wb") as f:
                f.write(content)

        # Git commit
        repo.index.add([str(archive_dir.relative_to(self.local_path))])

        if direction == "sent":
            commit_message = f"Add sent email: {subject}\n\nTo: {from_address}\nDate: {received_date}"
        else:
            commit_message = f"Add email: {subject}\n\nFrom: {from_address}\nDate: {received_date}"
        repo.config_writer().set_value("user", "name", settings.GIT_AUTHOR_NAME).release()
        repo.config_writer().set_value("user", "email", settings.GIT_AUTHOR_EMAIL).release()

        commit = repo.index.commit(commit_message)

        # Push to remote
        try:
            origin = repo.remotes.origin
            origin.push()
            logger.info(f"Successfully pushed email archive for {message_id}")
        except GitCommandError as e:
            logger.error(f"Failed to push to remote: {e}")
            raise

        # アーカイブディレクトリの相対パスを返す
        archive_relative_path = str(archive_dir.relative_to(self.local_path))
        return commit.hexsha, archive_relative_path
