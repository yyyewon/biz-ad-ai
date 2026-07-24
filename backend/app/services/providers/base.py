from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal


ImageRenderMode = Literal["photo_restyle", "background_swap"]


class TextGenerationProvider(ABC):
    """
    텍스트 생성 provider 공통 interface.
    """

    @abstractmethod
    async def generate_text(
        self,
        *,
        prompt: str,
        system_instruction: str | None = None,
    ) -> str:
        """
        광고 문구 텍스트를 생성한다.
        """


class ImageGenerationProvider(ABC):
    """
    이미지 생성 provider 공통 interface.

    서버에 이미지 파일을 저장하지 않기 위해 provider는 생성 결과를 bytes로 반환한다.
    """

    @abstractmethod
    async def generate(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        mask_image_bytes: bytes | None = None,
        size: str | None = None,
        render_mode: ImageRenderMode = "photo_restyle",
        negative_prompt: str | None = None,
        img2img_strength: float | None = None,
    ) -> list[bytes]:
        """
        입력 이미지 bytes를 기반으로 광고 이미지 bytes 목록을 생성한다.
        """

    @abstractmethod
    async def generate_backgrounds(
        self,
        *,
        prompt: str,
        num_images: int,
    ) -> list[bytes]:
        """
        배경 이미지 bytes 목록을 생성한다.
        """

    def release_gpu_resources(self) -> None:
        """Optional hook to free GPU memory before a downstream GPU stage."""
        return None
