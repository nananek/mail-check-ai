#!/usr/bin/env python3
"""OpenAI使用量をテスト"""
import sys
sys.path.insert(0, '/mnt/docker/mail-check-ai')

from src.utils.openai_usage_monitor import OpenAIUsageMonitor
from src.config import settings

monitor = OpenAIUsageMonitor(settings.OPENAI_API_KEY)

print("=" * 80)
print("OpenAI使用量照会テスト")
print("=" * 80)

try:
    # 今月の使用量を取得
    print("\n📊 今月の使用量を取得中...")
    usage = monitor.get_usage()
    print(f"✅ 成功!")
    print(f"   期間: {usage['start_date']} 〜 {usage['end_date']}")
    print(f"   合計: ${usage['total_usage']:.2f}")
    
    # サブスクリプション情報を取得
    print("\n💳 サブスクリプション情報を取得中...")
    sub_info = monitor.get_subscription_info()
    print(f"✅ 成功!")
    print(f"   ハードリミット: ${sub_info.get('hard_limit_usd', 0):.2f}")
    print(f"   ソフトリミット: ${sub_info.get('soft_limit_usd', 0):.2f}")
    
    print("\n" + "=" * 80)
    print("✅ すべてのテストが成功しました！")
    print("=" * 80)
    
except Exception as e:
    print(f"\n❌ エラー: {e}")
    import traceback
    traceback.print_exc()
