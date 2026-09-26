"""스레드 API 공용 도우미 (답글 엔진·반응 수집 엔진이 같이 씀. publish.py 는 건드리지 않음).

- 토큰: 환경변수 THREADS_TOKEN (GitHub Secrets). 절대 출력하지 않는다.
- 모의 모드: 환경변수 THREADS_MOCK=<fixture.json> 이면 네트워크 없이 파일 속 응답을 돌려준다(로컬 시험용).
  fixture 형식: {"GET me": {...}, "GET me/threads": {...}, "GET <id>/conversation": {...}, "GET <id>/insights": {...}}
- DRY_RUN: 환경변수 DRY_RUN=1 또는 저장소 루트에 DRY_RUN 파일 → POST(글쓰기) 요청을 보내지 않는다.
"""
import os, json, datetime, itertools, requests

API = 'https://graph.threads.net/v1.0'
ROOT = os.path.dirname(os.path.abspath(__file__))
KST = datetime.timezone(datetime.timedelta(hours=9))
_mock_cache = None
_fake_ids = itertools.count(900000)


def now_kst():
    fixed = os.environ.get('NOW_KST')  # 시험용 시계 고정 (예: 2026-10-02T12:00:00+09:00)
    return datetime.datetime.fromisoformat(fixed) if fixed else datetime.datetime.now(KST)


def paused():
    return os.path.exists(os.path.join(ROOT, 'PAUSE'))


def dry_run():
    return os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes') or os.path.exists(os.path.join(ROOT, 'DRY_RUN'))


def _mock(method, path, params):
    global _mock_cache
    if _mock_cache is None:
        _mock_cache = json.load(open(os.environ['THREADS_MOCK'], encoding='utf-8'))
    if method == 'POST':
        return {'id': f'mock{next(_fake_ids)}'}
    key = f'{method} {path}'
    if key not in _mock_cache:
        raise RuntimeError(f'{key} → 404 (모의 데이터 없음)')
    return _mock_cache[key]


def api(method, path, **params):
    if os.environ.get('THREADS_MOCK'):
        return _mock(method, path, params)
    if method == 'POST' and dry_run():
        raise RuntimeError('DRY_RUN 중 POST 호출 — 호출부에서 막아야 함')
    params['access_token'] = os.environ['THREADS_TOKEN']
    r = requests.request(method, f'{API}/{path}', params=params, timeout=60)
    if not r.ok:
        err = r.json().get('error', {}) if r.headers.get('content-type', '').startswith('application/json') else {}
        raise RuntimeError(f'{method} {path} → {r.status_code} {err.get("message", r.text[:200])}')
    return r.json()


def get_all(path, max_pages=5, **params):
    """페이지 넘기며 data 모으기 (after 커서)."""
    out, after = [], None
    for _ in range(max_pages):
        if after: params['after'] = after
        d = api('GET', path, **params)
        out += d.get('data', [])
        after = d.get('paging', {}).get('cursors', {}).get('after')
        if not after or not d.get('paging', {}).get('next'):
            break
    return out


def parse_ts(s):
    """스레드 timestamp '2026-09-30T12:30:05+0000' → aware datetime."""
    if s.endswith('+0000'): s = s[:-5] + '+00:00'
    return datetime.datetime.fromisoformat(s)


def my_posts(days=30):
    """최근 days일 안에 올린 우리 게시물(리포스트 제외)."""
    since = now_kst() - datetime.timedelta(days=days)
    posts = get_all('me/threads', fields='id,timestamp,permalink,text,media_type,is_quote_post', limit=50)
    return [p for p in posts if p.get('media_type') != 'REPOST_FACADE' and parse_ts(p['timestamp']) >= since]
