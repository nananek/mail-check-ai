"""OpenAI API使用量監視モジュール"""
import requests
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from src.config import settings

logger = logging.getLogger(__name__)


class OpenAIUsageMonitor:
    """OpenAI API使用量を監視するクラス"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openai.com/v1"
        
    def get_usage(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        """
        使用量を取得
        
        Args:
            start_date: 開始日 (YYYY-MM-DD形式)
            end_date: 終了日 (YYYY-MM-DD形式)
            
        Returns:
            {
                "total_usage": float,  # 合計使用額（ドル）
                "daily_costs": [...]   # 日次コストリスト
            }
        """
        # デフォルトは今月の使用量
        if not start_date:
            start_date = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        if not end_date:
            end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # 使用量エンドポイント
        url = f"{self.base_url}/dashboard/billing/usage"
        params = {
            "start_date": start_date,
            "end_date": end_date
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # 合計使用額を計算（セント→ドル）
            total_cents = data.get("total_usage", 0)
            total_dollars = total_cents / 100.0
            
            logger.info(f"OpenAI usage from {start_date} to {end_date}: ${total_dollars:.2f}")
            
            return {
                "total_usage": total_dollars,
                "daily_costs": data.get("daily_costs", []),
                "start_date": start_date,
                "end_date": end_date
            }
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                logger.error("OpenAI API key is invalid")
            else:
                logger.error(f"Failed to get OpenAI usage: {e}")
            raise
        except Exception as e:
            logger.error(f"Error getting OpenAI usage: {e}")
            raise
    
    def get_subscription_info(self) -> Dict[str, Any]:
        """
        サブスクリプション情報を取得
        
        Returns:
            {
                "hard_limit_usd": float,  # ハードリミット（ドル）
                "soft_limit_usd": float,  # ソフトリミット（ドル）
            }
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        url = f"{self.base_url}/dashboard/billing/subscription"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            return {
                "hard_limit_usd": data.get("hard_limit_usd", 0),
                "soft_limit_usd": data.get("soft_limit_usd", 0),
                "system_hard_limit_usd": data.get("system_hard_limit_usd", 0),
            }
            
        except Exception as e:
            logger.error(f"Error getting OpenAI subscription info: {e}")
            raise
