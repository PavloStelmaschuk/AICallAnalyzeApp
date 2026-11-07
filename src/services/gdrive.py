import asyncio
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from src.config import DriveStructureConfig

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


@dataclass(slots=True)
class DriveAudioFile:
    """Метадані знайденого файлу на Google Drive разом із відносним шляхом папок."""

    file_id: str
    file_name: str
    mime_type: str
    folder_parts: list[str]
    parent_folder_id: str | None = None


class GoogleDriveService:
    """
    Сервіс для моніторингу папок Google Drive (Нода 34)
    та завантаження аудіофайлів (Нода 43).
    """

    def __init__(
        self,
        credentials_path: str | Path,
        root_folder_id: str,
        structure_config: DriveStructureConfig,
        temp_download_dir: str | Path = "/tmp/call_qa_audio",
    ) -> None:
        self.credentials_path = Path(credentials_path)
        self.root_folder_id = root_folder_id
        self.structure_config = structure_config
        self.temp_download_dir = Path(temp_download_dir)
        self.temp_download_dir.mkdir(parents=True, exist_ok=True)
        self._service: Any | None = None

    def _get_service(self) -> Any:
        if self._service is None:
            if not self.credentials_path.exists():
                raise FileNotFoundError(
                    f"Файл ключів Google Service Account не знайдено: {self.credentials_path}"
                )
            creds = service_account.Credentials.from_service_account_file(
                str(self.credentials_path), scopes=SCOPES
            )
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _list_children_sync(self, folder_id: str) -> list[dict[str, Any]]:
        """Синхронно отримує всі елементи всередині вказаної папки Google Drive."""
        service = self._get_service()
        items: list[dict[str, Any]] = []
        page_token: str | None = None

        query = f"'{folder_id}' in parents and trashed = false"
        while True:
            response = (
                service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, parents, createdTime)",
                    pageToken=page_token,
                    pageSize=100,
                )
                .execute()
            )
            items.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return items

    def _scan_recursive_sync(
        self,
        current_folder_id: str,
        current_parts: list[str],
    ) -> list[DriveAudioFile]:
        """Рекурсивно обходить дерево папок і збирає аудіофайли."""
        discovered: list[DriveAudioFile] = []
        children = self._list_children_sync(current_folder_id)

        for item in children:
            item_id = item["id"]
            item_name = item["name"]
            mime_type = item.get("mimeType", "")

            if mime_type == FOLDER_MIME_TYPE:
                discovered.extend(
                    self._scan_recursive_sync(item_id, [*current_parts, item_name])
                )
            elif self.structure_config.is_allowed_audio_file(item_name, mime_type):
                discovered.append(
                    DriveAudioFile(
                        file_id=item_id,
                        file_name=item_name,
                        mime_type=mime_type,
                        folder_parts=list(current_parts),
                        parent_folder_id=current_folder_id,
                    )
                )

        return discovered

    async def list_audio_files(self) -> list[DriveAudioFile]:
        """Асинхронна обгортка для сканування кореневої папки Google Drive (Нода 34)."""
        return await asyncio.to_thread(
            self._scan_recursive_sync, self.root_folder_id, []
        )

    def _download_file_sync(self, file_id: str, file_name: str) -> Path:
        """Синхронно завантажує файл із Google Drive у тимчасову директорію (Нода 43)."""
        service = self._get_service()
        safe_name = f"{file_id}_{Path(file_name).name}"
        target_path = self.temp_download_dir / safe_name

        request = service.files().get_media(fileId=file_id)
        with io.FileIO(target_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        logger.info("Аудіофайл завантажено з Google Drive: %s -> %s", file_name, target_path)
        return target_path

    async def download_audio_file(self, file_id: str, file_name: str) -> Path:
        """Асинхронно завантажує аудіофайл у локальну тимчасову папку (Нода 43)."""
        return await asyncio.to_thread(self._download_file_sync, file_id, file_name)

