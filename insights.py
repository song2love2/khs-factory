"""경한송 무한공장 — 스레드 반응 수집 엔진 (GitHub Actions, 매주 일요일 22:00 KST + 수동).

- 최근 COLLECT_DAYS일 우리 게시물마다 insights(views, likes, replies, reposts, quotes, shares)를 읽어
  reports/insights.csv 에 한 줄씩 누적(스냅샷: 같은 글도 매주 새 줄 → 시간에 따른 증가를 볼 수 있음)
- done/*.json 과 post_id 로 이어서 유형(공감/브랜딩/참여)·미디어 유무를 붙인다. done 에 없는 글은 유형 '수동'
- 계정 팔로워 수(followers_count)도 가능하면 기록 → reports/followers.csv
- 주간 요약: reports/insights_weekly_<날짜>.md (지난 7일 발행분 상위/하위, 유형별·미디어별 평균, 팔로워 증감)
필요 권한: threads_basic + threads_manage_insights (insights 엔드포인트는 이 권한 없으면 403/권한 오류)
DRY_RUN: 읽기만 하는 엔진이라 API 호출은 그대로 하고, 결과 파일을 _dryrun/ 에 쓴다(커밋 안 됨).
"""
import os, sys, csv, json, glob, datetime
import threads_api as T

ROOT = T.ROOT
METRICS = ['views', 'likes', 'replies', 'reposts', 'quotes', 'shares']
COLLECT_DAYS = int(os.environ.get('INSIGHTS_DAYS', '30'))
FIELDS = ['collected_at', 'post_id', 'queue_id', 'type', 'media', 'posted_at', 'age_h'] + METRICS + ['engagement', 'permalink', 'text_head']


def out_dir():
    d = os.environ.get('OUT_DIR') or (os.path.join(ROOT, '_dryrun') if T.dry_run() else ROOT)
    os.makedirs(os.path.join(d, 'reports'), exist_ok=True)
    return d


def done_map():
    m = {}
    for f in glob.glob(os.path.join(os.environ.get('DONE_DIR') or os.path.join(ROOT, 'done'), '*.json')):
        try:
            p = json.load(open(f, encoding='utf-8'))
            if p.get('post_id'): m[p['post_id']] = p
        except Exception:
            pass
    return m


def metric_value(item):
    if 'total_value' in item: return int(item['total_value'].get('value', 0) or 0)
    vals = item.get('values') or []
    return int(sum((v.get('value') or 0) for v in vals)) if vals else 0


def post_insights(pid):
    d = T.api('GET', f'{pid}/insights', metric=','.join(METRICS))
    got = {x['name']: metric_value(x) for x in d.get('data', [])}
    return {k: got.get(k, 0) for k in METRICS}


def media_kind(p, q):
    mt = p.get('media_type', '')
    if mt in ('VIDEO',): return '영상'
    if mt in ('IMAGE', 'CAROUSEL_ALBUM'): return '이미지'
    if q and q.get('media'):
        return '영상' if q['media'][0].lower().endswith(('.mp4', '.mov')) else '이미지'
    return '텍스트'


def read_csv(f):
    if not os.path.exists(f): return []
    return list(csv.DictReader(open(f, encoding='utf-8-sig')))


def append_csv(f, fields, rows):
    head = not os.path.exists(f)
    with open(f, 'a', encoding='utf-8-sig' if head else 'utf-8', newline='') as w:
        c = csv.DictWriter(w, fieldnames=fields)
        if head: c.writeheader()
        for r in rows: c.writerow(r)


def followers(uid):
    try:
        d = T.api('GET', f'{uid}/threads_insights', metric='followers_count')
        for x in d.get('data', []):
            if x.get('name') == 'followers_count': return metric_value(x)
    except Exception as e:
        print(f'⚠ 팔로워 수 읽기 실패(건너뜀): {e}')
    return None


def avg(rows, k):
    return sum(int(r[k]) for r in rows) / len(rows) if rows else 0


