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
)

render_metrics_dashboard()
