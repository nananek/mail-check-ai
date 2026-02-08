from fastapi import FastAPI, HTTPException, Depends, Request, Form, Path, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
import os
import pytz

from src.database import get_db
from src.models import DraftQueue, Customer, EmailAddress, MailAccount, ProcessedEmail, SystemSetting
from src.config import settings

app = FastAPI(
    title="Mail Check AI API",
    description="""
## Mail Check AI - メール自動処理システム

顧客からのメールを自動的に処理し、AIで解析してGitea Issueを作成、返信下書きを生成するシステムです。

### 主な機能
- 📧 **メール自動受信**: POP3でメールを取得
- 🤖 **AI解析**: OpenAIで内容を分析
- 📝 **下書き生成**: 返信文を自動生成
- 🎫 **Issue作成**: Gitea Issueを自動作成
- 📂 **Gitアーカイブ**: メールと添付ファイルをGitリポジトリに保存
- 💬 **Discord通知**: 処理結果をDiscordに通知

### 技術スタック
- FastAPI + SQLAlchemy + PostgreSQL
- OpenAI GPT-4
- Gitea API + GitPython
- Docker + Docker Compose
    """,
    version="1.0.0",
    contact={
        "name": "Mail Check AI Support",
        "url": "https://github.com/yourusername/mail-check-ai",
    },
    license_info={
        "name": "MIT",
    },
)

# Templates setup
templates = Jinja2Templates(directory="src/templates")

# Add timezone filter to Jinja2
def get_system_timezone(db: Session) -> str:
    """システム設定からタイムゾーンを取得"""
    tz_setting = db.query(SystemSetting).filter_by(key='timezone').first()
    return tz_setting.value if tz_setting and tz_setting.value else 'Asia/Tokyo'

def format_datetime_tz(dt, tz_name='Asia/Tokyo'):
    """Datetimeをタイムゾーンでフォーマット"""
    if dt is None:
        return ''
    if dt.tzinfo is None:
        # Assume UTC if naive
        dt = pytz.utc.localize(dt)
    tz = pytz.timezone(tz_name)
    return dt.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')

templates.env.filters['datetime_tz'] = format_datetime_tz

# Static files (if needed later)
if os.path.exists("src/static"):
    app.mount("/static", StaticFiles(directory="src/static"), name="static")


# ========== Pydantic Schemas ==========

class DraftResponse(BaseModel):
    """下書き応答モデル"""
    id: int = Field(..., description="下書きID", example=1)
    customer_id: int = Field(..., description="顧客ID", example=1)
    customer_name: str = Field(..., description="顧客名", example="株式会社サンプル")
    message_id: str = Field(..., description="元メールのMessage-ID", example="<abc123@example.com>")
    reply_draft: str = Field(..., description="返信下書き本文", example="お世話になっております。...")
    summary: str = Field(..., description="メール要約", example="見積もり依頼の件")
    issue_title: Optional[str] = Field(None, description="作成されたIssueのタイトル", example="見積もり依頼: ABC案件")
    issue_url: Optional[str] = Field(None, description="作成されたIssueのURL", example="https://gitea.example.com/owner/repo/issues/123")
    status: str = Field(..., description="ステータス (pending/sent/archived)", example="pending")
    created_at: datetime = Field(..., description="作成日時", example="2026-02-08T10:30:00")
    
    class Config:
        from_attributes = True


class DraftUpdate(BaseModel):
    """下書き更新リクエスト"""
    status: str = Field(..., description="更新するステータス (pending/sent/archived)", example="sent")


class CustomerResponse(BaseModel):
    """顧客情報応答モデル"""
    id: int = Field(..., description="顧客ID", example=1)
    name: str = Field(..., description="顧客名", example="株式会社サンプル")
    email_count: int = Field(..., description="登録メールアドレス数", example=3)
    created_at: datetime = Field(..., description="登録日時", example="2026-01-15T09:00:00")


class CustomerDetailResponse(BaseModel):
    """顧客詳細応答モデル"""
    id: int = Field(..., description="顧客ID", example=1)
    name: str = Field(..., description="顧客名", example="株式会社サンプル")
    repo_url: str = Field(..., description="GiteaリポジトリURL", example="https://gitea.example.com/owner/repo.git")
    discord_webhook: Optional[str] = Field(None, description="Discord Webhook URL")
    created_at: datetime = Field(..., description="登録日時", example="2026-01-15T09:00:00")


