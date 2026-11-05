"""
RE:AIR - Flask 서버
항공편이 멈춰도, 당신의 여행은 멈추지 않도록.
"""
import os
import threading
import time
from collections import defaultdict, deque

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_from_directory

# .env 파일에 적어 둔 환경변수(API 키 등)를 불러옵니다.
# (ai_client가 환경변수를 읽기 때문에 import보다 먼저 실행)
load_dotenv()

import ai_client  # noqa: E402  생성형 AI 연결 모듈
import prompts    # noqa: E402  AI 지시문

app = Flask(__name__)


# =========================================================
# 입력값 검사 규칙
# (브라우저에서도 검사하지만, 서버에서 한 번 더 검사해야 안전합니다)
# =========================================================
FIELDS = [
    "problem_type", "location", "destination", "departure_time",
    "remaining_time", "situation", "budget", "priority",
]

REQUIRED_MESSAGES = {
    "problem_type": "문제 유형을 선택해 주세요.",
    "location": "현재 위치를 입력해 주세요.",
    "destination": "목적지를 입력해 주세요.",
    "departure_time": "출발 예정 시간을 입력해 주세요.",
    "situation": "지금 상황을 적어 주세요.",
    "priority": "가장 중요한 조건을 골라 주세요.",
}

ALLOWED_VALUES = {
    "problem_type": {"항공편 결항", "항공편 지연", "환승 실패"},
    "priority": {"비용 최소화", "빠른 귀국", "기존 일정 유지", "편안함과 안전"},
}

MAX_LENGTH = {"location": 100, "destination": 100, "situation": 1000}
SITUATION_MIN_LENGTH = 15


def validate_trip_input(data):
    """입력값을 정리하고, 문제가 있으면 {항목: 오류 메시지} 형태로 돌려줍니다."""
    trip = {field: str(data.get(field) or "").strip() for field in FIELDS}
    errors = {}

    for field, message in REQUIRED_MESSAGES.items():
        if not trip[field]:
            errors[field] = message

    if trip["situation"] and len(trip["situation"]) < SITUATION_MIN_LENGTH:
        errors["situation"] = f"조금만 더 자세히 적어 주세요. ({SITUATION_MIN_LENGTH}자 이상)"

    for field, limit in MAX_LENGTH.items():
        if len(trip[field]) > limit:
            errors[field] = f"{limit}자 이내로 입력해 주세요."

    for field, allowed in ALLOWED_VALUES.items():
        if trip[field] and trip[field] not in allowed:
            errors[field] = "보기 중에서 골라 주세요."

    return trip, errors


# =========================================================
# 과다 사용 방지 (인터넷에 공개했을 때 학교 API 사용량 보호)
# =========================================================
PER_USER_LIMIT = int(os.getenv("RATE_LIMIT_PER_USER", "10"))   # 한 사람당 10분에 최대 요청 수
PER_USER_WINDOW = 600                                          # 10분(초)
DAILY_LIMIT = int(os.getenv("RATE_LIMIT_DAILY", "300"))        # 하루 전체 최대 요청 수

_user_requests = defaultdict(deque)
_daily = {"day": "", "count": 0}
_lock = threading.Lock()


def client_ip():
    """요청한 사람의 IP. (Render 같은 서버에서는 X-Forwarded-For에 실제 IP가 담겨 옴)"""
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or request.remote_addr or "unknown"


def check_rate_limit():
    """허용되면 None, 너무 많으면 사용자에게 보여 줄 메시지를 돌려줍니다."""
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    with _lock:
        if _daily["day"] != today:
            _daily.update(day=today, count=0)
        if _daily["count"] >= DAILY_LIMIT:
            return "오늘 사용 가능한 AI 요청을 모두 사용했어요. [시연용 데이터로 보기]로 체험해 주세요."

        history = _user_requests[client_ip()]
        while history and now - history[0] > PER_USER_WINDOW:
            history.popleft()
        if len(history) >= PER_USER_LIMIT:
            wait = int(PER_USER_WINDOW - (now - history[0])) // 60 + 1
            return f"요청이 너무 많아요. 약 {wait}분 뒤에 다시 시도해 주세요."

        history.append(now)
        _daily["count"] += 1
    return None


# =========================================================
# AI 결과 정리
# (AI가 가끔 형식을 조금 틀리게 보내도 화면이 깨지지 않도록 다듬습니다)
# =========================================================
LEVELS = {"낮음", "보통", "높음"}


def _text(value, default=""):
    return str(value).strip() if value not in (None, "") else default


def _text_list(value, limit):
    if not isinstance(value, list):
        return []
    return [_text(v) for v in value if _text(v)][:limit]


def _level(value):
    value = _text(value)
    return value if value in LEVELS else "보통"


