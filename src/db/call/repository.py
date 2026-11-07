import logging
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.call.model import Call, CallStatus

logger = logging.getLogger(__name__)


class CallRepositoryInterface(Protocol):
    async def get_by_drive_id(self, drive_file_id: str) -> Call | None:
        ...

    async def get_by_id(self, call_id: int) -> Call | None:
        ...

    async def create(
        self,
        drive_file_id: str,
        file_name: str,
        manager_id: int,
        call_type: str,
        status: CallStatus = CallStatus.PROCESSING,
    ) -> Call:
        ...

    async def update_status(
        self,
        call: Call,
        status: CallStatus,
        error_message: str | None = None,
    ) -> None:
        ...


class CallRepository(CallRepositoryInterface):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_drive_id(self, drive_file_id: str) -> Call | None:
        stmt = select(Call).where(Call.drive_file_id == drive_file_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, call_id: int) -> Call | None:
        stmt = select(Call).where(Call.id == call_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        drive_file_id: str,
        file_name: str,
        manager_id: int,
        call_type: str,
        status: CallStatus = CallStatus.PROCESSING,
    ) -> Call:
        call = Call(
            drive_file_id=drive_file_id,
            file_name=file_name,
            manager_id=manager_id,
            call_type=call_type,
            status=status,
        )
        self.session.add(call)
        await self.session.flush()
        return call

    async def update_status(
        self,
        call: Call,
        status: CallStatus,
        error_message: str | None = None,
    ) -> None:
        call.status = status
        call.error_message = error_message
        call.processed_at = datetime.now(timezone.utc)
        await self.session.commit()

