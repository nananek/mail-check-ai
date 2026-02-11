"""OpenAI使用量通知ワーカー"""
import time
import logging
import requests
import json
from datetime import datetime
from pathlib import Path
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 状態ファイル（最後の通知額を記録）
STATE_FILE = Path("/tmp/openai_usage_state.txt")
USAGE_LOG_FILE = Path("/tmp/openai_usage.jsonl")


class UsageNotifier:
    """OpenAI使用量を監視して通知するクラス"""
    
    def __init__(self):
        self.check_interval = 3600  # 1時間ごとにチェック
        self.notification_threshold = 1.0  # 1ドルごとに通知
        
    def get_total_usage(self) -> float:
        """使用量ログファイルから合計コストを計算"""
        if not USAGE_LOG_FILE.exists():
            return 0.0
        
        total_cost = 0.0
        try:
            with open(USAGE_LOG_FILE, 'r') as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        total_cost += entry.get('total_cost_usd', 0.0)
            return total_cost
        except Exception as e:
            logger.error(f"Failed to read usage log: {e}")
            return 0.0
    
    def get_usage_stats(self) -> dict:
        """使用量統計を取得"""
        if not USAGE_LOG_FILE.exists():
            return {
                "total_cost": 0.0,
                "total_tokens": 0,
                "call_count": 0,
                "first_call": None,
                "last_call": None
            }
        
        total_cost = 0.0
        total_tokens = 0
        call_count = 0
        first_call = None
        last_call = None
        
        try:
            with open(USAGE_LOG_FILE, 'r') as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        total_cost += entry.get('total_cost_usd', 0.0)
                        total_tokens += entry.get('total_tokens', 0)
                        call_count += 1
                        
                        timestamp = entry.get('timestamp')
                        if first_call is None:
                            first_call = timestamp
                        last_call = timestamp
            
            return {
                "total_cost": total_cost,
                "total_tokens": total_tokens,
                "call_count": call_count,
                "first_call": first_call,
                "last_call": last_call
            }
        except Exception as e:
            logger.error(f"Failed to read usage stats: {e}")
            return {
                "total_cost": 0.0,
                "total_tokens": 0,
                "call_count": 0,
                "first_call": None,
                "last_call": None
            }
        
    def load_last_notified_amount(self) -> float:
        """最後に通知した金額を読み込む"""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, 'r') as f:
                    return float(f.read().strip())
            except:
                return 0.0
        return 0.0
    
    def save_last_notified_amount(self, amount: float) -> None:
        """最後に通知した金額を保存"""
        with open(STATE_FILE, 'w') as f:
            f.write(str(amount))
    
    def send_discord_notification(self, message: str) -> None:
        """Discordへ通知"""
        webhook_url = settings.DISCORD_WEBHOOK_URL
        if not webhook_url:
            logger.warning("Discord webhook URL not configured")
            return
        
        try:
            payload = {
                "embeds": [{
                    "title": "💰 OpenAI使用量通知",
                    "description": message,
                    "color": 15844367,  # ゴールド
                    "timestamp": datetime.utcnow().isoformat()
                }]
            }
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Usage notification sent to Discord")
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")
    
    def check_and_notify(self) -> None:
        """使用量をチェックして必要なら通知"""
        try:
            # 使用量統計を取得
            stats = self.get_usage_stats()
            current_usage = stats["total_cost"]
            
            logger.info(f"Current OpenAI usage: ${current_usage:.4f} ({stats['call_count']} calls, {stats['total_tokens']} tokens)")
            
            # 最後の通知額を取得
            last_notified = self.load_last_notified_amount()
            
            # 1ドル単位で通知すべきか判定
            current_threshold_count = int(current_usage / self.notification_threshold)
            last_threshold_count = int(last_notified / self.notification_threshold)
            
            if current_threshold_count > last_threshold_count:
                # 通知が必要
                message = (
                    f"OpenAI APIの使用量が **${current_usage:.4f}** に達しました。\n\n"
                    f"📊 統計:\n"
                    f"- API呼び出し回数: {stats['call_count']}回\n"
                    f"- 合計トークン数: {stats['total_tokens']:,}トークン\n"
                    f"- 合計コスト: ${current_usage:.4f}\n"
                    f"- 前回通知: ${last_notified:.4f}"
                )
                
                if stats['first_call']:
                    message += f"\n- 初回呼び出し: {stats['first_call'][:19]}"
                if stats['last_call']:
                    message += f"\n- 最終呼び出し: {stats['last_call'][:19]}"
                
                self.send_discord_notification(message)
                self.save_last_notified_amount(current_usage)
                logger.info(f"Notification sent: ${last_notified:.4f} -> ${current_usage:.4f}")
            
        except Exception as e:
            logger.error(f"Error in check_and_notify: {e}")
    
    def run(self) -> None:
        """メインループ"""
        logger.info("OpenAI Usage Notifier started")
        logger.info(f"Check interval: {self.check_interval} seconds")
        logger.info(f"Notification threshold: ${self.notification_threshold}")
        
        while True:
            try:
                self.check_and_notify()
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
            
            logger.info(f"Sleeping for {self.check_interval} seconds...")
            time.sleep(self.check_interval)


if __name__ == "__main__":
    notifier = UsageNotifier()
    notifier.run()
