import os
import shutil


def rename_thumbnails_to_images(thumbnails_dir: str, images_dir: str):
    os.makedirs(images_dir, exist_ok=True)

    for filename in os.listdir(thumbnails_dir):
        if filename.startswith("thumbnail_") and filename.endswith(".png"):
            # "thumbnail_0004.png" → "4.png"
            num_str = filename.replace("thumbnail_", "").replace(".png", "")
            new_filename = f"{int(num_str)}"  # 앞의 0 제거
            src_path = os.path.join(thumbnails_dir, filename)
            dst_path = os.path.join(images_dir, new_filename)

            shutil.copy2(src_path, dst_path)  # 원본 유지 (복사)
            # os.rename(src_path, dst_path)  # 원본 이동하고 싶으면 이 줄 사용

            print(f"{filename} → {new_filename}")


# 사용 예시
rename_thumbnails_to_images("./static/thumbnail", "./static/paper_images")
