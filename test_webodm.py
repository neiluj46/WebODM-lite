"""
Orthophoto ultrarapide (profil Planar WebODM) via NodeODM GPU.

Usage : python3 test_webodm.py [dossier_images] [dossier_sortie]
"""

import json
import logging
import mimetypes
import os
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

import requests
from PIL import Image, ImageOps

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("NodeODMConnector")

NODEODM_URL = "http://localhost:3000"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
TARGET_SIZE = (2000, 1500)

POLL_INTERVAL = 3
REQUEST_TIMEOUT = 30
UPLOAD_BATCH_SIZE = 30
UPLOAD_TIMEOUT = 600

STATUS_QUEUED, STATUS_RUNNING, STATUS_FAILED, STATUS_COMPLETED, STATUS_CANCELED = 10, 20, 30, 40, 50

# Options exactes du profil Planar / Fast de WebODM
ODM_OPTIONS = [
    {"name": "fast-orthophoto", "value": True},
    {"name": "feature-quality", "value": "lowest"},
    {"name": "min-num-features", "value": 4000},
    {"name": "dsm", "value": False},
    {"name": "dtm", "value": False},
    {"name": "orthophoto-png", "value": True},
    {"name": "orthophoto-resolution", "value": 5.0},
    {"name": "radiometric-calibration", "value": "none"},
    {"name": "max-concurrency", "value": 4}
]


class NodeODMError(Exception):
    """Erreur renvoyée par NodeODM."""


def find_images(input_dir):
    return sorted(
        p for p in Path(input_dir).resolve().iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        and not p.name.startswith("odm_orthophoto")
    )


def resize_images(images, dest_dir):
    logger.info("Redimensionnement rapide de %d image(s)...", len(images))
    resized = []
    for idx, img_path in enumerate(images, 1):
        try:
            with Image.open(img_path) as img:
                exif = img.info.get("exif")
                xmp = img.info.get("xmp")
                img = ImageOps.exif_transpose(img)
                out = img.convert("RGB")
                out.thumbnail(TARGET_SIZE, Image.Resampling.LANCZOS)

                save_kwargs = {"quality": 80}
                if exif:
                    save_kwargs["exif"] = exif
                if xmp:
                    save_kwargs["xmp"] = xmp
                dest = dest_dir / f"{img_path.stem}.jpg"
                out.save(dest, "JPEG", **save_kwargs)
                resized.append(dest)
        except Exception as e:
            logger.warning("Erreur image %s : %s", img_path.name, e)
    return resized


def nodeodm_request(method, path, **kwargs):
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    response = requests.request(method, f"{NODEODM_URL}{path}", **kwargs)
    response.raise_for_status()
    if "application/json" in response.headers.get("Content-Type", ""):
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            raise NodeODMError(data["error"])
    return response


def create_and_upload_task(images):
    init_resp = nodeodm_request(
        "POST", "/task/new/init",
        data={"options": json.dumps(ODM_OPTIONS)}
    )
    task_id = init_resp.json().get("uuid")

    total = len(images)
    for start in range(0, total, UPLOAD_BATCH_SIZE):
        batch = images[start:start + UPLOAD_BATCH_SIZE]
        with ExitStack() as stack:
            files = []
            for img in batch:
                mime_type, _ = mimetypes.guess_type(img)
                files.append(("images", (img.name, stack.enter_context(open(img, "rb")), mime_type or "image/jpeg")))

            nodeodm_request(
                "POST", f"/task/new/upload/{task_id}",
                files=files,
                timeout=UPLOAD_TIMEOUT
            )

    nodeodm_request("POST", f"/task/new/commit/{task_id}")
    return task_id


def wait_for_task(task_id):
    last_state = None
    start_time = time.time()
    while True:
        try:
            info = nodeodm_request("GET", f"/task/{task_id}/info").json()
        except requests.exceptions.RequestException:
            time.sleep(POLL_INTERVAL)
            continue

        code = info.get("status", {}).get("code")
        if code == STATUS_COMPLETED:
            elapsed = time.time() - start_time
            logger.info("Traitement terminé en %.1f secondes !", elapsed)
            return
        if code in (STATUS_FAILED, STATUS_CANCELED):
            raise NodeODMError(f"Échec tâche : {info.get('lastError')}")

        progress = round(info.get("progress", 0))
        if progress != last_state:
            logger.info("Progression : %d%%", progress)
            last_state = progress

        time.sleep(POLL_INTERVAL)


def download_orthophoto(task_id, output_dir):
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    for asset in ("orthophoto.png", "orthophoto.tif"):
        destination = out_path / f"odm_{asset}"
        tmp_destination = destination.with_suffix(destination.suffix + ".part")

        try:
            response = nodeodm_request("GET", f"/task/{task_id}/download/{asset}", stream=True, timeout=600)
        except Exception:
            continue

        with response, open(tmp_destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        os.replace(tmp_destination, destination)
        logger.info("Orthophoto enregistrée : %s", destination)
        return destination

    raise NodeODMError("Téléchargement impossible")


def process_nodeodm(images_dir=".", output_dir="./output"):
    images = find_images(images_dir)
    if len(images) < 2:
        return None

    with tempfile.TemporaryDirectory(prefix="resized_") as tmp:
        resized = resize_images(images, Path(tmp))
        task_id = create_and_upload_task(resized)
        wait_for_task(task_id)

    return download_orthophoto(task_id, output_dir)


if __name__ == "__main__":
    try:
        process_nodeodm(*sys.argv[1:3])
    except Exception as err:
        logger.error("Erreur : %s", err)
        sys.exit(1)
