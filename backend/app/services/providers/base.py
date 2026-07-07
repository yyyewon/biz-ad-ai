from pathlib import Path
from typing import Protocol


class ImageGenerationProvider(Protocol):
    def generate(
        self,
        *,
        input_image_path: Path,
        prompt: str,
        num_images: int,
        output_dir: Path,
        mask_image_path: Path | None = None,
    ) -> list[Path]:
        """광고 이미지를 생성하고 저장된 파일 경로 목록을 반환합니다."""

    def generate_backgrounds(
        self,
        *,
        prompt: str,
        num_images: int,
        output_dir: Path,
        file_prefix: str = "background",
    ) -> list[Path]:
        """배경 이미지만 생성하고 저장된 파일 경로 목록을 반환합니다."""
