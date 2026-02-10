from openai import OpenAI
from typing import Dict, Any
import json
import logging
from src.config import settings

logger = logging.getLogger(__name__)


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
        salutation: Optional[str] = None,
        greeting_template: str = 'いつもお世話になっております。',
        signature_template: str = ''
    ) -> Dict[str, Any]:
        """
        メールを解析してJSON形式の結果を返す
        
        Args:
            email_body: メール本文
            subject: 件名
            from_address: 送信者アドレス
            attachments_text: 添付ファイルのテキスト
            customer_name: 顧客名
            salutation: 標準の宛名（例: 株式会社ABC 伊呂波社長様）
            greeting_template: 書き出し文（例: いつもお世話になっております。ほげの会計 ほげのでございます。）
            signature_template: 標準の署名
        
        Returns:
            {
                "summary": "メール要約",
                "issue_title": "Issueタイトル",
                "issue_body": "Issue本文（Markdown）",
                "reply_draft": "返信案"
            }
        """
        # コンテキスト構築
        context_parts = [
            f"顧客名: {customer_name}",
            f"送信者: {from_address}",
            f"件名: {subject}",
            f"\n--- メール本文 ---\n{email_body}"
        ]
        
        # 添付ファイルの内容を追加
        if attachments_text:
            context_parts.append("\n--- 添付ファイル ---")
            for filename, content in attachments_text.items():
                # ファイル拡張子を取得
                ext = filename.split('.')[-1].upper() if '.' in filename else 'FILE'
                context_parts.append(f"\n▼ {filename} ({ext}形式)")
                
                # 内容が空でない場合のみ追加
                if content and not content.startswith('['):
                    # 長すぎる場合は先頭のみ（既に切り詰められている場合が多い）
                    if len(content) > 8000:
                        context_parts.append(content[:8000] + "\n[... 以降省略 ...]")
                    else:
                        context_parts.append(content)
                else:
                    # エラーメッセージやメタ情報の場合
                    context_parts.append(content)
        
        # 返信テンプレート情報を追加
        context_parts.append("\n--- 返信フォーマット情報 ---")
        context_parts.append(f"書き出し文: {greeting_template}")
        if salutation:
            context_parts.append(f"標準の宛名: {salutation}")
        else:
            context_parts.append("標準の宛名: 設定なし（メール本文から判断）")
        if signature_template:
            context_parts.append(f"署名:\n{signature_template}")
        
        full_context = "\n".join(context_parts)
        
        # プロンプト
        system_prompt = """あなたは顧客サポートAIアシスタントです。
受信したメールを解析し、以下の情報をJSON形式で返してください。

メールには本文に加えて、PDF、Word、Excel、CSVなどの添付ファイルが含まれることがあります。
添付ファイルの内容も必ず確認し、重要な情報（数値、表、データなど）を要約と返信に含めてください。

返すJSON形式:
{
  "summary": "メール本文と添付ファイルの内容を含む簡潔な要約（2-4文）",
  "issue_title": "このメールに基づくIssueのタイトル（50文字以内、添付ファイルの内容も反映）",
  "issue_body": "Issue本文（Markdown形式、詳細な内容と次のアクション、添付ファイルの重要データも記載）",
  "reply_draft": "顧客への返信案（丁寧で具体的、添付ファイルの内容を確認したことを示す）"
}

【重要】返信案（reply_draft）の作成ルール:
1. 必ず「書き出し文」から開始してください（書き出し文が複数行の場合はそのまま使用）
2. 書き出し文の後は必ず1行空けてください
3. 宛名:
   - 「標準の宛名」が設定されている場合: その宛名を使用（例: 株式会社ABC 伊呂波社長様）
   - 「標準の宛名」が未設定の場合: メール本文や署名から送信者の役職・名前を推測して適切な宛名を付ける（「ご担当者様」は避ける）
4. 宛名の後は1行空けてから返信本文を記載
5. 「署名」が設定されている場合は、最後に署名を追加

フォーマット例:
```
いつもお世話になっております。
ほげの会計 ほげのでございます。

株式会社ABC 伊呂波社長様

（返信本文）

----------------
株式会社DEF
営業部 山田太郎
```

その他の重要事項:
- 添付ファイルに表やデータが含まれる場合、重要な数値や項目を具体的に言及してください
- 添付ファイルが解析できなかった場合は、その旨を返信案に含めてください
- 必ずJSON形式のみを返してください。他の説明は不要です。"""
        
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
            
            logger.info(f"Successfully analyzed email from {from_address}")
            return result
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response as JSON: {e}")
            raise
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
