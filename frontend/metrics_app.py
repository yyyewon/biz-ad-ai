"""
Metrics dashboard entry (Docker dev: port 8555).

로컬:
  streamlit run metrics_app.py --server.port 8555
"""
from __future__ import annotations

import streamlit as st

from core.metrics.dashboard import render_metrics_dashboard

st.set_page_config(
    page_title="Biz Ad AI Metrics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    div[data-testid="stMetric"] {
        background: #f4f6f9;
        padding: 0.65rem 0.85rem;
        border-radius: 0.5rem;
        border: 1px solid #e6eaf0;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.85rem;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.45rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

render_metrics_dashboard()
