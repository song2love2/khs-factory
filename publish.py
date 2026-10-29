"""경한송 무한공장 — 스레드 자동 발행기 (GitHub Actions가 오후~밤 30분마다 깨움).

GitHub 예약은 4~6시간씩 늦게 돌아서(10-20~29 실측) 한 번만 깨우면 새벽에 올라간다.
그래서 여러 번 깨우고, 그날의 '목표 시각'(21:00~23:40 사이, 날짜로 정해지는 무작위)이 지난 뒤
처음 깨어난 실행이 1건만 올린다(오늘 글이 대기열에서 빠지면 그날은 끝). 밀린 글이 있으면 목표 시각 뒤 실행마다(30분 간격) 1건씩 따라잡는다.
새벽 4시 전 실행은 전날 몫으로 친다. 수동 실행(FORCE=1)은 목표 시각을 무시하고 바로 1건.
queue/*.json 중 예약시각(scheduled)이 지난 글을 오래된 순으로 발행하고 done/으로 옮긴다.
- 토큰: 환경변수 THREADS_TOKEN (GitHub Secrets). 절대 출력하지 않는다.
- 미디어: media/ 파일 → GitHub Pages 공개주소(PAGES_BASE)로 스레드에 넘긴다.
- 저장소 루트에 PAUSE 파일이 있으면 아무것도 하지 않는다(킬스위치).
글 형식: {"id","channel":"threads","account":"sub","type","scheduled":"2026-09-30T21:00:00+09:00",
         "text","media":["media/xxx.mp4" | "media/xxx.jpg"]}
"""
import os, sys, json, glob, time, shutil, datetime, random, requests

API = 'https://graph.threads.net/v1.0'
PAGES_BASE = os.environ.get('PAGES_BASE', 'https://song2love2.github.io/khs-factory')
MAX_PER_RUN = int(os.environ.get('MAX_PER_RUN', '1'))
ROOT = os.path.dirname(os.path.abspath(__file__))
KST = datetime.timezone(datetime.timedelta(hours=9))
DAY_SHIFT = datetime.timedelta(hours=4)   # 새벽 4시 전은 전날 몫


def pub_day(t):
    return (t - DAY_SHIFT).date()


def target_time(day):
    m = random.Random(f'khs-{day.isoformat()}').randint(0, 160)   # 21:00 + 0~160분
    return datetime.datetime.combine(day, datetime.time(21, 0), KST) + datetime.timedelta(minutes=m)


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
    day = pub_day(now)
    due = []
    for f in glob.glob(os.path.join(ROOT, 'queue', '*.json')):
        p = json.load(open(f, encoding='utf-8'))
        if datetime.datetime.fromisoformat(p['scheduled']) <= now:
            due.append((p['scheduled'], f, p))
    due.sort()
    overdue = [d for d in due if pub_day(datetime.datetime.fromisoformat(d[0])) < day]
    tgt = target_time(day)
    force = os.environ.get('FORCE') == '1'
    print(f'{now:%Y-%m-%d %H:%M} KST · 발행 대기 {len(due)}건(밀린 것 {len(overdue)}) · 오늘 목표 {tgt:%H:%M}')
    if not due:
        print('올릴 글 없음 (오늘 몫 이미 발행했거나 대기열 비어 있음)'); return
    if not force and now < tgt:
        print('아직 목표 시각 전 → 대기'); return
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
