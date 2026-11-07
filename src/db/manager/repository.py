import logging
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.manager.model import Manager

logger = logging.getLogger(__name__)


class ManagerRepositoryInterface(Protocol):
    """Інтерфейс для роботи з менеджерами."""

    async def get_by_name(self, name: str) -> Manager | None:
        """Отримує менеджера за ім'ям."""
        ...

    async def get_by_id(self, manager_id: int) -> Manager | None:
        """Отримує менеджера за ідентифікатором."""
        ...

    async def create(self, name: str, drive_folder_id: str | None = None) -> Manager:
        """Створює нового менеджера."""
        ...

    async def get_or_create(
        self, name: str, drive_folder_id: str | None = None
    ) -> tuple[Manager, bool]:
        """Знаходить або створює менеджера (повертає менеджера та флаг чи був створений)."""
        ...


class ManagerRepository(ManagerRepositoryInterface):
    """SQLAlchemy реалізація репозиторію менеджерів."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_name(self, name: str) -> Manager | None:
        stmt = select(Manager).where(Manager.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, manager_id: int) -> Manager | None:
        stmt = select(Manager).where(Manager.id == manager_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, name: str, drive_folder_id: str | None = None) -> Manager:
        manager = Manager(name=name, drive_folder_id=drive_folder_id)
        self.session.add(manager)
        await self.session.flush()
        logger.info("Створено нового менеджера в БД: %s (id=%s)", name, manager.id)
        return manager

    async def get_or_create(
        self, name: str, drive_folder_id: str | None = None
    ) -> tuple[Manager, bool]:
        existing = await self.get_by_name(name)
        if existing is not None:
            return existing, False

        manager = await self.create(name=name, drive_folder_id=drive_folder_id)
        return manager, True

