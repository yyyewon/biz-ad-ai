import io
import threading

from PIL import Image
from loguru import logger

from app.core.config import get_settings
from app.utils.memory_monitor import ensure_model_load_memory, log_model_memory_snapshot


class FoodClassifierProvider:
    """
    CLIP 모델을 사용해 이미지의 음식 카테고리를 분류하는 Provider
    """
    def __init__(self) -> None:
        self._classifier = None
        self._load_lock = threading.Lock()

        # 서비스에서 사용하는 음식 카테고리
        self.food_options = [
            "국, 찌개",
            "튀김, 치킨",
            "구이, 바베큐",
            "덮밥, 볶음, 비빔",
            "빵, 디저트, 케이크",
            "버거, 샌드위치",
            "커피, 음료"
        ]

        # Zero-shot 분류 정확도를 극대화하기 위한 상세 영어 프롬프트 매핑
        self.korean_to_english = {
            "국, 찌개": "soup, stew, broth, hot pot, boiling soup, Korean jjigae, ramen soup",
            "튀김, 치킨": "fried food, fried chicken, deep-fried dish, tempura, crispy nuggets, french fries",
            "구이, 바베큐": "grilled meat, barbecue, steak, roasted food, BBQ, grilled fish, skewers",
            "덮밥, 볶음, 비빔": "rice bowl, stir-fried dish, bibimbap, fried rice, stir-fried noodles, donburi",
            "빵, 디저트, 케이크": "bread, dessert, cake, pastry, bakery, sweet waffle, macaron, donut",
            "버거, 샌드위치": "burger, sandwich, hamburger, sub, hot dog, toast",
            "커피, 음료": "coffee, beverage, tea, latte, juice, soda, cocktail, soft drink, iced beverage"
        }

    def _ensure_model_loaded(self) -> None:
        """처음 분류 요청이 들어올 때 모델을 메모리(가능하면 GPU)에 올립니다."""
        if self._classifier is not None:
            return

        with self._load_lock:
            # double-checked locking: 락 대기 중 다른 스레드가 이미 로드했을 수 있음
            if self._classifier is not None:
                return
            try:
                model_name = "openai/clip-vit-base-patch32"
                before_load = log_model_memory_snapshot(
                    "before_food_classifier_load",
                    model_name=model_name,
                )
                ensure_model_load_memory(
                    model_name=model_name,
                    min_available_ram_gb=get_settings().model_load_min_available_ram_gb,
                    load_stage="before_food_classifier_load",
                    snapshot=before_load,
                )

                import torch
                from transformers import pipeline

                device = 0 if torch.cuda.is_available() else -1
                logger.info(
                    "food_classifier | Loading CLIP model on device: {}",
                    "cuda" if device == 0 else "cpu"
                )
                self._classifier = pipeline(
                    "zero-shot-image-classification",
                    model=model_name,
                    device=device
                )
                log_model_memory_snapshot(
                    "after_food_classifier_load",
                    model_name=model_name,
                    torch_module=torch,
                )
            except Exception as e:
                logger.error("food_classifier_load_failed | error={}", str(e))
                raise e

    def classify(self, image_bytes: bytes) -> str:
        self._ensure_model_loaded()

        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            candidate_labels = [self.korean_to_english[opt] for opt in self.food_options]
            english_to_korean = {v: k for k, v in self.korean_to_english.items()}

            results = self._classifier(image, candidate_labels=candidate_labels)

            top_label = results[0]["label"]
            predicted_food = english_to_korean[top_label]

            logger.info("food_classification_success | predicted={}", predicted_food)
            return predicted_food

        except Exception as e:
            logger.error("food_classification_failed | error={}, fallback to '국, 찌개'", str(e))
            return "국, 찌개"

# 싱글톤 인스턴스 노출
food_classifier_provider = FoodClassifierProvider()
