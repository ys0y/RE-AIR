"""
RE:AIR - 항공 지연 데이터 분석 모듈 (빅데이터)

한국공항공사 공공데이터(공공데이터포털)를 읽어 지연·결항 위험을 계산합니다.
  - data/airport_delay.csv  : 공항별 지연 현황 (공항, 국내/국제, 운항편수, 지연편수, 원인별 건수)
  - data/airport_cancel.csv : 공항별 결항 현황 (계획편수, 결항편수, 원인별 건수)
  - data/hourly_delay.csv   : 2017~2025년 월·시간대별 지연 (여객, 지연편수, 지연시간)
※ 인천공항은 한국공항공사 관할이 아니라 포함되지 않습니다.
※ 편명별 기록이 아니라 '같은 공항·시간대·월'의 과거 통계로 위험도를 추정합니다.
"""
import csv
import os
import re
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

SOURCE = "한국공항공사 공공데이터(공공데이터포털) · 인천공항 제외"

AIRLINES = {
    "KE": "대한항공", "OZ": "아시아나항공", "7C": "제주항공", "LJ": "진에어", "TW": "티웨이항공",
    "BX": "에어부산", "RS": "에어서울", "ZE": "이스타항공", "YP": "에어프레미아", "RF": "에어로케이",
    "4V": "플라이강원", "JL": "일본항공", "NH": "전일본공수", "MM": "피치항공", "CX": "캐세이퍼시픽",
}


