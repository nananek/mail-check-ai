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
from src.models import (
    Customer, EmailAddress, MailAccount, ProcessedEmail, SystemSetting,
    ConversationThread, ThreadEmail, SmtpRelayConfig
)
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
        "poll_interval": os.getenv("POLL_INTERVAL", "60"),
        "thread_count": db.query(ConversationThread).count(),
        "incoming_count": db.query(ProcessedEmail).filter_by(direction='incoming').count(),
        "outgoing_count": db.query(ProcessedEmail).filter_by(direction='outgoing').count(),
    }

    recent_emails = db.query(ProcessedEmail).order_by(
        ProcessedEmail.processed_at.desc()
    ).limit(5).all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "recent_emails": recent_emails,
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
    # 自動プロビジョニングが利用可能か（Gitea + Discord Bot の両方が設定済み）
    auto_provision_available = all([
        settings.DEFAULT_GITEA_HOST,
        settings.DEFAULT_GITEA_TOKEN,
        settings.DISCORD_BOT_TOKEN,
        settings.DISCORD_CATEGORY_ID,
    ])

    return templates.TemplateResponse("customers.html", {
        "request": request,
        "customers": customers_data,
        "default_gitea_host": settings.DEFAULT_GITEA_HOST,
        "has_default_token": settings.DEFAULT_GITEA_TOKEN is not None,
        "auto_provision_available": auto_provision_available,
    })


@app.post("/customers")
async def create_customer(
    name: str = Form(...),
    repo_url: str = Form(""),
    gitea_token: str = Form(None),
    discord_webhook: str = Form(None),
    auto_provision: bool = Form(False),
    db: Session = Depends(get_db)
):
    """顧客を作成（自動プロビジョニング対応）"""
    from src.utils.provisioning import create_gitea_repo, create_discord_channel_with_webhook

    final_repo_url = None
    final_discord_webhook = None

    if auto_provision:
        # Giteaリポジトリを自動作成
        try:
            final_repo_url = create_gitea_repo(name)
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=f"Giteaリポジトリの自動作成に失敗: {e}")

        # Discordチャンネル＋Webhookを自動作成
        try:
            final_discord_webhook = create_discord_channel_with_webhook(name)
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=f"Discordチャンネルの自動作成に失敗: {e}")
    else:
        # 手動入力モード
        final_repo_url = repo_url.strip()
        if not final_repo_url:
            raise HTTPException(status_code=400, detail="リポジトリURLを入力してください")

        # If repo_url is in short form (owner/repo) and we have a default host, expand it
        if settings.DEFAULT_GITEA_HOST and '://' not in final_repo_url:
            if not final_repo_url.endswith('.git'):
                final_repo_url = f"{final_repo_url}.git"
            final_repo_url = f"{settings.DEFAULT_GITEA_HOST.rstrip('/')}/{final_repo_url}"

        final_discord_webhook = discord_webhook if discord_webhook else None

    # Use default token if not provided
    final_gitea_token = gitea_token.strip() if gitea_token and gitea_token.strip() else settings.DEFAULT_GITEA_TOKEN

    # Validate that we have a token
    if not final_gitea_token:
        raise HTTPException(status_code=400, detail="Gitea token is required (no default configured)")

    customer = Customer(
        name=name,
        repo_url=final_repo_url,
        gitea_token=final_gitea_token,
        discord_webhook=final_discord_webhook
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
            "salutation": e.salutation,
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
    salutation: str = Form(None),
    db: Session = Depends(get_db)
):
    """メールアドレスを追加"""
    email_addr = EmailAddress(
        email=email.lower().strip(),
        customer_id=customer_id,
        salutation=salutation.strip() if salutation else None
    )
    db.add(email_addr)
    db.commit()
    return RedirectResponse(url="/email-addresses", status_code=303)


