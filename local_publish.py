"""가게 노트북 주 발행기 (11-12 대표: 업로드 21~23시 + 올라가면 바로 1시간 스레드 활동).

- 부르는 곳: 예약작업 khs-threads-engage-runner 의 '발행' 회차(시간표 = 엔진/스레드_시간표.py, 목표 시각 = publish.target_time)
- 토큰: 콘텐츠공장/엔진/비밀값.env 의 THREADS_TOKEN (출력 금지)
- 순서: git pull → publish.py (목표 시각 지난 대기열 1건) → queue/done 변경을 커밋·푸시(3번 재시도)
- GitHub Actions는 예비(GRACE_MIN=60). 둘 다 돌아도 publish.py가 같은 글을 계정에서 확인해 중복 발행을 막는다.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(HERE, "..", "엔진", "비밀값.env")


def git(*args):
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, encoding="utf-8")


def main():
    for line in open(ENV, encoding="utf-8"):
        if line.startswith("THREADS_TOKEN="):
            os.environ["THREADS_TOKEN"] = line.split("=", 1)[1].strip()
    if not os.environ.get("THREADS_TOKEN"):
        sys.exit("THREADS_TOKEN 없음")
    r = git("pull", "--rebase", "-q")
    print("git pull:", "ok" if r.returncode == 0 else r.stderr.strip()[-200:])
    sys.path.insert(0, HERE)
    import publish
    code = 0
    try:
        publish.main()
    except SystemExit as e:
        code = e.code or 0
    git("add", "-A", "queue", "done")
    if git("diff", "--cached", "--quiet").returncode != 0:
        git("commit", "-q", "-m", "발행 기록(로컬 실행기)")
        for i in range(3):
            p = git("push", "-q")
            if p.returncode == 0:
                break
            git("pull", "--rebase", "-q")
        print("git push:", "ok" if p.returncode == 0 else p.stderr.strip()[-200:])
    sys.exit(code)


if __name__ == "__main__":
    main()
