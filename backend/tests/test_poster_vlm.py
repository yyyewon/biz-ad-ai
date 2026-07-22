from app.utils.poster_vlm import _build_hints_from_parsed


def test_vlm_design_json_becomes_semantic_template_overrides() -> None:
    hints = _build_hints_from_parsed(
        {
            "design": {
                "template_id": "centered",
                "density": "compact",
                "image_text_relation": "separate",
                "headline_scale": "small",
            }
        },
        width=400,
        height=600,
    )

    assert hints.template_overrides == {
        "composition": "centered",
        "price_style": "ticket",
        "headline_menu_gap_ratio": 0.010,
        "menu_overlap_ratio": 0.0,
        "headline_size_ratio": 0.042,
    }


def test_vlm_numeric_typography_does_not_control_renderer_tokens() -> None:
    hints = _build_hints_from_parsed(
        {
            "typography": {
                "headline_size_ratio": 0.9,
                "menu_size_ratio": 0.01,
            }
        },
        width=400,
        height=600,
    )

    assert hints.template_overrides is None