class MailAccountResponse(BaseModel):
    """メールアカウント応答モデル"""
    id: int = Field(..., description="アカウントID", example=1)
    host: str = Field(..., description="POP3サーバーホスト", example="pop.example.com")
    port: int = Field(..., description="POP3ポート番号", example=995)
    username: str = Field(..., description="ユーザー名", example="user@example.com")
    use_ssl: bool = Field(..., description="SSL/TLS使用フラグ", example=True)
    enabled: bool = Field(..., description="有効/無効フラグ", example=True)
    created_at: datetime = Field(..., description="登録日時", example="2026-01-15T09:00:00")


class HealthResponse(BaseModel):
    """ヘルスチェック応答"""
    status: str = Field(..., description="ステータス", example="ok")
    service: str = Field(..., description="サービス名", example="Mail Check AI API")
    version: str = Field(..., description="バージョン", example="1.0.0")


# ========== Web UI Routes ==========

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """ダッシュボード"""
    tz = get_system_timezone(db)
    
    stats = {
        "customer_count": db.query(Customer).count(),
        "email_count": db.query(EmailAddress).count(),
        "active_accounts": db.query(MailAccount).filter_by(enabled=True).count(),
        "pending_drafts": db.query(DraftQueue).filter_by(status="pending").count(),
        "poll_interval": os.getenv("POLL_INTERVAL", "60")
    }
    
    recent_emails = db.query(ProcessedEmail).order_by(
        ProcessedEmail.processed_at.desc()
    ).limit(5).all()
    
    recent_drafts = db.query(DraftQueue).filter_by(status="pending").order_by(
        DraftQueue.created_at.desc()
    ).limit(5).all()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "recent_emails": recent_emails,
        "recent_drafts": recent_drafts,
        "timezone": tz
    })


# ========== REST API Endpoints ==========

@app.get(
    "/api/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="ヘルスチェック",
    description="APIサーバーの稼働状態を確認します。"
)
def health_check():
    """
    ## ヘルスチェックエンドポイント
    
    APIサーバーが正常に稼働しているかを確認するためのエンドポイントです。
    
    ### レスポンス
    - `status`: 常に "ok" を返します
    - `service`: サービス名
    - `version`: APIバージョン
    """
    return {
        "status": "ok",
        "service": "Mail Check AI API",
        "version": "1.0.0"
    }


@app.get(
    "/api/drafts/{customer_id}",
    response_model=List[DraftResponse],
    tags=["Drafts"],
    summary="顧客の下書き一覧を取得",
    description="指定した顧客IDに紐づく返信下書き一覧を取得します。"
)
def get_customer_drafts(
    customer_id: int = Path(..., description="顧客ID", example=1),
    status: str = Query("pending", description="フィルタするステータス (pending/sent/archived)", example="pending"),
    db: Session = Depends(get_db)
):
    """
    ## 顧客別下書き一覧取得
    
    特定の顧客に関連する返信下書きをステータス別に取得します。
    
    ### パラメータ
    - `customer_id`: 顧客ID（必須）
    - `status`: フィルタするステータス（オプション、デフォルト: pending）
      - `pending`: 未送信
      - `sent`: 送信済み
      - `archived`: アーカイブ済み
    
    ### レスポンス
    下書き情報の配列を返します。各下書きには以下が含まれます：
    - AI生成の返信下書き本文
    - メール要約
    - 作成されたGitea Issue情報
    """
    customer = db.query(Customer).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    drafts = db.query(DraftQueue).filter_by(
        customer_id=customer_id,
        status=status
    ).order_by(DraftQueue.created_at.desc()).all()
    
    result = []
    for draft in drafts:
        result.append(DraftResponse(
            id=draft.id,
            customer_id=draft.customer_id,
            customer_name=customer.name,
            message_id=draft.message_id,
            reply_draft=draft.reply_draft,
            summary=draft.summary,
            issue_title=draft.issue_title,
            issue_url=draft.issue_url,
            status=draft.status,
            created_at=draft.created_at
        ))
    
    return result


