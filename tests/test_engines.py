"""로컬 시험 — 네트워크·토큰 없이 모의 데이터로 답글 엔진·반응 수집 엔진을 검사한다.
사용: python tests/test_engines.py   (저장소 루트에서, 또는 어디서든)
"""
import os, sys, json, csv, shutil, tempfile, subprocess, importlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FIX = os.path.join(HERE, 'fixtures')
sys.path.insert(0, REPO)
import reply_rules as R

fails = []
def ok(cond, msg):
    if not cond: fails.append(msg); print('  ✗', msg)


# 1) 템플릿 뱅크 ─────────────────────────────────────────────
bank = R.load_bank()
tpls = [t for v in bank.values() for t in v]
print(f'[뱅크] 템플릿 {len(tpls)}개, 분류 {len(bank)}개')
ok(len(tpls) >= 40, f'템플릿 40개 이상이어야 함 ({len(tpls)})')
ok(len({t["id"] for t in tpls}) == len(tpls), '템플릿 id 중복')
ok(len({t["text"] for t in tpls}) == len(tpls), '템플릿 문장 중복')
for t in tpls:
    txt = t['text'].replace('{pick}', '1')
    bad = R.lint_reply(txt)
    ok(not bad, f'{t["id"]} 답글 검사 불합격: {bad}')
# 로컬이면 공장 검사기(엔진/lint.py)로도 한 번 더
eng = os.path.join(os.path.dirname(REPO), '엔진')
if os.path.exists(os.path.join(eng, 'lint.py')):
    sys.path.insert(0, eng)
    lint = importlib.import_module('lint')
    for t in tpls:
        why = [w for w in lint.check({'channel': 'threads', 'text': t['text'].replace('{pick}', '1'), 'media': []}, {}, []) if '줄' not in w]
        ok(not why, f'{t["id"]} 엔진 lint 불합격: {why}')
    print('[뱅크] 엔진/lint.py 교차검사 완료')

# 2) 분류기 ─────────────────────────────────────────────────
BAL = '밸런스 게임 하나만 하자\n① 평생 딸기맛만\n② 평생 키위맛만'
CASES = [  # (댓글, 글, 유형, 기대등급, 기대분류 or None)
    ('와 색감 미쳤다 너무 예쁘다', '', '공감', 'green', '칭찬'),
    ('존맛탱 ㅠㅠ', '', '공감', 'green', '칭찬'),
    ('ㅋㅋㅋㅋ 이거 나잖아', '', '공감', 'green', '웃음'),
    ('무슨 맛이 제일 맛있어?', '', '브랜딩', 'green', '맛질문'),
    ('이거 맛있어?', '', '브랜딩', 'green', '맛질문'),
    ('나도 오늘 너무 힘들었어', '', '공감', 'green', '공감'),
    ('🍓🍓', '', '공감', 'green', '이모지'),
    ('1번! 딸기는 못 참지', BAL, '참여', 'green', '밸런스'),
    ('②', BAL, '참여', 'green', '밸런스'),
    ('퇴근하고 소파에서', '', '공감', 'green', '참여답'),
    ('주문했는데 아직 안 왔어요', '', '공감', 'red', '배송'),
    ('환불 가능한가요', '', '공감', 'red', '환불·교환'),
    ('젤리에서 머리카락 나왔어요', '', '공감', 'red', '이물질'),
    ('포장 뜯었더니 곰팡이가', '', '공감', 'red', '클레임'),
    ('알러지 있는데 먹어도 될까요', '', '공감', 'red', '알레르기·안전'),
    ('목에 걸릴까봐 걱정돼요', '', '공감', 'red', '알레르기·안전'),
    ('다이어트에 좋아요?', '', '공감', 'red', '건강·효능'),
    ('이거 먹으면 살 빠져요?', '', '공감', 'red', '건강·효능'),
    ('칼로리 얼마예요', '', '공감', 'red', '건강·효능'),
    ('임산부도 괜찮나요', '', '공감', 'red', '건강·효능'),
    ('좀 비싸다', '', '공감', 'red', '가격·흥정'),
    ('3개 사면 깎아줘요?', '', '공감', 'red', '가격·흥정'),
    ('협찬 문의 드려요', '', '공감', 'red', '협업·광고·스팸'),
    ('부업 관심 있으면 dm', '', '공감', 'red', '협업·광고·스팸'),
    ('맞팔해요~', '', '공감', 'red', '협업·광고·스팸'),
    ('https://bit.ly/abc 여기 보세요', '', '공감', 'red', '협업·광고·스팸'),
    ('ㅅㅂ 이게 뭐임', '', '공감', 'red', '욕설·악플'),
    ('맛없어요', '', '공감', 'red', '클레임'),
    ('우리 아이가 너무 좋아해요', '', '공감', 'yellow', None),
    ('애들 간식으로 딱이네', '', '공감', 'yellow', None),
    ('어디서 사요?', '', '공감', 'yellow', '구매·문의'),
    ('존나 맛있음', '', '공감', 'yellow', None),
    ('둘 다 싫은데 ㅋㅋ', BAL, '참여', 'yellow', None),
    ('흠 그렇구나', '', '브랜딩', 'yellow', '미분류'),
    ('이거 몇 개 들었어?', '', '브랜딩', 'yellow', '질문'),
    ('아이고 귀여워라', '', '공감', 'green', '칭찬'),
    ('얼마나 맛있길래 ㅋㅋ', '', '공감', 'green', '웃음'),
    ('가 ' * 70, '', '공감', 'yellow', '긴 댓글'),
]
bad = 0
for text, post, typ, want, wcat in CASES:
    cls, cat, why, pick = R.classify(text, post, typ)
    if cls != want or (wcat and cat != wcat):
        bad += 1; ok(False, f'분류 「{text[:20]}」 기대 {want}/{wcat} → 실제 {cls}/{cat}')
