import csv
import mimetypes
import os
import re
from urllib.parse import parse_qs, urlparse

import gdown
import requests


def extract_file_id(url: str) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "id" in qs and qs["id"]:
        return qs["id"][0]
    m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", parsed.path)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    raise ValueError(f"Can't figure out the file ID from the URL: {url}")


def _pick_extension_from_headers(content_type: str) -> str:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "image/tiff": ".tif",
    }
    if content_type in mapping:
        return mapping[content_type]
    ext = mimetypes.guess_extension(content_type or "")
    return ext or ""


def _is_likely_html(resp: requests.Response) -> bool:
    ct = resp.headers.get("Content-Type", "")
    return "text/html" in ct.lower()


def download_gdrive_file(url: str, dest_path: str, chunk_size: int = 1 << 14):
    file_id = extract_file_id(url)
    session = requests.Session()

    base = "https://drive.google.com/uc?export=download"
    params = {"id": file_id}
    resp = session.get(base, params=params, stream=True)
    resp.raise_for_status()

    def get_confirm_token(r: requests.Response):
        for k, v in r.cookies.items():
            if k.startswith("download_warning"):
                return v
        if _is_likely_html(r):
            m = re.search(r"confirm=([0-9A-Za-z_]+)", r.text)
            if m:
                return m.group(1)
        return None

    token = get_confirm_token(resp)
    if token:
        params["confirm"] = token
        resp = session.get(base, params=params, stream=True)
        resp.raise_for_status()

    if _is_likely_html(resp):
        raise RuntimeError("Can't download. The link might be private.")

    final_path = dest_path

    # if willing to save with format extensions..
    # root, ext = os.path.splitext(dest_path)
    # if not ext:
    #     guessed_ext = _pick_extension_from_headers(resp.headers.get("Content-Type", ""))
    #     final_path = root + guessed_ext if guessed_ext else dest_path

    os.makedirs(os.path.dirname(final_path) or ".", exist_ok=True)

    with open(final_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)

    return final_path


def download_images(csv_file_path: str, output_folder: str):
    os.makedirs(output_folder, exist_ok=True)

    with open(csv_file_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            file_id = row["uid"]
            gdrive_url = row["thumbnail"]
            if gdrive_url:
                try:
                    saved = download_gdrive_file(
                        gdrive_url, os.path.join(output_folder, file_id)
                    )
                    print(f"[download success] {saved}")

                except Exception as e:
                    print(f"[error]: {file_id} / URL: {gdrive_url} / {e}")


# csv_file = "sitedata/lbds.csv"
# output_dir = "static/paper_images"
# download_images(csv_file, output_dir)

with open("sitedata/lbds.csv", newline="", encoding="utf-8") as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        file_id = row["uid"]
        gdrive_url = row["thumbnail_link"]
        try:
            output_dir = "static/images/lbd/thumbnails/"
            os.makedirs(output_dir, exist_ok=True)
            # gdown >= 6 removed the fuzzy kwarg (fuzzy matching is the default)
            gdown.download(gdrive_url, output_dir)
            print(f"[download success] {file_id}")

        except Exception as e:
            print(f"[error]: {file_id} / URL: {gdrive_url} / {e}")
