# -*- coding: utf-8 -*-
"""极值统计：把一串逐小时降雨压成"年最大值序列"，用 Gumbel 分布拟合，
反推"N 年一遇的小时/多小时雨强"，以及给定一场雨对应的重现期。

Gumbel（极值 I 型）是工程暴雨强度公式最常用的底分布之一。这里用矩法估参，
零依赖、可复现、结果与水文手册量级一致。

关键洞察不在拟合本身，而在拟合"喂进去的是什么数据"——
喂再分析格点数据，拟合出的极值会系统性偏小（见 calibrate 模块）。
"""
import math
from collections import defaultdict

EULER = 0.5772156649015329


def annual_maxima(times, precip, window_h=1):
    """滑动 window_h 小时累积雨量的年最大值序列。返回 {year: max_mm}。"""
    n = len(precip)
    w = max(1, int(window_h))
    # 前缀和加速滑窗
    pre = [0.0] * (n + 1)
    for i in range(n):
        pre[i + 1] = pre[i] + precip[i]
    ann = defaultdict(float)
    for i in range(n - w + 1):
        s = pre[i + w] - pre[i]
        yr = times[i][:4]
        if s > ann[yr]:
            ann[yr] = s
    return dict(ann)


def gumbel_fit(values):
    """矩法估计 Gumbel 参数。返回 (loc mu, scale beta)。"""
    x = [v for v in values if v is not None]
    n = len(x)
    if n < 5:
        raise ValueError("样本年数不足（<5），无法可靠拟合极值分布")
    mean = sum(x) / n
    var = sum((v - mean) ** 2 for v in x) / (n - 1)
    sd = math.sqrt(var)
    beta = sd * math.sqrt(6) / math.pi
    mu = mean - EULER * beta
    return mu, beta


def return_level(mu, beta, years):
    """N 年一遇对应的量级。"""
    return mu - beta * math.log(-math.log(1.0 - 1.0 / years))


def return_period(mu, beta, value):
    """给定量级反推重现期（年）。value 越大重现期越长。"""
    z = (value - mu) / beta
    p_exceed = 1.0 - math.exp(-math.exp(-z))  # 年超越概率
    if p_exceed <= 1e-12:
        return float("inf")
    return 1.0 / p_exceed


def fit_report(times, precip, window_h=1, periods=(2, 5, 10, 20, 50, 100, 1000)):
    """一站式：年最大值序列 → 拟合 → 各重现期量级。"""
    ann = annual_maxima(times, precip, window_h)
    years = sorted(ann)
    vals = [ann[y] for y in years]
    mu, beta = gumbel_fit(vals)
    curve = {int(t): return_level(mu, beta, t) for t in periods}
    return {
        "n_years": len(years),
        "year_span": (years[0], years[-1]) if years else (None, None),
        "observed_max": max(vals),
        "observed_max_year": years[vals.index(max(vals))],
        "mu": mu, "beta": beta,
        "window_h": window_h,
        "return_levels": curve,
    }
