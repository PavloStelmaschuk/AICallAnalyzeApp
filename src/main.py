import argparse
import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import EnvSettings, load_yaml_config
from src.db.session import build_engine, build_session_factory, init_db
from src.services.gdrive import GoogleDriveService
from src.services.gemini import GeminiService
from src.services.pipeline import CallProcessingPipeline


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )


async def run_app(run_once: bool = False) -> None:
    env = EnvSettings()
    configure_logging(env.log_level)
    logger = logging.getLogger("main")

    yaml_config = load_yaml_config(env.config_yaml_path)
    logger.info(
        "Конфігурацію завантажено. Шаблон папок: '%s', дозволені типи: %s",
        yaml_config.drive_structure.path_pattern,
        yaml_config.drive_structure.valid_call_types,
    )

    engine = build_engine(env.database_url)
    await init_db(engine)
    session_factory = build_session_factory(engine)

    gdrive_service = GoogleDriveService(
        credentials_path=env.google_application_credentials,
        root_folder_id=env.gdrive_root_folder_id,
        structure_config=yaml_config.drive_structure,
        temp_download_dir=env.temp_download_dir,
    )
    gemini_service = GeminiService(
        api_key=env.gemini_api_key,
        gemini_config=yaml_config.gemini,
        prompts_config=yaml_config.prompts,
    )

    pipeline = CallProcessingPipeline(
        config=yaml_config,
        session_factory=session_factory,
        gdrive_service=gdrive_service,
        gemini_service=gemini_service,
    )

    if run_once:
        await pipeline.run_polling_cycle()
        await engine.dispose()
        return

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        pipeline.run_polling_cycle,
        trigger="interval",
        seconds=env.polling_interval_seconds,
        max_instances=1,
        coalesce=True,
        id="gdrive_polling_job",
    )
    scheduler.start()
    logger.info(
        "Сервіс поллінгу запущено (інтервал: %d с). Виконуємо першу перевірку...",
        env.polling_interval_seconds,
    )

    # Перший запуск одразу при старті
    await pipeline.run_polling_cycle()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    await stop_event.wait()
    logger.info("Зупинка планувальника та закриття з'єднань з БД...")
    scheduler.shutdown(wait=False)
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Google Drive -> Gemini Audio Transcription & QA Service"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Виконати один цикл перевірки Google Drive і завершити роботу",
    )
    args = parser.parse_args()
    asyncio.run(run_app(run_once=args.once))


if __name__ == "__main__":
    main()

