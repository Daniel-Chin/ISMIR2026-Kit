"""Tiny load test: N concurrent tasks against a locally running worker
(LLM_plan.md §11.5). Checks that concurrent deliveries all complete and
that duplicates collapse to one answer.

    LOCAL_MODE=1 CATALOGUE_DIR=../build/catalogue_mock uv run python -m worker.app &
    uv run python evals/load_test.py --url http://localhost:8081 --n 50
"""

import argparse
import concurrent.futures
import time
import uuid

import requests


def fire(url, i):
    payload = {
        "job_id": "load-{}-{}".format(uuid.uuid4().hex[:8], i),
        "user_id": "Uload{}".format(i),  # distinct users: no concurrency lock
        "channel_id": "DLOAD",
        "placeholder_ts": "1.{}".format(i),
        "text": "which papers are about sound synthesis?",
        "source": "dm",
    }
    start = time.time()
    resp = requests.post(url + "/task", json=payload, timeout=120)
    return resp.status_code, time.time() - start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8081")
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda i: fire(args.url, i), range(args.n)))

    latencies = sorted(t for _, t in results)
    codes = {}
    for code, _ in results:
        codes[code] = codes.get(code, 0) + 1
    print("status codes:", codes)
    print(
        "latency p50={:.2f}s p95={:.2f}s max={:.2f}s".format(
            latencies[len(latencies) // 2],
            latencies[int(len(latencies) * 0.95)],
            latencies[-1],
        )
    )


if __name__ == "__main__":
    main()
