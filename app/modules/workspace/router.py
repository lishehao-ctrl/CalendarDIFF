from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.session import get_db
from app.modules.workspace.schemas import WorkspaceBootstrapResponse
from app.modules.workspace.service import build_workspace_bootstrap
from app.state import SchedulerStatus

router = APIRouter(prefix="/v1/workspace", tags=["workspace"], dependencies=[Depends(require_api_key)])


@router.get("/bootstrap", response_model=WorkspaceBootstrapResponse)
def get_workspace_bootstrap(request: Request, db: Session = Depends(get_db)) -> WorkspaceBootstrapResponse:
    scheduler_runner = getattr(request.app.state, "scheduler_runner", None)
    scheduler_status: SchedulerStatus | None = getattr(scheduler_runner, "status", None)
    return build_workspace_bootstrap(db, scheduler_status=scheduler_status)
