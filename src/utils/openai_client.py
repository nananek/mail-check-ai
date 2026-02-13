from openai import OpenAI
from typing import Dict, Any, Optional, List, Sequence
import json
import logging
from pathlib import Path
from datetime import datetime
from src.config import settings

logger = logging.getLogger(__name__)

# 使用量記録ファイル
USAGE_LOG_FILE = Path("/tmp/openai_usage.jsonl")


class OpenAIClient:
    """OpenAI APIとの通信を管理するクラス"""
    
    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL
    
    def analyze_email(
        self,
        email_body: str,
        subject: str,
        from_address: str,
        attachments_text: Dict[str, str],
        customer_name: str,
        thread_context: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        メールを解析してJSON形式の結果を返す

        Returns:
            {
                "summary": "メール要約",
                "topics": [{"title": "...", "body": "..."}]
            }
        """
        # コンテキスト構築
        context_parts = [
            f"顧客名: {customer_name}",
            f"送信者: {from_address}",
            f"件名: {subject}",
        ]

        # 会話履歴がある場合はコンテキストに追加
        if thread_context and len(thread_context) > 0:
            context_parts.append("\n--- 会話履歴 (最新のやり取り) ---")
            for i, tc in enumerate(thread_context):
                direction_label = "受信" if tc['direction'] == 'incoming' else "送信"
                context_parts.append(
                    f"\n[{direction_label} {i+1}] {tc['date']}\n"
                    f"From: {tc['from']} → To: {tc['to']}\n"
                    f"件名: {tc['subject']}\n"
                    f"要約: {tc['summary'] or '(なし)'}\n"
                    f"本文: {tc['body_preview'][:300]}..."
                )
            context_parts.append("\n--- 上記は過去のやり取りです。以下が今回のメールです。 ---")

        context_parts.append(f"\n--- メール本文 ---\n{email_body}")

        # 添付ファイルの内容を追加
        if attachments_text:
            context_parts.append("\n--- 添付ファイル ---")
            for filename, content in attachments_text.items():
                ext = filename.split('.')[-1].upper() if '.' in filename else 'FILE'
                context_parts.append(f"\n▼ {filename} ({ext}形式)")
                if content and not content.startswith('['):
                    if len(content) > 8000:
                        context_parts.append(content[:8000] + "\n[... 以降省略 ...]")
                    else:
                        context_parts.append(content)
                else:
                    context_parts.append(content)

        full_context = "\n".join(context_parts)
        
        # プロンプト
        system_prompt = """あなたは顧客サポートAIアシスタントです。
受信したメールを解析し、以下の情報をJSON形式で返してください。

メールには本文に加えて、PDF、Word、Excel、CSVなどの添付ファイルが含まれることがあります。
添付ファイルの内容も必ず確認し、重要な情報（数値、表、データなど）を要約に含めてください。

【重要】メールに複数のトピック（質問、依頼、報告など）が含まれる場合は、それぞれを個別のトピックとして分けてください。

返すJSON形式:
{
  "summary": "メール全体と添付ファイルの内容を含む簡潔な要約（2-4文）",
  "topics": [
    {
      "title": "トピックのタイトル（50文字以内、添付ファイルの内容も反映）",
      "body": "トピックの詳細（Markdown形式、詳細な内容と次のアクション、添付ファイルの重要データも記載）"
    }
  ]
}

注：
- 単一のトピックしかない場合でも、topics配列に1つの要素として含めてください
- 複数トピックがある場合は、それぞれを個別の要素として分けてください（例：質問3つ→3つのトピック）
- 各トピックのbodyには、そのトピック特有の詳細情報とアクションアイテムを記載してください
- 添付ファイルに表やデータが含まれる場合、重要な数値や項目を具体的に言及してください
- 必ずJSON形式のみを返してください。他の説明は不要です。

【会話履歴がある場合】
- 過去のやり取りの文脈を踏まえて、メールを解析してください
- 過去に言及された内容やアクションアイテムがある場合、進捗をフォローしてください"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_context}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content
            result = json.loads(result_text)
            
            # 使用量を記録
            self._log_usage(response, from_address)
            
            logger.info(f"Successfully analyzed email from {from_address}")
            return result
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response as JSON: {e}")
            raise
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
    
    def analyze_outgoing_email(
        self,
        email_body: str,
        subject: str,
        to_address: str,
        attachments_text: Dict[str, str],
        customer_name: str,
        thread_context: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """送信メールを解析してJSON形式の結果を返す（返信ドラフト不要）"""
        context_parts = [
            f"顧客名: {customer_name}",
            f"宛先: {to_address}",
            f"件名: {subject}",
        ]

        if thread_context and len(thread_context) > 0:
            context_parts.append("\n--- 会話履歴 ---")
            for i, tc in enumerate(thread_context):
                direction_label = "受信" if tc['direction'] == 'incoming' else "送信"
                context_parts.append(
                    f"\n[{direction_label} {i+1}] {tc['date']}\n"
                    f"From: {tc['from']} → To: {tc['to']}\n"
                    f"要約: {tc['summary'] or '(なし)'}\n"
                    f"本文: {tc['body_preview'][:300]}..."
                )

        context_parts.append(f"\n--- 送信メール本文 ---\n{email_body}")

        if attachments_text:
            context_parts.append("\n--- 添付ファイル ---")
            for filename, content in attachments_text.items():
                ext = filename.split('.')[-1].upper() if '.' in filename else 'FILE'
                context_parts.append(f"\n▼ {filename} ({ext}形式)")
                if len(content) > 4000:
                    context_parts.append(content[:4000] + "\n[... 以降省略 ...]")
                else:
                    context_parts.append(content)

        full_context = "\n".join(context_parts)

        system_prompt = """あなたはメール業務管理AIです。
送信されたメール（こちらから顧客へ送ったメール）を解析し、以下の情報をJSON形式で返してください。

返すJSON形式:
{
  "summary": "送信内容の簡潔な要約（2-3文）",
  "action_items": ["約束したアクション1", "約束したアクション2"],
  "topics_discussed": ["議題1", "議題2"],
  "follow_up_needed": true または false,
  "follow_up_note": "フォローアップが必要な場合の詳細"
}

注：
- 送信メールなので返信案は不要です
- 顧客に対して何を伝えたか、何を約束したかを正確に記録してください
- 会話履歴がある場合は、文脈を踏まえて分析してください
- 必ずJSON形式のみを返してください"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_context}
                ],
                temperature=0.5,
                response_format={"type": "json_object"}
            )

            result_text = response.choices[0].message.content
            result = json.loads(result_text)
            self._log_usage(response, f"outgoing:{to_address}")
            logger.info(f"Successfully analyzed outgoing email to {to_address}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response as JSON: {e}")
            raise
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

    def _log_usage(self, response, context: str = "") -> None:
        """API使用量を記録"""
        try:
            usage = response.usage
            if not usage:
                return
            
            # モデルごとの料金（$/1M tokens）
            pricing = {
                "gpt-4o": {"input": 2.50, "output": 10.00},
                "gpt-4o-mini": {"input": 0.150, "output": 0.600},
                "gpt-4": {"input": 30.00, "output": 60.00},
                "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
            }
            
            model = self.model
            if model not in pricing:
                # デフォルト料金（gpt-4o）
                model_pricing = pricing["gpt-4o"]
            else:
                model_pricing = pricing[model]
            
            # コスト計算
            input_cost = (usage.prompt_tokens / 1_000_000) * model_pricing["input"]
            output_cost = (usage.completion_tokens / 1_000_000) * model_pricing["output"]
            total_cost = input_cost + output_cost
            
            # 使用量ログを記録
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "model": self.model,
                "context": context,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "input_cost_usd": round(input_cost, 6),
                "output_cost_usd": round(output_cost, 6),
                "total_cost_usd": round(total_cost, 6)
            }
            
            # JSONLファイルに追記
            with open(USAGE_LOG_FILE, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
            
            logger.debug(f"Logged usage: {usage.total_tokens} tokens, ${total_cost:.6f}")
            
        except Exception as e:
            logger.warning(f"Failed to log API usage: {e}")
