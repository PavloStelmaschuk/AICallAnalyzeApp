import asyncio
import logging
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import GeminiConfig, PromptsConfig
from src.schemas.evaluation import CallEvaluationResult

logger = logging.getLogger(__name__)


class GeminiService:
    """
    Сервіс для роботи з Google Gemini AI:
    - Нода 42: Upload Audio to Gemini (Files API)
    - Нода 41: Транскрибація аудіофайлу
    - Нода 50: Структурована оцінка якості розмови (QA)
    """

    def __init__(
        self,
        api_key: str,
        gemini_config: GeminiConfig,
        prompts_config: PromptsConfig,
    ) -> None:
        self.client = genai.Client(api_key=api_key)
        self.gemini_config = gemini_config
        self.prompts_config = prompts_config

    def _upload_and_wait_sync(self, audio_path: Path, mime_type: str | None = None) -> Any:
        """Завантажує аудіофайл у Gemini Files API та чекає переходу у стан ACTIVE."""
        upload_config: dict[str, Any] = {}
        if mime_type:
            upload_config["mime_type"] = mime_type

        uploaded = self.client.files.upload(
            file=str(audio_path),
            config=upload_config if upload_config else None,
        )
        logger.info("Файл завантажено у Gemini Files API: %s", uploaded.name)

        while uploaded.state and uploaded.state.name == "PROCESSING":
            import time

            time.sleep(2)
            uploaded = self.client.files.get(name=uploaded.name)

        if uploaded.state and uploaded.state.name not in ("ACTIVE", None):
            raise RuntimeError(
                f"Помилка обробки файлу в Gemini Files API: state={uploaded.state.name}"
            )
        return uploaded

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def upload_audio(self, audio_path: Path, mime_type: str | None = None) -> Any:
        """Нода 42: Асинхронне завантаження аудіо у Gemini."""
        return await asyncio.to_thread(self._upload_and_wait_sync, audio_path, mime_type)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def transcribe_audio(self, uploaded_file: Any) -> str:
        """Нода 41: Транскрибація завантаженого аудіофайлу через Gemini."""
        prompt = self.prompts_config.transcription

        def _call() -> str:
            response = self.client.models.generate_content(
                model=self.gemini_config.transcription_model,
                contents=[uploaded_file, prompt],
                config=types.GenerateContentConfig(
                    temperature=self.gemini_config.temperature,
                ),
            )
            if not response.text:
                raise ValueError("Gemini повернув порожню транскрипцію")
            return response.text.strip()

        transcript = await asyncio.to_thread(_call)
        logger.info("Транскрибацію завершено (%d символів)", len(transcript))
        return transcript

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def evaluate_call_quality(
        self,
        manager_name: str,
        call_type: str,
        transcript: str,
    ) -> CallEvaluationResult:
        """Нода 50: Оцінка якості розмови з гарантованим поверненням схеми CallEvaluationResult."""
        prompt = self.prompts_config.render_evaluation_prompt(
            manager_name=manager_name,
            call_type=call_type,
            transcript=transcript,
        )

        def _call() -> CallEvaluationResult:
            response = self.client.models.generate_content(
                model=self.gemini_config.evaluation_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=self.gemini_config.temperature,
                    response_mime_type="application/json",
                    response_schema=CallEvaluationResult,
                ),
            )
            if response.parsed is not None and isinstance(
                response.parsed, CallEvaluationResult
            ):
                return response.parsed
            if not response.text:
                raise ValueError("Gemini повернув порожню відповідь оцінки якості")
            return CallEvaluationResult.model_validate_json(response.text)

        result = await asyncio.to_thread(_call)
        logger.info(
            "Оцінку якості завершено для %s (%s): overall_score=%d",
            manager_name,
            call_type,
            result.overall_score,
        )
        return result

    async def delete_uploaded_file(self, uploaded_file: Any) -> None:
        """Видаляє тимчасовий аудіофайл із сховища Gemini Files API."""
        try:
            file_name = getattr(uploaded_file, "name", None)
            if file_name:
                await asyncio.to_thread(self.client.files.delete, name=file_name)
                logger.debug("Видалено файл із Gemini Files API: %s", file_name)
        except Exception as exc:
            logger.warning("Не вдалося видалити файл із Gemini Files API: %s", exc)

