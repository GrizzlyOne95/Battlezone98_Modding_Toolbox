import io
import json
import os
import stat
import sys
import tarfile
import zipfile

STEAMCMD_URLS = {
    "win32": "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip",
    "darwin": "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_osx.tar.gz",
    "linux": "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz",
}


class AppFileManager:
    def __init__(self, logger=None, has_pil=False, image_module=None):
        self.logger = logger
        self.has_pil = has_pil
        self.image_module = image_module

    def log(self, msg):
        if self.logger:
            self.logger(msg)

    def load_json_file(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_json_file(self, path, data):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def load_config(self, config_path, legacy_paths=None):
        candidate_paths = [config_path]
        for path in legacy_paths or []:
            if path not in candidate_paths:
                candidate_paths.append(path)

        for path in candidate_paths:
            if not os.path.exists(path):
                continue
            try:
                return self.load_json_file(path)
            except Exception:
                pass
        return {}

    def save_config(self, config_path, data):
        self.save_json_file(config_path, data)

    def save_profile(self, path, data):
        self.save_json_file(path, data)

    def load_profile(self, path):
        return self.load_json_file(path)

    def resize_preview_image(self, image_path, temp_dir):
        if not self.has_pil or self.image_module is None:
            return None

        img = self.image_module.open(image_path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((1024, 1024), self.image_module.Resampling.LANCZOS)

        out_path = os.path.join(temp_dir, os.path.basename(image_path) + "_resized.jpg")
        for quality in range(90, 20, -5):
            img.save(out_path, "jpeg", quality=quality, optimize=True)
            if os.path.getsize(out_path) < 1024 * 1024:
                return out_path
        return None

    def download_steamcmd(self, base_dir, request_with_retry, platform=None):
        """Download Valve's SteamCMD for this OS; returns the program to run."""
        platform = platform or ("win32" if sys.platform == "win32" else
                                "darwin" if sys.platform == "darwin" else "linux")
        url = STEAMCMD_URLS[platform]
        response = request_with_retry("GET", url, operation_name="Download SteamCMD", timeout=30)

        target_dir = os.path.join(base_dir, "steamcmd")
        os.makedirs(target_dir, exist_ok=True)

        if platform == "win32":
            archive = zipfile.ZipFile(io.BytesIO(response.content))
            archive.extractall(target_dir)
            exe_path = os.path.join(target_dir, "steamcmd.exe")
        else:
            with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
                safe = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
                archive.extractall(target_dir, **safe)
            exe_path = os.path.join(target_dir, "steamcmd.sh")
            if os.path.exists(exe_path):
                os.chmod(exe_path, os.stat(exe_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if not os.path.exists(exe_path):
            raise FileNotFoundError(f"{os.path.basename(exe_path)} not found after extraction.")
        return exe_path
