from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ParsedFolderMetadata(BaseModel):
    """Розібрані метадані зі шляху папок Google Drive."""

    manager_name: str
    call_type: str


class DriveStructureConfig(BaseModel):
    """Конфігурація структури папок на Google Drive та валідації типів дзвінків."""

    path_pattern: str = "{manager_name}/{call_type}"
    valid_call_types: list[str] = Field(
        default_factory=lambda: ["cold_call", "consultation", "follow_up", "support", "closing"]
    )
    allow_any_call_type: bool = False
    allowed_extensions: list[str] = Field(
        default_factory=lambda: [".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"]
    )

    def parse_folder_parts(self, folder_parts: list[str]) -> ParsedFolderMetadata | None:
        """
        Розбирає список сегментів шляху відносно кореневої папки згідно з `path_pattern`.
        Наприклад, для шаблону "{manager_name}/{call_type}" та шляху ["Іван Петренко", "cold_call"]
        повертає ParsedFolderMetadata(manager_name="Іван Петренко", call_type="cold_call").
        """
        pattern_parts = [p.strip() for p in self.path_pattern.strip("/").split("/") if p.strip()]
        if len(folder_parts) < len(pattern_parts):
            return None

        extracted: dict[str, str] = {}
        for pat_seg, actual_seg in zip(pattern_parts, folder_parts):
            if pat_seg.startswith("{") and pat_seg.endswith("}"):
                key = pat_seg[1:-1].strip()
                extracted[key] = actual_seg.strip()
            elif pat_seg != actual_seg:
                return None

        manager_name = extracted.get("manager_name", "Unknown Manager")
        call_type = extracted.get("call_type", "default")
        if not manager_name:
            return None

        return ParsedFolderMetadata(manager_name=manager_name, call_type=call_type)

    def is_valid_call_type(self, call_type: str) -> bool:
        """Перевіряє, чи входить назва папки (тип дзвінка) до списку дозволених."""
        if self.allow_any_call_type:
            return True
        normalized = call_type.strip().lower()
        valid_normalized = {t.strip().lower() for t in self.valid_call_types}
        return normalized in valid_normalized

    def is_allowed_audio_file(self, file_name: str, mime_type: str | None = None) -> bool:
        """Перевіряє, чи є файл аудіофайлом за розширенням або MIME-типом."""
        suffix = Path(file_name).suffix.lower()
        if suffix in {ext.lower() for ext in self.allowed_extensions}:
            return True
        if mime_type and mime_type.startswith("audio/"):
            return True
        return False


class GeminiConfig(BaseModel):
    """Налаштування моделей Google Gemini."""

    transcription_model: str = "gemini-2.5-flash"
    evaluation_model: str = "gemini-2.5-flash"
    temperature: float = 0.2


class PromptsConfig(BaseModel):
    """Конфігурація промптів для транскрибації та оцінки якості."""

    transcription: str
    evaluation_default: str
    evaluation_by_call_type: dict[str, str] = Field(default_factory=dict)

    def render_evaluation_prompt(
        self,
        manager_name: str,
        call_type: str,
        transcript: str,
    ) -> str:
        """Повертає відформатований промпт для конкретного типу дзвінка або дефолтний."""
        template = self.evaluation_by_call_type.get(
            call_type,
            self.evaluation_by_call_type.get(call_type.lower(), self.evaluation_default),
        )
        return template.format(
            manager_name=manager_name,
            call_type=call_type,
            transcript=transcript,
        )


class YamlAppConfig(BaseModel):
    """Повна модель конфігураційного файлу config.yaml."""

    drive_structure: DriveStructureConfig = Field(default_factory=DriveStructureConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    prompts: PromptsConfig


class EnvSettings(BaseSettings):
    """Налаштування середовища з .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    google_application_credentials: str = Field(
        default="./credentials.json", alias="GOOGLE_APPLICATION_CREDENTIALS"
    )
    gdrive_root_folder_id: str = Field(default="", alias="GDRIVE_ROOT_FOLDER_ID")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./call_qa.db", alias="DATABASE_URL"
    )
    polling_interval_seconds: int = Field(default=60, alias="POLLING_INTERVAL_SECONDS")
    config_yaml_path: str = Field(default="./config.yaml", alias="CONFIG_YAML_PATH")
    temp_download_dir: str = Field(
        default="/tmp/call_qa_audio", alias="TEMP_DOWNLOAD_DIR"
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


def load_yaml_config(path: str | Path = "./config.yaml") -> YamlAppConfig:
    """Завантажує та валідує YAML-конфігурацію."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Конфігураційний файл не знайдено: {config_path.resolve()}")
    with config_path.open("r", encoding="utf-8") as f:
        raw_data: dict[str, Any] = yaml.safe_load(f) or {}
    return YamlAppConfig.model_validate(raw_data)

