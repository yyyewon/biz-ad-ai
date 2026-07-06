"""
Step 3: 생성 결과 확인
"""
from __future__ import annotations
import hashlib
import streamlit as st

from core.state import prev_step, reset_all
from core.api_client import generate_ad
from core.auth import is_logged_in, refresh_me, is_quota_exceeded, get_daily_usage
from core.config import KAKAO_LOGIN_ENDPOINT
from components.ui_kit import phone_preview, feed_grid, alert, quota_exceeded_banner


def _input_signature() -> tuple:
    b = st.session_state.business
    u = st.session_state.upload
    img_hash = hashlib.md5(u["image_bytes"]).hexdigest() if u["image_bytes"] else ""
    return (
        b["store_name"],
        b["menu_name"],
        b["purpose"],
        b["request_note"],
        tuple(sorted(u["moods"])),
        u["tone"],
        img_hash,
    )


def _render_login_required() -> None:
    with st.container(border=True):
        st.markdown('<div class="rg-card-title">🔐 로그인이 필요해요</div>', unsafe_allow_html=True)
        st.caption("소셜 로그인 후 하루 3회까지 광고 콘텐츠를 생성할 수 있어요.")
        st.link_button("카카오로 로그인", KAKAO_LOGIN_ENDPOINT, width="stretch")

    if st.button("← 이전 단계로 돌아가기", type="secondary"):
        prev_step()
        st.rerun()


def _render_quota_exceeded() -> None:
    with st.container(border=True):
        usage = get_daily_usage() or {}
        quota_exceeded_banner(limit=usage.get("limit"))
        st.caption("오늘 사용한 횟수는 내일 자정(KST) 이후 초기화돼요.")
        if st.button("처음부터 다시 만들기", type="primary", width="stretch"):
            reset_all()
            st.rerun()


def _run_generation() -> None:
    b = st.session_state.business
    u = st.session_state.upload
    mock = st.session_state.mock_mode
    access_token = st.session_state.auth.get("access_token")

    with st.spinner("AI가 광고 문구와 이미지를 만들고 있어요..."):
        result = generate_ad(
            store_name=b["store_name"],
            menu_name=b["menu_name"],
            purpose=b["purpose"],
            request_note=b["request_note"],
            image_bytes=u["image_bytes"],
            image_name=u["image_name"],
            moods=u["moods"],
            tone=u["tone"],
            access_token=access_token,
            mock=mock,
        )

    if not result["ok"]:
        st.session_state.generation.update(
            status="error",
            error_message=result["error"],
            error_code=result.get("error_code"),
        )
        if not mock and result.get("error_code") == "DAILY_LIMIT_EXCEEDED":
            refresh_me()
        return

    st.session_state.generation.update(
        status="done",
        caption=result["data"]["caption"],
        images=result["data"]["images"],
        error_message="",
        error_code=None,
        signature=_input_signature(),
    )

    if not mock:
        refresh_me()


def render() -> None:
    with st.container(border=True):
        st.markdown(
            '<span class="rg-eyebrow">STEP 3</span>'
            '<div class="rg-card-title">완성된 콘텐츠를 확인해 주세요</div>'
            '<div class="rg-card-desc">마음에 들지 않으면 문구를 직접 수정하거나, 다시 생성할 수 있어요.</div>',
            unsafe_allow_html=True,
        )

    if not st.session_state.mock_mode and not is_logged_in():
        _render_login_required()
        return

    gen = st.session_state.generation
    current_sig = _input_signature()

    needs_new_generation = gen["status"] == "idle" or gen.get("signature") != current_sig

    if needs_new_generation:
        if is_quota_exceeded():
            _render_quota_exceeded()
            return
        _run_generation()
        gen = st.session_state.generation

    if gen["status"] == "error":
        alert(f"⚠️ {gen['error_message']}", kind="error")

        if gen.get("error_code") == "DAILY_LIMIT_EXCEEDED":
            st.caption("오늘 사용한 횟수는 내일 자정(KST) 이후 초기화돼요.")
            if st.button("처음부터 다시 만들기", type="primary", width="stretch"):
                reset_all()
                st.rerun()
        else:
            if st.button("다시 시도하기", type="primary"):
                st.session_state.generation["status"] = "idle"
                st.rerun()
            if st.button("← 이전 단계로 돌아가기", type="secondary"):
                prev_step()
                st.rerun()
        return

    if gen["status"] != "done":
        return

    left, right = st.columns(2, gap="medium")

    with left:
        with st.container(border=True):
            st.markdown('<div class="rg-card-title">📱 게시물 미리보기</div>', unsafe_allow_html=True)
            hero_image = gen["images"][0] if gen["images"] else None
            phone_preview(
                store_name=st.session_state.business["store_name"],
                caption=st.session_state.get("edited_caption", gen["caption"]),
                hero_image_bytes=hero_image,
            )
            st.markdown(
                '<div class="rg-card-title" style="margin-top:1.2rem;">🎇 피드 그리드 미리보기</div>',
                unsafe_allow_html=True,
            )
            feed_grid(gen["images"])

    with right:
        with st.container(border=True):
            st.markdown('<div class="rg-card-title">✏️ 문구 수정</div>', unsafe_allow_html=True)
            st.text_area(
                "AI가 만든 문구를 자유롭게 수정해 보세요",
                value=gen["caption"],
                key="edited_caption",
                height=160,
            )

            st.markdown(
                '<div class="rg-card-title" style="margin-top:1.2rem;">✨ 생성된 이미지</div>',
                unsafe_allow_html=True,
            )
            if gen["images"]:
                idx_key = "selected_image_idx"
                if idx_key not in st.session_state:
                    st.session_state[idx_key] = 0
                idx = st.session_state[idx_key] % len(gen["images"])

                st.image(gen["images"][idx], width="stretch")
                dots = " ".join("●" if i == idx else "○" for i in range(len(gen["images"])))
                st.markdown(f'<div style="text-align:center;color:var(--rg-ink-faint);">{dots}</div>', unsafe_allow_html=True)

                nav1, nav2, nav3 = st.columns([1, 1, 2])
                with nav1:
                    if st.button("← 이전", width="stretch"):
                        st.session_state[idx_key] = (idx - 1) % len(gen["images"])
                        st.rerun()
                with nav2:
                    if st.button("다음 →", width="stretch"):
                        st.session_state[idx_key] = (idx + 1) % len(gen["images"])
                        st.rerun()
                with nav3:
                    st.download_button(
                        "이 이미지 다운로드",
                        data=gen["images"][idx],
                        file_name=f"{st.session_state.business['store_name']}_ad_{idx+1}.png",
                        mime="image/png",
                        type="primary",
                        width="stretch",
                    )

    footer_left, footer_right = st.columns(2)
    with footer_left:
        if st.button("← 옵션 다시 선택하기", type="secondary", width="stretch"):
            prev_step()
            st.rerun()
    with footer_right:
        if st.button("🔄 처음부터 다시 만들기", type="secondary", width="stretch"):
            reset_all()
            st.rerun()