# Image Prompt Pipeline (OpenAI / HF)

## 1. 목적

이미지 생성 프롬프트가 OpenAI·HF에서 어떻게 연결되는지 정리한다.

- **OpenAI** → `food_type_prompts.py`
- **HF** → `hf_food_type_prompts.py` (별도 파일)
- 전환은 `model.yaml`의 `image_generation_provider`로 결정

---

## 2. provider 전환 (`model.yaml`)

`active_profile`의 `image_generation_provider` 값에 따라 **모델 + 프롬프트 파일**이 같이 바뀐다.


| profile 예시                    | `image_generation_provider` | 프롬프트 파일                   |
| ----------------------------- | --------------------------- | ------------------------- |
| `all_openai`                  | `openai`                    | `food_type_prompts.py`    |
| `all_hf`                      | `hf`                        | `hf_food_type_prompts.py` |
| `hybrid_openai_text_hf_image` | `hf`                        | `hf_food_type_prompts.py` |
| `hybrid_hf_text_openai_image` | `openai`                    | `food_type_prompts.py`    |


설정: `backend/config/model.yaml`

```text
model.yaml (active_profile → image_generation_provider)
  ↓
get_provider_name("image_generation")   # "openai" | "hf"
  ↓
image_pipeline.py 에서 프롬프트 빌더 분기
```

---



## 3. 관련 파일


| 파일                                                             | provider   | 역할                                                                                          |
| -------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------- |
| `backend/app/services/pipelines/food_type_prompts.py`          | **OpenAI** | studio / poster / reels 템플릿, `FOOD_VARIANT_PROMPT_TEMPLATES`, `build_food_variant_prompt()` |
| `backend/app/services/pipelines/hf_food_type_prompts.py`       | **HF**     | HF 템플릿, `HF_FOOD_VARIANT_PROMPT_TEMPLATES`, `build_hf_food_variant_prompt()`                |
| `backend/app/services/pipelines/image_variant_prompts.py`      | 진입점        | OpenAI: `build_variant_prompt()`, HF: `build_hf_variant_prompts()`                          |
| `backend/app/services/pipelines/image_pipeline.py`             | 실행         | provider 분기, variant 3장 병렬 생성                                                               |
| `backend/app/services/providers/openai_image_provider.py`      | OpenAI     | `images.edit` 호출                                                                            |
| `backend/app/services/providers/hf_sdxl_lightning_provider.py` | HF         | img2img 호출                                                                                  |


---



## 4. 전체 흐름

```text
generate_pipeline.py
  └─ image_pipeline.generate_image_ads()
       ├─ get_provider_name("image_generation")    ← model.yaml
       ├─ get_image_provider()                     ← factory
       └─ variant 3장 병렬 (_generate_variant_image)
            ├─ [OpenAI] build_variant_prompt()
            │     └─ food_type_prompts.build_food_variant_prompt()
            ├─ [HF]     build_hf_variant_prompts()
            │     └─ hf_food_type_prompts.build_hf_food_variant_prompt()
            │         + negative 분리 + img2img_strength
            └─ provider.generate(...)
```

PIL 텍스트(헤드라인·가격·가게명)는 프롬프트와 별도: `image_text_overlay.py`, `poster_taglines.py`

---



## 5. OpenAI 연결

`image_generation_provider != "hf"` 일 때:

```text
build_variant_prompt()                        [image_variant_prompts.py]
  → build_food_variant_prompt()               [food_type_prompts.py]
  → FOOD_VARIANT_PROMPT_TEMPLATES[(food_type, variant)]
  → openai_image_provider.generate(
       prompt=variant_prompt,
       negative_prompt=None,
     )
```

- OpenAI provider는 프롬프트 문자열을 만들지 않음 — pipeline이 만든 문자열을 `images.edit`에 전달
- 템플릿의 `NEG:` 줄은 positive prompt 안에 포함 (HF처럼 분리하지 않음)

---



## 6. HF 연결

`image_generation_provider == "hf"` 일 때:

```text
build_hf_variant_prompts()                    [image_variant_prompts.py]
  → build_hf_food_variant_prompt()            [hf_food_type_prompts.py]
  → HF_FOOD_VARIANT_PROMPT_TEMPLATES[(food_type, variant)]
  → strip_prompt_neg_line()                   ← positive
  → build_hf_variant_negative_prompt()        ← negative
  → resolve_hf_img2img_strength()             [image_variant_prompts.py]
  → hf provider.generate(
       prompt=positive,
       negative_prompt=negative,
       img2img_strength=...,
     )
```


| 항목                | OpenAI                          | HF                                  |
| ----------------- | ------------------------------- | ----------------------------------- |
| 프롬프트 파일           | `food_type_prompts.py`          | `hf_food_type_prompts.py`           |
| template registry | `FOOD_VARIANT_PROMPT_TEMPLATES` | `HF_FOOD_VARIANT_PROMPT_TEMPLATES`  |
| negative          | prompt 내 `NEG:`                 | `negative_prompt` 파라미터              |
| img2img strength  | 없음                              | studio 0.68, poster 0.65, feed 0.45 |


`hf_food_type_prompts.py`는 초기에 OpenAI 템플릿을 복사해 두었음. HF 튜닝 시 이 파일만 수정하면 OpenAI에 영향 없음.

---



## 7. variant · food_type

- **variant:** `studio`, `poster`, `instagram_feed`
- **food_type:** `soup_stew`, `fried`, `grilled_bbq`, `rice_dish`, `bread_dessert`, `burger_sandwich`, `coffee_drink`
- 조합 키: `(food_type, variant)` → 각 registry dict

---



## 8. 어디 파일 수정하면 되나


| 수정 목적                                 | 파일                                                             |
| ------------------------------------- | -------------------------------------------------------------- |
| **OpenAI** studio / poster / reels 문구 | `backend/app/services/pipelines/food_type_prompts.py`          |
| **HF** studio / poster / reels 문구     | `backend/app/services/pipelines/hf_food_type_prompts.py`       |
| HF negative prompt                    | `hf_food_type_prompts.py` (`build_hf_variant_negative_prompt`) |
| HF img2img strength                   | `backend/app/services/pipelines/image_variant_prompts.py`      |
| OpenAI ↔ HF 전환                        | `backend/config/model.yaml` (`active_profile`)                 |
| HF 모델 ID·파라미터                         | `backend/config/model.yaml` (`hf.image_generation`)            |


**규칙:** OpenAI → `food_type_prompts.py`, HF → `hf_food_type_prompts.py`. 서로 영향 없음.

---



## 9. 프롬프트 미리보기

```bash
cd backend
python scripts/preview_image_prompts.py --food-type fried --variant poster   # OpenAI
```

HF: `hf_food_type_prompts.build_hf_food_variant_prompt()` 로 문자열 확인.