def weekly_md(rows, now, fol_rows):
    """rows = 이번 실행 스냅샷. 지난 7일 발행분만 요약."""
    week = [r for r in rows if (now - datetime.datetime.fromisoformat(r['posted_at'])).days < 7]
    L = [f'# 스레드 부계정 주간 반응 — {now:%Y-%m-%d} ({"월화수목금토일"[now.weekday()]})', '',
         f'> 수집 {now:%Y-%m-%d %H:%M} KST · 지난 7일 발행 {len(week)}건 · 전체 추적 {len(rows)}건 (최근 {COLLECT_DAYS}일)',
         '> 반응합계(engagement) = 좋아요+답글+리포스트+인용+공유. 발행 후 경과시간이 달라 최근 글은 숫자가 작게 나올 수 있음.', '']
    if len(fol_rows) >= 1:
        cur = fol_rows[-1]; prev = fol_rows[-2] if len(fol_rows) >= 2 else None
        diff = f' ({int(cur["followers"]) - int(prev["followers"]):+d}, 지난 수집 {prev["collected_at"][:10]} 대비)' if prev else ' (첫 기록)'
        L += [f'**팔로워 {cur["followers"]}명**{diff}', '']
    if not week:
        L += ['지난 7일 발행분 없음.', '']
        return '\n'.join(L) + '\n'
    tot = {k: sum(int(r[k]) for r in week) for k in METRICS + ['engagement']}
    L += ['## 합계', '', '| 조회 | 좋아요 | 답글 | 리포스트 | 인용 | 공유 | 반응합계 |', '|---:|---:|---:|---:|---:|---:|---:|',
          '| ' + ' | '.join(f'{tot[k]:,}' for k in METRICS + ['engagement']) + ' |', '']
    key = lambda r: (int(r['views']), int(r['engagement']))
    srt = sorted(week, key=key, reverse=True)
    n = min(3, len(srt))
    def tbl(title, items):
        out = [f'## {title}', '', '| 글 | 유형 | 미디어 | 조회 | 좋아요 | 답글 | 반응합계 | 첫 줄 |', '|---|---|---|---:|---:|---:|---:|---|']
        for r in items:
            out.append(f'| [{r["queue_id"] or r["post_id"]}]({r["permalink"]}) | {r["type"]} | {r["media"]} | {int(r["views"]):,} | {r["likes"]} | {r["replies"]} | {r["engagement"]} | {r["text_head"]} |')
        return out + ['']
    L += tbl(f'상위 {n} (조회수 순)', srt[:n])
    if len(srt) > 3:
        L += tbl(f'하위 {min(3, len(srt) - 3)}', list(reversed(srt[-min(3, len(srt) - 3):])))
    for label, col in (('유형별 평균', 'type'), ('미디어별 평균', 'media')):
        L += [f'## {label}', '', f'| {label.split("별")[0]} | 글 수 | 평균 조회 | 평균 좋아요 | 평균 답글 | 평균 반응합계 |', '|---|---:|---:|---:|---:|---:|']
        for g in sorted({r[col] for r in week}):
            gr = [r for r in week if r[col] == g]
            L.append(f'| {g} | {len(gr)} | {avg(gr, "views"):,.0f} | {avg(gr, "likes"):.1f} | {avg(gr, "replies"):.1f} | {avg(gr, "engagement"):.1f} |')
        L.append('')
    best = max({r['type'] for r in week}, key=lambda g: avg([r for r in week if r['type'] == g], 'views'))
    L += ['## 다음 주 생산 메모 (설계서 §7: 한 번에 한 변수만)', '',
          f'- 조회 평균 1위 유형: **{best}** → 표본이 3건 이상 쌓일 때까지는 비율 조정 보류, 이후 승자 +10%p.',
          '- 이 파일은 화요일 `khs-threads-weekly` 생산과 금요일 주간보고가 읽는다.', '']
    return '\n'.join(L) + '\n'


def main():
    if T.paused():
        print('PAUSE 파일 있음 → 반응 수집 중지'); return
    d = out_dir()
    now = T.now_kst()
    me = T.api('GET', 'me', fields='id,username')
    dm = done_map()
    posts = T.my_posts(COLLECT_DAYS)
    print(f'{now:%Y-%m-%d %H:%M} KST · @{me["username"]} · 최근 {COLLECT_DAYS}일 게시물 {len(posts)}개')
    rows, failed = [], 0
    for p in posts:
        q = dm.get(p['id'])
        try:
            m = post_insights(p['id'])
        except Exception as e:
            print(f'❌ {p["id"]} insights 실패: {e}'); failed += 1; continue
        posted = T.parse_ts(p['timestamp']).astimezone(T.KST)
        r = dict(collected_at=now.isoformat(timespec='seconds'), post_id=p['id'], queue_id=(q or {}).get('id', ''),
                 type=(q or {}).get('type', '수동'), media=media_kind(p, q), posted_at=posted.isoformat(timespec='seconds'),
                 age_h=int((now - posted).total_seconds() // 3600), **m,
                 engagement=sum(m[k] for k in METRICS if k != 'views'), permalink=p.get('permalink', ''),
                 text_head=' '.join((p.get('text') or '').split('\n')[0].split())[:30].replace('|', '/'))
        rows.append(r)
    append_csv(os.path.join(d, 'reports', 'insights.csv'), FIELDS, rows)
    fcnt = followers(me['id'])
    ff = os.path.join(d, 'reports', 'followers.csv')
    if fcnt is not None:
        append_csv(ff, ['collected_at', 'followers'], [dict(collected_at=now.isoformat(timespec='seconds'), followers=fcnt)])
    md = weekly_md([{k: str(v) for k, v in r.items()} for r in rows], now, read_csv(ff))
    out = os.path.join(d, 'reports', f'insights_weekly_{now:%Y-%m-%d}.md')
    open(out, 'w', encoding='utf-8').write(md)
    print(f'완료: 수집 {len(rows)} · 실패 {failed} · 팔로워 {fcnt} → {out}')
    if failed and not rows: sys.exit(1)


if __name__ == '__main__':
    main()
