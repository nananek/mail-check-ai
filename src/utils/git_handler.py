import os
import shutil
from pathlib import Path
from typing import List, Tuple
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
        if self.repo_url.startswith("https://"):
            # https://gitea.example.com/user/repo.git -> https://token@gitea.example.com/user/repo.git
            parts = self.repo_url.replace("https://", "").split("/", 1)
            return f"https://{self.gitea_token}@{parts[0]}/{parts[1]}"
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
        received_date: str
    ) -> str:
        """
        メールと添付ファイルをリポジトリに保存
        
        Returns:
            コミットハッシュ
        """
        repo = self.sync_repository()
        
        # アーカイブディレクトリ構造: archive/YYYY-MM/message_id/
        date_path = received_date[:7]  # YYYY-MM
        archive_dir = self.local_path / "archive" / date_path / message_id.replace("<", "").replace(">", "").replace("/", "_")
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        # メール本文を保存
        email_file = archive_dir / "email.txt"
        with open(email_file, "w", encoding="utf-8") as f:
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
        
        return commit.hexsha
