"""댓글 분류기 + 답글 고르기 (LLM 없이 규칙만).

분류 순서 (먼저 걸리는 게 이김)
  1) 🔴 RED   — 클레임·환불·배송·이물질·알레르기/안전·건강/효능·가격/흥정·협업/광고·스팸·욕설 → 답글 금지, 대표 보고
  2) 🟡 YELLOW — 아이·아기 언급, 구매/연락 문의, 너무 긴 댓글, '?'가 붙은 일반 질문, 규칙에 안 걸리는 것 → 보류, 목록 적재
  3) 🟢 GREEN — 밸런스게임 답 / 웃음 / 칭찬 / 맛 질문 / 공감 / 이모지만 / (참여·공감 글의) 짧은 답 → 자동 답글
규칙 정본: 00_본부/톤_금지표현.md, CLAUDE.md §3-1(어린이 노출 최소화), 콘텐츠공장/00_무한공장_설계서.md §2.
"""
import re, os, json, hashlib

ROOT = os.path.dirname(os.path.abspath(__file__))

# ── 1) 🔴 대표에게 넘길 것 ─────────────────────────────────────────
RED = [
    ('환불·교환', r'환불|반품|교환|취소해|돈\s*돌려'),
    ('배송', r'배송|택배|송장|출고|언제\s*(와|오|도착)|안\s*와|안와|도착\s*안|파손|주문했는데|주문\s*했는데'),
    ('이물질', r'이물|머리카락|벌레|플라스틱|비닐|쇳조각|뭐가\s*들어'),
    ('클레임', r'불량|상했|상한\s|곰팡|쉰내|이상한\s*(맛|냄새)|냄새\s*나|녹았|터졌|녹아서|딱딱해|실망|최악|맛없|노맛|별로|후회|사기꾼|사기\s*(아니|같|치)|거짓|뒷광고|과대|신고'),
    ('알레르기·안전', r'알레르기|알러지|두드러기|가려워|가렵|성분|원재료|첨가물|목에\s*걸|걸렸|질식|기도|삼키|씹지|위험|안전'),
    ('건강·효능', r'다이어트|살\s*(빠|찌|쪄|안\s*쪄|안\s*찌)|체중|칼로리|kcal|혈당|당뇨|당\s*(함량|수치|성분)|설탕|변비|소화|배탈|설사|복통|장\s*건강|효과|효능|건강|약\s*먹|임산부|임신|수유|몸에\s*(좋|나쁘|괜찮)|먹어도\s*(돼|되|괜찮)|먹여도'),
    ('가격·흥정', r'할인|깎아|싸게|비싸|가격|얼마(?!나)|원이야|원이에|쿠폰|적립|공구|도매|대량|최저가|무료|나눔|이벤트|증정|협상'),
    ('협업·광고·스팸', r'협업|협찬|제휴|광고|홍보|입점|납품|제안|디엠|\bdm\b|쪽지|오픈채팅|open\.kakao|카톡\s*(주|줘|아이디)|텔레그램|https?://|www\.|\.com|\.kr|맞팔|선팔|팔로우\s*(해|하면|부탁)|부업|수익|재테크|투자|코인|대출'),
    ('욕설·악플', r'씨발|시발|ㅅㅂ|ㅆㅂ|병신|ㅂㅅ|좆|개새|꺼져|닥쳐|미친놈|미친년|ㅗ|죽어|쓰레기'),
]
# ── 2) 🟡 보류 ─────────────────────────────────────────────────────
YELLOW = [
    ('아이 언급(어린이 방침)', r'아이(?!스|고|디|폰|패드|템|돌|유|쇼핑)|애기|아기|애들|우리\s*애|어린이|유아|아들|딸래미|딸내미|초딩|유치원|어린이집|돌\s*지난|\d+\s*개월'),
    ('구매·문의', r'어디서\s*(사|팔|구매|파)|구매|주문|판매|파나요|팔아|사고\s*싶|살\s*수|매장|위치|주소|링크|스토어|사이트|문의|연락'),
    ('거친 말(문맥 확인)', r'존나|졸라|ㅈㄴ|개맛(?!있)'),
]
# ── 3) 🟢 자동 답글 ───────────────────────────────────────────────
GREEN = [
    ('웃음', r'ㅋㅋ|ㅎㅎㅎ|웃기|웃겨|웃프|빵\s*터|[😂🤣😆😹]'),
    ('맛질문', r'무슨\s*맛|어떤\s*맛|맛\s*(뭐|몇|종류)|뭐가\s*(제일\s*)?맛|최애\s*맛|추천\s*맛|맛\s*추천|식감\s*(어때|어떻)|맛\s*어때|무슨\s*맛이'),
    ('칭찬', r'맛있|맛나|존맛|꿀맛|JMT|jmt|최고|좋아|좋다|예쁘|이쁘|예뻐|이뻐|귀엽|귀여|탱글|쫄깃|대박|짱|굿|good|사랑|반했|미쳤|먹고\s*싶|먹고싶|침\s*고|군침|영롱|색\s*감|비주얼|멋지|멋있|응원|화이팅|파이팅'),
    ('공감', r'나도|저도|맞아|맞네|인정|ㅇㅈ|공감|그러게|완전|그치|고생|힘내|수고|위로|힐링|ㅠㅠ|ㅜㅜ'),
]
BALANCE = r'^\s*(?:([①②③1-3])\s*(?:번|번이|번파|!|\.|\s|$)|([①②③]))'
EMOJI_ONLY = re.compile(r'^[\s\W_]*$', re.UNICODE)  # 글자·숫자 없이 기호/이모지뿐
EMOJI_CHAR = re.compile('[\U0001F300-\U0001FAFF☀-➿]')
Q_WORDS = r'뭐|어디|언제|어떻게|왜|얼마|몇|무슨|어떤|누구'
NEGATIVE_HINT = r'싫|아쉽|그닥|글쎄|왜\s*이래|이상해|불편|짜증'