def normalize_analysis(data, priority):
    """AI의 분석 결과를 화면에서 쓰는 형식으로 정리합니다. 너무 망가져 있으면 오류를 냅니다."""
    analysis = data.get("analysis") if isinstance(data, dict) else None
    strategies = data.get("strategies") if isinstance(data, dict) else None
    if not isinstance(analysis, dict) or not isinstance(strategies, list) or len(strategies) < 3:
        raise ai_client.AIError("AI 결과가 완전하지 않아요. 다시 시도해 주세요.", "bad_json")

    urgent = analysis.get("urgent") if isinstance(analysis.get("urgent"), dict) else {}
    clean_analysis = {
        "summary": _text(analysis.get("summary")),
        "problems": _text_list(analysis.get("problems"), 4),
        "impacts": [
            {"area": _text(m.get("area"), "영향"), "level": _level(m.get("level")), "detail": _text(m.get("detail"))}
            for m in (analysis.get("impacts") or []) if isinstance(m, dict)
        ][:4],
        "urgent": {"title": _text(urgent.get("title")), "reason": _text(urgent.get("reason"))},
        "check_first": _text_list(analysis.get("check_first"), 5),
    }

    clean_strategies = []
    for index, s in enumerate(strategies[:3]):
        if not isinstance(s, dict):
            raise ai_client.AIError("AI 결과가 완전하지 않아요. 다시 시도해 주세요.", "bad_json")
        clean_strategies.append({
            "id": "ABC"[index],  # 순서대로 A, B, C로 고정
            "label": _text(s.get("label"), ["비용 최소화", "빠른 귀국", "기존 일정 유지"][index]),
            "title": _text(s.get("title")),
            "description": _text(s.get("description")),
            "pros": _text_list(s.get("pros"), 3),
            "cons": _text_list(s.get("cons"), 3),
            "cautions": _text_list(s.get("cautions"), 3),
            "actions": _text_list(s.get("actions"), 4),
            "cost_level": _level(s.get("cost_level")),
            "speed_level": _level(s.get("speed_level")),
            "keep_level": _level(s.get("keep_level")),
            "recommended": s.get("recommended") is True,
            "fit_reason": _text(s.get("fit_reason")),
        })

    # 추천 전략은 정확히 하나만: 없거나 여러 개면 사용자 우선순위와 label이 같은 전략을 고릅니다.
    if sum(s["recommended"] for s in clean_strategies) != 1:
        match = next((s for s in clean_strategies if priority and priority in s["label"]), clean_strategies[0])
        for s in clean_strategies:
            s["recommended"] = s is match

    return {"analysis": clean_analysis, "strategies": clean_strategies}


STATUSES = {"유지", "변경", "추가", "취소"}
WHEN_VALUES = {"지금 즉시", "1시간 이내", "오늘 중", "내일"}


def normalize_plan(data):
    """AI의 일정표·문의문·체크리스트를 화면 형식으로 정리합니다."""
    if not isinstance(data, dict):
        raise ai_client.AIError("AI 결과가 완전하지 않아요. 다시 시도해 주세요.", "bad_json")
    itinerary = data.get("itinerary") if isinstance(data.get("itinerary"), dict) else {}
    rows = [
        {
            "time": _text(r.get("time"), "-"),
            "original": _text(r.get("original"), "-"),
            "new": _text(r.get("new")),
            "status": _text(r.get("status")) if _text(r.get("status")) in STATUSES else "변경",
        }
        for r in (itinerary.get("rows") or []) if isinstance(r, dict) and _text(r.get("new"))
    ][:7]
    messages = [
        {
            "target": _text(m.get("target"), "문의처"),
            "purpose": _text(m.get("purpose")),
            "ko": _text(m.get("ko")),
            "en": _text(m.get("en")),
            "ja": _text(m.get("ja")),
        }
        for m in (data.get("messages") or []) if isinstance(m, dict) and _text(m.get("ko"))
    ][:3]
    checklist = [
        {
            "priority": index + 1,
            "when": _text(c.get("when")) if _text(c.get("when")) in WHEN_VALUES else "오늘 중",
            "task": _text(c.get("task")),
            "detail": _text(c.get("detail")),
        }
        for index, c in enumerate(c for c in (data.get("checklist") or []) if isinstance(c, dict) and _text(c.get("task")))
    ][:6]

    if not rows or not messages or not checklist:
        raise ai_client.AIError("AI 결과가 완전하지 않아요. 다시 시도해 주세요.", "bad_json")
    return {
        "itinerary": {"summary": _text(itinerary.get("summary")), "rows": rows},
        "messages": messages,
        "checklist": checklist,
    }


def clean_strategy(raw):
    """브라우저가 보낸 선택 전략에서 필요한 글자만 짧게 꺼냅니다. (토큰 절약 + 안전)"""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "id": _text(raw.get("id"))[:1],
        "label": _text(raw.get("label"))[:20],
        "title": _text(raw.get("title"))[:40],
        "description": _text(raw.get("description"))[:120],
        "actions": [a[:50] for a in _text_list(raw.get("actions"), 4)],
    }


