import base64
from pathlib import Path

from openai import OpenAI

from app.services.providers.base import ImageGenerationProvider


class OpenAIImageProvider(ImageGenerationProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-image-1-mini",
        size: str = "1024x1536",
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY가 없습니다.")
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._size = size

    def generate(
        self,
        *,
        input_image_path: Path,
        prompt: str,
        num_images: int,
        output_dir: Path,
        mask_image_path: Path | None = None,
    ) -> list[Path]:
        if not input_image_path.exists():
            raise FileNotFoundError(f"입력 이미지를 찾을 수 없습니다: {input_image_path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_paths: list[Path] = []

        for idx in range(num_images):
            with input_image_path.open("rb") as image_file:
                if mask_image_path:
                    with mask_image_path.open("rb") as mask_file:
                        result = self._client.images.edit(
                            model=self._model,
                            image=image_file,
                            mask=mask_file,
                            prompt=prompt,
                            size=self._size,
                        )
                else:
                    result = self._client.images.edit(
                        model=self._model,
                        image=image_file,
                        prompt=prompt,
                        size=self._size,
                    )

            image_b64 = result.data[0].b64_json
            if not image_b64:
                raise RuntimeError("OpenAI 이미지 응답에 b64 데이터가 없습니다.")

            image_bytes = base64.b64decode(image_b64)
            output_file = output_dir / f"generated_{idx + 1}.png"
            output_file.write_bytes(image_bytes)
            output_paths.append(output_file)

        return output_paths

    def generate_backgrounds(
        self,
        *,
        prompt: str,
        num_images: int,
        output_dir: Path,
        file_prefix: str = "background",
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_paths: list[Path] = []

        for idx in range(num_images):
            result = self._client.images.generate(
                model=self._model,
                prompt=prompt,
                size=self._size,
            )

            image_b64 = result.data[0].b64_json
            if not image_b64:
                raise RuntimeError("OpenAI 배경 생성 응답에 b64 데이터가 없습니다.")

            image_bytes = base64.b64decode(image_b64)
            output_file = output_dir / f"{file_prefix}_{idx + 1}.png"
            output_file.write_bytes(image_bytes)
            output_paths.append(output_file)

        return output_paths
