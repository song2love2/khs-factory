"""경한송 무한공장 — 스레드 부계정 댓글 자동답글 엔진 (GitHub Actions, 하루 3회).

흐름: 최근 우리 게시물 → 댓글(대화 전체) 수집 → reply_rules.classify → 🟢 답글 / 🔴🟡 보고 목록
- 🟢 green : 템플릿 뱅크에서 골라 답글 (reply_rules.lint_reply 통과분만)
- 🔴 red   : 답글 금지. reports/replies_escalation.md 에 적재 (대표 확인)
- 🟡 yellow: 보류. 같은 파일에 적재
안전장치
- 저장소 루트 PAUSE 파일 → 아무것도 안 함 (기존 킬스위치)
- DRY_RUN=1 또는 루트 DRY_RUN 파일 → 답글 안 올림. 결과는 _dryrun/ 에만 씀(커밋 안 됨)
- 우리 계정 댓글 무시 · 같은 사용자 하루 1회 · 게시물당 누적 상한 · 실행당 상한 · 처리한 댓글 id는 state 에 기록(중복 방지)
- 게시 후 72시간 지난 댓글에는 답글 안 달고 기록만
필요 권한: threads_basic, threads_read_replies, threads_manage_replies
"""
import os, sys, json, time, random, datetime
import threads_api as T
import reply_rules as R

ROOT = T.ROOT
POST_DAYS = int(os.environ.get('REPLY_POST_DAYS', '14'))        # 최근 며칠 게시물의 댓글을 보나
MAX_PER_RUN = int(os.environ.get('REPLY_MAX_PER_RUN', '8'))     # 한 번 실행에 최대 답글 수
MAX_PER_POST = int(os.environ.get('REPLY_MAX_PER_POST', '15'))  # 게시물당 누적 자동답글 상한
STALE_H = int(os.environ.get('REPLY_STALE_HOURS', '72'))        # 이보다 오래된 댓글엔 답글 안 함
RECENT_N = 20                                                    # 최근 N개 답글과 같은 템플릿 피하기
GAP = (20, 45)                                                   # 답글 사이 사람 같은 간격(초)
ICON = {'red': '🔴', 'yellow': '🟡'}


def out_dir():
    d = os.environ.get('OUT_DIR') or (os.path.join(ROOT, '_dryrun') if T.dry_run() else ROOT)
    os.makedirs(os.path.join(d, 'state'), exist_ok=True)
    os.makedirs(os.path.join(d, 'reports'), exist_ok=True)
    return d


def load_state(d):
    f = os.path.join(d, 'state', 'replies_state.json')
    if not os.path.exists(f) and d != ROOT and not os.environ.get('OUT_DIR'):  # DRY_RUN 은 실제 상태에서 출발(시험용 OUT_DIR 제외)
        f = os.path.join(ROOT, 'state', 'replies_state.json')
    s = json.load(open(f, encoding='utf-8')) if os.path.exists(f) else {}
    for k, v in (('handled', {}), ('user_last', {}), ('post_count', {}), ('post_tpl', {}), ('recent_tpl', [])):
        s.setdefault(k, v)
    return s


