"""Validate skill archives without executing uploaded code or dependency hooks."""

import io
import shutil
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from agent.skill import _get_skill_dir, get_skill_manager
from agent.skill.registry import parse_frontmatter
from agent.workflow import get_workflow_manager
from channels.webui import state
from dao.webui import WebStore

MAX_BYTES = 30 * 1024 * 1024


def stage(data):
    if len(data) > MAX_BYTES:
        raise ValueError("Archive exceeds 30 MiB")
    base = Path(_get_skill_dir())
    tmp = Path(tempfile.mkdtemp(prefix=".upload-", dir=base.parent))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            entries = z.infolist()
            if len(entries) > 2000 or sum(x.file_size for x in entries) > 100 * 1024 * 1024:
                raise ValueError("Archive too large")
            for item in entries:
                path = PurePosixPath(item.filename)
                mode = item.external_attr >> 16
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in item.filename
                    or ":" in item.filename
                    or len(path.parts) > 12
                    or (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                    or item.file_size > max(1, item.compress_size) * 200
                ):
                    raise ValueError("Unsafe archive entry")
                target = tmp.joinpath(*path.parts)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(item) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        roots = [p.parent for p in tmp.glob("SKILL.md")] + [p.parent for p in tmp.glob("*/SKILL.md")]
        if len(roots) != 1:
            raise ValueError("Expected one SKILL.md at root or one top-level folder")
        skill_root = roots[0]
        meta, _ = parse_frontmatter((skill_root / "SKILL.md").read_text(encoding="utf-8"))
        name = meta.get("name", "")
        if not isinstance(meta.get("description"), str) or not meta["description"].strip():
            raise ValueError("Skill description is required")
        if not name or not all(ch.isalnum() or ch in "_-" for ch in name):
            raise ValueError("Invalid skill name")
        # Store preview in the same database; temporary path never comes from the browser.

        token = uuid.uuid4().hex
        WebStore().layout("package:" + token, dict(path=str(skill_root), temp=str(tmp), name=name))
        return dict(
            id=token,
            name=name,
            description=meta.get("description", ""),
            files=[str(p.relative_to(skill_root)) for p in skill_root.rglob("*") if p.is_file()],
            dependencies=(skill_root / "requirements.txt").exists() or (skill_root / "package.json").exists(),
        )
    except BaseException:
        shutil.rmtree(tmp)
        raise


def install(token, replace=False):

    item = WebStore().layout("package:" + token)
    if not item or not Path(item["path"]).is_dir():
        raise ValueError("Upload expired; upload again")
    manager = get_skill_manager()
    existing = manager.get_skill(item["name"])
    target = Path(existing.dir_path) if existing else Path(_get_skill_dir()) / item["name"]
    if target.exists():
        if not replace:
            raise ValueError("Skill exists; explicit replacement required")
        ensure_unused(item["name"])
    base = Path(_get_skill_dir()).resolve()
    if target.resolve().parent != base:
        raise ValueError("Invalid skill directory")
    backup = base.parent / (".backup-" + uuid.uuid4().hex)
    if target.exists():
        target.rename(backup)
    try:
        Path(item["path"]).rename(target)
        manager.reload()
        if manager.get_skill(item["name"]) is None:
            raise ValueError("Skill could not be registered")
    except BaseException:
        if target.exists():
            shutil.rmtree(target)
        if backup.exists():
            backup.rename(target)
        raise
    finally:
        if backup.exists():
            shutil.rmtree(backup)
    if Path(item["temp"]).exists():
        shutil.rmtree(item["temp"])
    return dict(name=item["name"], installed=True)


def ensure_unused(name):

    if state.busy.is_set():
        raise ValueError("Agent busy; retry at the next safe boundary")
    workflows = get_workflow_manager()
    for wf in workflows.list_workflows() if workflows else []:
        if any(name in (n.get("config", {}).get("skills") or []) for n in wf.spec.get("nodes", [])):
            raise ValueError("Skill referenced by workflow: " + wf.name)
    if workflows and workflows.list_runs(status="active"):
        raise ValueError("Workflow running; retry when idle")
    if get_skill_manager().is_active(name):
        get_skill_manager().unload_skill(name)


def delete(name):
    ensure_unused(name)
    manager = get_skill_manager()
    skill = manager.get_skill(name)
    if not skill:
        raise ValueError("Skill not found")
    path = Path(skill.dir_path).resolve()
    if path.parent != Path(_get_skill_dir()).resolve():
        raise ValueError("Invalid skill path")
    shutil.rmtree(path)
    manager.reload()
    return dict(deleted=True)
