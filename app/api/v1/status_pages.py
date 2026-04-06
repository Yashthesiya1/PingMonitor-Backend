"""Status pages API — user-managed public status pages."""
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.user import User
from app.models.endpoint import Endpoint
from app.models.check import EndpointCheck
from app.models.status_page import StatusPage, StatusPageEndpoint
from app.dependencies import get_current_user

router = APIRouter(prefix="/status-pages", tags=["Status Pages"])


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:100] if slug else "status"


# ========== User-facing (authenticated) ==========

class StatusPageCreate(BaseModel):
    name: str = Field(max_length=100)
    slug: str | None = None
    description: str | None = None
    primary_color: str = "#6c5ce7"
    endpoint_ids: list[str] = []


class StatusPageUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    primary_color: str | None = None
    logo_url: str | None = None
    is_public: bool | None = None


class StatusPageEndpointItem(BaseModel):
    id: str
    endpoint_id: str
    display_name: str | None
    display_order: int

    model_config = {"from_attributes": True}


class StatusPageResponse(BaseModel):
    id: str
    user_id: str
    slug: str
    name: str
    description: str | None
    logo_url: str | None
    primary_color: str
    custom_domain: str | None
    is_public: bool
    created_at: datetime
    endpoints: list[StatusPageEndpointItem] = []

    model_config = {"from_attributes": True}


@router.get("", response_model=list[StatusPageResponse])
async def list_status_pages(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StatusPage).where(StatusPage.user_id == user.id).order_by(StatusPage.created_at.desc())
    )
    pages = result.scalars().all()

    items = []
    for p in pages:
        eps_result = await db.execute(
            select(StatusPageEndpoint).where(StatusPageEndpoint.status_page_id == p.id)
        )
        items.append(StatusPageResponse(
            id=str(p.id), user_id=str(p.user_id), slug=p.slug, name=p.name,
            description=p.description, logo_url=p.logo_url, primary_color=p.primary_color,
            custom_domain=p.custom_domain, is_public=p.is_public, created_at=p.created_at,
            endpoints=[StatusPageEndpointItem.model_validate(e) for e in eps_result.scalars().all()],
        ))
    return items


@router.post("", response_model=StatusPageResponse, status_code=201)
async def create_status_page(
    body: StatusPageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    slug = body.slug or _slugify(body.name)

    # Check slug is unique
    existing = await db.execute(select(StatusPage).where(StatusPage.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Slug already taken, try a different name")

    page = StatusPage(
        user_id=user.id,
        slug=slug,
        name=body.name,
        description=body.description,
        primary_color=body.primary_color,
    )
    db.add(page)
    await db.flush()

    # Add endpoints
    for i, ep_id in enumerate(body.endpoint_ids):
        # Verify endpoint belongs to user
        ep_check = await db.execute(
            select(Endpoint.id).where(Endpoint.id == ep_id, Endpoint.user_id == user.id)
        )
        if ep_check.scalar_one_or_none():
            db.add(StatusPageEndpoint(
                status_page_id=page.id,
                endpoint_id=ep_id,
                display_order=i,
            ))

    await db.commit()
    await db.refresh(page)

    eps_result = await db.execute(
        select(StatusPageEndpoint).where(StatusPageEndpoint.status_page_id == page.id)
    )
    return StatusPageResponse(
        id=str(page.id), user_id=str(page.user_id), slug=page.slug, name=page.name,
        description=page.description, logo_url=page.logo_url, primary_color=page.primary_color,
        custom_domain=page.custom_domain, is_public=page.is_public, created_at=page.created_at,
        endpoints=[StatusPageEndpointItem.model_validate(e) for e in eps_result.scalars().all()],
    )


@router.patch("/{page_id}", response_model=StatusPageResponse)
async def update_status_page(
    page_id: str,
    body: StatusPageUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StatusPage).where(StatusPage.id == page_id, StatusPage.user_id == user.id)
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Status page not found")

    if body.name is not None: page.name = body.name
    if body.description is not None: page.description = body.description
    if body.primary_color is not None: page.primary_color = body.primary_color
    if body.logo_url is not None: page.logo_url = body.logo_url
    if body.is_public is not None: page.is_public = body.is_public

    await db.commit()
    await db.refresh(page)

    eps_result = await db.execute(
        select(StatusPageEndpoint).where(StatusPageEndpoint.status_page_id == page.id)
    )
    return StatusPageResponse(
        id=str(page.id), user_id=str(page.user_id), slug=page.slug, name=page.name,
        description=page.description, logo_url=page.logo_url, primary_color=page.primary_color,
        custom_domain=page.custom_domain, is_public=page.is_public, created_at=page.created_at,
        endpoints=[StatusPageEndpointItem.model_validate(e) for e in eps_result.scalars().all()],
    )


@router.delete("/{page_id}")
async def delete_status_page(
    page_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StatusPage).where(StatusPage.id == page_id, StatusPage.user_id == user.id)
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Status page not found")
    await db.delete(page)
    await db.commit()
    return {"message": "Status page deleted"}


class UpdateEndpointsRequest(BaseModel):
    endpoint_ids: list[str]


@router.put("/{page_id}/endpoints")
async def update_status_page_endpoints(
    page_id: str,
    body: UpdateEndpointsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StatusPage).where(StatusPage.id == page_id, StatusPage.user_id == user.id)
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Status page not found")

    # Remove all existing
    await db.execute(delete(StatusPageEndpoint).where(StatusPageEndpoint.status_page_id == page_id))

    # Add new
    for i, ep_id in enumerate(body.endpoint_ids):
        ep_check = await db.execute(
            select(Endpoint.id).where(Endpoint.id == ep_id, Endpoint.user_id == user.id)
        )
        if ep_check.scalar_one_or_none():
            db.add(StatusPageEndpoint(status_page_id=page_id, endpoint_id=ep_id, display_order=i))

    await db.commit()
    return {"message": "Endpoints updated"}
