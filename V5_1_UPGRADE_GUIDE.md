# Pipe Investment Dashboard v5.1 — HRC 자동화

## 변경점
- US HRC: SteelBenchmarker 공개 `history.pdf`의 **USA Hot-Rolled Band** 자동 수집
- 단위: PDF의 괄호 안 **$/net ton (= $/short ton)** 값을 사용해 대시보드의 `$/st`와 일치
- HRC 자동 수집 실패 시 `config.json`의 `US_HRC` 값으로 자동 fallback
- US OCTG: 기존처럼 `config.json` 수동 입력
- HRC/OCTG/Spread/Score 이력은 `history.json`에 계속 누적
- 데이터 상태 영역에 HRC 소스와 발표일 표시

## GitHub에 올릴 파일
기존 저장소에 v5.1 전체 파일을 업로드해 덮어써도 됩니다. 특히 아래 파일은 반드시 교체하세요.

1. `index.html`
2. `update_data.py`
3. `requirements.txt`
4. `.github/workflows/pages.yml`
5. `history.json` (v5 이전이라면 새로 추가)

`config.json`의 `US_HRC`는 삭제하지 마세요. 자동 수집 실패 때 쓰는 fallback 값입니다.

## 확인 방법
Actions 실행 성공 후 사이트의 **데이터 상태 → HRC 소스**가 `SteelBenchmarker · <발표일>`이면 자동화 성공입니다.
`config.json fallback`이면 Actions 로그의 `HRC auto:` 오류를 확인하세요.

## 발표 주기
SteelBenchmarker의 가격은 통상 월 2회 발표되므로 GitHub Actions가 매일 실행되어도 HRC 값은 새 가격 발표 때만 바뀝니다.
