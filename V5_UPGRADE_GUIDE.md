# Pipe Investment Dashboard v5 업그레이드

## v5 변경점
- Oil Rigs / US HRC / US OCTG / OCTG-HRC Spread / Pipe Cycle Score의 History 선 그래프 추가
- `history.json`에 날짜별 스냅샷 영구 누적
- 카드 변화율 기간을 명시: WTI/Brent/USD-KRW는 1W %, Rig는 WoW rigs, HRC/OCTG/Spread는 1M %
- 기존 Score History의 예시값 대신 v5부터 실제 실행값을 날짜별로 누적
- GitHub Actions가 `data.json`과 `history.json`을 함께 커밋/배포

## GitHub에 올릴 파일
기존 저장소에서 아래 파일을 v5 파일로 교체/추가하세요.
1. `index.html` 교체
2. `update_data.py` 교체
3. `.github/workflows/pages.yml` 교체
4. `history.json` 새로 추가

`config.json`, `requirements.txt`는 기존 것을 그대로 사용해도 됩니다.

## 중요
HRC/OCTG는 현재 `config.json` 수동 입력값입니다. 따라서 config 값이 바뀌지 않으면 History도 수평선으로 보입니다. 라이선스/공식 시계열 소스를 연결하면 같은 구조에서 자동 History로 전환할 수 있습니다.
