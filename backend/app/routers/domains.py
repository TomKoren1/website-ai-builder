from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Domain, Project, User
from app.schemas import DomainCreate, DomainOut
from app.security.deps import get_current_user

router = APIRouter(prefix="/domains", tags=["domains"])


@router.post("", response_model=DomainOut)
async def create_domain(
    body: DomainCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, body.project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    domain = Domain(
        project_id=body.project_id,
        domain_name=body.domain_name,
        s3_bucket_name=body.s3_bucket_name,
    )
    db.add(domain)
    await db.commit()
    await db.refresh(domain)
    return domain