def _read(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _num(value):
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def _load():
    """서버가 켜질 때 한 번만 데이터를 읽어 필요한 통계를 미리 계산해 둡니다."""
    delay = _read("airport_delay.csv")
    cancel = _read("airport_cancel.csv")
    hourly = _read("hourly_delay.csv")

    stats = {"airports": {}, "national": {}, "hour": {}, "month": {}}

    # 1) 공항별 지연률·결항률
    for r in delay:
        ops = _num(r["운항편수"])
        if ops <= 0:
            continue
        stats["airports"][(r["공항"], r["노선"])] = {
            "ops": int(ops),
            "delay_rate": _num(r["지연편수"]) / ops * 100,
        }
    for r in cancel:
        key = (r["공항"], r["노선"])
        if key in stats["airports"] and _num(r["계획편수"]) > 0:
            stats["airports"][key]["cancel_rate"] = _num(r["결항편수"]) / _num(r["계획편수"]) * 100

    # 2) 전국 평균 + 원인 비율
    for route in ("국내", "국제"):
        rows = [r for r in delay if r["노선"] == route]
        ops = sum(_num(r["운항편수"]) for r in rows)
        stats["national"][route] = sum(_num(r["지연편수"]) for r in rows) / ops * 100 if ops else 0
    ops_all = sum(_num(r["운항편수"]) for r in delay)
    delayed_all = sum(_num(r["지연편수"]) for r in delay)
    stats["national"]["전체"] = delayed_all / ops_all * 100
    cause_cols = {"연결편": "비행기 연결편 지연건수", "기상": "기상 원인 지연 건수",
                  "정비": "비행기 정비 원인 지연 건수", "기타": "기타 건수"}
    cause_total = sum(sum(_num(r[c]) for r in delay) for c in cause_cols.values())
    stats["delay_causes"] = {k: round(sum(_num(r[c]) for r in delay) / cause_total * 100) for k, c in cause_cols.items()}
    planned = sum(_num(r["계획편수"]) for r in cancel)
    cancelled = sum(_num(r["결항편수"]) for r in cancel)
    stats["national"]["결항"] = cancelled / planned * 100
    stats["cancel_weather"] = round(sum(_num(r["기상 원인 결항(건)"]) for r in cancel) / cancelled * 100)

    # 3) 시간대별 평균 지연시간 (출발편, 국내/국제)
    hour_sum = defaultdict(lambda: [0.0, 0.0])
    month_sum = defaultdict(lambda: [0.0, 0.0])
    for r in hourly:
        if r["출도착"] != "출발":
            continue
        route = r["국내_국제"]
        hour_sum[(route, int(_num(r["시간대"])))][0] += _num(r["합계지연시간(분)"])
        hour_sum[(route, int(_num(r["시간대"])))][1] += _num(r["지연(편)"])
        # 월별: 여객 1만 명당 지연 편수 (계절별 지연 빈도 지표)
        month_sum[(route, int(_num(r["월"])))][0] += _num(r["지연(편)"])
        month_sum[(route, int(_num(r["월"])))][1] += _num(r["여객(명)"])

    for route in ("국내", "국제"):
        hours = {h: s / n for (rt, h), (s, n) in hour_sum.items() if rt == route and n >= 30}
        total_s = sum(s for (rt, _), (s, n) in hour_sum.items() if rt == route)
        total_n = sum(n for (rt, _), (s, n) in hour_sum.items() if rt == route)
        stats["hour"][route] = {"by_hour": hours, "avg": total_s / total_n if total_n else 0}
        months = {m: d / p * 10000 for (rt, m), (d, p) in month_sum.items() if rt == route and p > 0}
        stats["month"][route] = {"by_month": months, "avg": sum(months.values()) / len(months) if months else 0}
    return stats


STATS = _load()
AIRPORT_NAMES = sorted({name for name, _ in STATS["airports"]})


def _level(ratio):
    if ratio < 0.9:
        return "낮음"
    if ratio < 1.15:
        return "보통"
    return "높음"


def parse_flight(flight_no):
    """편명(예: KE1234, 7c 101)에서 항공사 이름을 찾아 줍니다."""
    code = re.sub(r"\s+", "", (flight_no or "").upper())[:8]
    if not code:
        return "", ""
    return code, AIRLINES.get(code[:2], "")


def risk_check(airport, route, hour, month, flight_no=""):
    """공항·국내/국제·출발 시각·월로 과거 데이터 기반 지연 위험을 계산합니다."""
    route = route if route in ("국내", "국제") else "국제"
    code, airline = parse_flight(flight_no)
    national = STATS["national"][route]
    result = {
        "flight": code, "airline": airline, "airport": airport, "route": route,
        "source": SOURCE, "factors": [], "tips": [],
    }

    ratios = []
    ap = STATS["airports"].get((airport, route))
    if ap:
        ratio = ap["delay_rate"] / national if national else 1
        ratios.append(ratio)
        result["factors"].append({
            "label": "공항 지연률",
            "value": f"{ap['delay_rate']:.1f}%",
            "compare": f"평균 {national:.1f}%",
            "level": _level(ratio),
        })
        if "cancel_rate" in ap:
            result["cancel_rate"] = round(ap["cancel_rate"], 2)
    else:
        result["airport_note"] = "인천·해외 공항은 데이터가 없어 시간대·계절 통계로만 계산했어요."

    hours = STATS["hour"][route]
    if hour in hours["by_hour"]:
        minutes = hours["by_hour"][hour]
        ratio = minutes / hours["avg"] if hours["avg"] else 1
        ratios.append(ratio)
        result["factors"].append({
            "label": f"{hour}시대 지연 시간",
            "value": f"{minutes:.0f}분",
            "compare": f"평균 {hours['avg']:.0f}분",
            "level": _level(ratio),
        })
        result["hour_minutes"] = round(minutes)

    months = STATS["month"][route]
    if month in months["by_month"]:
        ratio = months["by_month"][month] / months["avg"] if months["avg"] else 1
        ratios.append(ratio)
        result["factors"].append({
            "label": f"{month}월 지연 빈도",
            "value": f"{ratio * 100:.0f}%",
            "compare": "연평균 100%",
            "level": _level(ratio),
        })

    overall = sum(ratios) / len(ratios) if ratios else 1
    result["level"] = _level(overall)
    result["score"] = round(min(overall, 2) / 2 * 100)  # 막대 표시용 0~100

    # 데이터 기반 대비 팁 (AI 호출 없음)
    causes = STATS["delay_causes"]
    tips = [f"지연의 {causes['연결편']}%는 앞 비행기 때문 → 출발 전 이전 편 도착 확인"]
    if result.get("hour_minutes"):
        tips.append(f"지연되면 평균 {result['hour_minutes']}분 → 도착 후 일정에 여유 두기")
    else:
        tips.append(f"결항의 {STATS['cancel_weather']}%는 날씨 → 전날 날씨 확인")
    if result["level"] == "높음":
        tips.append("여행 마지막 날이라면 다음 날 오전은 비워 두기")
    result["tips"] = tips
    return result


def data_context(trip):
    """
    AI에게 함께 보낼 '실제 데이터 요약' (항공 문제일 때만).
    짧게 유지해 토큰을 아낍니다.
    """
    if trip.get("problem_type") != "항공 문제":
        return ""
    causes = STATS["delay_causes"]
    lines = [
        f"- 한국 공항(인천 제외) 전체 지연률 {STATS['national']['전체']:.1f}%, 결항률 {STATS['national']['결항']:.2f}%",
        f"- 한국 공항 지연 원인: 앞 비행기 연결 {causes['연결편']}%, 기타 {causes['기타']}%, 정비 {causes['정비']}%, 기상 {causes['기상']}%",
        f"- 결항 원인의 {STATS['cancel_weather']}%는 기상",
    ]
    text = f"{trip.get('location', '')} {trip.get('situation', '')}"
    for name in AIRPORT_NAMES:
        if name in text:
            for route in ("국내", "국제"):
                ap = STATS["airports"].get((name, route))
                if ap:
                    lines.append(f"- {name}공항 {route}선 지연률 {ap['delay_rate']:.1f}%")
            break
    return "\n".join(lines)
