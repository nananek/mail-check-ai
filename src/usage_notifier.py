"""OpenAI使用量通知ワーカー"""
import time
import logging
import requests
from datetime import datetime
from pathlib import Path
from src.config import settings
from src.utils.openai_usage_monitor import OpenAIUsageMonitor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 状態ファイル（最後の通知額を記録）
STATE_FILE = Path("/tmp/openai_usage_state.txt")


class UsageNotifier:
    """OpenAI使用量を監視して通知するクラス"""
    
    def __init__(self):
        self.monitor = OpenAIUsageMonitor(settings.OPENAI_API_KEY)
        self.check_interval = 3600  # 1時間ごとにチェック
        self.notification_threshold = 1.0  # 1ドルごとに通知
        
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
            # 今月の使用量を取得
            usage_data = self.monitor.get_usage()
            current_usage = usage_data["total_usage"]
            
            logger.info(f"Current OpenAI usage: ${current_usage:.2f}")
            
            # 最後の通知額を取得
            last_notified = self.load_last_notified_amount()
            
            # 1ドル単位で通知すべきか判定
            current_threshold_count = int(current_usage / self.notification_threshold)
            last_threshold_count = int(last_notified / self.notification_threshold)
            
            if current_threshold_count > last_threshold_count:
                # 通知が必要
                message = (
                    f"OpenAI APIの使用量が **${current_usage:.2f}** に達しました。\n\n"
                    f"📊 今月の使用状況:\n"
                    f"- 開始日: {usage_data['start_date']}\n"
                    f"- 現在: ${current_usage:.2f}\n"
                    f"- 前回通知: ${last_notified:.2f}"
                )
                
                # サブスクリプション情報も取得
                try:
                    sub_info = self.monitor.get_subscription_info()
                    if sub_info.get("hard_limit_usd"):
                        message += f"\n- 上限: ${sub_info['hard_limit_usd']:.2f}"
                except:
                    pass
                
                self.send_discord_notification(message)
                self.save_last_notified_amount(current_usage)
                logger.info(f"Notification sent: ${last_notified:.2f} -> ${current_usage:.2f}")
            
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