def _hit(rules, t):
    for label, pat in rules:
        if re.search(pat, t, re.I): return label
    return None


def classify(text, post_text='', post_type=''):
    """→ (등급 'green'|'yellow'|'red', 세부분류, 사유, 밸런스 번호 또는 None)"""
    t = (text or '').strip()
    if not t:
        return 'yellow', '빈 댓글', '내용 없음(사진/스티커만?)', None
    r = _hit(RED, t)
    if r: return 'red', r, f'키워드 규칙: {r}', None
    y = _hit(YELLOW, t)
    if y: return 'yellow', y, f'보류 규칙: {y}', None
    if len(t) > 120:
        return 'yellow', '긴 댓글', f'{len(t)}자 — 사람이 읽고 판단', None
    if re.search(NEGATIVE_HINT, t):
        return 'yellow', '부정 뉘앙스', '불만일 수 있음', None
    if EMOJI_ONLY.match(t) and EMOJI_CHAR.search(t):
        return 'green', '이모지', '', None
    if re.search(r'밸런스|[①②]|몇\s*번|번호', post_text):
        m = re.match(BALANCE, t)
        if m:
            pick = (m.group(1) or m.group(2))
            pick = {'①': '1', '②': '2', '③': '3'}.get(pick, pick)
            return 'green', '밸런스', '', pick
    g = _hit(GREEN, t)
    if g == '맛질문': return 'green', '맛질문', '', None
    if '?' in t or '？' in t:
        if g == '칭찬' and '맛' in t and len(t) <= 40:
            return 'green', '맛질문', '', None
        if g in ('웃음', '칭찬', '공감') and len(t) <= 40 and not re.search(Q_WORDS, t):
            return 'green', g, '', None
        return 'yellow', '질문', '규칙에 없는 질문 — 사람이 답하는 게 안전', None
    if g: return 'green', g, '', None
    if post_type in ('참여', '공감') and len(t) <= 60:
        return 'green', '참여답', '', None
    return 'yellow', '미분류', '규칙에 안 걸림', None


# ── 답글 고르기 ────────────────────────────────────────────────────
def load_bank():
    b = json.load(open(os.path.join(ROOT, 'reply_bank.json'), encoding='utf-8'))
    return {k: v for k, v in b.items() if not k.startswith('_')}


def choose(bank, category, seed, recent_ids=(), post_ids=(), pick=None):
    """같은 게시물에서 이미 쓴 템플릿, 최근 N회 쓴 템플릿은 피한다. seed(댓글 id)로 결정적 선택."""
    pool = bank.get(category) or bank['참여답']
    fresh = [x for x in pool if x['id'] not in post_ids and x['id'] not in recent_ids]
    if not fresh: fresh = [x for x in pool if x['id'] not in post_ids] or pool
    h = int(hashlib.sha1(str(seed).encode()).hexdigest(), 16)
    tpl = fresh[h % len(fresh)]
    return tpl['id'], tpl['text'].replace('{pick}', pick or '1')


# ── 답글 자체 검사 (엔진/lint.py 의 금지어와 같은 목록 + 답글 전용) ─────────
BANNED = ['다이어트 효과', '치료', '1위', '최초', '살 안 찌는', '살안찌는', '사르르',
          '살 빠', '살빠', '체중 감량', '체중감량', '변비', '혈당', '당뇨', '면역', '디톡스', '해독',
          '건강해지', '건강에 좋', '몸에 좋', '약효', '효능', '부작용 없',
          '다이어트', '칼로리', '아이', '애들', '어린이', '키즈', '유아',
          '할인', '원', '구매', '링크', '하트 놓고', '스하리', '반하리', '맞팔', '팔로우']


def lint_reply(text):
    why = [f'금지: "{w}"' for w in BANNED if w in text and not (w == '원' and not re.search(r'\d\s*원', text))]
    emo = len(re.findall(r'[\U0001F300-\U0001FAFF☀-➿]', text))
    if emo > 2: why.append(f'이모지 {emo}개')
    if len(text) > 80: why.append(f'{len(text)}자 — 답글은 짧게')
    if re.search(r'습니다|하세요|드려요|드립니다', text): why.append('존댓말/공지체')
    return why
