from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List
from pydantic import BaseModel

from src.database import get_db
from src.models import DraftQueue, Customer

app = FastAPI(
    title="Mail Check AI API",
    description="AI Mail Processor - Draft Management API",
    version="1.0.0"
)


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


@app.get("/")
def root():
    """ヘルスチェック"""
    return {
        "status": "ok",
        "service": "Mail Check AI API",
        "version": "1.0.0"
    }


@app.get("/drafts/{customer_id}", response_model=List[DraftResponse])
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


@app.get("/drafts", response_model=List[DraftResponse])
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


@app.patch("/drafts/{draft_id}/complete")
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


@app.patch("/drafts/{draft_id}")
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


@app.delete("/drafts/{draft_id}")
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


# 顧客管理エンドポイント
@app.get("/customers")
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
