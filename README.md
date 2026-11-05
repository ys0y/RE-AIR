# RE:AIR ✈️

> 항공편이 멈춰도, 당신의 여행은 멈추지 않도록.

항공편 결항·지연·환승 실패가 생겼을 때, 생성형 AI가 여행 전체의 연쇄 피해를 분석하고
**개인 맞춤 복구 전략 3가지 → 새 일정표 → 한/영/일 문의 메시지 → 행동 체크리스트**를 만들어 주는 서비스입니다.

한양여자대학교 NEXT AI 해커톤 출품작

## 주요 기능
- AI 상황 분석 (현재 문제, 영향, 가장 시급한 일, 먼저 확인할 사항)
- 조건별 복구 전략 3가지 (비용 · 속도 · 일정 유지) + AI 추천
- 선택한 전략에 맞춘 일정 재설계 (기존 ↔ 변경 비교)
- 한국어 · English · 日本語 문의 메시지 (복사 / 크게 보기)
- 우선순위 행동 체크리스트
- AI 오류 시 시연용 데이터로 전환, 앱 설치(PWA) 지원

## 기술 스택
Python · Flask · HTML/CSS/JavaScript · 생성형 AI API(학교 제공 게이트웨이, Claude)

## 내 컴퓨터에서 실행
```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # .env 파일에 API 키 입력
venv\Scripts\python app.py  # http://127.0.0.1:5000
```

> AI가 생성한 안내는 참고용이며, 실제 항공편·숙소 정보는 항공사와 숙소에 직접 확인해야 합니다.
