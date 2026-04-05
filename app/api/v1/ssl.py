"""SSL certificate API endpoints."""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models.user import User
from app.models.endpoint import Endpoint
from app.models.ssl_cert import SslCertificate
from app.dependencies import get_current_user
from app.services.ssl_checker import check_ssl_certificate

router = APIRouter(prefix="/ssl", tags=["SSL"])


class SslCertResponse(BaseModel):
    id: str
    endpoint_id: str
    issuer: str | None
    subject: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    days_remaining: int | None
    is_valid: bool
    error: str | None
    last_checked_at: datetime

    model_config = {"from_attributes": True}


@router.post("/check/{endpoint_id}", response_model=SslCertResponse)
async def check_endpoint_ssl(
    endpoint_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check SSL cert for an endpoint and store the result."""
    # Verify ownership
    ep_result = await db.execute(
        select(Endpoint).where(Endpoint.id == endpoint_id, Endpoint.user_id == user.id)
    )
    endpoint = ep_result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    # Run SSL check in thread (it's blocking)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, check_ssl_certificate, endpoint.url)

    # Upsert SSL cert record
    existing_result = await db.execute(
        select(SslCertificate).where(SslCertificate.endpoint_id == endpoint_id)
    )
    cert = existing_result.scalar_one_or_none()

    if cert:
        cert.issuer = result["issuer"]
        cert.subject = result["subject"]
        cert.valid_from = result["valid_from"]
        cert.valid_to = result["valid_to"]
        cert.days_remaining = result["days_remaining"]
        cert.is_valid = result["is_valid"]
        cert.error = result["error"]
        cert.last_checked_at = datetime.utcnow()
    else:
        cert = SslCertificate(
            endpoint_id=endpoint_id,
            issuer=result["issuer"],
            subject=result["subject"],
            valid_from=result["valid_from"],
            valid_to=result["valid_to"],
            days_remaining=result["days_remaining"],
            is_valid=result["is_valid"],
            error=result["error"],
        )
        db.add(cert)

    await db.commit()
    await db.refresh(cert)
    return cert


@router.get("/{endpoint_id}", response_model=SslCertResponse)
async def get_endpoint_ssl(
    endpoint_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get stored SSL cert info for an endpoint."""
    # Verify ownership
    ep_result = await db.execute(
        select(Endpoint.id).where(Endpoint.id == endpoint_id, Endpoint.user_id == user.id)
    )
    if not ep_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Endpoint not found")

    cert_result = await db.execute(
        select(SslCertificate).where(SslCertificate.endpoint_id == endpoint_id)
    )
    cert = cert_result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="No SSL check recorded")

    return cert