def run_ai_json(system_prompt, user_prompt, normalize, max_tokens):
    """AI를 호출하고 결과를 정리합니다. 형식이 깨진 답이 오면 한 번 더 시도합니다."""
    for attempt in range(2):
        try:
            data = ai_client.chat_json(system_prompt, user_prompt, max_tokens=max_tokens, temperature=0.6)
            return normalize(data)
        except ai_client.AIError as e:
            if e.code != "bad_json" or attempt == 1:
                raise
            print("[AI] 형식이 맞지 않는 답변 - 다시 요청합니다.", flush=True)


# =========================================================
# 화면 / API 주소
# =========================================================
@app.route("/")
def index():
    """메인 화면을 보여 줍니다."""
    return render_template("index.html")


@app.route("/sw.js")
def service_worker():
    """앱 설치용 서비스 워커. 사이트 전체(/)를 관리하려면 맨 위 주소에서 제공해야 합니다."""
    response = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/api/health")
def health():
    """서버가 잘 켜졌는지, API 키가 설정되었는지 확인하는 용도입니다."""
    return jsonify({
        "status": "ok",
        **ai_client.key_diagnosis(),  # 키 값 자체는 절대 보내지 않음 (길이·형식만)
        "model": ai_client.get_config()["model"],
    })


@app.route("/api/ai-test")
def ai_test():
    """브라우저에서 이 주소를 열면 AI 연결이 잘 되는지 확인할 수 있습니다. (내 컴퓨터에서만)"""
    if os.getenv("RENDER"):  # Render 서버에서는 자동으로 RENDER 환경변수가 생김
        return jsonify({"ok": False, "error": "배포 환경에서는 사용할 수 없어요."}), 404
    try:
        result = ai_client.test_connection()
        return jsonify({"ok": True, **result})
    except ai_client.AIError as e:
        return jsonify({"ok": False, "error": e.message, "code": e.code}), 502


@app.post("/api/analyze")
def analyze():
    """사용자의 여행 상황을 받아 분석합니다."""
    data = request.get_json(silent=True) or {}
    trip, errors = validate_trip_input(data)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    # 내 컴퓨터에서만: 터미널에 받은 입력을 출력 (배포 서버에서는 개인정보 보호를 위해 기록하지 않음)
    if not os.getenv("RENDER"):
        print("\n[입력 수신]", flush=True)
        for key, value in trip.items():
            print(f"  {key}: {value}", flush=True)

    limited = check_rate_limit()
    if limited:
        return jsonify({"ok": False, "input": trip, "error": limited, "code": "rate_limit"}), 429

    # 생성형 AI로 상황 분석 + 복구 전략 3가지 생성
    started = time.time()
    try:
        result = run_ai_json(
            prompts.ANALYZE_SYSTEM,
            prompts.build_analyze_prompt(trip),
            normalize=lambda data: normalize_analysis(data, trip["priority"]),
            max_tokens=3000,  # 토큰 한도 고정 - 대신 프롬프트에서 글자 수를 제한
        )
    except ai_client.AIError as e:
        print(f"[AI 오류] {e.code}: {e.message}", flush=True)
        return jsonify({"ok": False, "input": trip, "error": e.message, "code": e.code}), 502

    seconds = round(time.time() - started, 1)
    print(f"[AI 분석 완료] {seconds}초", flush=True)
    return jsonify({"ok": True, "input": trip, "seconds": seconds, **result})


@app.post("/api/plan")
def plan():
    """선택한 전략으로 새 일정표 + 다국어 문의문 + 체크리스트를 만듭니다."""
    data = request.get_json(silent=True) or {}
    trip, errors = validate_trip_input(data.get("input") or {})
    strategy = clean_strategy(data.get("strategy"))
    if errors or not strategy["title"]:
        return jsonify({"ok": False, "error": "입력 정보가 부족해요. 처음부터 다시 시도해 주세요."}), 400

    limited = check_rate_limit()
    if limited:
        return jsonify({"ok": False, "error": limited, "code": "rate_limit"}), 429

    started = time.time()
    try:
        result = run_ai_json(
            prompts.PLAN_SYSTEM,
            prompts.build_plan_prompt(trip, strategy),
            normalize=normalize_plan,
            max_tokens=2500,
        )
    except ai_client.AIError as e:
        print(f"[AI 오류] {e.code}: {e.message}", flush=True)
        return jsonify({"ok": False, "error": e.message, "code": e.code}), 502

    seconds = round(time.time() - started, 1)
    print(f"[AI 계획 완료] {strategy['id']}안 · {seconds}초", flush=True)
    return jsonify({"ok": True, "seconds": seconds, **result})


if __name__ == "__main__":
    import socket
    import sys

    # python app.py --phone  → 같은 와이파이의 휴대폰에서도 접속 가능
    if "--phone" in sys.argv:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
        except OSError:
            ip = "(내 컴퓨터 IP)"
        print(f"\n  휴대폰 브라우저에서 접속: http://{ip}:5000  (같은 와이파이 필요)\n", flush=True)
        app.run(debug=True, host="0.0.0.0", port=5000)
    else:
        app.run(debug=True, port=5000)
