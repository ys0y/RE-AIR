"""
RE:AIR - 생성형 AI 연결 모듈

학교에서 제공한 AI 게이트웨이(OpenAI 호환 방식)에 요청을 보내고 답을 받아옵니다.
접속 정보는 모두 .env 파일에서 읽습니다. (코드에 API 키를 직접 쓰지 않음)
    AI_API_KEY   : API 키
    AI_BASE_URL  : 접속 주소
    AI_MODEL     : 사용할 모델 이름
"""
import json
import os
import re
import time

import requests

DEFAULT_BASE_URL = "https://factchat-cloud.mindlogic.ai/v1/gateway"
DEFAULT_MODEL = "claude-sonnet-5-5"


class AIError(Exception):
    """AI 호출 중 생긴 문제. 사용자에게 보여 줄 한국어 메시지와 오류 종류(code)를 담습니다."""

    def __init__(self, message, code="ai_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def get_config():
    """환경변수에서 접속 정보를 읽습니다."""
    return {
        "api_key": os.getenv("AI_API_KEY", "").strip(),
        "base_url": os.getenv("AI_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/"),
        "model": os.getenv("AI_MODEL", DEFAULT_MODEL).strip(),
    }


def _build_request(config, messages, max_tokens, temperature):
    """
    모델 종류에 맞는 요청 주소와 내용을 만듭니다.
    - Claude 모델: Claude 전용 주소를 쓰고 '생각(thinking)' 기능을 끕니다.
      (켜져 있으면 보이지 않는 생각에 토큰을 다 써서 답이 잘리고 느려집니다)
    - 그 밖의 모델: OpenAI 호환 주소를 씁니다.
    """
    if config["model"].startswith("claude"):
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        return f"{config['base_url']}/claude/v1/messages/", {
            "model": config["model"],
            "system": system,
            "messages": [m for m in messages if m["role"] != "system"],
            "max_tokens": max_tokens,
            # temperature는 최신 Claude 모델에서 지원하지 않아 보내지 않습니다.
            "thinking": {"type": "between_tools"},  # 이 게이트웨이에서 '생각 끄기' 설정
        }
    return f"{config['base_url']}/chat/completions/", {
        "model": config["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }


def _read_answer(data):
    """응답 데이터에서 답변 글자와 '잘렸는지' 여부를 꺼냅니다."""
    if "choices" in data:  # OpenAI 호환 형식
        choice = data["choices"][0]
        content = choice["message"]["content"]
        if isinstance(content, list):  # 일부 모델은 여러 조각으로 보냄
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return content or "", choice.get("finish_reason") == "length"
    # Claude 형식
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return text, data.get("stop_reason") == "max_tokens"


def chat(messages, max_tokens=3000, temperature=0.7, timeout=120):
    """
    AI에게 대화 메시지를 보내고, 답변 글자(text)를 돌려줍니다.
    messages 예: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
    """
    config = get_config()
    if not config["api_key"]:
        raise AIError("API 키가 설정되지 않았어요. .env 파일을 확인해 주세요.", "no_key")

    url, body = _build_request(config, messages, max_tokens, temperature)
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json=body,
            timeout=timeout,
        )
    except requests.Timeout:
        raise AIError("AI 응답이 너무 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.", "timeout")
    except requests.ConnectionError:
        raise AIError("AI 서버에 연결할 수 없어요. 인터넷 연결을 확인해 주세요.", "network")

    status = response.status_code
    if status in (401, 403):
        raise AIError("API 키가 올바르지 않거나 사용 권한이 없어요.", "auth")
    if status == 429:
        raise AIError("AI 사용량이 많아 잠시 제한됐어요. 1분 뒤 다시 시도해 주세요.", "rate_limit")
    if status >= 500:
        raise AIError("AI 서버에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요.", "server")
    if not response.ok:
        print(f"[AI] 요청 실패 {status}: {response.text[:300]}", flush=True)
        raise AIError(f"AI 요청이 실패했어요. (오류 코드 {status})", "http_error")

    try:
        data = response.json()
        content, truncated = _read_answer(data)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise AIError("AI 응답 형식이 예상과 달라요.", "bad_response")

    # 토큰 사용량을 터미널에 표시 (Claude 형식 / OpenAI 형식 모두 지원)
    usage = data.get("usage") or {}
    used_in = usage.get("input_tokens", usage.get("prompt_tokens"))
    used_out = usage.get("output_tokens", usage.get("completion_tokens"))
    print(f"[AI] 토큰 사용 - 입력 {used_in} / 출력 {used_out} (한도 {max_tokens})", flush=True)

    if truncated:
        print("[AI] 답변이 토큰 한도에 걸려 잘렸어요. (프롬프트의 글자 수 제한을 더 줄여 보세요)", flush=True)
    if not content:
        raise AIError("AI가 빈 답변을 보냈어요. 다시 시도해 주세요.", "empty")
    return content


def extract_json(text):
    """AI 답변에서 JSON 부분만 꺼내 파이썬 데이터(dict)로 바꿉니다."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise AIError("AI 답변에서 결과 데이터를 찾지 못했어요.", "bad_json")
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        raise AIError("AI 답변을 해석하지 못했어요. 다시 시도해 주세요.", "bad_json")


def chat_json(system_prompt, user_prompt, **kwargs):
    """시스템 지시문 + 사용자 내용을 보내고, 결과를 JSON(dict)으로 받습니다."""
    text = chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        **kwargs,
    )
    return extract_json(text)


def test_connection():
    """AI 연결 테스트: 짧은 질문을 보내고 걸린 시간과 답변을 돌려줍니다."""
    started = time.time()
    reply = chat_json(
        "너는 여행 복구 도우미야. 반드시 JSON만 출력해.",
        '항공편이 결항된 여행자에게 건넬 응원 한 문장을 만들어 줘. 형식: {"message": "..."}',
        max_tokens=200,
    )
    return {
        "model": get_config()["model"],
        "seconds": round(time.time() - started, 1),
        "reply": reply,
    }
