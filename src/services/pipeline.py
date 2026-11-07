import logging
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import YamlAppConfig
from src.db.call import CallRepository, CallStatus
from src.db.evaluation import EvaluationRepository
from src.db.manager import ManagerRepository
from src.services.gdrive import DriveAudioFile, GoogleDriveService
from src.services.gemini import GeminiService

logger = logging.getLogger(__name__)


class CallProcessingPipeline:
    """
    Оркестратор пайплайну обробки дзвінків:
    1. Тригер Google Drive (виявлення нових аудіофайлів)
    2. Перевірка / створення менеджера в БД
    3. Валідація назви папки (типу дзвінка) згідно з конфігом
    4. Завантаження аудіо -> Upload у Gemini -> Транскрибація -> Оцінка якості
    5. Запис результатів у БД
    """

    def __init__(
        self,
        config: YamlAppConfig,
        session_factory: async_sessionmaker[AsyncSession],
        gdrive_service: GoogleDriveService,
        gemini_service: GeminiService,
    ) -> None:
        self.config = config
        self.session_factory = session_factory
        self.gdrive_service = gdrive_service
        self.gemini_service = gemini_service

    async def process_single_file(self, audio_file: DriveAudioFile) -> CallStatus | None:
        """Обробляє один знайдений аудіофайл із Google Drive."""
        async with self.session_factory() as session:
            manager_repo = ManagerRepository(session)
            call_repo = CallRepository(session)
            eval_repo = EvaluationRepository(session)

            # 1. Перевірка, чи файл вже оброблено в БД
            existing_call = await call_repo.get_by_drive_id(audio_file.file_id)
            if existing_call is not None and existing_call.status in (
                CallStatus.COMPLETED,
                CallStatus.IGNORED,
                CallStatus.PROCESSING,
            ):
                logger.debug(
                    "Файл %s (%s) вже має статус %s — пропускаємо",
                    audio_file.file_name,
                    audio_file.file_id,
                    existing_call.status,
                )
                return None

            # 2. Розбір шляху папок згідно з шаблоном у config.yaml
            metadata = self.config.drive_structure.parse_folder_parts(
                audio_file.folder_parts
            )
            if metadata is None:
                logger.warning(
                    "Шлях папок %s для файлу '%s' не відповідає шаблону '%s' — ігноруємо",
                    audio_file.folder_parts,
                    audio_file.file_name,
                    self.config.drive_structure.path_pattern,
                )
                return CallStatus.IGNORED

            # 3. Перевірка наявності менеджера в БД (якщо немає — створюємо)
            manager, _ = await manager_repo.get_or_create(name=metadata.manager_name)

            # 4. Валідація назви папки (типу дзвінка)
            is_valid_type = self.config.drive_structure.is_valid_call_type(
                metadata.call_type
            )
            if not is_valid_type:
                reason = (
                    f"Невалідний тип дзвінка (назва папки): '{metadata.call_type}'. "
                    f"Дозволені: {self.config.drive_structure.valid_call_types}"
                )
                logger.info("Ігноруємо файл '%s': %s", audio_file.file_name, reason)
                call = existing_call or await call_repo.create(
                    drive_file_id=audio_file.file_id,
                    file_name=audio_file.file_name,
                    manager_id=manager.id,
                    call_type=metadata.call_type,
                    status=CallStatus.IGNORED,
                )
                await call_repo.update_status(
                    call=call, status=CallStatus.IGNORED, error_message=reason
                )
                return CallStatus.IGNORED

            # Створюємо або оновлюємо запис дзвінка у статусі PROCESSING
            call = existing_call or await call_repo.create(
                drive_file_id=audio_file.file_id,
                file_name=audio_file.file_name,
                manager_id=manager.id,
                call_type=metadata.call_type,
                status=CallStatus.PROCESSING,
            )
            call.status = CallStatus.PROCESSING
            await session.commit()

            local_audio_path: Path | None = None
            uploaded_gemini_file: Any | None = None

            try:
                # 5. Завантаження аудіо з Google Drive (Нода 43)
                local_audio_path = await self.gdrive_service.download_audio_file(
                    file_id=audio_file.file_id,
                    file_name=audio_file.file_name,
                )

                # 6. Завантаження аудіо у Gemini Files API (Нода 42)
                uploaded_gemini_file = await self.gemini_service.upload_audio(
                    audio_path=local_audio_path,
                    mime_type=audio_file.mime_type or None,
                )

                # 7. Транскрибація аудіо в Gemini (Нода 41)
                transcript = await self.gemini_service.transcribe_audio(
                    uploaded_file=uploaded_gemini_file
                )

                # 8. Оцінка якості розмови в Gemini (Нода 50)
                evaluation_result = await self.gemini_service.evaluate_call_quality(
                    manager_name=manager.name,
                    call_type=metadata.call_type,
                    transcript=transcript,
                )

                # 9. Запис у БД (замість Google Sheets ноди 51)
                await eval_repo.save_evaluation(
                    call=call,
                    transcript=transcript,
                    evaluation_result=evaluation_result,
                )
                logger.info(
                    "Успішно оброблено дзвінок '%s' (Менеджер: %s, Тип: %s, Оцінка: %d/100)",
                    audio_file.file_name,
                    manager.name,
                    metadata.call_type,
                    evaluation_result.overall_score,
                )
                return CallStatus.COMPLETED

            except Exception as exc:
                logger.exception(
                    "Помилка під час обробки файлу '%s' (%s): %s",
                    audio_file.file_name,
                    audio_file.file_id,
                    exc,
                )
                await call_repo.update_status(
                    call=call, status=CallStatus.FAILED, error_message=str(exc)
                )
                return CallStatus.FAILED

            finally:
                # Очищення тимчасових файлів
                if uploaded_gemini_file is not None:
                    await self.gemini_service.delete_uploaded_file(uploaded_gemini_file)
                if local_audio_path is not None and local_audio_path.exists():
                    local_audio_path.unlink(missing_ok=True)

    async def run_polling_cycle(self) -> dict[str, int]:
        """Виконує один цикл опитування Google Drive та обробляє всі нові файли."""
        logger.info("Запуск циклу сканування Google Drive...")
        audio_files = await self.gdrive_service.list_audio_files()
        logger.info("Знайдено %d аудіофайлів у папці Google Drive", len(audio_files))

        stats = {"completed": 0, "ignored": 0, "failed": 0, "skipped": 0}
        for audio_file in audio_files:
            status = await self.process_single_file(audio_file)
            if status is None:
                stats["skipped"] += 1
            elif status == CallStatus.COMPLETED:
                stats["completed"] += 1
            elif status == CallStatus.IGNORED:
                stats["ignored"] += 1
            elif status == CallStatus.FAILED:
                stats["failed"] += 1

        logger.info("Цикл сканування завершено: %s", stats)
        return stats
