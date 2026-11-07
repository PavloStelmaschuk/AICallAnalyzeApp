from pydantic import BaseModel, Field


class CriterionScore(BaseModel):
    """Оцінка за окремим критерієм якості розмови."""

    criterion: str = Field(description="Назва критерію оцінювання")
    score: int = Field(ge=0, le=10, description="Оцінка від 0 до 10")
    comment: str = Field(description="Коротке обґрунтування оцінки з прикладами з розмови")


class CallEvaluationResult(BaseModel):
    """Структурована відповідь від Gemini з оцінкою якості дзвінка (Нода 50)."""

    overall_score: int = Field(
        ge=0,
        le=100,
        description="Загальна підсумкова оцінка якості дзвінка від 0 до 100",
    )
    summary: str = Field(
        description="Короткий зміст розмови (про що говорили, результат дзвінка)"
    )
    criteria_scores: list[CriterionScore] = Field(
        description="Детальні оцінки за кожним критерієм"
    )
    strengths: list[str] = Field(
        description="Сильні сторони менеджера у цій розмові"
    )
    weaknesses: list[str] = Field(
        description="Помилки або зони росту менеджера у цій розмові"
    )
    recommendations: str = Field(
        description="Конкретні поради менеджеру для покращення наступних дзвінків"
    )