def save_state(d, s):
    json.dump(s, open(os.path.join(d, 'state', 'replies_state.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def queue_types():
    """done/*.json 의 post_id → (queue id, 유형)."""
    m = {}
    import glob
    for f in glob.glob(os.path.join(os.environ.get('DONE_DIR') or os.path.join(ROOT, 'done'), '*.json')):
        try:
            p = json.load(open(f, encoding='utf-8'))
            if p.get('post_id'): m[p['post_id']] = (p.get('id', ''), p.get('type', ''))
        except Exception:
            pass
    return m


def one_line(s, n=120):
    s = ' '.join((s or '').split())
    return s if len(s) <= n else s[:n] + '…'


def append_escalation(d, rows):
    if not rows: return
    f = os.path.join(d, 'reports', 'replies_escalation.md')
    head = not os.path.exists(f)
    with open(f, 'a', encoding='utf-8') as w:
        if head:
            w.write('# 스레드 댓글 — 대표 확인 목록 (자동답글 안 함)\n\n'
                    '> 🔴 = 답글 금지(클레임·환불·배송·이물질·알레르기/안전·건강/효능·가격·협업/광고·스팸·욕설) · 🟡 = 애매해서 보류.\n'
                    '> 답은 대표가 스레드 앱에서 직접. 처리했으면 줄 앞 `[ ]` 를 `[x]` 로. 금요일 주간보고에 미처리 건수를 올린다.\n')
        w.write(f'\n## {T.now_kst():%Y-%m-%d %H:%M} KST 실행\n\n')
        for r in rows:
            w.write(f'- [ ] {ICON[r["cls"]]} **{r["cat"]}** · @{r["user"]} · {r["ts"]} — 「{one_line(r["text"])}」\n'
                    f'  - 게시물: {r["post_ref"]} · 사유: {r["why"]}' + (f' · [댓글 보기]({r["link"]})' if r.get('link') else '') + '\n')


def append_log(d, rows):
    if not rows: return
    import csv
    f = os.path.join(d, 'reports', 'replies_log.csv')
    head = not os.path.exists(f)
    with open(f, 'a', encoding='utf-8-sig' if head else 'utf-8', newline='') as w:
        c = csv.writer(w)
        if head: c.writerow(['run_at', 'post_id', 'queue_id', 'comment_id', 'user', 'class', 'category', 'comment', 'reply_tpl', 'reply', 'result'])
        for r in rows: c.writerow(r)


def send_reply(uid, comment_id, text):
    c = T.api('POST', f'{uid}/threads', media_type='TEXT', text=text, reply_to_id=comment_id)
    time.sleep(0 if os.environ.get('THREADS_MOCK') else 5)  # 텍스트 컨테이너도 잠깐 기다리는 게 권장
    res = T.api('POST', f'{uid}/threads_publish', creation_id=c['id'])
    return res['id']


def main():
    if T.paused():
        print('PAUSE 파일 있음 → 답글 엔진 중지'); return
    dry = T.dry_run()
    d = out_dir()
    st = load_state(d)
    bank = R.load_bank()
    now = T.now_kst(); today = f'{now:%Y-%m-%d}'
    me = T.api('GET', 'me', fields='id,username')
    uid, myname = me['id'], me['username']
    qmap = queue_types()
    posts = T.my_posts(POST_DAYS)
    print(f'{now:%Y-%m-%d %H:%M} KST · @{myname} · 최근 {POST_DAYS}일 게시물 {len(posts)}개 · {"DRY_RUN" if dry else "실행"}')

    esc, log, sent, failed = [], [], 0, 0
    run_at = now.isoformat(timespec='seconds')
    for p in posts:
        pid = p['id']
        qid, ptype = qmap.get(pid, ('', ''))
        try:
            comments = T.get_all(f'{pid}/conversation',
                                 fields='id,text,username,timestamp,permalink,is_reply_owned_by_me,hide_status,replied_to',
                                 reverse='false')
        except Exception as e:
            print(f'⚠ {pid} 댓글 읽기 실패: {e}'); failed += 1; continue
        post_ref = f'[{qid or pid}]({p.get("permalink", "")})'
        for c in sorted(comments, key=lambda x: x.get('timestamp', '')):
            cid, user, text = c['id'], c.get('username', ''), c.get('text', '') or ''
            if cid in st['handled']: continue
            if c.get('is_reply_owned_by_me') or user == myname:
                continue  # 우리 계정 댓글 무시 (기록도 안 함)
            if c.get('hide_status') not in (None, 'NOT_HUSHED', 'UNHUSHED'):
                st['handled'][cid] = {'at': run_at, 'action': 'hidden'}; continue
            cls, cat, why, pick = R.classify(text, p.get('text', ''), ptype)
            ts = T.parse_ts(c['timestamp']).astimezone(T.KST)
            row = dict(cls=cls, cat=cat, why=why, user=user, text=text, ts=f'{ts:%m-%d %H:%M}', post_ref=post_ref, link=c.get('permalink'))
            if cls != 'green':
                esc.append(row)
                st['handled'][cid] = {'at': run_at, 'action': 'escalated', 'cls': cls, 'cat': cat}
                log.append([run_at, pid, qid, cid, user, cls, cat, one_line(text), '', '', 'escalated'])
                continue
            # 🟢 — 제한 확인
            skip = None
            if (now - ts).total_seconds() > STALE_H * 3600: skip = f'{STALE_H}시간 지난 댓글'
            elif st['user_last'].get(user) == today: skip = '같은 사용자 오늘 이미 답함'
            elif st['post_count'].get(pid, 0) >= MAX_PER_POST: skip = f'게시물 상한 {MAX_PER_POST}'
            if not skip and sent >= MAX_PER_RUN:
                continue  # 실행당 상한 → 기록 안 하고 다음 실행으로 넘김
            if skip:
                st['handled'][cid] = {'at': run_at, 'action': 'skipped', 'why': skip}
                log.append([run_at, pid, qid, cid, user, cls, cat, one_line(text), '', '', 'skip: ' + skip]); continue
            tid, reply = R.choose(bank, cat, cid, st['recent_tpl'], st['post_tpl'].get(pid, []), pick)
            bad = R.lint_reply(reply)
            if bad:
                row.update(cls='yellow', why='답글 검사 불합격: ' + ' / '.join(bad)); esc.append(row)
                st['handled'][cid] = {'at': run_at, 'action': 'escalated', 'cls': 'yellow', 'cat': 'lint'}; continue
            try:
                if dry:
                    rid = 'DRY'
                else:
                    if sent: time.sleep(0 if os.environ.get('THREADS_MOCK') else random.randint(*GAP))
                    rid = send_reply(uid, cid, reply)
            except Exception as e:
                print(f'❌ 답글 실패 {cid}: {e}'); failed += 1
                log.append([run_at, pid, qid, cid, user, cls, cat, one_line(text), tid, reply, f'error: {e}'])
                continue  # handled 에 안 넣음 → 다음 실행에 재시도
            sent += 1
            st['handled'][cid] = {'at': run_at, 'action': 'replied', 'tpl': tid, 'reply_id': rid}
            st['user_last'][user] = today
            st['post_count'][pid] = st['post_count'].get(pid, 0) + 1
            st['post_tpl'].setdefault(pid, []).append(tid)
            st['recent_tpl'] = (st['recent_tpl'] + [tid])[-RECENT_N:]
            log.append([run_at, pid, qid, cid, user, cls, cat, one_line(text), tid, reply, 'replied' if not dry else 'dry'])
            print(f'🟢 @{user} 「{one_line(text, 40)}」 → {reply}')

    for r in esc:
        print(f'{ICON[r["cls"]]} @{r["user"]} 「{one_line(r["text"], 40)}」 [{r["cat"]}]')
    append_escalation(d, esc)
    append_log(d, log)
    save_state(d, st)
    print(f'완료: 답글 {sent} · 보고 {len(esc)} (🔴 {sum(r["cls"] == "red" for r in esc)} / 🟡 {sum(r["cls"] == "yellow" for r in esc)}) · 오류 {failed}' + (f' · 결과 폴더 {d}' if dry else ''))
    if failed: sys.exit(1)


if __name__ == '__main__':
    main()
