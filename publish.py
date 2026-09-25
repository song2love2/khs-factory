"""경한송 무한공장 — 스레드 자동 발행기 (GitHub Actions에서 매일 실행).

queue/*.json 중 예약시각(scheduled)이 지난 글을 오래된 순으로 최대 MAX_PER_RUN개 발행하고 done/으로 옮긴다.
- 토큰: 환경변수 THREADS_TOKEN (GitHub Secrets). 절대 출력하지 않는다.
- 미디어: media/ 파일 → GitHub Pages 공개주소(PAGES_BASE)로 스레드에 넘긴다.
- 저장소 루트에 PAUSE 파일이 있으면 아무것도 하지 않는다(킬스위치).
글 형식: {"id","channel":"threads","account":"sub","type","scheduled":"2026-09-30T21:30:00+09:00",
         "text","media":["media/xxx.mp4" | "media/xxx.jpg"]}
"""
import os, sys, json, glob, time, shutil, datetime, requests

API = 'https://graph.threads.net/v1.0'
PAGES_BASE = os.environ.get('PAGES_BASE', 'https://song2love2.github.io/khs-factory')
MAX_PER_RUN = int(os.environ.get('MAX_PER_RUN', '1'))
ROOT = os.path.dirname(os.path.abspath(__file__))
KST = datetime.timezone(datetime.timedelta(hours=9))


def api(method, path, **params):
    params['access_token'] = os.environ['THREADS_TOKEN']
    r = requests.request(method, f'{API}/{path}', params=params, timeout=60)
    if not r.ok:
        err = r.json().get('error', {}) if r.headers.get('content-type', '').startswith('application/json') else {}
        raise RuntimeError(f'{method} {path} → {r.status_code} {err.get("message", r.text[:200])}')
    return r.json()


def wait_ready(cid, tries=30):
    for _ in range(tries):
        st = api('GET', cid, fields='status,error_message')
        if st.get('status') == 'FINISHED': return
        if st.get('status') in ('ERROR', 'EXPIRED'): raise RuntimeError(f'미디어 처리 실패: {st}')
        time.sleep(10)
    raise RuntimeError('미디어 처리 시간 초과')


def post(p):
    me = api('GET', 'me', fields='id,username')
    uid, text, media = me['id'], p['text'], p.get('media', [])
    if not media:
        c = api('POST', f'{uid}/threads', media_type='TEXT', text=text)
    else:
        m = media[0]
        url = f'{PAGES_BASE}/{m}'
        if m.lower().endswith(('.mp4', '.mov')):
            c = api('POST', f'{uid}/threads', media_type='VIDEO', video_url=url, text=text)
        else:
            c = api('POST', f'{uid}/threads', media_type='IMAGE', image_url=url, text=text)
    wait_ready(c['id'])
    res = api('POST', f'{uid}/threads_publish', creation_id=c['id'])
    link = api('GET', res['id'], fields='permalink').get('permalink')
    return res['id'], link, me['username']


def main():
    if os.path.exists(os.path.join(ROOT, 'PAUSE')):
        print('PAUSE 파일 있음 → 발행 중지'); return
    now = datetime.datetime.now(KST)
    due = []
    for f in glob.glob(os.path.join(ROOT, 'queue', '*.json')):
        p = json.load(open(f, encoding='utf-8'))
        if datetime.datetime.fromisoformat(p['scheduled']) <= now:
            due.append((p['scheduled'], f, p))
    due.sort()
    print(f'{now:%Y-%m-%d %H:%M} KST · 발행 대기 {len(due)}건 · 이번 실행 최대 {MAX_PER_RUN}건')
    print('연결 확인: @' + api('GET', 'me', fields='username')['username'])  # 토큰 점검(읽기만)
    failed = 0
    for _, f, p in due[:MAX_PER_RUN]:
        try:
            pid, link, user = post(p)
            p.update(posted_at=datetime.datetime.now(KST).isoformat(timespec='seconds'), post_id=pid, permalink=link, account_name=user)
            json.dump(p, open(os.path.join(ROOT, 'done', os.path.basename(f)), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            os.remove(f)
            print(f'✅ {p["id"]} → @{user} {link}')
        except Exception as e:
            failed += 1
            print(f'❌ {p["id"]}: {e}')
    if failed: sys.exit(1)


if __name__ == '__main__':
    main()
