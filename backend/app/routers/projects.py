import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import gitea_client
from app.db import get_db
from app.models import Project, User
from app.schemas import ProjectCreate, ProjectOut
from app.security.csrf import verify_csrf
from app.security.deps import get_current_user

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, dependencies=[Depends(verify_csrf)])
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo_name = f"project-{uuid.uuid4().hex[:12]}"
    repo_path = await gitea_client.create_repo(repo_name)

    project = Project(user_id=user.id, name=body.name, git_repo_path=repo_path)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Project).where(Project.user_id == user.id))
    return result.all()


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
