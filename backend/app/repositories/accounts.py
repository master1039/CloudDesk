"""Agent profile and customer-account resource persistence."""

from __future__ import annotations

from collections.abc import Sequence

from app.models import Product, Profile, Subscription, Workspace
from sqlalchemy import func, select

from .base import BaseRepository


class ProfileRepository(BaseRepository[Profile]):
    model = Profile

    async def get_by_email(self, email: str) -> Profile | None:
        statement = select(Profile).where(func.lower(Profile.email) == email.strip().lower())
        return await self.session.scalar(statement)


class SubscriptionRepository(BaseRepository[Subscription]):
    model = Subscription

    async def get_for_customer(self, customer_id: str) -> Subscription | None:
        return await self.session.scalar(
            select(Subscription).where(Subscription.customer_id == customer_id)
        )


class WorkspaceRepository(BaseRepository[Workspace]):
    model = Workspace

    async def get_by_slug(self, slug: str) -> Workspace | None:
        return await self.session.scalar(select(Workspace).where(Workspace.slug == slug))

    async def list_for_customer(self, customer_id: str) -> Sequence[Workspace]:
        statement = (
            select(Workspace)
            .where(Workspace.customer_id == customer_id)
            .order_by(Workspace.name, Workspace.id)
        )
        return (await self.session.scalars(statement)).all()


class ProductRepository(BaseRepository[Product]):
    model = Product

    async def get_by_slug(self, slug: str) -> Product | None:
        return await self.session.scalar(select(Product).where(Product.slug == slug))

    async def list_active(self) -> Sequence[Product]:
        statement = select(Product).where(Product.is_active.is_(True)).order_by(Product.name)
        return (await self.session.scalars(statement)).all()
