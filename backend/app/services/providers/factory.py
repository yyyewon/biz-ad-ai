from app.core.config import get_settings
from app.services.providers.openai_image_provider import OpenAIImageProvider


def get_image_provider() -> OpenAIImageProvider:
    settings = get_settings()
    return OpenAIImageProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_image_model,
        size=settings.openai_image_size,
    )
