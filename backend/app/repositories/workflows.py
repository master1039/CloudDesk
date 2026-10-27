"""Workflow trace, action, approval, and escalation persistence."""

from __future__ import annotations

from collections.abc import Sequence

from app.models import (
    ApprovalRequest,
    Escalation,
    ResolutionAction,
    WorkflowEvent,
    WorkflowRun,
)
from app.schemas.common import ApprovalStatus, EscalationStatus, WorkflowStatus
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .base import BaseRepository


class WorkflowRunRepository(BaseRepository[WorkflowRun]):
    model = WorkflowRun

    async def get_by_thread_id(self, thread_id: str) -> WorkflowRun | None:
        return await self.session.scalar(
            select(WorkflowRun).where(WorkflowRun.thread_id == thread_id)
        )

    async def get_with_trace(self, workflow_id: str) -> WorkflowRun | None:
        statement = (
            select(WorkflowRun)
            .where(WorkflowRun.id == workflow_id)
            .options(
                selectinload(WorkflowRun.events),
                selectinload(WorkflowRun.actions),
                selectinload(WorkflowRun.approvals),
                selectinload(WorkflowRun.escalations),
            )
        )
        return await self.session.scalar(statement)

    async def get_active_for_ticket(self, ticket_id: str) -> WorkflowRun | None:
        statement = (
            select(WorkflowRun)
            .where(
                WorkflowRun.ticket_id == ticket_id,
                WorkflowRun.status.in_(
                    (
                        WorkflowStatus.QUEUED,
                        WorkflowStatus.RUNNING,
                        WorkflowStatus.WAITING_ON_APPROVAL,
                    )
                ),
            )
            .order_by(WorkflowRun.created_at.desc())
            .limit(1)
        )
        return await self.session.scalar(statement)


class WorkflowEventRepository(BaseRepository[WorkflowEvent]):
    model = WorkflowEvent

    async def list_for_workflow(self, workflow_id: str) -> Sequence[WorkflowEvent]:
        statement = (
            select(WorkflowEvent)
            .where(WorkflowEvent.workflow_id == workflow_id)
            .order_by(WorkflowEvent.created_at, WorkflowEvent.id)
        )
        return (await self.session.scalars(statement)).all()


class ResolutionActionRepository(BaseRepository[ResolutionAction]):
    model = ResolutionAction

    async def list_for_workflow(self, workflow_id: str) -> Sequence[ResolutionAction]:
        statement = (
            select(ResolutionAction)
            .where(ResolutionAction.workflow_id == workflow_id)
            .order_by(ResolutionAction.created_at, ResolutionAction.id)
        )
        return (await self.session.scalars(statement)).all()


class ApprovalRequestRepository(BaseRepository[ApprovalRequest]):
    model = ApprovalRequest

    async def get_pending_for_workflow(self, workflow_id: str) -> ApprovalRequest | None:
        statement = (
            select(ApprovalRequest)
            .where(
                ApprovalRequest.workflow_id == workflow_id,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
            .order_by(ApprovalRequest.created_at.desc())
            .limit(1)
        )
        return await self.session.scalar(statement)


class EscalationRepository(BaseRepository[Escalation]):
    model = Escalation

    async def list_open_for_ticket(self, ticket_id: str) -> Sequence[Escalation]:
        statement = (
            select(Escalation)
            .where(
                Escalation.ticket_id == ticket_id,
                Escalation.status.in_((EscalationStatus.OPEN, EscalationStatus.IN_PROGRESS)),
            )
            .order_by(Escalation.created_at.desc(), Escalation.id.desc())
        )
        return (await self.session.scalars(statement)).all()
