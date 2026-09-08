# PIPE INVESTMENT DASHBOARD v3

## 자동화 구조
update_data.py → data.json → index.html

## 자동 수집
- WTI: CL=F
- Brent: BZ=F
- USD/KRW: KRW=X
- 세아제강 / 넥스틸 / 휴스틸 주가: yfinance
- Baker Hughes Rig Count: best-effort. 페이지 구조 변경 시 기존값 유지.

## 수동 입력
config.json:
- US_HRC
- US_OCTG
- EXPORT_SCORE
- US_POLICY_SCORE

## Windows 로컬 실행
1. `pip install -r requirements.txt`
2. `python update_data.py`
3. `python -m http.server 8000`
4. 브라우저: http://localhost:8000

## GitHub 자동 업데이트
저장소에 전체 파일 업로드 후 GitHub Pages 활성화.
`.github/workflows/update.yml`가 평일 KST 07:10, 토요일 KST 22:30에 자동 실행.

## 점수 가중치
OCTG/Spread 35%, Rig Count 20%, Oil 10%, HRC 10%, Export 10%, US Policy 10%, FX 5%.
