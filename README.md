# khs-factory
경한송젤리 스레드 부계정(@khsjelly_funny) 자동 발행 저장소.
- queue/ 예약 대기 · done/ 발행 완료 기록 · media/ 첨부 영상(Pages로 공개)
- 매일 21:30 KST GitHub Actions가 publish.py 실행. 루트에 PAUSE 파일이 있으면 정지.
- 비밀값(토큰)은 이 저장소에 없음 — GitHub Secrets에만.

## 엔진 3개

| 워크플로 | 언제 (KST) | 스크립트 | 결과 |
|---|---|---|---|
| `publish.yml` 스레드 자동 발행 | 매일 21:30 | `publish.py` | `queue/` → `done/` |
| `replies.yml` 댓글 자동답글 | 매일 12:00 · 18:00 · 23:30 (+수동) | `reply_bot.py` (`reply_rules.py`, `reply_bank.json`) | `state/replies_state.json`, `reports/replies_escalation.md`, `reports/replies_log.csv` |
| `insights.yml` 반응 수집 | 매주 일요일 22:00 (+수동) | `insights.py` | `reports/insights.csv`(누적), `reports/followers.csv`, `reports/insights_weekly_<날짜>.md` |

GitHub 예약 실행은 몇 분~수십 분 늦을 수 있다. 공용 도우미는 `threads_api.py`(publish.py 는 따로 동작).

### 공통 스위치
- **PAUSE** 파일(저장소 루트) → 세 엔진 모두 즉시 정지.
- **DRY_RUN** 파일(루트) 또는 환경변수 `DRY_RUN=1` → 답글을 올리지 않고, 결과는 `_dryrun/`(커밋 안 됨)에만 쓴다. Actions 화면 「Run workflow」에서 `dry_run` 체크로도 가능(댓글 엔진 수동 실행 기본값 = DRY_RUN).
- 로컬 시험: `python tests/test_engines.py` — 네트워크·토큰 없이 모의 데이터(`tests/fixtures/`)로 분류 38건·중복방지·PAUSE·반응 집계를 검사. 댓글 워크플로는 답글 전에 이 시험을 먼저 돌리고, 실패하면 답글을 안 단다.

## 댓글 자동답글 규칙 (설계서 §2, 대표 승인 09-26)
- 🟢 칭찬·웃음·가벼운 맛 질문·공감·이모지·밸런스게임 번호·참여글의 짧은 답 → `reply_bank.json` 템플릿(58개, 반말 사장 일기체)으로 답글. 답글마다 금지어·효능·가격·어린이·존댓말 검사.
- 🔴 클레임·환불·배송·이물질·알레르기/안전·건강/효능 질문·가격/흥정·협업/광고·스팸·욕설 → **답글 금지**, `reports/replies_escalation.md` 에 적재.
- 🟡 아이·아기 언급(어린이 방침), 구매/연락 문의, 긴 댓글, 규칙에 없는 질문, 부정 뉘앙스, 미분류 → 보류, 같은 파일에 적재.
- 제한: 우리 계정 댓글 무시 · 같은 사용자 하루 1회 · 게시물당 누적 15개 · 실행당 8개 · 답글 간격 20~45초 · 게시 후 72시간 지난 댓글엔 답글 안 함 · 같은 게시물에서 같은 템플릿 반복 금지, 최근 20개 답글과 겹치지 않게.
- 처리한 댓글 id는 `state/replies_state.json` 에 남아 두 번 처리하지 않는다. 답글 실패분만 다음 실행에 재시도.
- 규칙·템플릿을 고치면 `python tests/test_engines.py` 가 통과해야 한다.

## 필요한 Threads 권한(스코프)
| 엔진 | 권한 |
|---|---|
| 발행 | `threads_basic`, `threads_content_publish` |
| 댓글 읽기·답글 | `threads_read_replies`(댓글 읽기), `threads_manage_replies`(답글 달기) |
| 반응 수집 | **`threads_manage_insights` 필요** — 게시물 `/{id}/insights`(views·likes·replies·reposts·quotes·shares)와 계정 `/{user-id}/threads_insights`(followers_count) 둘 다 이 권한이 있어야 읽힌다 |

토큰에 권한이 빠져 있으면 해당 워크플로가 권한 오류로 실패한다(발행은 영향 없음). 이 경우 Meta 앱 'KHS Publisher'에서 권한을 추가하고 **토큰을 새로 발급**해야 한다(갱신만으로는 권한이 늘지 않음).

## 토큰 갱신 방식 제안 (구현 안 함)
- 장기 토큰은 60일 만료(09-26 발급 → 11월 하순). **발급 후 24시간 이상 지나고 만료 전**이면 갱신 가능:
  `GET https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=<현재 장기 토큰>` → 새 60일 토큰.
- 제안 순서(11-15 전후, 금요일): ① AI가 로컬 스크립트로 `엔진/비밀값.env` 의 토큰을 갱신(값은 화면에 출력 안 함) → ② **대표가 직접** GitHub 저장소 Settings → Secrets and variables → Actions → `THREADS_TOKEN` 에 새 값 붙여넣기 → ③ Actions에서 「스레드 댓글 자동답글」을 DRY_RUN으로 수동 실행해 연결 확인.
- 완전 자동화(Actions가 스스로 갱신·Secrets 교체)는 Secrets 쓰기 권한이 있는 GitHub 토큰을 따로 만들어야 해서 보안 판단이 필요 → 대표 결정 후 진행.