@app.post("/email-addresses/update")
async def update_email_address(
    old_email: str = Form(...),
    email: str = Form(...),
    customer_id: int = Form(...),
    salutation: str = Form(None),
    db: Session = Depends(get_db)
):
    """メールアドレスを更新"""
    old_email = old_email.lower().strip()
    new_email = email.lower().strip()
    
    # 既存のメールアドレスを取得
    email_record = db.query(EmailAddress).filter_by(email=old_email).first()
    if not email_record:
        raise HTTPException(status_code=404, detail="Email address not found")
    
    # メールアドレスが変更された場合
    if old_email != new_email:
        # 新しいメールアドレスが既に存在しないかチェック
        existing = db.query(EmailAddress).filter_by(email=new_email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email address already exists")
        
        # 古いレコードを削除して新しいレコードを作成（主キーが変更されるため）
        db.delete(email_record)
        db.flush()
        
        new_record = EmailAddress(
            email=new_email,
            customer_id=customer_id,
            salutation=salutation.strip() if salutation else None
        )
        db.add(new_record)
    else:
        # メールアドレスは同じで、顧客IDや宛名のみ変更
        email_record.customer_id = customer_id
        email_record.salutation = salutation.strip() if salutation else None
    
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


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    """設定画面"""
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


# ========== Thread Routes ==========

@app.get("/threads", response_class=HTMLResponse)
async def threads_page(
    request: Request,
    customer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """会話スレッド一覧画面"""
    tz = get_system_timezone(db)
    customers = db.query(Customer).all()

    query = db.query(ConversationThread)
    if customer_id:
        query = query.filter_by(customer_id=customer_id)

    threads_raw = query.order_by(ConversationThread.updated_at.desc()).limit(50).all()

    threads_data = []
    for t in threads_raw:
        latest_email = db.query(ThreadEmail).filter_by(
            thread_id=t.id
        ).order_by(ThreadEmail.date.desc()).first()

        threads_data.append({
            "id": t.id,
            "subject": t.subject,
            "customer_name": t.customer.name,
            "email_count": db.query(ThreadEmail).filter_by(thread_id=t.id).count(),
            "updated_at": t.updated_at,
            "latest_direction": latest_email.direction if latest_email else None,
            "latest_summary": latest_email.summary if latest_email else None
        })

    return templates.TemplateResponse("threads.html", {
        "request": request,
        "customers": customers,
        "threads": threads_data,
        "selected_customer_id": customer_id,
        "timezone": tz
    })


@app.get("/threads/{thread_id}", response_class=HTMLResponse)
async def thread_detail_page(
    request: Request,
    thread_id: int = Path(...),
    db: Session = Depends(get_db)
):
    """スレッド詳細画面"""
    tz = get_system_timezone(db)

    thread = db.query(ConversationThread).filter_by(id=thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    emails = db.query(ThreadEmail).filter_by(
        thread_id=thread_id
    ).order_by(ThreadEmail.date.asc()).all()

    return templates.TemplateResponse("thread_detail.html", {
        "request": request,
        "thread": {
            "id": thread.id,
            "subject": thread.subject,
            "customer_name": thread.customer.name,
            "emails": emails
        },
        "timezone": tz
    })


@app.get(
    "/api/threads",
    tags=["Threads"],
    summary="スレッド一覧を取得"
)
def api_list_threads(
    customer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """会話スレッド一覧を取得"""
    query = db.query(ConversationThread)
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    threads = query.order_by(ConversationThread.updated_at.desc()).limit(50).all()
    return [
        {
            "id": t.id,
            "customer_id": t.customer_id,
            "subject": t.subject,
            "email_count": len(t.emails),
            "updated_at": t.updated_at.isoformat()
        }
        for t in threads
    ]


@app.get(
    "/api/threads/{thread_id}",
    tags=["Threads"],
    summary="スレッド詳細を取得"
)
def api_get_thread(
    thread_id: int = Path(...),
    db: Session = Depends(get_db)
):
    """スレッド内のメール一覧を含む詳細情報を取得"""
    thread = db.query(ConversationThread).filter_by(id=thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    emails = db.query(ThreadEmail).filter_by(
        thread_id=thread_id
    ).order_by(ThreadEmail.date.asc()).all()

    return {
        "id": thread.id,
        "subject": thread.subject,
        "customer_id": thread.customer_id,
        "emails": [
            {
                "id": e.id,
                "message_id": e.message_id,
                "direction": e.direction,
                "from_address": e.from_address,
                "to_addresses": e.to_addresses,
                "subject": e.subject,
                "body_preview": e.body_preview,
                "summary": e.summary,
                "date": e.date.isoformat()
            }
            for e in emails
        ]
    }


# ========== SMTP Relay Config Routes ==========

@app.get("/smtp-relay", response_class=HTMLResponse)
async def smtp_relay_page(request: Request, db: Session = Depends(get_db)):
    """SMTP中継設定画面"""
    configs = db.query(SmtpRelayConfig).all()
    return templates.TemplateResponse("smtp_relay.html", {
        "request": request,
        "configs": configs,
        "smtp_relay_enabled": settings.SMTP_RELAY_ENABLED,
        "smtp_relay_port": settings.SMTP_RELAY_PORT
    })


@app.post("/smtp-relay")
async def create_smtp_relay_config(
    name: str = Form(...),
    relay_username: str = Form(...),
    relay_password: str = Form(...),
    host: str = Form(...),
    port: int = Form(587),
    username: str = Form(...),
    password: str = Form(...),
    use_tls: bool = Form(False),
    use_ssl: bool = Form(False),
    enabled: bool = Form(False),
    db: Session = Depends(get_db)
):
    """転送先SMTP設定を追加"""
    existing = db.query(SmtpRelayConfig).filter_by(relay_username=relay_username).first()
    if existing:
        raise HTTPException(status_code=400, detail="このリレーユーザー名は既に使用されています")
    config = SmtpRelayConfig(
        name=name, relay_username=relay_username, relay_password=relay_password,
        host=host, port=port,
        username=username, password=password,
        use_tls=use_tls, use_ssl=use_ssl, enabled=enabled
    )
    db.add(config)
    db.commit()
    return RedirectResponse(url="/smtp-relay", status_code=303)


@app.post("/smtp-relay/update")
async def update_smtp_relay_config(
    config_id: int = Form(...),
    name: str = Form(...),
    relay_username: str = Form(...),
    relay_password: str = Form(None),
    host: str = Form(...),
    port: int = Form(587),
    username: str = Form(...),
    password: str = Form(None),
    use_tls: bool = Form(False),
    use_ssl: bool = Form(False),
    enabled: bool = Form(False),
    db: Session = Depends(get_db)
):
    """転送先SMTP設定を更新"""
    config = db.query(SmtpRelayConfig).filter_by(id=config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    # relay_usernameの重複チェック（自分自身を除く）
    existing = db.query(SmtpRelayConfig).filter(
        SmtpRelayConfig.relay_username == relay_username,
        SmtpRelayConfig.id != config_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="このリレーユーザー名は既に使用されています")

    config.name = name
    config.relay_username = relay_username
    if relay_password:
        config.relay_password = relay_password
    config.host = host
    config.port = port
    config.username = username
    if password:
        config.password = password
    config.use_tls = use_tls
    config.use_ssl = use_ssl
    config.enabled = enabled
    db.commit()
    return RedirectResponse(url="/smtp-relay", status_code=303)


@app.get(
    "/api/smtp-relay/{config_id}",
    tags=["SMTP Relay"],
    summary="SMTP中継設定を取得"
)
def get_smtp_relay_config(
    config_id: int = Path(...),
    db: Session = Depends(get_db)
):
    """SMTP中継設定の詳細を取得（パスワードは含まない）"""
    config = db.query(SmtpRelayConfig).filter_by(id=config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    return {
        "id": config.id,
        "name": config.name,
        "relay_username": config.relay_username,
        "host": config.host,
        "port": config.port,
        "username": config.username,
        "use_tls": config.use_tls,
        "use_ssl": config.use_ssl,
        "enabled": config.enabled
    }


@app.delete(
    "/api/smtp-relay/{config_id}",
    tags=["SMTP Relay"],
    summary="SMTP中継設定を削除"
)
def delete_smtp_relay_config(
    config_id: int = Path(...),
    db: Session = Depends(get_db)
):
    """SMTP中継設定を削除"""
    config = db.query(SmtpRelayConfig).filter_by(id=config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    db.delete(config)
    db.commit()
    return {"status": "success", "message": "Config deleted"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
