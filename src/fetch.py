# -*- coding: utf-8 -*-
"""真实数据接入层：全部走 open-meteo 免费开放接口，无需 API Key。

三个数据源：
  · ERA5 历史再分析小时降雨（archive-api）—— 用来拟合"这块地在过去几十年里最多下过多大的雨"
  · GloFAS 河道流量预报（flood-api）—— 上游河道未来几天的流量，判断外洪风险
  · 数字高程（api，elevation）—— 判断你脚下是不是一块洼地

只依赖标准库 urllib/json，Python 3.9 可跑。联网失败会抛 FetchError，上层自行降级。
"""
import json
import time
import urllib.parse
import urllib.request
import urllib.error

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FLOOD = "https://flood-api.open-meteo.com/v1/flood"
FORECAST = "https://api.open-meteo.com/v1/forecast"
ELEVATION = "https://api.open-meteo.com/v1/elevation"

TZ = "Asia/Shanghai"


class FetchError(Exception):
    pass


def _get(url, params, timeout=90, retries=2):
    q = urllib.parse.urlencode(params, doseq=True)
    full = url + "?" + q
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "storm-blindspot/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise FetchError("接口请求失败：%s（%s）" % (full, last))


def hourly_precip_archive(lat, lon, start_date, end_date):
    """ERA5 逐小时降雨 mm。返回 (times, precip) 两个等长列表。"""
    d = _get(ARCHIVE, {
        "latitude": lat, "longitude": lon,
        "start_date": start_date, "end_date": end_date,
        "hourly": "precipitation", "timezone": TZ,
    })
    h = d.get("hourly") or {}
    t = h.get("time") or []
    p = [0.0 if v is None else float(v) for v in (h.get("precipitation") or [])]
    if not t:
        raise FetchError("ERA5 未返回降雨数据（坐标或日期可能超出覆盖范围）")
    return t, p, d.get("latitude"), d.get("longitude"), d.get("elevation")


def river_discharge_forecast(lat, lon, days=7):
    """GloFAS 未来 days 天的日均河道流量 m³/s。返回 (dates, discharge)。"""
    d = _get(FLOOD, {
        "latitude": lat, "longitude": lon,
        "daily": "river_discharge", "forecast_days": days,
    })
    dd = d.get("daily") or {}
    return dd.get("time") or [], [None if v is None else float(v) for v in (dd.get("river_discharge") or [])]


def precip_forecast(lat, lon, days=3):
    """未来 days 天逐小时降雨预报 mm。返回 (times, precip)。"""
    d = _get(FORECAST, {
        "latitude": lat, "longitude": lon,
        "hourly": "precipitation", "forecast_days": days, "timezone": TZ,
    })
    h = d.get("hourly") or {}
    return h.get("time") or [], [0.0 if v is None else float(v) for v in (h.get("precipitation") or [])]


def elevation_grid(points):
    """一次查多点高程。points=[(lat,lon),...]，返回 [m,...]。"""
    lats = ",".join(str(p[0]) for p in points)
    lons = ",".join(str(p[1]) for p in points)
    d = _get(ELEVATION, {"latitude": lats, "longitude": lons})
    return d.get("elevation") or []
