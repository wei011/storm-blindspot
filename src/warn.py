# -*- coding: utf-8 -*-
"""把逐小时降雨预报翻译成国标暴雨预警信号级别，以及对照本地排水设计能力。

暴雨预警信号用的是"绝对阈值"（多少小时下多少毫米），不受再分析低估影响，
所以它是这个工具里"实用可信"的那一半——storm-blindspot 用它给预报兜底。
"""


def max_window_sum(precip, window_h):
    """未来预报里 window_h 小时滑动累积雨量的峰值。"""
    w = max(1, int(window_h))
    n = len(precip)
    if n < w:
        return sum(precip)
    best = s = sum(precip[:w])
    for i in range(w, n):
        s += precip[i] - precip[i - w]
        if s > best:
            best = s
    return best


def warning_level(precip, levels):
    """给定逐小时预报和国标级别定义，返回触发的最高级别。levels 从 data/cities.json 读入。"""
    order = {"blue": 1, "yellow": 2, "orange": 3, "red": 4}
    hit = None
    detail = []
    for lv in levels:
        peak = max_window_sum(precip, lv["window_h"])
        triggered = peak >= lv["threshold_mm"]
        detail.append({
            "code": lv["code"], "name": lv["name"],
            "window_h": lv["window_h"], "threshold_mm": lv["threshold_mm"],
            "forecast_peak_mm": round(peak, 1), "triggered": triggered,
        })
        if triggered and (hit is None or order[lv["code"]] > order[hit["code"]]):
            hit = detail[-1]
    return hit, detail


def pipe_capacity_mm_h(recurrence_years, city_intensity):
    """占位：把设计重现期换算成排水能力(mm/h)需要本地暴雨强度公式；
    此处不臆造参数，仅返回 None，由 CLI 用文字提示"设计重现期"本身。"""
    return None