@app.get(
    "/api/drafts",
    response_model=List[DraftResponse],
    tags=["Drafts"],
    summary="全顧客の下書き一覧を取得",
    description="すべての顧客に関する返信下書きをステータス別に取得します。"
)
def get_all_pending_drafts(
    status: str = Query("pending", description="フィルタするステータス (pending/sent/archived)", example="pending"),
    db: Session = Depends(get_db)
):
    """
    ## 全下書き一覧取得
    
    全顧客の返信下書きをステータス別に取得します。
    管理画面での一括確認に使用されます。
    
    ### パラメータ
    - `status`: フィルタするステータス（デフォルト: pending）
    """
    drafts = db.query(DraftQueue).filter_by(status=status).order_by(
        DraftQueue.created_at.desc()
    ).all()
    
    result = []
    for draft in drafts:
        result.append(DraftResponse(
            id=draft.id,
            customer_id=draft.customer_id,
            customer_name=draft.customer.name,
            message_id=draft.message_id,
            reply_draft=draft.reply_draft,
            summary=draft.summary,
            issue_title=draft.issue_title,
            issue_url=draft.issue_url,
            status=draft.status,
            created_at=draft.created_at
        ))
    
    return result


@app.patch(
    "/api/drafts/{draft_id}/complete",
    tags=["Drafts"],
    summary="下書きを完了済みとしてマーク",
    description="指定した下書きを送信済み（sent）ステータスに変更します。"
)
def mark_draft_complete(
    draft_id: int = Path(..., description="下書きID", example=1),
    db: Session = Depends(get_db)
):
    """
    ## 下書き完了マーク
    
    下書きを送信済み（sent）としてマークします。
    メール送信後に実行されます。
    
    ### パラメータ
    - `draft_id`: 下書きID
    
    ### レスポンス
    完了日時が自動的に記録されます。
    """
    draft = db.query(DraftQueue).filter_by(id=draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft.status = "sent"
    draft.completed_at = datetime.utcnow()
    db.commit()
    
    return {"status": "success", "message": "Draft marked as sent"}


@app.patch(
    "/api/drafts/{draft_id}",
    tags=["Drafts"],
    summary="下書きのステータスを更新",
    description="指定した下書きのステータスを任意の値に変更します。"
)
def update_draft_status(
    update: DraftUpdate,
    draft_id: int = Path(..., description="下書きID", example=1),
    db: Session = Depends(get_db)
):
    """
    ## 下書きステータス更新
    
    下書きのステータスを変更します。
    
    ### パラメータ
    - `draft_id`: 下書きID
    - `update.status`: 新しいステータス (pending/sent/archived)
    
    ### ステータス遷移
    - `pending` → `sent`: メール送信完了
    - `pending` → `archived`: 送信せずにアーカイブ
    - `sent` → `archived`: 処理完了後にアーカイブ
    """
    draft = db.query(DraftQueue).filter_by(id=draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    if update.status not in ["pending", "sent", "archived"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    draft.status = update.status
    if update.status in ["sent", "archived"]:
        draft.completed_at = datetime.utcnow()
    db.commit()
    
    return {"status": "success", "message": f"Draft status updated to {update.status}"}


@app.delete(
    "/api/drafts/{draft_id}",
    tags=["Drafts"],
    summary="下書きを削除",
    description="指定した下書きをデータベースから完全に削除します。"
)
def delete_draft(
    draft_id: int = Path(..., description="下書きID", example=1),
    db: Session = Depends(get_db)
):
    """
    ## 下書き削除
    
    下書きをデータベースから完全に削除します。
    この操作は取り消せません。
    
    ### パラメータ
    - `draft_id`: 削除する下書きのID
    
    ### 注意
    通常はステータスを `archived` に変更することを推奨します。
    """
    draft = db.query(DraftQueue).filter_by(id=draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    db.delete(draft)
    db.commit()
    
    return {"status": "success", "message": "Draft deleted"}


@app.get(
    "/api/customers",
    response_model=List[CustomerResponse],
    tags=["Customers"],
    summary="全顧客のリストを取得",
    description="登録されているすべての顧客情報を取得します。"
)
def list_customers(db: Session = Depends(get_db)):
    """
    ## 顧客一覧取得
    
    登録されているすべての顧客の基本情報を取得します。
    
    ### レスポンス
    各顧客について以下の情報が含まれます：
    - 顧客ID、名前
    - 登録メールアドレス数
    - 登録日時
    """
    customers = db.query(Customer).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "email_count": len(c.email_addresses),
            "created_at": c.created_at
        }
        for c in customers
    ]


@app.get("/customers", response_class=HTMLResponse)
async def customers_page(request: Request, db: Session = Depends(get_db)):
    """顧客管理画面"""
    customers = db.query(Customer).all()
    customers_data = [
        {
            "id": c.id,
            "name": c.name,
            "repo_url": c.repo_url,
            "discord_webhook": c.discord_webhook,
            "email_count": len(c.email_addresses),
            "created_at": c.created_at
        }
        for c in customers
    ]
    return templates.TemplateResponse("customers.html", {
        "request": request,
        "customers": customers_data,
        "default_gitea_host": settings.DEFAULT_GITEA_HOST,
        "has_default_token": settings.DEFAULT_GITEA_TOKEN is not None
    })


@app.post("/customers")
async def create_customer(
    name: str = Form(...),
    repo_url: str = Form(...),
    gitea_token: str = Form(None),
    discord_webhook: str = Form(None),
    db: Session = Depends(get_db)
):
    """顧客を作成"""
    # Process repository URL
    final_repo_url = repo_url.strip()
    
    # If repo_url is in short form (owner/repo) and we have a default host, expand it
    if settings.DEFAULT_GITEA_HOST and '://' not in final_repo_url:
        # Short form: owner/repo -> https://gitea.example.com/owner/repo.git
        if not final_repo_url.endswith('.git'):
            final_repo_url = f"{final_repo_url}.git"
        final_repo_url = f"{settings.DEFAULT_GITEA_HOST.rstrip('/')}/{final_repo_url}"
    
    # Use default token if not provided
    final_gitea_token = gitea_token.strip() if gitea_token and gitea_token.strip() else settings.DEFAULT_GITEA_TOKEN
    
    # Validate that we have a token
    if not final_gitea_token:
        raise HTTPException(status_code=400, detail="Gitea token is required (no default configured)")
    
    customer = Customer(
        name=name,
        repo_url=final_repo_url,
        gitea_token=final_gitea_token,
        discord_webhook=discord_webhook if discord_webhook else None
    )
    db.add(customer)
    db.commit()
    return RedirectResponse(url="/customers", status_code=303)


@app.post("/customers/update")
async def update_customer(
    customer_id: int = Form(...),
    name: str = Form(...),
    repo_url: str = Form(...),
    gitea_token: str = Form(None),
    discord_webhook: str = Form(None),
    db: Session = Depends(get_db)
):
    """顧客を更新"""
    customer = db.query(Customer).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Process repository URL
    final_repo_url = repo_url.strip()
    
    # If repo_url is in short form (owner/repo) and we have a default host, expand it
    if settings.DEFAULT_GITEA_HOST and '://' not in final_repo_url:
        # Short form: owner/repo -> https://gitea.example.com/owner/repo.git
        if not final_repo_url.endswith('.git'):
            final_repo_url = f"{final_repo_url}.git"
        final_repo_url = f"{settings.DEFAULT_GITEA_HOST.rstrip('/')}/{final_repo_url}"
    
    customer.name = name
    customer.repo_url = final_repo_url
    if gitea_token and gitea_token.strip():
        customer.gitea_token = gitea_token.strip()
    customer.discord_webhook = discord_webhook if discord_webhook else None
    db.commit()
    return RedirectResponse(url="/customers", status_code=303)


@app.get("/email-addresses", response_class=HTMLResponse)
async def email_addresses_page(request: Request, db: Session = Depends(get_db)):
    """メールアドレス管理画面"""
    customers = db.query(Customer).all()
    emails = db.query(EmailAddress).all()
    emails_data = [
        {
            "email": e.email,
            "customer_id": e.customer_id,
            "customer_name": e.customer.name,
            "created_at": e.created_at
        }
        for e in emails
    ]
    return templates.TemplateResponse("email_addresses.html", {
        "request": request,
        "customers": customers,
        "emails": emails_data
    })


@app.post("/email-addresses")
async def create_email_address(
    customer_id: int = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    """メールアドレスを追加"""
    email_addr = EmailAddress(
        email=email.lower().strip(),
        customer_id=customer_id
    )
    db.add(email_addr)
    db.commit()
    return RedirectResponse(url="/email-addresses", status_code=303)


@app.get("/mail-accounts", response_class=HTMLResponse)
async def mail_accounts_page(request: Request, db: Session = Depends(get_db)):
    """メールアカウント管理画面"""
    accounts = db.query(MailAccount).all()
    return templates.TemplateResponse("mail_accounts.html", {
        "request": request,
        "accounts": accounts
    })


@app.post("/mail-accounts")
async def create_mail_account(
    host: str = Form(...),
    port: int = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    use_ssl: bool = Form(False),
    enabled: bool = Form(False),
    db: Session = Depends(get_db)
):
    """メールアカウントを追加"""
    account = MailAccount(
        host=host,
        port=port,
        username=username,
        password=password,
        use_ssl=use_ssl,
        enabled=enabled
    )
    db.add(account)
    db.commit()
    return RedirectResponse(url="/mail-accounts", status_code=303)


@app.post("/mail-accounts/update")
async def update_mail_account(
    account_id: int = Form(...),
    host: str = Form(...),
    port: int = Form(...),
    username: str = Form(...),
    password: str = Form(None),
    use_ssl: bool = Form(False),
    enabled: bool = Form(False),
    db: Session = Depends(get_db)
):
    """メールアカウントを更新"""
    account = db.query(MailAccount).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    account.host = host
    account.port = port
    account.username = username
    if password:
        account.password = password
    account.use_ssl = use_ssl
    account.enabled = enabled
    db.commit()
    return RedirectResponse(url="/mail-accounts", status_code=303)


@app.get("/drafts", response_class=HTMLResponse)
async def drafts_page(
    request: Request,
    customer_id: int = None,
    status: str = "pending",
    db: Session = Depends(get_db)
):
    """下書き管理画面"""
    customers = db.query(Customer).all()
    
    query = db.query(DraftQueue).filter_by(status=status)
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    
    drafts = query.order_by(DraftQueue.created_at.desc()).all()
    drafts_data = [
        {
            "id": d.id,
            "customer_id": d.customer_id,
            "customer_name": d.customer.name,
            "message_id": d.message_id,
            "reply_draft": d.reply_draft,
            "summary": d.summary,
            "issue_title": d.issue_title,
            "issue_url": d.issue_url,
            "status": d.status,
            "created_at": d.created_at
        }
        for d in drafts
    ]
    
    return templates.TemplateResponse("drafts.html", {
        "request": request,
        "customers": customers,
        "drafts": drafts_data,
        "status": status,
        "selected_customer_id": customer_id
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    """設定画面"""
    # Get current timezone setting
    tz_setting = db.query(SystemSetting).filter_by(key='timezone').first()
    current_timezone = tz_setting.value if tz_setting and tz_setting.value else 'Asia/Tokyo'
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "current_timezone": current_timezone,
        "gitea_host": settings.DEFAULT_GITEA_HOST,
        "gitea_token": settings.DEFAULT_GITEA_TOKEN
    })


@app.post("/settings")
async def update_settings(
    timezone: str = Form(...),
    db: Session = Depends(get_db)
):
    """設定を更新"""
    # Update or create timezone setting
    tz_setting = db.query(SystemSetting).filter_by(key='timezone').first()
    if tz_setting:
        tz_setting.value = timezone
        tz_setting.updated_at = datetime.utcnow()
    else:
        tz_setting = SystemSetting(key='timezone', value=timezone)
        db.add(tz_setting)
    
    db.commit()
    return {"status": "success", "message": "Settings updated"}


# ========== API Endpoints for AJAX ==========


@app.get(
    "/api/customers/{customer_id}",
    response_model=CustomerDetailResponse,
    tags=["Customers"],
    summary="顧客詳細を取得",
    description="指定した顧客の詳細情報を取得します。"
)
def get_customer(
    customer_id: int = Path(..., description="顧客ID", example=1),
    db: Session = Depends(get_db)
):
    """
    ## 顧客詳細取得
    
    指定した顧客の詳細情報を取得します。
    
    ### パラメータ
    - `customer_id`: 顧客ID
    
    ### レスポンス
    GiteaリポジトリURL、Discord Webhook URLなどの詳細情報が含まれます。
    """
    customer = db.query(Customer).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {
        "id": customer.id,
        "name": customer.name,
        "repo_url": customer.repo_url,
        "discord_webhook": customer.discord_webhook,
        "created_at": customer.created_at
    }


@app.delete(
    "/api/customers/{customer_id}",
    tags=["Customers"],
    summary="顧客を削除",
    description="指定した顧客をデータベースから削除します。関連する下書きも削除されます。"
)
def delete_customer(
    customer_id: int = Path(..., description="顧客ID", example=1),
    db: Session = Depends(get_db)
):
    """
    ## 顧客削除
    
    顧客をデータベースから削除します。
    
    ### パラメータ
    - `customer_id`: 削除する顧客のID
    
    ### 注意
    関連する下書き、メールアドレスも一緒に削除されます。
    """
    customer = db.query(Customer).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    db.delete(customer)
    db.commit()
    return {"status": "success", "message": "Customer deleted"}


@app.delete(
    "/api/email-addresses/{email}",
    tags=["Email Addresses"],
    summary="メールアドレスを削除",
    description="指定したメールアドレスをホワイトリストから削除します。"
)
def delete_email_address(
    email: str = Path(..., description="削除するメールアドレス", example="customer@example.com"),
    db: Session = Depends(get_db)
):
    """
    ## メールアドレス削除
    
    ホワイトリストからメールアドレスを削除します。
    
    ### パラメータ
    - `email`: 削除するメールアドレス
    
    ### 注意
    このアドレスからのメールは今後処理されなくなります。
    """
    email_addr = db.query(EmailAddress).filter_by(email=email).first()
    if not email_addr:
        raise HTTPException(status_code=404, detail="Email address not found")
    db.delete(email_addr)
    db.commit()
    return {"status": "success", "message": "Email address deleted"}


@app.get(
    "/api/mail-accounts/{account_id}",
    response_model=MailAccountResponse,
    tags=["Mail Accounts"],
    summary="メールアカウント詳細を取得",
    description="指定したPOP3アカウントの詳細情報を取得します。"
)
def get_mail_account(
    account_id: int = Path(..., description="アカウントID", example=1),
    db: Session = Depends(get_db)
):
    """
    ## メールアカウント詳細取得
    
    POP3アカウントの詳細情報を取得します。
    パスワードは含まれません（セキュリティ上の理由）。
    
    ### パラメータ
    - `account_id`: アカウントID
    """
    account = db.query(MailAccount).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {
        "id": account.id,
        "host": account.host,
        "port": account.port,
        "username": account.username,
        "use_ssl": account.use_ssl,
        "enabled": account.enabled,
        "created_at": account.created_at
    }


@app.patch(
    "/api/mail-accounts/{account_id}/toggle",
    tags=["Mail Accounts"],
    summary="メールアカウントの有効/無効を切り替え",
    description="POP3アカウントの有効/無効状態を切り替えます。"
)
def toggle_mail_account(
    account_id: int = Path(..., description="アカウントID", example=1),
    enabled: bool = Query(..., description="有効にする場合はtrue、無効にする場合はfalse", example=True),
    db: Session = Depends(get_db)
):
    """
    ## メールアカウント有効/無効切り替え
    
    POP3アカウントの有効/無効を切り替えます。
    無効化されたアカウントからはメールを取得しません。
    
    ### パラメータ
    - `account_id`: アカウントID
    - `enabled`: 有効化する場合は `true`、無効化する場合は `false`
    """
    account = db.query(MailAccount).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.enabled = enabled
    db.commit()
    return {"status": "success", "message": f"Account {'enabled' if enabled else 'disabled'}"}


@app.delete(
    "/api/mail-accounts/{account_id}",
    tags=["Mail Accounts"],
    summary="メールアカウントを削除",
    description="指定したPOP3アカウントをデータベースから削除します。"
)
def delete_mail_account(
    account_id: int = Path(..., description="アカウントID", example=1),
    db: Session = Depends(get_db)
):
    """
    ## メールアカウント削除
    
    POP3アカウントをデータベースから削除します。
    
    ### パラメータ
    - `account_id`: 削除するアカウントのID
    
    ### 注意
    削除されたアカウントからはメールを取得できなくなります。
    """
    account = db.query(MailAccount).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(account)
    db.commit()
    return {"status": "success", "message": "Account deleted"}


@app.get(
    "/api/drafts/{draft_id}/text",
    tags=["Drafts"],
    summary="下書きテキストを取得",
    description="指定した下書きの返信本文のみを取得します。"
)
def get_draft_text(
    draft_id: int = Path(..., description="下書きID", example=1),
    db: Session = Depends(get_db)
):
    """
    ## 下書きテキスト取得
    
    下書きの返信本文のみを取得します。
    メール送信時にテキストエリアに表示するために使用されます。
    
    ### パラメータ
    - `draft_id`: 下書きID
    
    ### レスポンス
    `reply_draft` フィールドに返信本文が含まれます。
    """
    draft = db.query(DraftQueue).filter_by(id=draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"reply_draft": draft.reply_draft}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
