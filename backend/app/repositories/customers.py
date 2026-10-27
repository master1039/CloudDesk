"""Customer, account-context, and durable-memory persistence."""

from __future__ import annotations

from collections.abc import Sequence

from app.models import Customer, CustomerMemory
from app.schemas.common import MemoryType
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .base import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    model = Customer

    async def get_by_email(self, email: str) -> Customer | None:
        statement = select(Customer).where(func.lower(Customer.email) == email.strip().lower())
        return await self.session.scalar(statement)

    async def get_by_external_ref(self, external_ref: str) -> Customer | None:
        return await self.session.scalar(
            select(Customer).where(Customer.external_ref == external_ref)
        )

    async def get_with_context(self, customer_id: str) -> Customer | None:
        """Load the F4 account context without later lazy database access."""

        statement = (
            select(Customer)
            .where(Customer.id == customer_id)
            .options(
                selectinload(Customer.subscription),
                selectinload(Customer.workspaces),
                selectinload(Customer.tickets),
                selectinload(Customer.memory_notes),
            )
        )
        return await self.session.scalar(statement)


class CustomerMemoryRepository(BaseRepository[CustomerMemory]):
    model = CustomerMemory

    async def list_for_customer(
        self,
        customer_id: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> Sequence[CustomerMemory]:
        statement = select(CustomerMemory).where(CustomerMemory.customer_id == customer_id)
        if memory_type is not None:
            statement = statement.where(CustomerMemory.memory_type == memory_type)
        statement = statement.order_by(CustomerMemory.created_at.desc())
        statement = self._page(statement, offset=0, limit=limit)
        return (await self.session.scalars(statement)).all()

    async def get_by_fingerprint(
        self, customer_id: str, memory_type: MemoryType, fingerprint: str
    ) -> CustomerMemory | None:
        statement = select(CustomerMemory).where(
            CustomerMemory.customer_id == customer_id,
            CustomerMemory.memory_type == memory_type,
            CustomerMemory.fingerprint == fingerprint,
        )
        return await self.session.scalar(statement)
