from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aws.s3 import ensure_bucket_exists
from app.db import get_db
from app.models import Domain, Project, User
from app.schemas import DomainCreate, DomainOut
from app.security.csrf import verify_csrf
from app.security.deps import get_current_user

router = APIRouter(prefix="/domains", tags=["domains"])


@router.post("", response_model=DomainOut, dependencies=[Depends(verify_csrf)])
async def create_domain(
    body: DomainCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, body.project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    # One bucket per project, reused across that project's domains (a
    # project can only ever have one deployed site, whatever domain(s)
    # point at it) — deterministic from project_id, never derived from
    # domain_name or any other client input. See DomainCreate's comment
    # for why that matters.
    existing = await db.scalar(select(Domain).where(Domain.project_id == body.project_id))
    bucket_name = existing.s3_bucket_name if existing else f"site-{project.id}"
    ensure_bucket_exists(bucket_name)

    domain = Domain(
        project_id=body.project_id,
        domain_name=body.domain_name,
        s3_bucket_name=bucket_name,
    )
    db.add(domain)
    await db.commit()
    await db.refresh(domain)
    return domain
