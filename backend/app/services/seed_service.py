"""Idempotent loader for the checked-in CloudDesk demo dataset."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.database import create_tables, dispose_database, get_session_factory
from app.models import (
    Customer,
    CustomerMemory,
    Incident,
    Product,
    Profile,
    Subscription,
    SupportArticle,
    Ticket,
    TicketMessage,
    Workspace,
)
from app.schemas.common import (
    Channel,
    IncidentStatus,
    MemoryType,
    MessageDirection,
    Role,
    Severity,
    SubscriptionPlan,
    SubscriptionStatus,
    TicketCategory,
    TicketStatus,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

SEEDED_MODELS = (
    Profile,
    Customer,
    Product,
    SupportArticle,
    Incident,
    Ticket,
    CustomerMemory,
)


@dataclass(frozen=True)
class SeedResult:
    seeded: bool
    profiles: int
    customers: int
    tickets: int
    articles: int


def _load_json(directory: Path, filename: str) -> list[dict[str, Any]]:
    path = directory / filename
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Missing demo data file: {path}") from error
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{path} must contain a JSON array of objects")
    return payload


def _parse_article(path: Path, root: Path) -> SupportArticle:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Knowledge article lacks front matter: {path}")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"Knowledge article has unclosed front matter: {path}") from error

    metadata: dict[str, str] = {}
    for line in lines[1:closing]:
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"Invalid front matter in {path}: {line}")
        metadata[key.strip()] = value.strip().strip('"')

    required = {"title", "category", "tags", "summary"}
    missing = required - metadata.keys()
    if missing:
        raise ValueError(f"Knowledge article {path} is missing: {sorted(missing)}")
    raw_tags = metadata["tags"].strip("[]")
    tags = [tag.strip().strip('"') for tag in raw_tags.split(",") if tag.strip()]
    body = "\n".join(lines[closing + 1 :]).strip()
    if not body:
        raise ValueError(f"Knowledge article body is empty: {path}")

    return SupportArticle(
        slug=path.stem,
        title=metadata["title"],
        category=TicketCategory(metadata["category"]),
        tags=tags,
        summary=metadata["summary"],
        body=body,
        source_path=path.relative_to(root).as_posix(),
    )


async def _current_result(session: AsyncSession, *, seeded: bool) -> SeedResult:
    async def count(model: type[Any]) -> int:
        value = await session.scalar(select(func.count()).select_from(model))
        return int(value or 0)

    return SeedResult(
        seeded=seeded,
        profiles=await count(Profile),
        customers=await count(Customer),
        tickets=await count(Ticket),
        articles=await count(SupportArticle),
    )


async def bootstrap_demo_data(session: AsyncSession, sample_data_dir: Path) -> SeedResult:
    """Load the complete demo dataset only when all seeded tables are empty."""

    for model in SEEDED_MODELS:
        existing = await session.scalar(select(func.count()).select_from(model))
        if existing:
            return await _current_result(session, seeded=False)

    profiles = [
        Profile(
            email=item["email"],
            display_name=item["display_name"],
            role=Role(item["role"]),
        )
        for item in _load_json(sample_data_dir, "profiles.json")
    ]
    customers = {
        item["external_ref"]: Customer(
            external_ref=item["external_ref"],
            name=item["name"],
            email=item["email"],
            company=item.get("company"),
            phone=item.get("phone"),
            attributes=item.get("attributes", {}),
        )
        for item in _load_json(sample_data_dir, "customers.json")
    }
    for item in _load_json(sample_data_dir, "subscriptions.json"):
        customers[item["customer_ref"]].subscription = Subscription(
            plan=SubscriptionPlan(item["plan"]),
            status=SubscriptionStatus(item.get("status", "active")),
            seats=item["seats"],
            amount=Decimal(str(item["amount"])),
            currency=item.get("currency", "USD"),
            billing_interval=item.get("billing_interval", "monthly"),
            attributes=item.get("attributes", {}),
        )
    workspaces: dict[str, Workspace] = {}
    for item in _load_json(sample_data_dir, "workspaces.json"):
        workspace = Workspace(
            name=item["name"],
            slug=item["slug"],
            storage_used_bytes=item["storage_used_bytes"],
            storage_limit_bytes=item["storage_limit_bytes"],
            settings=item.get("settings", {}),
        )
        customers[item["customer_ref"]].workspaces.append(workspace)
        workspaces[workspace.slug] = workspace

    products = {
        item["slug"]: Product(
            name=item["name"],
            slug=item["slug"],
            description=item.get("description"),
            attributes=item.get("attributes", {}),
        )
        for item in _load_json(sample_data_dir, "products.json")
    }
    session.add_all([*profiles, *customers.values(), *products.values()])
    await session.flush()

    incidents = [
        Incident(
            product=products[item["product_slug"]],
            title=item["title"],
            description=item["description"],
            status=IncidentStatus(item["status"]),
            severity=Severity(item["severity"]),
            affected_services=item["affected_services"],
        )
        for item in _load_json(sample_data_dir, "incidents.json")
    ]
    tickets: list[Ticket] = []
    for item in _load_json(sample_data_dir, "tickets.json"):
        ticket = Ticket(
            display_id=item["display_id"],
            customer=customers[item["customer_ref"]],
            workspace=workspaces.get(item.get("workspace_slug")),
            product=products.get(item.get("product_slug")),
            subject=item["subject"],
            body=item["body"],
            channel=Channel(item["channel"]),
            status=TicketStatus(item.get("status", "new")),
            category=TicketCategory(item["category"]),
            severity=Severity(item["severity"]),
            injection_detected=item.get("injection_detected", False),
            attributes=item.get("attributes", {}),
        )
        ticket.messages.append(
            TicketMessage(
                direction=MessageDirection.INBOUND,
                author_name=customers[item["customer_ref"]].name,
                body=item["body"],
                channel=Channel(item["channel"]),
            )
        )
        tickets.append(ticket)

    memories = [
        CustomerMemory(
            customer=customers[item["customer_ref"]],
            memory_type=MemoryType(item["memory_type"]),
            content=item["content"],
            fingerprint=item["fingerprint"],
            attributes={"resolution": item["resolution"]},
        )
        for item in _load_json(sample_data_dir, "previous_resolutions.json")
    ]
    articles = [
        _parse_article(path, sample_data_dir)
        for path in sorted((sample_data_dir / "knowledge_base").glob("*.md"))
    ]
    if len(articles) != 15:
        raise ValueError(f"Expected 15 knowledge articles, found {len(articles)}")

    session.add_all([*incidents, *tickets, *memories, *articles])
    await session.flush()
    return await _current_result(session, seeded=True)


async def seed_demo_database() -> SeedResult:
    """Create tables and seed the configured database for ``make seed``."""

    from app.core.config import get_settings

    settings = get_settings()
    await create_tables()
    try:
        async with get_session_factory().begin() as session:
            return await bootstrap_demo_data(session, settings.sample_data_dir)
    finally:
        await dispose_database()


def main() -> None:
    result = asyncio.run(seed_demo_database())
    print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()
