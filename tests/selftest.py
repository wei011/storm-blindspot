# -*- coding: utf-8 -*-
"""离线自测：不联网，用内置合成序列验证极值统计与盲区标定的数学正确性。"""
import os
import sys
import math

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from src import extremes, blindspot, warn  # noqa: E402


def _synthetic_years(n=40, base=10.0, step=0.5):
    """造 n 年、每年 8760 小时的序列，让年最大值大致线性增长，便于验证拟合可跑通。"""
    times, precip = [], []
    for y in range(n):
        year = 1980 + y
        peak_hour = 100 + y  # 每年峰值出现位置错开
        for h in range(200):  # 每年只放 200 小时足够测试滑窗与年归组
            times.append("%04d-07-01T%02d:00" % (year, h % 24))
            precip.append(base + step * y if h == peak_hour % 200 else 0.1)
    return times, precip


def test_annual_maxima():
    t, p = _synthetic_years()
    ann = extremes.annual_maxima(t, p, window_h=1)
    assert len(ann) == 40, ann
    assert abs(ann["1980"] - 10.0) < 1e-6
    assert abs(ann["2019"] - (10.0 + 0.5 * 39)) < 1e-6
    print("  ✓ annual_maxima 年归组与滑窗峰值正确")


def test_gumbel_roundtrip():
    # 已知 Gumbel(mu,beta) 采样的理论矩，验证矩法反解接近
    mu, beta = 20.0, 5.0
    mean = mu + 0.5772 * beta
    sd = math.pi * beta / math.sqrt(6)
    # 用理论矩造一组对称样本
    vals = [mean + sd * z for z in (-1.2, -0.6, 0, 0.6, 1.2, 1.8, -1.8, 0.3)]
    m, b = extremes.gumbel_fit(vals)
    lvl = extremes.return_level(m, b, 100)
    rp = extremes.return_period(m, b, lvl)
    assert 90 < rp < 110, rp  # 100年一遇量级反推回来应约100年
    print("  ✓ gumbel 拟合与重现期互逆自洽（100年→%.0f年）" % rp)


def test_kappa_and_verdict():
    assert blindspot.kappa(200, 20) == 10.0
    assert blindspot.kappa(200, 0) == float("inf")
    assert "数量级" in blindspot.classify_gap(10)
    v = blindspot.calibration_verdict([9.3, 43.6, 3.4])
    assert "不存在" in v, v  # 跨度>5倍应判"无通用订正系数"
    print("  ✓ κ 计算与'单一订正系数不成立'判据正确")


def test_sliding_peak():
    p = [0, 5, 10, 3, 0, 0]
    assert blindspot.sliding_peak(p, 1) == 10
    assert blindspot.sliding_peak(p, 2) == 15  # 5+10
    assert blindspot.sliding_peak(p, 3) == 18  # 5+10+3
    print("  ✓ 滑动窗口峰值正确")


def test_waterlogging():
    assert blindspot.waterlogging_index(100, [105, 103, 104, 108]) == 5.0
    assert blindspot.waterlogging_index(110, [105, 103]) == -6.0
    print("  ✓ 洼地指数正确")


def test_warning_levels():
    levels = [
        {"code": "blue", "name": "暴雨蓝色", "window_h": 12, "threshold_mm": 50},
        {"code": "red", "name": "暴雨红色", "window_h": 3, "threshold_mm": 100},
    ]
    # 3小时内塞120mm：既超蓝也超红，取红
    p = [40, 40, 40] + [0] * 20
    hit, detail = warn.warning_level(p, levels)
    assert hit["code"] == "red", hit
    print("  ✓ 暴雨预警级别取最高档正确")


if __name__ == "__main__":
    print("storm-blindspot 离线自测：")
    for fn in (test_annual_maxima, test_gumbel_roundtrip, test_kappa_and_verdict,
               test_sliding_peak, test_waterlogging, test_warning_levels):
        fn()
    print("\n全部通过 ✅（数学层不依赖网络；联网命令请跑 run.py calibrate）")
