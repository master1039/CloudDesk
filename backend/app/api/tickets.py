"""Protected ticket HTTP routes for Phase 4."""

from __future__ import annotations

from typing import Annotated

from app.core.database import get_session
from app.core.security import require_role
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import Role
from app.schemas.tickets import (
    CreateTicketRequest,
    TicketDetail,
    TicketListParams,
    TicketListResponse,
)
from app.services.ticket_service import (
    CustomerNotFoundError,
    TicketNotFoundError,
    TicketService,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/tickets", tags=["tickets"])
ViewerUser = Annotated[AuthenticatedUser, Depends(require_role(Role.VIEWER))]
AgentUser = Annotated[AuthenticatedUser, Depends(require_role(Role.AGENT))]
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]
TicketQuery = Annotated[TicketListParams, Query()]


@router.get("", response_model=TicketListResponse)
async def list_tickets(
    params: TicketQuery,
    _: ViewerUser,
    session: DatabaseSession,
) -> TicketListResponse:
    """List tickets using the documented filters and stable pagination envelope."""

    return await TicketService(session).list_tickets(params)


@router.post("", response_model=TicketDetail, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    request: CreateTicketRequest,
    _: AgentUser,
    session: DatabaseSession,
) -> TicketDetail:
    """Create an unclassified ticket from an approved support channel (F1)."""

    try:
        return await TicketService(session).create_ticket(request)
    except CustomerNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        ) from error


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket(
    ticket_id: str,
    _: ViewerUser,
    session: DatabaseSession,
) -> TicketDetail:
    """Return one ticket with messages and links to related support context."""

    try:
        return await TicketService(session).get_ticket(ticket_id)
    except TicketNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        ) from error

