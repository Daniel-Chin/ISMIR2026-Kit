"""Upload versioned catalogue artifacts to GCS and flip latest.json.

Follows the root repo convention of gating real side effects: dry run by
default, pass --prod to actually upload. Uses the gcloud CLI (operator
machines already have it for Cloud Run deploys); no extra Python deps.

    python catalogue/upload.py --dir build/catalogue/ --version 2026-07-18 \
        --bucket gs://ismir2026-assistant-catalogue --prod

Order matters: artifacts first, latest.json last — the worker only switches
after everything it will download is in place.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile


def artifact_names(version):
    return [
        "catalogue-{}.json".format(version),
        "embeddings-{}.npy".format(version),
        "embeddings-{}.ids.json".format(version),
        "search-{}.sqlite".format(version),
    ]


def run(cmd, prod):
    print(("RUN " if prod else "DRY-RUN ") + " ".join(cmd))
    if prod:
        subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="build/catalogue/")
    parser.add_argument("--version", required=True)
    parser.add_argument("--bucket", required=True, help="gs://bucket[/prefix]")
    parser.add_argument("--prod", action="store_true", help="actually upload")
    args = parser.parse_args()

    bucket = args.bucket.rstrip("/")
    if not bucket.startswith("gs://"):
        print("--bucket must start with gs://", file=sys.stderr)
        sys.exit(1)

    paths = [os.path.join(args.dir, name) for name in artifact_names(args.version)]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        print(
            "missing artifacts (run build_catalogue.py + build_index.py first):",
            file=sys.stderr,
        )
        for p in missing:
            print("  " + p, file=sys.stderr)
        sys.exit(1)

    for path in paths:
        run(
            [
                "gcloud",
                "storage",
                "cp",
                path,
                "{}/{}".format(bucket, os.path.basename(path)),
            ],
            args.prod,
        )

    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump({"version": args.version}, f)
        latest = f.name
    try:
        run(
            ["gcloud", "storage", "cp", latest, "{}/latest.json".format(bucket)],
            args.prod,
        )
    finally:
        os.unlink(latest)

    if not args.prod:
        print("dry run complete — re-run with --prod to upload")


if __name__ == "__main__":
    main()
