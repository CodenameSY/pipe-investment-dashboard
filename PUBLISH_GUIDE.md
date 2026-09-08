# PIPE INVESTMENT DASHBOARD v4 WEB

이 버전은 로컬 서버 없이 GitHub Pages 주소로 접속하는 배포형입니다.

## 최초 1회 설정

1. GitHub에서 새 저장소를 만듭니다.
   - 추천 저장소 이름: `pipe-investment-dashboard`
2. 이 폴더의 모든 파일/폴더를 저장소 루트에 업로드합니다.
3. 저장소의 `Settings` → `Pages`로 이동합니다.
4. `Build and deployment` → `Source`를 `GitHub Actions`로 선택합니다.
5. `Actions` 탭에서 `Update data and deploy dashboard` 워크플로가 완료될 때까지 확인합니다.

## 접속 주소

일반적으로 다음 형태입니다.

`https://사용자이름.github.io/pipe-investment-dashboard/`

저장소 이름을 다르게 만들었다면 마지막 경로만 저장소 이름으로 바뀝니다.

## 자동 업데이트

- 평일 오전 7:10 KST: 일간 데이터 갱신
- 토요일 오후 10:30 KST: 주간 데이터 갱신
- 수동 갱신: Actions → workflow → Run workflow

## 현재 자동 수집

- WTI
- Brent
- USD/KRW
- 세아제강 주가
- 넥스틸 주가
- 휴스틸 주가
- Baker Hughes Rig Count: best-effort

## 현재 수동 입력

`config.json`
- US_HRC
- US_OCTG
- EXPORT_SCORE
- US_POLICY_SCORE

수동 입력값을 바꾼 뒤 GitHub에 저장하면 자동으로 다시 배포됩니다.

## 중요

GitHub Pages 주소로 접속하면 `python -m http.server 8000`은 필요 없습니다.
