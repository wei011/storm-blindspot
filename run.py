#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""storm-blindspot · 暴雨盲区

一句话：我们用来研究洪水、规划排水、给房子定保费的那套"权威降雨数据"，
到底把最凶的暴雨抹平了多少倍？这个工具用真实接口把这个盲区量出来。

子命令：
  calibrate            用三座城市的官方实测极值，标定再分析数据的低估倍数 κ
  blindspot <city>     拉该市 ERA5 长序列，拟合"N年一遇小时雨强"，对比实测极值看盲区
  warn <city>          用国标暴雨预警阈值翻译未来 3 天预报（绝对阈值，不受盲区影响）
  risk <city>          综合：未来降雨预警 + 上游河道流量 + 脚下洼地指数
  ls                   城市库
  spec <city>          某市的坐标、分级、排水设计重现期、实测锚点

通用参数：
  --lat --lon          自定义坐标（覆盖城市库，可体检任意地点）
  --years N            ERA5 回溯年数（默认 44，1980 至今；最长可到 1950）
  --window N           极值统计的累积小时窗（默认 1，即小时雨强）
  --json               结构化输出，喂给 agent

纯标准库，唯一外部依赖是 open-meteo 免费接口（无需 Key）。
"""
import os
import sys
import json
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from src import fetch, extremes, blindspot, warn  # noqa: E402

DATA = json.load(open(os.path.join(HERE, "data", "cities.json"), encoding="utf-8"))
CITIES = DATA["cities"]
DRAIN = DATA["drainage_gb50014"]
WARN_LEVELS = DATA["rain_warning_gb"]["levels"]

TIER_NAME = DATA["_meta"]["tiers"]


def _arg(args, name, default=None):
    if name in args:
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def _resolve(args):
    """返回 (key, name, lat, lon, tier, anchor)。支持 --lat/--lon 覆盖。"""
    lat = _arg(args, "--lat")
    lon = _arg(args, "--lon")
    key = None
    for a in args:
        if a in CITIES:
            key = a
            break
    if key:
        c = CITIES[key]
        return key, c["name"], float(lat or c["lat"]), float(lon or c["lon"]), c["tier"], c.get("anchor")
    if lat and lon:
        return None, "自定义点(%s,%s)" % (lat, lon), float(lat), float(lon), None, None
    return None, None, None, None, None, None


def _era5_dates(years):
    end = datetime.date.today()
    start = datetime.date(max(1950, end.year - years), 1, 1)
    return start.isoformat(), end.isoformat()


# ---------- 子命令 ----------

def cmd_ls(args):
    rows = []
    for k, c in CITIES.items():
        mark = "  ★有实测锚点" if c.get("anchor") else ""
        rows.append((k, c["name"], c["tier"], mark))
    if "--json" in args:
        print(json.dumps([{"key": r[0], "name": r[1], "tier": r[2]} for r in rows], ensure_ascii=False, indent=2))
        return
    print("城市库（%d 座）：\n" % len(rows))
    for k, name, tier, mark in rows:
        print("  %-11s %-6s %s%s" % (k, name, tier, mark))
    print("\n★ = 有官方通报出处的历史极值，可用于 calibrate。任意坐标可用 --lat --lon 体检。")


def cmd_spec(args):
    key, name, lat, lon, tier, anchor = _resolve(args)
    if not name:
        sys.exit("用法：run.py spec <city>，或 --lat --lon")
    pipe = DRAIN["pipe_recurrence_years"].get(tier or "")
    wl = DRAIN["waterlogging_recurrence_years"].get(tier or "")
    out = {
        "key": key, "name": name, "lat": lat, "lon": lon,
        "tier": tier, "tier_name": TIER_NAME.get(tier or ""),
        "pipe_recurrence_years": pipe, "waterlogging_recurrence_years": wl,
        "anchor": anchor,
    }
    if "--json" in args:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print("=== %s ===" % name)
    print("坐标：%.4f, %.4f" % (lat, lon))
    print("城镇分级：%s（%s）" % (tier, TIER_NAME.get(tier or "未知")))
    if pipe:
        print("\nGB 50014-2021 雨水管渠设计重现期（年）：")
        print("  中心城区 %s | 非中心城区 %s | 重要地区 %s | 地下通道/下沉广场 %s"
              % (pipe["central"], pipe["non_central"], pipe["key_area"], pipe["underpass_plaza"]))
        print("  内涝防治设计重现期：%s 年" % wl)
        print("  （通俗说：中心城区排水管就是按'几年一遇'的雨设计的——超了就淹）")
    if anchor:
        print("\n历史极值锚点：%s mm / %s小时" % (anchor["value_mm"], anchor["window_h"]))
        print("  %s" % anchor["label"])
        print("  时间：%s" % anchor["when"])
        print("  出处：%s" % anchor["source"])


def cmd_calibrate(args):
    """核心命令：三城实测 vs ERA5，量盲区。"""
    anchored = [(k, c) for k, c in CITIES.items() if c.get("anchor")]
    results = []
    print("正在从 ERA5 再分析拉取三座城市对应时段的降雨（各约需数秒）...\n", file=sys.stderr)
    for k, c in anchored:
        a = c["anchor"]
        # 同场暴雨、同一地点：取事件当天 ±1 天、在实测发生的坐标上取 ERA5 滑窗峰值。
        # 这样比的是"同一场雨"，而不是拿全年最大的另一场雨来稀释盲区。
        elat = a.get("event_lat", c["lat"])
        elon = a.get("event_lon", c["lon"])
        d0 = datetime.date.fromisoformat(a["event_date"])
        s = (d0 - datetime.timedelta(days=1)).isoformat()
        e = (d0 + datetime.timedelta(days=1)).isoformat()
        try:
            t, p, glat, glon, elev = fetch.hourly_precip_archive(elat, elon, s, e)
        except fetch.FetchError as ex:
            print("  [跳过] %s：%s" % (c["name"], ex))
            continue
        era5_peak = blindspot.sliding_peak(p, a["window_h"])
        k_val = blindspot.kappa(a["value_mm"], era5_peak)
        results.append({
            "city": c["name"], "window_h": a["window_h"],
            "observed_mm": a["value_mm"], "era5_peak_mm": round(era5_peak, 1),
            "kappa": None if k_val == float("inf") else round(k_val, 1),
            "verdict": blindspot.classify_gap(k_val),
            "grid": [glat, glon], "source": a["source"],
        })
    verdict = blindspot.calibration_verdict([
        (r["kappa"] if r["kappa"] is not None else float("inf")) for r in results])

    if "--json" in args:
        print(json.dumps({"anchors": results, "conclusion": verdict}, ensure_ascii=False, indent=2))
        return
    print("低估倍数标定（κ = 官方实测 ÷ ERA5 再分析峰值）：\n")
    print("  %-8s %-8s %-12s %-12s %-8s" % ("城市", "窗口", "官方实测", "ERA5峰值", "低估倍数"))
    print("  " + "-" * 52)
    for r in results:
        kd = "∞" if r["kappa"] is None else ("%.1f×" % r["kappa"])
        print("  %-7s %3d小时 %8.1fmm %10.1fmm %8s   %s"
              % (r["city"], r["window_h"], r["observed_mm"], r["era5_peak_mm"], kd, r["verdict"]))
    print("\n结论：" + verdict)
    print("\n注：ERA5 格点约 25km，取的是城市坐标所在格点值。深圳/北京锚点位于山区或城郊格点，")
    print("    盲区尤其大——这正是'一个修正系数救不了再分析数据'的证据。")


def cmd_blindspot(args):
    key, name, lat, lon, tier, anchor = _resolve(args)
    if not name:
        sys.exit("用法：run.py blindspot <city>，或 --lat --lon")
    years = int(_arg(args, "--years", "44"))
    window = int(_arg(args, "--window", "1"))
    start, end = _era5_dates(years)
    print("正在拉取 %s %s→%s 的 ERA5 逐小时降雨并拟合极值分布...\n" % (name, start[:4], end[:4]),
          file=sys.stderr)
    t, p, glat, glon, elev = fetch.hourly_precip_archive(lat, lon, start, end)
    rep = extremes.fit_report(t, p, window_h=window)

    era5_100 = rep["return_levels"].get(100)
    era5_1000 = rep["return_levels"].get(1000)
    out = {"city": name, "grid": [glat, glon], "elevation_m": elev,
           "window_h": window, "fit": rep}

    # 若有实测锚点且窗口匹配，算盲区
    gap = None
    if anchor and anchor["window_h"] == window:
        obs = anchor["value_mm"]
        rp = extremes.return_period(rep["mu"], rep["beta"], obs)
        gap = {"observed_mm": obs, "era5_says_return_period_years":
               None if rp == float("inf") else round(rp),
               "era5_100yr_level_mm": round(era5_100, 1),
               "underestimate_vs_100yr": round(obs / era5_100, 1) if era5_100 else None}
        out["blindspot"] = gap

    if "--json" in args:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return

    ys, ye = rep["year_span"]
    print("=== %s · %d 小时雨强的极值分析 ===" % (name, window))
    print("样本：%s–%s 共 %d 年（ERA5 格点 %.3f,%.3f，高程 %sm）"
          % (ys, ye, rep["n_years"], glat, glon, elev))
    print("这些年里再分析记录到的最大 %d 小时雨量：%.1f mm（%s 年）\n"
          % (window, rep["observed_max"], rep["observed_max_year"]))
    print("ERA5 口径下的'N 年一遇'%d 小时雨强：" % window)
    for yr in (2, 5, 10, 20, 50, 100, 1000):
        print("  %5d 年一遇：%6.1f mm" % (yr, rep["return_levels"][yr]))
    if gap:
        rpt = gap["era5_says_return_period_years"]
        print("\n盲区：该市官方实测极值 %.1f mm（%s）" % (anchor["value_mm"], anchor["when"]))
        print("  按 ERA5 拟合，这场雨要 %s年一遇——"
              % ("∞（超出拟合上限）" if rpt is None else "%d " % rpt))
        print("  也就是说，真实发生过的雨，在再分析数据眼里几乎'不可能发生'。")
        print("  它比 ERA5 认定的'百年一遇'（%.1fmm）还高 %.1f 倍。"
              % (gap["era5_100yr_level_mm"], gap["underestimate_vs_100yr"]))
    else:
        print("\n（该市无匹配窗口的官方实测锚点；换 --window 1 看小时雨强盲区，或用 calibrate 看三城对比。）")


def cmd_warn(args):
    key, name, lat, lon, tier, anchor = _resolve(args)
    if not name:
        sys.exit("用法：run.py warn <city>，或 --lat --lon")
    days = int(_arg(args, "--days", "3"))
    t, p = fetch.precip_forecast(lat, lon, days)
    hit, detail = warn.warning_level(p, WARN_LEVELS)
    out = {"city": name, "days": days, "highest": hit, "levels": detail}
    if "--json" in args:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print("=== %s 未来 %d 天暴雨预警研判（国标绝对阈值口径）===\n" % (name, days))
    total = round(sum(p), 1)
    print("预报累计降雨：%.1f mm\n" % total)
    print("  %-10s %-16s %-12s %s" % ("级别", "阈值", "预报峰值", "触发"))
    print("  " + "-" * 48)
    for d in detail:
        print("  %-9s %2d小时≥%3dmm    %7.1fmm     %s"
              % (d["name"], d["window_h"], d["threshold_mm"], d["forecast_peak_mm"],
                 "⚠️ 触发" if d["triggered"] else "—"))
    if hit:
        print("\n最高触发：%s。这是绝对阈值，不受再分析盲区影响，可直接采信。" % hit["name"])
    else:
        print("\n未来 %d 天预报雨量未触及任何暴雨预警阈值。" % days)


def cmd_risk(args):
    key, name, lat, lon, tier, anchor = _resolve(args)
    if not name:
        sys.exit("用法：run.py risk <city>，或 --lat --lon")
    # 1) 降雨预警
    t, p = fetch.precip_forecast(lat, lon, 3)
    hit, detail = warn.warning_level(p, WARN_LEVELS)
    # 2) 河道流量
    rd_t, rd = fetch.river_discharge_forecast(lat, lon, 7)
    rd_valid = [v for v in rd if v is not None]
    rd_trend = None
    if len(rd_valid) >= 2:
        rd_trend = round((rd_valid[-1] - rd_valid[0]) / rd_valid[0] * 100, 0) if rd_valid[0] else None
    # 3) 洼地指数（自身 + 上下左右各 ~1km）
    d = 0.01
    pts = [(lat, lon), (lat + d, lon), (lat - d, lon), (lat, lon + d), (lat, lon - d)]
    elev = fetch.elevation_grid(pts)
    wi = blindspot.waterlogging_index(elev[0] if elev else None, elev[1:] if elev else [])

    out = {
        "city": name,
        "rain_warning": hit["name"] if hit else "无",
        "rain_total_3d_mm": round(sum(p), 1),
        "river_discharge_m3s": {"now": rd_valid[0] if rd_valid else None,
                                "in_7d": rd_valid[-1] if rd_valid else None,
                                "trend_pct": rd_trend},
        "elevation_self_m": elev[0] if elev else None,
        "waterlogging_index_m": wi,
    }
    if "--json" in args:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print("=== %s 内涝综合研判 ===\n" % name)
    print("① 天上：未来3天预报累计 %.1f mm，暴雨预警 %s"
          % (out["rain_total_3d_mm"], out["rain_warning"]))
    if rd_valid:
        tr = "" if rd_trend is None else "（7天%s%.0f%%）" % ("↑" if rd_trend >= 0 else "↓", abs(rd_trend))
        print("② 河里：上游河道流量 现约 %.1f → 7天后 %.1f m³/s %s"
              % (rd_valid[0], rd_valid[-1], tr))
    else:
        print("② 河里：该点无 GloFAS 河道数据（多为无大河经过的内陆点）")
    if wi is not None:
        if wi > 3:
            desc = "明显低于周边 %.1fm，是相对洼地，积水风险偏高" % wi
        elif wi > 0:
            desc = "略低于周边 %.1fm" % wi
        else:
            desc = "高于或持平周边（%.1fm），地形排水相对有利" % wi
        print("③ 脚下：高程 %.0fm，%s" % (out["elevation_self_m"], desc))
    print("\n提示：①是绝对阈值可信；②③是趋势与地形参考。真正的内涝还取决于本地管网、")
    print("     泵站与实时调度，本工具不替代官方预警——它替代的是'我以为这里不会淹'的错觉。")


CMDS = {
    "ls": cmd_ls, "spec": cmd_spec, "calibrate": cmd_calibrate,
    "blindspot": cmd_blindspot, "warn": cmd_warn, "risk": cmd_risk,
}


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd = args[0]
    fn = CMDS.get(cmd)
    if not fn:
        sys.exit("未知子命令：%s\n可用：%s" % (cmd, " ".join(CMDS)))
    try:
        fn(args[1:])
    except fetch.FetchError as e:
        sys.exit("联网取数失败：%s\n（本工具依赖 open-meteo 免费接口，请检查网络后重试）" % e)


if __name__ == "__main__":
    main()
