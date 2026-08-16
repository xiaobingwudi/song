# -*- coding: utf-8 -*-
"""自建筛选栏组件（纯 HTML，标签在左、一行、无留白、日期一行）。

返回 dict：{"start","end","materials":[],"qty_min","qty_max","reset"}
"""
import streamlit.components.v1 as components
import pathlib

_build = str(pathlib.Path(__file__).parent / "frontend")

filter_bar = components.declare_component(
    "filter_bar",
    path=_build,
)
