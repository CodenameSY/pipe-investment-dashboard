# 에너지 서비스·해양시추 Telegram 데일리 브리프

HP, PTEN, HAL, SLB, WFRD, RIG, NE, SDRL, VAL 및 비교용 BKR의 새 공시와 공개 업황 지표를 점검합니다. 유료 데이터·생성형 AI API를 사용하지 않는 Python 표준 라이브러리 프로그램입니다. 기존 대시보드와 별도 폴더·워크플로·상태 브랜치를 사용합니다.

## 시작하기

1. Telegram에서 공식 **@BotFather**를 찾아 `/newbot`으로 봇을 생성합니다. 발급된 토큰은 비밀번호처럼 관리하고 저장소·이슈·채팅에 붙이지 마세요. 유출됐다면 BotFather에서 재발급합니다.
2. 생성한 봇의 개인 대화를 열어 `/start`를 보냅니다. 그룹은 봇을 초대한 후 그룹 안에서 봇을 대상으로 명령을 보내세요. 채널은 봇에 게시 권한을 부여해야 합니다.
3. 저장소를 내려받은 폴더에서 `python -m energy_brief.setup_chat`을 실행합니다. 숨김 입력창에 토큰을 넣으면 최근 수신 메시지의 채팅 이름과 `chat_id`만 보여줍니다. 원하는 채팅을 선택하세요. 그룹의 음수 ID는 `-`까지 그대로 사용합니다. 이 도구는 토큰을 저장하지 않습니다. 기존 webhook을 사용하는 봇은 getUpdates를 사용할 수 없으므로, 별도 봇을 만드는 편이 간단합니다. webhook을 임의로 삭제하지 않습니다.
4. [저장소 Actions Secrets 설정](https://github.com/CodenameSY/pipe-investment-dashboard/settings/secrets/actions) → **New repository secret**으로 아래 세 값을 등록합니다.

| Secret 이름 | 값 |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | BotFather가 발급한 토큰 |
| `TELEGRAM_CHAT_ID` | 전송할 개인/그룹 채팅 ID 또는 권한이 있는 채널의 `@username` |
| `SEC_USER_AGENT` | 실제 서비스 이름과 연락 이메일. 예: `EnergyBrief your-email@example.com` — 예시 주소 대신 본인 주소 |

추가 데이터 API 키는 필요하지 않습니다. 키가 필요한 수집기를 추가할 때에도 Secrets에 보관해야 합니다. Secrets 값은 프로그램 로그·상태 파일·메시지에 저장하지 않습니다. 저장소가 공개이므로 상태 브랜치의 공개 뉴스·메시지 본문·Telegram message_id는 공개될 수 있습니다. token/chat_id는 저장하지 않습니다.

5. [Actions](https://github.com/CodenameSY/pipe-investment-dashboard/actions/workflows/energy-brief.yml) → **Energy services daily brief** → **Run workflow**에서 `test`를 선택해 테스트 메시지 수신을 확인합니다.
6. `preview`로 소스 수집을 점검합니다. 미발송·상태 JSON 미변경입니다. 처음 한 번은 빈 상태 브랜치가 생성될 수 있습니다.
7. `run`으로 첫 기준선을 저장합니다. 첫 성공 관측은 과거 뉴스 폭주를 막기 위해 발송하지 않습니다. 이후 매일 **한국시간 08:07** 예정으로 실행되고, 새 대상 사건이나 임계치 변화가 있을 때만 발송합니다. 사용자가 늦게 Secrets를 등록했으면 다시 `run`을 실행하면 됩니다.

GitHub cron은 정시 실행을 보장하지 않으며 혼잡 시 지연·누락될 수 있습니다. 공개 저장소의 장기간 활동 부재로 일정이 비활성화될 수 있으므로 Actions 화면을 확인하세요. [공식 schedule 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule). GitHub Actions의 계정별 무료 실행량·정책을 따르며 별도 유료 서비스는 설치하지 않습니다.

## 무료 수집 범위와 한계

| 항목 | 구현 범위 |
| --- | --- |
| WTI 현물 | FRED `DCOILWTICO` CSV, EIA 원자료. 관측일 기준이며 실시간 가격이 아닙니다. 7일 이상 지연된 값은 최신 신호로 쓰지 않습니다. |
| WTI 12~24개월 선물곡선 | 안정적인 무료 자동 소스 미확보. `UNAVAILABLE`. 최근월 선물을 장기곡선으로 대체하지 않습니다. |
| Baker Hughes US rigs | 공식 자료의 자동 접근 차단으로 공개 AOGR 재게시 자료 사용. 출처·기준일·품질 표시. |
| Permian / Haynesville | OilPriceAPI 공개 페이지의 재게시 수치. 공식 원자료와 대조하지 못한 `secondary_unverified` 참고값이며 지역 숫자로 확정 투자 신호를 만들지 않습니다. |
| Frac spread / US LNG feedgas | 안정적인 무료 일별 시계열 미확보. `UNAVAILABLE`. LNG 수출량을 feedgas로 바꾸어 표시하지 않습니다. |
| 회사 실적·guidance·계약·backlog | SEC submissions의 대상 양식·항목 및 제한된 본문 키워드 필터. 원문 링크·공시일 제공. 실적 수치 비교나 전체 첨부자료를 완전하게 분석하는 기능은 아닙니다. |
| 공식 IR | PTEN·RIG RSS를 설정. 나머지는 SEC 기반. RSS 링크 확인과 실제 실행 환경의 접속 성공은 다릅니다. 403/파싱 실패는 소스 장애로 남깁니다. |
| Offshore utilization/dayrate | 개별 회사 공시에 나타나는 관련 사건은 검토 대상. 업계 전체 시계열·평균 가동률·dayrate는 자동 추정하지 않습니다. |
| FPSO/subsea FID | 별도 프로젝트 전수 수집기 없음. 감시 기업 공시 외 프로젝트는 커버하지 못합니다. |

검증한 IR 주소와 누락 범위는 [SOURCES.md](SOURCES.md)를 참고하세요. 시장 전체를 빠짐없이 감시하는 서비스가 아니며 차단된 소스는 “변화 없음”으로 간주하지 않습니다. 외부 페이지가 바뀌면 수집기가 실패할 수 있습니다.

## 변화 판단과 메시지

메시지는 **핵심 변화 / Land / Services / Offshore / 유가 연결 / 투자판단** 순서입니다. 자동 투자추천 대신 새로운 실적·중요계약·구조조정·정기 재무공시 등 투자 가설을 재검토할 근거를 추립니다. 단순 행사 안내는 제외하려고 키워드 필터를 사용하지만 오탐·누락이 있을 수 있습니다. 중요한 사건의 방향과 금액은 원문 확인이 필요합니다.

WTI는 마지막 알림/초기 기준값 대비 누적 **5% 또는 3달러** 변동을 필터로 사용합니다. 작은 일별 변동마다 기준을 갱신하지 않습니다. 이 임계치는 객관적 투자판정 기준이 아닌 잡음 필터입니다. US rig count는 마지막 기준선 대비 누적 5기 이상 변화를 알립니다. Basin은 참고값만 제공합니다. 소스의 관측일·원문 URL을 함께 표시합니다. 데이터 미확보 항목으로 업황 회복·악화를 단정하지 않습니다.

동일 공시 accession/피드 이벤트 ID는 재전송하지 않습니다. SEC와 IR에 동시에 나온 같은 사건은 표현·주소가 달라 각각 검토 대상으로 잡힐 수 있습니다. 새 자료가 없으면 Telegram 메시지를 보내지 않습니다. 수집 오류는 Actions에서 확인합니다.

## 상태·실패·재실행

`energy-brief-state` 브랜치의 `state.json`에 기준선, 확인한 사건, pending 메시지와 chunk별 상태를 저장합니다. 캐시 만료에 의존하지 않습니다. Actions 실행은 하나씩 진행됩니다. 저장 실패·손상된 상태는 초기화하지 않고 중단합니다. 상태 브랜치를 삭제하면 첫 관측 기준선부터 다시 시작하므로 임의로 지우지 마세요.

발송 전 outbox와 `sending`을 원격 저장하고, 성공 시 메시지 receipt를 다시 저장합니다. 네트워크 타임아웃이나 전송 중 프로세스 종료로 Telegram 수신 여부가 불확실하면 `sending`/`uncertain`을 자동 재전송하지 않습니다. Telegram에는 멱등성 키가 없으므로 정확히 1회 전달을 보장할 수 없습니다.

- 일반 수집 장애·명확한 전송 거절: 원인을 해결한 뒤 `run`을 다시 실행합니다. 이미 확인된 chunk는 건너뜁니다.
- 불확실 전송: Telegram 채팅에서 보고서 ID와 chunk 번호를 확인합니다. 받은 경우 `resolve-sent`, 못 받은 것이 확인된 경우 `resolve-retry`를 선택한 뒤 `run`을 실행합니다. 확인 없이 retry를 고르면 중복될 수 있습니다.
- 여러 chunk 중 실패: 이전 성공 chunk는 유지되고 미전송 부분만 진행됩니다.
- Secrets 누락: 이름만 로그에 표시하고 종료합니다. 값은 출력하지 않습니다.
- 소스 일부 실패: 성공한 소스는 진행하되 실패 상태를 로그에 남깁니다. 실패 소스는 값/기준선을 덮어쓰지 않습니다. 복구 후 첫 관측/누락 기간 처리에는 날짜 필터가 적용됩니다. 7일을 넘긴 수집 중단 기간의 공시는 자동 소급 복구되지 않을 수 있습니다.

워크플로의 각 단계 로그와 요약에서 결과를 확인합니다. **Run workflow**로 재실행 가능하며, Secrets 설정을 바꾸었으면 새 실행을 권합니다. GitHub의 실패 알림을 받으려면 개인 Notifications 설정에서 Actions 알림을 켜세요.

## 개발·검증

Python 3.11 이상, 추가 패키지 설치 불필요.

```text
python -m unittest discover -s energy_brief -p "test_*.py" -v
python -m energy_brief --help
python -m energy_brief --state work/local-state.json --feeds energy_brief/feeds.json --include-bkr --dry-run
```

로컬 실행은 환경에 `SEC_USER_AGENT`가 필요하고 발송은 두 Telegram 변수도 필요합니다. 값이 기록되는 명령줄 대신 로컬 보안 환경 입력을 사용하세요. `ENERGY_STATE_REMOTE=1`은 Actions의 전용 Git 상태 저장용이며 일반 로컬 테스트에는 설정하지 않습니다. 모의 데이터 테스트는 중복 억제·부분 전송 실패·불확실 응답·오래된 관측·상태 보존을 확인합니다. Linux CI는 임시 Git 저장소로 상태 브랜치 복원도 검증합니다.

공식 문서: [Telegram Bot 생성](https://core.telegram.org/bots/tutorial), [sendMessage API](https://core.telegram.org/bots/api#sendmessage), [SEC 개발 안내](https://www.sec.gov/about/developer-resources), [FRED WTI](https://fred.stlouisfed.org/series/DCOILWTICO).
