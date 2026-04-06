from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from pydantic import BaseModel

from app.database import get_db
from app.models.user import User
from app.models.support import SupportTicket, TicketMessage
from app.dependencies import get_current_user, get_admin_user

router = APIRouter(prefix="/support", tags=["Support"])


# --- Schemas ---

class CreateTicketRequest(BaseModel):
    subject: str
    message: str
    category: str = "general"
    priority: str = "normal"


class ReplyRequest(BaseModel):
    content: str


class UpdateTicketRequest(BaseModel):
    status: str | None = None
    priority: str | None = None
    assigned_to: str | None = None


class MessageResponse(BaseModel):
    id: str
    sender_id: str
    sender_role: str
    sender_name: str = ""
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TicketResponse(BaseModel):
    id: str
    user_id: str
    user_email: str = ""
    user_name: str = ""
    subject: str
    status: str
    priority: str
    category: str
    assigned_to: str | None
    messages_count: int = 0
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class TicketDetailResponse(TicketResponse):
    messages: list[MessageResponse] = []


# ========================
# USER ENDPOINTS
# ========================

@router.post("/tickets", response_model=TicketResponse, status_code=201)
async def create_ticket(
    body: CreateTicketRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = SupportTicket(
        user_id=user.id,
        subject=body.subject,
        category=body.category,
        priority=body.priority,
    )
    db.add(ticket)
    await db.flush()

    # Add first message
    message = TicketMessage(
        ticket_id=ticket.id,
        sender_id=user.id,
        sender_role="user",
        content=body.message,
    )
    db.add(message)
    await db.commit()
    await db.refresh(ticket)

    return TicketResponse(
        id=ticket.id,
        user_id=ticket.user_id,
        user_email=user.email,
        user_name=user.name or "",
        subject=ticket.subject,
        status=ticket.status,
        priority=ticket.priority,
        category=ticket.category,
        assigned_to=ticket.assigned_to,
        messages_count=1,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        resolved_at=ticket.resolved_at,
    )


@router.get("/tickets", response_model=list[TicketResponse])
async def list_my_tickets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SupportTicket)
        .where(SupportTicket.user_id == user.id)
        .order_by(desc(SupportTicket.updated_at))
    )
    tickets = result.scalars().all()

    items = []
    for t in tickets:
        msg_count = (await db.execute(
            select(func.count()).where(TicketMessage.ticket_id == t.id)
        )).scalar() or 0

        items.append(TicketResponse(
            id=t.id, user_id=t.user_id, user_email=user.email,
            user_name=user.name or "", subject=t.subject, status=t.status,
            priority=t.priority, category=t.category, assigned_to=t.assigned_to,
            messages_count=msg_count, created_at=t.created_at,
            updated_at=t.updated_at, resolved_at=t.resolved_at,
        ))
    return items


