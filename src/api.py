from fastapi import FastAPI, HTTPException, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List
from pydantic import BaseModel
import os

from src.database import get_db
from src.models import DraftQueue, Customer, EmailAddress, MailAccount, ProcessedEmail
from src.config import settings

app = FastAPI(
    title="Mail Check AI API",
    description="AI Mail Processor - Draft Management API",
    version="1.0.0"
)

# Templates setup
templates = Jinja2Templates(directory="src/templates")

# Static files (if needed later)
if os.path.exists("src/static"):
    app.mount("/static", StaticFiles(directory="src/static"), name="static")


# Pydantic schemas
class DraftResponse(BaseModel):
    id: int
    customer_id: int
    customer_name: str
    message_id: str
    reply_draft: str
    summary: str
    issue_title: str | None
    issue_url: str | None
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class DraftUpdate(BaseModel):
    status: str


# ========== Web UI Routes ==========

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """ダッシュボード"""
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
        "recent_drafts": recent_drafts
    })


# ========== REST API Endpoints ==========

@app.get("/api/health")
def health_check():
    """ヘルスチェック"""
    return {
        "status": "ok",
        "service": "Mail Check AI API",
        "version": "1.0.0"
    }


@app.get("/api/drafts/{customer_id}", response_model=List[DraftResponse])
def get_customer_drafts(customer_id: int, status: str = "pending", db: Session = Depends(get_db)):
    """
    顧客の下書き一覧を取得
    
    Args:
        customer_id: 顧客ID
        status: フィルタするステータス (pending / sent / archived)
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


@app.get("/api/drafts", response_model=List[DraftResponse])
def get_all_pending_drafts(status: str = "pending", db: Session = Depends(get_db)):
    """
    全顧客の下書き一覧を取得
    
    Args:
        status: フィルタするステータス (pending / sent / archived)
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


@app.patch("/api/drafts/{draft_id}/complete")
def mark_draft_complete(draft_id: int, db: Session = Depends(get_db)):
    """
    下書きを完了済みとしてマーク
    
    Args:
        draft_id: 下書きID
    """
    draft = db.query(DraftQueue).filter_by(id=draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft.status = "sent"
    draft.completed_at = datetime.utcnow()
    db.commit()
    
    return {"status": "success", "message": "Draft marked as sent"}


@app.patch("/api/drafts/{draft_id}")
def update_draft_status(draft_id: int, update: DraftUpdate, db: Session = Depends(get_db)):
    """
    下書きのステータスを更新
    
    Args:
        draft_id: 下書きID
        update: 更新内容
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


@app.delete("/api/drafts/{draft_id}")
def delete_draft(draft_id: int, db: Session = Depends(get_db)):
    """
    下書きを削除
    
    Args:
        draft_id: 下書きID
    """
    draft = db.query(DraftQueue).filter_by(id=draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    db.delete(draft)
    db.commit()
    
    return {"status": "success", "message": "Draft deleted"}


@app.get("/api/customers")
def list_customers(db: Session = Depends(get_db)):
    """全顧客のリストを取得"""
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


@app.post("/ui/customers")
async def create_customer(
    name: str = Form(...),
    repo_url: str = Form(None),
    gitea_token: str = Form(None),
    discord_webhook: str = Form(None),
    db: Session = Depends(get_db)
):
    """顧客を作成"""
    # Use defaults if not provided
    final_repo_url = repo_url if repo_url else None
    final_gitea_token = gitea_token if gitea_token else settings.DEFAULT_GITEA_TOKEN
    
    # If repo_url is not provided but we have a default host, we can't proceed
    # Repo URL is still required as it's customer-specific
    if not final_repo_url:
        raise HTTPException(status_code=400, detail="Repository URL is required")
    
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
    
    customer.name = name
    customer.repo_url = repo_url
    if gitea_token:
        customer.gitea_token = gitea_token
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


@app.post("/ui/email-addresses")
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


@app.post("/ui/mail-accounts")
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


@app.get("/api/customers/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    """顧客詳細を取得"""
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


@app.delete("/api/customers/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    """顧客を削除"""
    customer = db.query(Customer).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    db.delete(customer)
    db.commit()
    return {"status": "success", "message": "Customer deleted"}


@app.delete("/api/email-addresses/{email}")
def delete_email_address(email: str, db: Session = Depends(get_db)):
    """メールアドレスを削除"""
    email_addr = db.query(EmailAddress).filter_by(email=email).first()
    if not email_addr:
        raise HTTPException(status_code=404, detail="Email address not found")
    db.delete(email_addr)
    db.commit()
    return {"status": "success", "message": "Email address deleted"}


@app.get("/api/mail-accounts/{account_id}")
def get_mail_account(account_id: int, db: Session = Depends(get_db)):
    """メールアカウント詳細を取得"""
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


@app.patch("/api/mail-accounts/{account_id}/toggle")
def toggle_mail_account(account_id: int, enabled: bool, db: Session = Depends(get_db)):
    """メールアカウントの有効/無効を切り替え"""
    account = db.query(MailAccount).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.enabled = enabled
    db.commit()
    return {"status": "success", "message": f"Account {'enabled' if enabled else 'disabled'}"}


@app.delete("/api/mail-accounts/{account_id}")
def delete_mail_account(account_id: int, db: Session = Depends(get_db)):
    """メールアカウントを削除"""
    account = db.query(MailAccount).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(account)
    db.commit()
    return {"status": "success", "message": "Account deleted"}


@app.get("/api/drafts/{draft_id}/text")
def get_draft_text(draft_id: int, db: Session = Depends(get_db)):
    """下書きテキストを取得"""
    draft = db.query(DraftQueue).filter_by(id=draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"reply_draft": draft.reply_draft}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
