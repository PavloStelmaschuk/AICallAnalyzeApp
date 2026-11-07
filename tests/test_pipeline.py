from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from src.config import DriveStructureConfig, load_yaml_config
from src.db.call import Call, CallStatus
from src.db.evaluation import CallEvaluation
from src.db.manager import Manager
from src.db.session import build_engine, build_session_factory, init_db
from src.schemas.evaluation import CallEvaluationResult, CriterionScore
from src.services.gdrive import DriveAudioFile
from src.services.pipeline import CallProcessingPipeline


def test_drive_structure_pattern_parsing() -> None:
    cfg = DriveStructureConfig(
        path_pattern="{manager_name}/{call_type}",
        valid_call_types=["cold_call", "consultation"],
    )
    parsed = cfg.parse_folder_parts(["Олена Коваль", "cold_call"])
    assert parsed is not None
    assert parsed.manager_name == "Олена Коваль"
    assert parsed.call_type == "cold_call"
    assert cfg.is_valid_call_type(parsed.call_type) is True
    assert cfg.is_valid_call_type("spam_folder") is False

    # Альтернативний порядок папок у конфізі
    reversed_cfg = DriveStructureConfig(path_pattern="{call_type}/{manager_name}")
    parsed_rev = reversed_cfg.parse_folder_parts(["consultation", "Іван Франко"])
    assert parsed_rev is not None
    assert parsed_rev.manager_name == "Іван Франко"
    assert parsed_rev.call_type == "consultation"


def test_prompts_rendering_from_yaml() -> None:
    config = load_yaml_config("./config.yaml")

    # Специфічний промпт для cold_call
    cold_prompt = config.prompts.render_evaluation_prompt(
        manager_name="Петро",
        call_type="cold_call",
        transcript="[00:01] Менеджер: Добрий день!",
    )
    assert "Cold Calling QA" in cold_prompt
    assert "Петро" in cold_prompt

    # Дефолтний промпт для іншого типу дзвінка
    default_prompt = config.prompts.render_evaluation_prompt(
        manager_name="Марія",
        call_type="support",
        transcript="[00:01] Клієнт: Алло",
    )
    assert "Тип дзвінка: support" in default_prompt
    assert "Марія" in default_prompt


@pytest.mark.asyncio
async def test_full_pipeline_flow(tmp_path: Path) -> None:
    config = load_yaml_config("./config.yaml")
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = build_session_factory(engine)

    # Фейковий тимчасовий аудіофайл
    dummy_audio = tmp_path / "call_1.mp3"
    dummy_audio.write_bytes(b"fake-mp3-bytes")

    # Мокаємо GoogleDriveService
    gdrive_mock = MagicMock()
    gdrive_mock.list_audio_files = AsyncMock(
        return_value=[
            # 1. Валідний файл (створить менеджера, транскрибує, оцінить і збереже в БД)
            DriveAudioFile(
                file_id="file_valid_1",
                file_name="call_1.mp3",
                mime_type="audio/mpeg",
                folder_parts=["Олександр Сидоренко", "cold_call"],
            ),
            # 2. Файл у невалідній папці типу дзвінка (має бути IGNORED за схемою)
            DriveAudioFile(
                file_id="file_invalid_folder_2",
                file_name="call_2.mp3",
                mime_type="audio/mpeg",
                folder_parts=["Олександр Сидоренко", "unknown_folder"],
            ),
        ]
    )
    gdrive_mock.download_audio_file = AsyncMock(return_value=dummy_audio)

    # Мокаємо GeminiService
    gemini_mock = MagicMock()
    gemini_mock.upload_audio = AsyncMock(return_value=MagicMock(name="files/abc123"))
    gemini_mock.transcribe_audio = AsyncMock(
        return_value="[00:01] Менеджер: Добрий день!\n[00:05] Клієнт: Вітаю."
    )
    gemini_mock.evaluate_call_quality = AsyncMock(
        return_value=CallEvaluationResult(
            overall_score=88,
            summary="Успішний холодний дзвінок, призначено демо.",
            criteria_scores=[
                CriterionScore(
                    criterion="Привітання",
                    score=9,
                    comment="Чітке представлення",
                )
            ],
            strengths=["Впевнений голос", "Чітке закриття на демо"],
            weaknesses=["Коротка пауза перед відповіддю"],
            recommendations="Продовжувати у тому ж дусі.",
        )
    )
    gemini_mock.delete_uploaded_file = AsyncMock()

    pipeline = CallProcessingPipeline(
        config=config,
        session_factory=session_factory,
        gdrive_service=gdrive_mock,
        gemini_service=gemini_mock,
    )

    # Перший цикл поллінгу
    stats = await pipeline.run_polling_cycle()
    assert stats == {"completed": 1, "ignored": 1, "failed": 0, "skipped": 0}

    # Другий цикл поллінгу — файли вже в БД, тому мають бути пропущені (skipped)
    stats_second = await pipeline.run_polling_cycle()
    assert stats_second == {"completed": 0, "ignored": 0, "failed": 0, "skipped": 2}

    # Перевіряємо записи в БД
    async with session_factory() as session:
        managers = (await session.execute(select(Manager))).scalars().all()
        assert len(managers) == 1
        assert managers[0].name == "Олександр Сидоренко"

        calls = (await session.execute(select(Call))).scalars().all()
        assert len(calls) == 2

        evaluations = (await session.execute(select(CallEvaluation))).scalars().all()
        assert len(evaluations) == 1
        assert evaluations[0].overall_score == 88
        assert "Добрий день" in evaluations[0].transcript

    await engine.dispose()
