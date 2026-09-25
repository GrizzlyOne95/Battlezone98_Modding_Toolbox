import os


class ContentFixer:
    def __init__(self, logger=None):
        self.logger = logger

    def log(self, msg):
        if self.logger:
            self.logger(msg)

    def build_upload_plan_prompt(self, item_id, game_name, appid, visibility, title, content, preview, auth_mode, manage_owner, change_note):
        mode = f"UPDATE ({item_id})" if item_id.isdigit() and item_id != "0" else "CREATE NEW"
        summary_lines = [
            "Upload Plan",
            f"- Mode: {mode}",
            f"- Game: {game_name} (AppID {appid})",
            f"- Workshop ID: {item_id or '0'}",
            f"- Visibility: {visibility}",
            f"- Title: {title}",
            f"- Content Folder: {os.path.abspath(content)}",
            f"- Preview Image: {os.path.abspath(preview)}",
            f"- Auth: {auth_mode}",
            f"- Manage Owner Field: {manage_owner or '(empty)'}",
            f"- Change Note: {change_note or '(empty)'}",
        ]
        return "\n".join(summary_lines) + "\n\nProceed with upload?"

    def apply_quick_fixes(self, issues, mod_dir, backup_dir=None):
        """Apply the one-to-one ODF fixes the lint attached to ``issues``.

        ``issues`` are ``(path, type, detail, line, fix)``; entries without a
        fix are skipped. The same code as Project > Validation: every line is
        checked before editing, originals go to ``backup_dir``.
        """
        from battlezone.validation.fixes import FixError, apply_fixes

        items = []
        for path, _issue_type, _detail, line, fix in issues:
            if fix:
                items.append((os.path.relpath(path, mod_dir).replace("\\", "/"), line, fix))
        if not items:
            return 0
        try:
            apply_fixes(mod_dir, items, backup_dir)
        except (FixError, OSError) as e:
            self.log(f"Quick fixes not applied: {e}")
            return 0
        return len(items)

    def delete_legacy_files(self, files, backup_dir=None, mod_dir=None):
        """Move legacy files out of the mod into ``backup_dir`` (deleted only when no backup dir is given)."""
        import shutil

        count = 0
        for path in files:
            try:
                if backup_dir:
                    target = self._backup_target(path, backup_dir, mod_dir)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.move(path, target)
                else:
                    os.remove(path)
                count += 1
            except Exception as e:
                self.log(f"Error removing {path}: {e}")
        return count

    @staticmethod
    def _backup_target(path, backup_dir, mod_dir=None):
        """Where ``path`` goes inside ``backup_dir``: its place in the mod when it is in the mod, else its name.

        Never outside ``backup_dir``: a relative path that climbs out ("../..")
        could land back on the original file, or anywhere else.
        """
        backup = os.path.abspath(backup_dir)
        rel = os.path.basename(path)
        try:
            mod = os.fspath(mod_dir) if mod_dir else ""
            # relpath raises ValueError for another drive on Windows
            candidate = os.path.relpath(os.path.abspath(path), os.path.abspath(mod)) if isinstance(mod, str) and mod else ""
        except (TypeError, ValueError):
            candidate = ""
        if candidate and not candidate.startswith(os.pardir) and not os.path.isabs(candidate):
            rel = candidate
        target = os.path.abspath(os.path.join(backup, rel))
        if os.path.commonpath([target, backup]) != backup:
            target = os.path.join(backup, os.path.basename(path))
        return target

    def fix_trn_files(self, files):
        count = 0
        for path in files:
            try:
                # latin-1 maps every byte, so non-ASCII text survives untouched
                with open(path, "r", encoding="latin-1", newline="") as f:
                    content = f.read()
                content = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
                with open(path, "w", encoding="latin-1", newline="") as f:
                    f.write(content)
                count += 1
            except Exception as e:
                self.log(f"Error fixing {path}: {e}")
        return count

    def fix_trn_duplicates(self, files):
        count = 0
        for path in files:
            try:
                with open(path, "r", encoding="latin-1", newline="") as f:
                    lines = f.readlines()

                new_lines = []
                size_found = False
                skip_mode = False

                for line in lines:
                    clean = line.split("//")[0].split("--")[0].strip().lower()
                    if clean == "[size]":
                        if size_found:
                            skip_mode = True
                        else:
                            size_found = True
                            skip_mode = False
                            new_lines.append(line)
                    elif clean.startswith("[") and clean.endswith("]"):
                        skip_mode = False
                        new_lines.append(line)
                    elif not skip_mode:
                        new_lines.append(line)

                with open(path, "w", encoding="latin-1", newline="") as f:
                    f.writelines(new_lines)
                count += 1
            except Exception as e:
                self.log(f"Error fixing {path}: {e}")
        return count
