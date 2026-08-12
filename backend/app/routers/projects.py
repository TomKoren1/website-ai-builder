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

# Committed once into every new project repo (Flow B — see
# docs/errors.md and infra/PHASE4-RUNBOOK-B.md). Deliberately identical
# across every project and entirely parameterized via workflow_dispatch
# inputs, rather than templated per-project — the bucket name, deployment
# id, and callback token all come from the dispatch call in chat.py's
# push(), so this file never needs to change per project. AWS/backend
# endpoints come from org-level Gitea Actions secrets (see the runbook),
# not from anything committed here.
_CI_WORKFLOW = """\
name: Deploy to S3
on:
  workflow_dispatch:
    inputs:
      bucket_name:
        required: true
      project_id:
        required: true
      deployment_id:
        required: true
      callback_token:
        required: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Validate site content
        run: test -f index.html || (echo "::error::no index.html at repo root" && exit 1)

      - name: Install AWS CLI
        # Gitea's own ubuntu-latest runner image (docker.gitea.com/runner-images)
        # is a real Ubuntu base, unlike GitHub's hosted runners it does NOT
        # come with the AWS CLI preinstalled. The official installer bundle
        # (not apt/pip) is what actually works unconditionally here — apt has
        # no awscli package on Ubuntu, and pip's externally-managed-environment
        # restriction on 24.04 blocks a plain `pip install`.
        run: |
          curl -sS "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
          unzip -q awscliv2.zip
          ./aws/install
          rm -rf awscliv2.zip aws

      - name: Assume ci-deploy-role
        run: |
          creds=$(aws sts assume-role \\
            --endpoint-url "$AWS_ENDPOINT_URL" \\
            --role-arn "$CI_DEPLOY_ROLE_ARN" \\
            --role-session-name gitea-actions \\
            --query 'Credentials' --output json)
          echo "AWS_ACCESS_KEY_ID=$(echo $creds | jq -r .AccessKeyId)" >> "$GITEA_ENV"
          echo "AWS_SECRET_ACCESS_KEY=$(echo $creds | jq -r .SecretAccessKey)" >> "$GITEA_ENV"
          echo "AWS_SESSION_TOKEN=$(echo $creds | jq -r .SessionToken)" >> "$GITEA_ENV"
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.CI_DEPLOY_APP_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.CI_DEPLOY_APP_SECRET_ACCESS_KEY }}
          AWS_ENDPOINT_URL: ${{ secrets.AWS_ENDPOINT_URL }}
          CI_DEPLOY_ROLE_ARN: ${{ secrets.CI_DEPLOY_ROLE_ARN }}
          # The AWS CLI refuses to run any command with no region configured,
          # even against LocalStack where the region is barely meaningful —
          # matches the us-east-1 default used everywhere else in this
          # project (backend's Settings.aws_region, reverse-proxy's).
          AWS_DEFAULT_REGION: us-east-1

      - name: Sync to S3
        id: sync
        continue-on-error: true
        run: >
          aws s3 sync . "s3://${{ inputs.bucket_name }}"
          --endpoint-url "$AWS_ENDPOINT_URL" --delete
          --exclude ".git/*" --exclude ".gitea/*"
        env:
          AWS_ENDPOINT_URL: ${{ secrets.AWS_ENDPOINT_URL }}
          AWS_DEFAULT_REGION: us-east-1

      - name: Report status to backend
        if: always()
        run: |
          curl -sf -X POST "$BACKEND_URL/projects/${{ inputs.project_id }}/deployments/${{ inputs.deployment_id }}/callback" \\
            -H "Content-Type: application/json" \\
            -d "{\\"status\\": \\"${{ steps.sync.outcome == 'success' && 'success' || 'failed' }}\\", \\"token\\": \\"${{ inputs.callback_token }}\\"}"
        env:
          BACKEND_URL: ${{ secrets.BACKEND_URL }}
"""


@router.post("", response_model=ProjectOut, dependencies=[Depends(verify_csrf)])
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo_name = f"project-{uuid.uuid4().hex[:12]}"
    repo_path = await gitea_client.create_repo(repo_name)
    await gitea_client.commit_files(
        repo_path,
        {".gitea/workflows/deploy.yml": _CI_WORKFLOW},
        "Add deploy workflow",
    )

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
