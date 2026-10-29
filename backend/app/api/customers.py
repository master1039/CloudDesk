"""Viewer-protected customer context routes for Phase 4."""

from __future__ import annotations

from typing import Annotated

from app.core.database import get_session
from app.core.security import require_role
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import Role
from app.schemas.customers import (
    CustomerDetail,
    CustomerListParams,
    CustomerListResponse,
)
from app.services.customer_service import CustomerNotFoundError, CustomerService
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])
ViewerUser = Annotated[AuthenticatedUser, Depends(require_role(Role.VIEWER))]
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]
CustomerQuery = Annotated[CustomerListParams, Query()]


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    params: CustomerQuery,
    _: ViewerUser,
    session: DatabaseSession,
) -> CustomerListResponse:
    """List customer account summaries with contract filters and pagination."""

    return await CustomerService(session).list_customers(params)


@router.get("/{customer_id}", response_model=CustomerDetail)
async def get_customer(
    customer_id: str,
    _: ViewerUser,
    session: DatabaseSession,
) -> CustomerDetail:
    """Return the bounded customer, subscription, workspace, ticket, and memory context (F4)."""

    try:
        return await CustomerService(session).get_customer(customer_id)
    except CustomerNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        ) from error

