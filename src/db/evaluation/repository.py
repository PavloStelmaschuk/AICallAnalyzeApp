import logging
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.call.model import Call, CallStatus
from src.db.call.repository import CallRepository
from src.db.evaluation.model import CallEvaluation
from src.schemas.evaluation import CallEvaluationResult

logger = logging.getLogger(__name__)


class EvaluationRepositoryInterface(Protocol):
    """Інтерфейс для збереження та отримання результатів оцінки дзвінків."""

    async def get_by_call_id(self, call_id: int) -> CallEvaluation | None:
        """Отримує оцінку за ідентифікатором дзвінка."""
        ...

    async def save_evaluation(
        self,
        call: Call,
        transcript: str,
        evaluation_result: CallEvaluationResult,
    ) -> CallEvaluation:
        """Зберігає оцінку якості та транскрипт, переводячи дзвінок у COMPLETED."""
        ...


class EvaluationRepository(EvaluationRepositoryInterface):
    """SQLAlchemy реалізація репозиторію оцінки дзвінків."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._call_repo = CallRepository(session)

    async def get_by_call_id(self, call_id: int) -> CallEvaluation | None:
        stmt = select(CallEvaluation).where(CallEvaluation.call_id == call_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def save_evaluation(
        self,
        call: Call,
        transcript: str,
        evaluation_result: CallEvaluationResult,
    ) -> CallEvaluation:
        evaluation = CallEvaluation(
            call_id=call.id,
            transcript=transcript,
            overall_score=evaluation_result.overall_score,
            summary=evaluation_result.summary,
            criteria_scores=[
                item.model_dump() for item in evaluation_result.criteria_scores
            ],
            strengths=evaluation_result.strengths,
            weaknesses=evaluation_result.weaknesses,
            recommendations=evaluation_result.recommendations,
        )
        self.session.add(evaluation)
        await self._call_repo.update_status(call=call, status=CallStatus.COMPLETED)
        return evaluation