print(f'[분류] {len(CASES) - bad}/{len(CASES)} 통과')
# 밸런스 번호
ok(R.classify('②', BAL, '참여')[3] == '2', '밸런스 ② → 2')

# 3) 답글 엔진 (모의 API, DRY_RUN) ──────────────────────────────
tmp = tempfile.mkdtemp(prefix='khs_reply_')
env = dict(os.environ, THREADS_MOCK=os.path.join(FIX, 'mock_api.json'), DRY_RUN='1', OUT_DIR=tmp,
           DONE_DIR=os.path.join(FIX, 'done'), NOW_KST='2026-10-03T23:30:00+09:00', PYTHONIOENCODING='utf-8')
env.pop('THREADS_TOKEN', None)
def run(script):
    r = subprocess.run([sys.executable, os.path.join(REPO, script)], env=env, capture_output=True, text=True, encoding='utf-8')
    print(r.stdout.rstrip()); print(r.stderr.rstrip()) if r.stderr.strip() else None
    return r
print('\n[답글 엔진 1회차]')
r1 = run('reply_bot.py')
ok(r1.returncode == 0, '답글 엔진 종료코드 0')
st = json.load(open(os.path.join(tmp, 'state', 'replies_state.json'), encoding='utf-8'))
acts = {k: v['action'] for k, v in st['handled'].items()}
replied = sorted(k for k, v in acts.items() if v == 'replied')
esc = sorted(k for k, v in acts.items() if v == 'escalated')
print('  답글:', replied, '| 보고:', esc)
ok(replied == ['C01', 'C07', 'C12', 'C13', 'C21', 'C22', 'C23'], f'답글 대상 {replied}')
ok(esc == ['C03', 'C04', 'C05', 'C09', 'C11', 'C14', 'C15', 'C24', 'C25'], f'보고 대상 {esc}')
ok('C02' not in acts, '우리 계정 댓글(C02)은 무시')
ok(acts.get('C06') == 'skipped' and acts.get('C26') == 'skipped', '같은 사용자 하루 1회(C06·C26 skip)')
ok(acts.get('C10') == 'skipped', '72시간 지난 댓글(C10) skip')
ok(acts.get('C08') == 'hidden', '숨김 댓글(C08)')
ok(len(set(st['post_tpl']['P1002'])) == len(st['post_tpl']['P1002']), '같은 게시물 템플릿 반복 없음')
md = open(os.path.join(tmp, 'reports', 'replies_escalation.md'), encoding='utf-8').read()
ok(md.count('- [ ] 🔴') == 7 and md.count('- [ ] 🟡') == 2, '보고 목록 🔴7 🟡2')
ok(os.path.exists(os.path.join(tmp, 'reports', 'replies_log.csv')), '답글 로그 CSV')
ok(not os.path.exists(os.path.join(REPO, '_dryrun')), '저장소 본체에 DRY_RUN 흔적 없음')
print('\n[답글 엔진 2회차 — 중복 방지]')
r2 = run('reply_bot.py')
ok('답글 0 · 보고 0' in r2.stdout, '2회차는 새로 처리할 것 없음')
ok(open(os.path.join(tmp, 'reports', 'replies_escalation.md'), encoding='utf-8').read().count('- [ ]') == 9, '보고 목록 중복 적재 없음')

# PAUSE
open(os.path.join(REPO, 'PAUSE'), 'w').close()
try:
    r3 = run('reply_bot.py'); ok('PAUSE' in r3.stdout, 'PAUSE 파일이면 중지')
finally:
    os.remove(os.path.join(REPO, 'PAUSE'))

# 4) 반응 수집 엔진 ──────────────────────────────────────────
print('\n[반응 수집]')
r4 = run('insights.py')
ok(r4.returncode == 0, '반응 수집 종료코드 0')
rows = list(csv.DictReader(open(os.path.join(tmp, 'reports', 'insights.csv'), encoding='utf-8-sig')))
ok(len(rows) == 4, f'수집 4건 (리포스트·30일 초과 제외) → {len(rows)}')
by = {r['post_id']: r for r in rows}
ok(by['P1002']['views'] == '2210' and by['P1002']['engagement'] == '73', 'P1002 수치(values 형식)')
ok(by['P1001']['views'] == '640' and by['P1001']['type'] == '브랜딩', 'P1001 수치(total_value 형식)·유형')
ok(by['PMAN']['type'] == '수동' and by['PMAN']['shares'] == '0', 'done 에 없는 글 = 수동, 없는 지표 0')
ok(by['P0930']['media'] == '영상' and by['P1002']['media'] == '텍스트', '미디어 구분')
wk = os.path.join(tmp, 'reports', 'insights_weekly_2026-10-03.md')
ok(os.path.exists(wk), '주간 요약 md')
print(open(wk, encoding='utf-8').read())
r5 = run('insights.py')
ok(len(list(csv.DictReader(open(os.path.join(tmp, 'reports', 'insights.csv'), encoding='utf-8-sig')))) == 8, 'CSV 누적(스냅샷 추가)')

shutil.rmtree(tmp, ignore_errors=True)
print('\n결과:', '모두 통과 ✅' if not fails else f'실패 {len(fails)}건 ❌')
sys.exit(1 if fails else 0)
