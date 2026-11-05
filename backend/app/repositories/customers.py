"""Customer, account-context, and durable-memory persistence."""

from __future__ import annotations

from collections.abc import Sequence

from app.models import Customer, CustomerMemory, Subscription
from app.schemas.common import MemoryType, SubscriptionPlan
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from .base import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    model = Customer

    @staticmethod
    def _apply_filters(
        statement: Select,
        *,
        search: str | None,
        plan: SubscriptionPlan | None,
    ) -> Select:
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Customer.name.ilike(pattern),
                    Customer.email.ilike(pattern),
                    Customer.company.ilike(pattern),
                )
            )
        if plan is not None:
            statement = statement.where(Subscription.plan == plan)
        return statement

    async def get_by_email(self, email: str) -> Customer | None:
        statement = select(Customer).where(func.lower(Customer.email) == email.strip().lower())
        return await self.session.scalar(statement)

    async def get_by_external_ref(self, external_ref: str) -> Customer | None:
        return await self.session.scalar(
            select(Customer).where(Customer.external_ref == external_ref)
        )

    async def get_with_context(self, customer_id: str) -> Customer | None:
        """Load subscription and workspace account context for F4."""

        statement = (
            select(Customer)
            .where(Customer.id == customer_id)
            .options(
                selectinload(Customer.subscription),
                selectinload(Customer.workspaces),
            )
        )
        return await self.session.scalar(statement)

    async def list_filtered(
        self,
        *,
        search: str | None = None,
        plan: SubscriptionPlan | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Customer]:
        statement = self._apply_filters(
            select(Customer)
            .outerjoin(Customer.subscription)
            .options(
                selectinload(Customer.subscription),
                selectinload(Customer.workspaces),
            ),
            search=search,
            plan=plan,
        )
        statement = statement.order_by(Customer.name, Customer.id)
        statement = self._page(statement, offset=offset, limit=limit)
        return (await self.session.scalars(statement)).all()

    async def count_filtered(
        self,
        *,
        search: str | None = None,
        plan: SubscriptionPlan | None = None,
    ) -> int:
        statement = self._apply_filters(
            select(func.count(Customer.id))
            .select_from(Customer)
            .outerjoin(Customer.subscription),
            search=search,
            plan=plan,
        )
        return int((await self.session.scalar(statement)) or 0)


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
        statement = statement.order_by(CustomerMemory.created_at.desc(), CustomerMemory.id.desc())
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
