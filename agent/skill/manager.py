#!/usr/bin/env python
# Copyright 2026 LemonClaw Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Skill 业务层门面

``SkillManager`` 是唯一的技能业务入口；Registry 只做文件扫描/解析/缓存；
DAO 只做纯 SQL；工具与命令都经由 ``SkillManager`` 访问技能；活跃全文仅由
``MemoryMiddleware`` 在每轮模型调用时统一注入。
"""

import hashlib
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from config import get_global_config
from dao.db import get_db_path
from dao.skill import Skill, SkillDAO, ensure_schema

from agent.skill.registry import SkillRegistry

logger = logging.getLogger(__name__)

LOAD_MAX_CHARS = 10000
_ENV_REF_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


# ============ 模块级辅助 ============

def _get_skill_dir() -> str:
    """技能包唯一目录：与 lemonclaw.db 同级的 .lemonclaw/skills/。"""
    skill_dir = get_db_path().parent / "skills"
    skill_dir.mkdir(parents=True, exist_ok=True)
    return str(skill_dir)


def _reload_dotenv() -> None:
    """重新加载 .lemonclaw/.env，拾取用户新增的密钥（仅补充缺失变量，不覆盖已有）。"""
    from dotenv import load_dotenv
    env_path = get_db_path().parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _venv_python(venv_dir: Path) -> str:
    """venv 解释器路径：Windows -> Scripts/python.exe，POSIX -> bin/python。"""
    return str(venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))


def resolve_env_refs(text: str) -> str:
    """将 ${VAR} 替换为 os.environ[VAR]；未设置的变量保留原样并告警。"""
    def _sub(m):
        var = m.group(1)
        val = os.environ.get(var)
        if val is None:
            logger.warning(f"技能引用的环境变量 {var} 未配置")
            return m.group(0)
        return val
    return _ENV_REF_RE.sub(_sub, text)


def _meta_to_skill(meta: dict[str, Any]) -> Skill:
    """registry 元数据 -> Skill（用于 upsert 与查询返回）。"""
    return Skill(
        name=meta["name"],
        version=meta.get("version", ""),
        description=meta.get("description", ""),
        tags=meta.get("tags", []) or [],
        emoji=meta.get("emoji"),
        dir_path=meta.get("dir_path", ""),
        required_envs=meta.get("required_envs", []) or [],
        primary_env=meta.get("primary_env"),
        synced_at=datetime.now(),
    )


# ============ SkillManager ============

class SkillManager:
    """技能业务门面：扫描索引 + 活跃集（LRU）+ 敏感参数门禁 + 依赖安装 + 脚本执行。"""

    def __init__(self):
        ensure_schema()
        cfg = get_global_config()
        self.max_active: int = cfg.MAX_ACTIVE_SKILLS
        self.load_max_chars: int = LOAD_MAX_CHARS
        self.script_timeout: int = cfg.SKILL_SCRIPT_TIMEOUT
        self.pip_index_url: str = cfg.PIP_INDEX_URL
        self.npm_registry: str = cfg.NPM_REGISTRY
        self.registry = SkillRegistry(_get_skill_dir())
        self.dao = SkillDAO()
        self._active: OrderedDict[str, None] = OrderedDict()  # 活跃技能集（LRU 顺序）
        self._sync_to_db()

    # ============ 索引同步 ============

    def _sync_to_db(self) -> None:
        """将 registry 元数据 upsert 进 skills 表，删除文件系统已不存在的技能。"""
        names: set[str] = set()
        for meta in self.registry.list_skills():
            try:
                self.dao.upsert_metadata(_meta_to_skill(meta))
            except Exception as e:
                logger.warning(f"upsert 技能元数据失败 {meta.get('name')}: {e}")
            names.add(meta["name"])
        try:
            self.dao.delete_missing(names)
        except Exception as e:
            logger.warning(f"delete_missing 失败: {e}")

    def reload(self) -> None:
        """热加载：重载 .env + 重扫 + 同步 DB + 清缓存；保留活跃集中仍可用的技能（删除/禁用/缺配置的移出）。"""
        _reload_dotenv()
        self.registry.reload()
        self._sync_to_db()
        for name in list(self._active.keys()):
            if not self.is_available(name):
                del self._active[name]

    # ============ 查询 ============

    def list_skills(self) -> list[Skill]:
        """返回 registry 元数据与 DAO 管理状态合并后的列表。"""
        result: list[Skill] = []
        for meta in self.registry.list_skills():
            skill = _meta_to_skill(meta)
            db = self.dao.get(meta["name"])
            if db:
                skill.enabled = db.enabled
                skill.access_count = db.access_count
                skill.last_access = db.last_access
            result.append(skill)
        return result

    def get_skill(self, name: str) -> Skill | None:
        """获取单个技能（registry 元数据 + DAO 管理状态）。"""
        meta = self.registry.get_metadata(name)
        if not meta:
            return None
        skill = _meta_to_skill(meta)
        db = self.dao.get(name)
        if db:
            skill.enabled = db.enabled
            skill.access_count = db.access_count
            skill.last_access = db.last_access
        return skill

    def is_available(self, name: str) -> bool:
        """可用 = 技能存在 + enabled=1 + required_envs 已配置 +（Node 技能需 node/npm 可用）。
        依赖是否已安装不影响可用性（由 load_skill 懒装）；安装失败由 deps_status 体现。"""
        skill = self.get_skill(name)
        if not skill or not skill.enabled:
            return False
        if not self._envs_satisfied_by_skill(skill):
            return False
        meta = self.registry.get_metadata(name) or {}
        if (meta.get("runtime", {}) or {}).get("node"):
            if not (shutil.which("node") and shutil.which("npm")):
                return False
        return True

    def required_envs_status(self, name: str) -> list[tuple[str, bool]]:
        """返回 [(env_var, is_configured), ...]，供 /skills show 展示（不含值）。"""
        skill = self.get_skill(name)
        if not skill:
            return []
        return [(env, bool(os.environ.get(env))) for env in skill.required_envs]

    def get_skill_summary_text(self) -> str:
        """仅【可用】技能的摘要（可用 = enabled 且 required_envs 已配置且 Node 可用）。供中间件每轮现取。"""
        enabled_set = self.dao.get_enabled_set()
        skills = [s for s in self.registry.list_skills()
                  if s["name"] in enabled_set and self._envs_satisfied(s)]
        if not skills:
            return ""
        lines = ["你拥有以下技能（如需详细指令请调用 load_skill）："]
        for skill in skills:
            name = skill["name"]
            desc = skill.get("description", "")
            tags = skill.get("tags", [])
            emoji = skill.get("emoji", "")
            line = f"- {name}"
            if emoji:
                line = f"- {emoji} {name}"
            if desc:
                line += f": {desc}"
            if tags:
                line += f" (tags: {', '.join(tags)})"
            lines.append(line)
        return "\n".join(lines)

    def _envs_satisfied(self, meta: dict[str, Any]) -> bool:
        """元数据级：required_envs 已配置 + Node 技能需 node/npm。"""
        for env in meta.get("required_envs", []) or []:
            if not os.environ.get(env):
                return False
        if (meta.get("runtime", {}) or {}).get("node"):
            if not (shutil.which("node") and shutil.which("npm")):
                return False
        return True

    def _envs_satisfied_by_skill(self, skill: Skill) -> bool:
        for env in skill.required_envs:
            if not os.environ.get(env):
                return False
        meta = self.registry.get_metadata(skill.name) or {}
        if (meta.get("runtime", {}) or {}).get("node"):
            if not (shutil.which("node") and shutil.which("npm")):
                return False
        return True

    # ============ 活跃生命周期 ============

    def load_skill(self, name: str) -> str:
        """激活技能（加入活跃集，LRU），返回简短确认（不返回全文）。"""
        skill = self.get_skill(name)
        if not skill:
            return f"技能 {name} 不存在，请检查名称"
        if not skill.enabled:
            return f"技能 {name} 已禁用，请先 /skills enable {name}"
        for env in skill.required_envs:
            if not os.environ.get(env):
                return f"技能 {name} 缺少环境变量 {env}，请在 .lemonclaw/.env 配置后 /skills reload"
        meta = self.registry.get_metadata(name) or {}
        if (meta.get("runtime", {}) or {}).get("node"):
            if not (shutil.which("node") and shutil.which("npm")):
                return f"技能 {name} 需要 Node.js，但运行时未安装 node/npm，请在镜像中预装"
        # 依赖未就绪 -> 提示 setup，不安装（P2-6：不在工具调用内同步联网安装）
        ds = self.deps_status(name)
        if ds not in ("无依赖", "已安装"):
            return f"技能 {name} 依赖未就绪（{ds}），请先执行 /skills setup {name}"
        # 已激活 -> 刷新 LRU 顺序
        if name in self._active:
            self._active.move_to_end(name)
            return f"技能 {name} 已处于激活状态"
        # 新增激活，必要时 LRU 淘汰
        self._active[name] = None
        evicted: str | None = None
        if len(self._active) > self.max_active:
            evicted, _ = self._active.popitem(last=False)
        self.dao.increment_access(name, datetime.now())
        msg = f"✅ 已激活技能: {name}"
        desc = meta.get("description", "")
        if desc:
            msg += f"\n📋 {desc}"
        msg += "\n（完整指令已注入上下文，用完可 unload_skill 卸载）"
        if evicted:
            msg += f"\n（已自动卸载最久未活跃的 {evicted} 以腾出名额）"
        return msg

    def unload_skill(self, name: str) -> str:
        """从活跃集移除；未激活返回提示。"""
        if name not in self._active:
            return f"技能 {name} 未激活"
        del self._active[name]
        return f"✅ 已卸载技能: {name}（下一轮不再注入）"

    def build_active_section(self) -> str:
        """供中间件调用：拼装【已加载技能指令】段（每个活跃技能全文，截断到 LOAD_MAX_CHARS）。无活跃返回空串。"""
        if not self._active:
            return ""
        parts = ["【已加载技能指令】（用完可调用 unload_skill 卸载以节省上下文）"]
        for name in self._active:  # LRU 顺序
            content = self.registry.get_full_content(name)
            if content is None:
                continue
            if len(content) > self.load_max_chars:
                half = self.load_max_chars // 2
                content = content[:half] + "\n\n[... 技能内容较长，已截断中间部分 ...]\n\n" + content[-half:]
            parts.append(f"\n## 技能：{name}\n\n{content}")
        return "\n".join(parts)

    def reset_active(self) -> None:
        """清空活跃集（reset_session 调用）。"""
        self._active.clear()

    def is_active(self, name: str) -> bool:
        """技能是否在活跃集中。"""
        return name in self._active

    # ============ 管理 ============

    def enable(self, name: str) -> bool:
        """启用技能，未命中返回 False。"""
        return self.dao.set_enabled(name, True)

    def disable(self, name: str) -> bool:
        """禁用技能，顺带从活跃集移出。未命中返回 False。"""
        ok = self.dao.set_enabled(name, False)
        if ok and name in self._active:
            del self._active[name]
        return ok

    # ============ 依赖安装（P6）============

    def _venv_dir(self, name: str) -> Path:
        """技能 venv 目录：.lemonclaw/venvs/<skill>/。"""
        return get_db_path().parent / "venvs" / name

    def deps_status(self, name: str) -> str:
        """返回依赖状态：无依赖 / 已安装 / 未安装 / 安装失败: <err>。"""
        meta = self.registry.get_metadata(name)
        if not meta:
            return "无依赖"
        runtime = meta.get("runtime", {}) or {}
        if not (runtime.get("python") or runtime.get("node")):
            return "无依赖"
        venv_dir = self._venv_dir(name)
        failed_marker = venv_dir / ".install_failed"
        if failed_marker.exists():
            try:
                err = failed_marker.read_text(encoding="utf-8").strip()
            except Exception:
                err = "未知错误"
            return f"安装失败: {err}"
        if (venv_dir / ".installed").exists():
            return "已安装"
        return "未安装"

    def setup_deps(self, name: str) -> tuple[bool, str]:
        """安装技能依赖（幂等，marker 校验依赖文件 hash）。
        - Python：创建/复用 venv，<venv_python> -m pip install -r <req> -i PIP_INDEX_URL
        - Node：先 shutil.which 检测 node/npm，再 npm install --registry NPM_REGISTRY
        成功写 .installed marker，失败写 .install_failed marker（含错误）。无依赖返回 (True, "无依赖")。"""
        meta = self.registry.get_metadata(name)
        if not meta:
            return False, f"技能 {name} 不存在"
        runtime = meta.get("runtime", {}) or {}
        if not (runtime.get("python") or runtime.get("node")):
            return True, "无依赖"

        venv_dir = self._venv_dir(name)
        venv_dir.mkdir(parents=True, exist_ok=True)

        # Node 依赖
        if runtime.get("node"):
            if not (shutil.which("node") and shutil.which("npm")):
                self._write_failed(venv_dir, "未安装 Node.js / npm")
                return False, "未安装 Node.js / npm，请在镜像中预装"
            skill_dir = Path(meta["dir_path"])
            try:
                subprocess.run(
                    ["npm", "install", "--prefix", str(skill_dir), "--registry", self.npm_registry],
                    check=True, capture_output=True, timeout=600,
                )
            except Exception as e:
                self._write_failed(venv_dir, str(e))
                return False, f"npm install 失败: {e}"

        # Python venv + pip
        if runtime.get("python"):
            try:
                bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
                if not bin_dir.exists():
                    subprocess.run(
                        [sys.executable or "python3", "-m", "venv", str(venv_dir)],
                        check=True, capture_output=True, timeout=300,
                    )
                req = runtime.get("python_req")
                if req:
                    subprocess.run(
                        [_venv_python(venv_dir), "-m", "pip", "install", "-r", req,
                         "-i", self.pip_index_url],
                        check=True, capture_output=True, timeout=600,
                    )
            except Exception as e:
                self._write_failed(venv_dir, str(e))
                return False, f"pip install 失败: {e}"

        # 成功：清失败标记，写 installed marker（含依赖文件 hash）
        (venv_dir / ".install_failed").unlink(missing_ok=True)
        (venv_dir / ".installed").write_text(self._deps_hash(meta), encoding="utf-8")
        return True, "依赖已就绪"

    def _write_failed(self, venv_dir: Path, err: str) -> None:
        try:
            (venv_dir / ".install_failed").write_text(err, encoding="utf-8")
        except Exception:
            pass

    def _deps_hash(self, meta: dict[str, Any]) -> str:
        """依赖文件内容 hash，用于 marker 校验是否需要重装。"""
        runtime = meta.get("runtime", {}) or {}
        h = hashlib.sha256()
        for key in ("python_req", "node_pkg"):
            p = runtime.get(key)
            if p and Path(p).exists():
                h.update(Path(p).read_bytes())
        return h.hexdigest()

    def run_script(self, name: str, script: str, args: str = "") -> str:
        """在技能隔离环境执行脚本（跨平台、无 shell、路径围栏）。"""
        meta = self.registry.get_metadata(name)
        if not meta:
            return f"技能 {name} 不存在"
        # 依赖就绪检查
        ds = self.deps_status(name)
        if ds not in ("无依赖", "已安装"):
            return f"技能 {name} 依赖未就绪（{ds}），请先执行 /skills setup {name}"
        # 路径围栏
        skill_dir = Path(meta["dir_path"])
        script_path = (skill_dir / script).resolve()
        try:
            script_path.relative_to(skill_dir.resolve())
        except ValueError:
            return f"❌ 脚本路径越界，禁止执行：{script}"
        if not script_path.exists():
            return f"❌ 脚本不存在：{script}"

        runtime = meta.get("runtime", {}) or {}
        argv = shlex.split(args)
        try:
            if runtime.get("python"):
                interp = _venv_python(self._venv_dir(name))
                cmd = [interp, str(script_path), *argv]
                proc = subprocess.run(cmd, capture_output=True,
                                      timeout=self.script_timeout, env=os.environ.copy())
            elif runtime.get("node"):
                env = os.environ.copy()
                env["NODE_PATH"] = str(skill_dir / "node_modules")
                cmd = ["node", str(script_path), *argv]
                proc = subprocess.run(cmd, capture_output=True,
                                      timeout=self.script_timeout, cwd=str(skill_dir), env=env)
            else:
                return f"技能 {name} 无运行时（非 Python/Node），无法执行脚本"
        except subprocess.TimeoutExpired:
            return f"❌ 脚本执行超时（{self.script_timeout}s）"
        out = proc.stdout.decode("utf-8", errors="replace")
        err = proc.stderr.decode("utf-8", errors="replace")
        result = out
        if err:
            result += ("\n[stderr]\n" if result else "") + err
        return result.strip()