@router.get("/tickets/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(
    ticket_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Users can only see their own tickets, admins can see all
    if ticket.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Get messages
    msgs_result = await db.execute(
        select(TicketMessage)
        .where(TicketMessage.ticket_id == ticket_id)
        .order_by(TicketMessage.created_at.asc())
    )
    messages = msgs_result.scalars().all()

    # Get sender names
    sender_ids = list(set(m.sender_id for m in messages))
    name_map = {}
    if sender_ids:
        users_result = await db.execute(select(User).where(User.id.in_(sender_ids)))
        for u in users_result.scalars().all():
            name_map[u.id] = u.name or u.email

    # Get ticket owner info
    owner_result = await db.execute(select(User).where(User.id == ticket.user_id))
    owner = owner_result.scalar_one_or_none()

    return TicketDetailResponse(
        id=ticket.id, user_id=ticket.user_id,
        user_email=owner.email if owner else "",
        user_name=owner.name if owner else "",
        subject=ticket.subject, status=ticket.status,
        priority=ticket.priority, category=ticket.category,
        assigned_to=ticket.assigned_to, messages_count=len(messages),
        created_at=ticket.created_at, updated_at=ticket.updated_at,
        resolved_at=ticket.resolved_at,
        messages=[
            MessageResponse(
                id=m.id, sender_id=m.sender_id, sender_role=m.sender_role,
                sender_name=name_map.get(m.sender_id, "Unknown"),
                content=m.content, created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.post("/tickets/{ticket_id}/reply", response_model=MessageResponse)
async def reply_to_ticket(
    ticket_id: str,
    body: ReplyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=404, detail="Ticket not found")

    sender_role = "admin" if user.role == "admin" else "user"

    message = TicketMessage(
        ticket_id=ticket_id,
        sender_id=user.id,
        sender_role=sender_role,
        content=body.content,
    )
    db.add(message)

    # If admin replies to open ticket, set to in_progress
    if sender_role == "admin" and ticket.status == "open":
        ticket.status = "in_progress"

    await db.commit()
    await db.refresh(message)

    return MessageResponse(
        id=message.id, sender_id=message.sender_id,
        sender_role=message.sender_role,
        sender_name=user.name or user.email,
        content=message.content, created_at=message.created_at,
    )


# ========================
# ADMIN ENDPOINTS
# ========================

class AdminTicketStats(BaseModel):
    total: int
    open: int
    in_progress: int
    resolved: int
    closed: int
    urgent: int


@router.get("/admin/stats", response_model=AdminTicketStats)
async def admin_ticket_stats(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    total = (await db.execute(select(func.count()).select_from(SupportTicket))).scalar() or 0
    open_count = (await db.execute(select(func.count()).where(SupportTicket.status == "open"))).scalar() or 0
    in_progress = (await db.execute(select(func.count()).where(SupportTicket.status == "in_progress"))).scalar() or 0
    resolved = (await db.execute(select(func.count()).where(SupportTicket.status == "resolved"))).scalar() or 0
    closed = (await db.execute(select(func.count()).where(SupportTicket.status == "closed"))).scalar() or 0
    urgent = (await db.execute(select(func.count()).where(SupportTicket.priority == "urgent"))).scalar() or 0

    return AdminTicketStats(
        total=total, open=open_count, in_progress=in_progress,
        resolved=resolved, closed=closed, urgent=urgent,
    )


@router.get("/admin/tickets", response_model=list[TicketResponse])
async def admin_list_tickets(
    status: str = Query(default=""),
    priority: str = Query(default=""),
    category: str = Query(default=""),
    search: str = Query(default=""),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(SupportTicket).order_by(desc(SupportTicket.updated_at))

    if status:
        query = query.where(SupportTicket.status == status)
    if priority:
        query = query.where(SupportTicket.priority == priority)
    if category:
        query = query.where(SupportTicket.category == category)
    if search:
        query = query.where(SupportTicket.subject.ilike(f"%{search}%"))

    result = await db.execute(query)
    tickets = result.scalars().all()

    # Get user info
    user_ids = list(set(t.user_id for t in tickets))
    user_map = {}
    if user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in users_result.scalars().all():
            user_map[u.id] = {"email": u.email, "name": u.name or ""}

    items = []
    for t in tickets:
        msg_count = (await db.execute(
            select(func.count()).where(TicketMessage.ticket_id == t.id)
        )).scalar() or 0

        u_info = user_map.get(t.user_id, {"email": "", "name": ""})
        items.append(TicketResponse(
            id=t.id, user_id=t.user_id, user_email=u_info["email"],
            user_name=u_info["name"], subject=t.subject, status=t.status,
            priority=t.priority, category=t.category, assigned_to=t.assigned_to,
            messages_count=msg_count, created_at=t.created_at,
            updated_at=t.updated_at, resolved_at=t.resolved_at,
        ))
    return items


@router.patch("/admin/tickets/{ticket_id}", response_model=TicketResponse)
async def admin_update_ticket(
    ticket_id: str,
    body: UpdateTicketRequest,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if body.status is not None:
        ticket.status = body.status
        if body.status == "resolved":
            ticket.resolved_at = datetime.now(timezone.utc)
    if body.priority is not None:
        ticket.priority = body.priority
    if body.assigned_to is not None:
        ticket.assigned_to = body.assigned_to

    await db.commit()
    await db.refresh(ticket)

    owner_result = await db.execute(select(User).where(User.id == ticket.user_id))
    owner = owner_result.scalar_one_or_none()

    msg_count = (await db.execute(
        select(func.count()).where(TicketMessage.ticket_id == ticket.id)
    )).scalar() or 0

    return TicketResponse(
        id=ticket.id, user_id=ticket.user_id,
        user_email=owner.email if owner else "",
        user_name=owner.name if owner else "",
        subject=ticket.subject, status=ticket.status,
        priority=ticket.priority, category=ticket.category,
        assigned_to=ticket.assigned_to, messages_count=msg_count,
        created_at=ticket.created_at, updated_at=ticket.updated_at,
        resolved_at=ticket.resolved_at,
    )
