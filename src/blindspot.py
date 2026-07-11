# -*- coding: utf-8 -*-
"""盲区标定：这个工具的立论所在。

再分析数据（ERA5 等）是全球气候研究、水文规划、保险定价的通用底料，
分辨率约 25 km。它把一个城市格点里的降雨做了空间平均——
于是把最凶的那种"局地对流暴雨"抹平了。

本模块做两件事：
  1. calibrate(): 拿有官方通报出处的历史极值实测值，去比 ERA5 在同点同时刻的峰值，
     算出低估倍数 κ = 实测 / 再分析。
  2. 说明为什么"乘一个 κ 修正"是错的：κ 在不同城市、不同地形之间差一个数量级，
     它不是一个常数，而是一个盲区的宽度。

低估倍数越大，代表"你若只信再分析数据做规划，越可能把百年一遇当成十年一遇"。
"""


def kappa(observed_mm, era5_peak_mm):
    """低估倍数。era5_peak_mm 为再分析在对应窗口的峰值。"""
    if era5_peak_mm <= 0:
        return float("inf")
    return observed_mm / era5_peak_mm


def sliding_peak(precip, window_h):
    """逐小时序列里 window_h 小时滑动累积的最大值。"""
    w = max(1, int(window_h))
    n = len(precip)
    if n < w:
        return sum(precip)
    best = 0.0
    s = sum(precip[:w])
    best = s
    for i in range(w, n):
        s += precip[i] - precip[i - w]
        if s > best:
            best = s
    return best


def classify_gap(k):
    """把低估倍数翻译成人话。"""
    if k == float("inf"):
        return "再分析几乎没记录到这场雨"
    if k < 2:
        return "基本抓住了"
    if k < 4:
        return "抹平了一半以上"
    if k < 10:
        return "低估了一个数量级上下"
    return "严重失真，差一个数量级以上"


def calibration_verdict(kappas):
    """给一组 κ 下总结论：单一修正系数是否成立。"""
    finite = [k for k in kappas if k != float("inf")]
    if not finite:
        return "样本不足"
    lo, hi = min(finite), max(finite)
    spread = hi / lo if lo > 0 else float("inf")
    if spread >= 5:
        return ("低估倍数在 %.1f×~%.1f× 之间横跳（相差 %.0f 倍），"
                "说明不存在一个通用的'订正系数'能把再分析数据修回真实——"
                "盲区的宽度本身随地形和天气系统剧烈变化。" % (lo, hi, spread))
    return "低估倍数相对集中在 %.1f×~%.1f×，可作粗略订正参考，但仍不建议外推。" % (lo, hi)


def waterlogging_index(elevation_self, elevation_neighbors):
    """洼地指数：自身高程相对周边邻域的下沉深度（米）。正值=比周边低=易积水。"""
    neigh = [e for e in elevation_neighbors if e is not None]
    if not neigh or elevation_self is None:
        return None
    return round(sum(neigh) / len(neigh) - elevation_self, 1)
