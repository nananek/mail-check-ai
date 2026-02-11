#!/usr/bin/env python3
"""OpenAI使用量をテスト"""
import sys
import json
from pathlib import Path

sys.path.insert(0, '/mnt/docker/mail-check-ai')

USAGE_LOG_FILE = Path("/tmp/openai_usage.jsonl")

print("=" * 80)
print("OpenAI使用量テスト（ローカル集計）")
print("=" * 80)

# 使用量ログファイルの存在確認
if not USAGE_LOG_FILE.exists():
    print(f"\n⚠️ 使用量ログファイルが見つかりません: {USAGE_LOG_FILE}")
    print("まだAPI呼び出しが行われていないようです。")
    print("\n次のステップ:")
    print("1. メールを処理してOpenAI APIを呼び出す")
    print("2. このスクリプトを再実行して使用量を確認")
    sys.exit(0)

# ログファイルから統計を集計
total_cost = 0.0
total_tokens = 0
call_count = 0
first_call = None
last_call = None

print(f"\n📊 使用量ログを読み込み中: {USAGE_LOG_FILE}")

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
    
    print("\n✅ 集計完了!")
    print(f"\n📈 統計情報:")
    print(f"   API呼び出し回数: {call_count}回")
    print(f"   合計トークン数: {total_tokens:,}トークン")
    print(f"   合計コスト: ${total_cost:.4f}")
    
    if first_call:
        print(f"   初回呼び出し: {first_call[:19]}")
    if last_call:
        print(f"   最終呼び出し: {last_call[:19]}")
    
    # 次の通知までの金額を計算
    notification_threshold = 1.0
    next_threshold = (int(total_cost / notification_threshold) + 1) * notification_threshold
    remaining = next_threshold - total_cost
    
    print(f"\n💰 通知情報:")
    print(f"   現在の金額: ${total_cost:.4f}")
    print(f"   次の通知: ${next_threshold:.2f}")
    print(f"   あと: ${remaining:.4f}")
    
    print("\n" + "=" * 80)
    print("✅ テスト完了")
    print("=" * 80)
    
except Exception as e:
    print(f"\n❌ エラー: {e}")
    import traceback
    traceback.print_exc()
