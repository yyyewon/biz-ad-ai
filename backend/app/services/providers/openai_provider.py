from openai import OpenAI

from app.core.config import get_settings


class OpenAIProvider:
    def __init__(self):
        self.api_key = get_settings().openai_api_key
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None

    def generate_text(
        self,
        prompt: str,
        system_instruction: str = "너는 친절하고 유능한 카피라이터야.",
    ) -> str:
        if not self.client:
            return "API 키가 설정되지 않아 텍스트를 생성할 수 없습니다."

        try:
            response = self.client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"OpenAI 호출 오류: {str(e)}"
