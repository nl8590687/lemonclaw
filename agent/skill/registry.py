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
技能注册表 - 扫描技能目录，维护元数据索引，按需加载全文（带缓存）

技能包格式（OpenClaw 兼容）::

    <name>-<version>/
    ├── SKILL.md        # 主技能文件（YAML frontmatter + markdown，必需）
    ├── _meta.json      # 元数据（可选）
    ├── requirements.txt # Python 依赖清单（可选，检测到则记 runtime.python）
    ├── package.json    # Node 依赖清单（可选，检测到则记 runtime.node）
    └── *.md            # 其他说明文件（按文件名字母序追加到全文）
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """
    解析 Markdown frontmatter

    返回：(元数据字典, 剩余正文)
    """
    frontmatter: dict[str, Any] = {}
    body = content

    # 检查是否有 frontmatter (--- 开头)
    if content.strip().startswith("---"):
        match = re.search(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL | re.MULTILINE)
        if match:
            frontmatter_str = match.group(1)
            body = content[match.end():]
            try:
                frontmatter = yaml.safe_load(frontmatter_str) or {}
            except Exception as e:
                logger.warning(f"解析 frontmatter 失败: {e}")

    return frontmatter, body


class SkillRegistry:
    """技能注册表 - 扫描技能目录，维护元数据索引，按需加载全文（带缓存）。"""

    def __init__(self, skill_dir: str):
        """
        初始化技能注册表

        Args:
            skill_dir: 唯一技能目录（.lemonclaw/skills/）。目录不存在视为空。
        """
        self.skill_dir = Path(skill_dir)
        self.metadata_index: dict[str, dict[str, Any]] = {}
        self.full_content_cache: dict[str, str] = {}
        self.scan()

    def scan(self) -> None:
        """扫描 self.skill_dir 下所有技能包，重建元数据索引。目录不存在视为空。"""
        self.metadata_index.clear()
        if not self.skill_dir.exists():
            return

        for skill_folder in self.skill_dir.iterdir():
            if not skill_folder.is_dir():
                continue

            # 必需文件：SKILL.md
            skill_md = skill_folder / "SKILL.md"
            if not skill_md.exists():
                continue

            # 可选文件：_meta.json
            meta_json = skill_folder / "_meta.json"

            metadata: dict[str, Any] = {}

            # 解析 SKILL.md 的 frontmatter
            try:
                content = skill_md.read_text(encoding="utf-8")
                frontmatter, _ = parse_frontmatter(content)
                metadata.update(frontmatter)
            except Exception as e:
                logger.warning(f"无法解析技能 {skill_folder.name}: {e}")
                continue

            # 加载 _meta.json（如果有）
            if meta_json.exists():
                try:
                    meta_data = json.loads(meta_json.read_text(encoding="utf-8"))
                    if "name" not in metadata and "slug" in meta_data:
                        metadata["name"] = meta_data["slug"]
                    if "version" not in metadata and "version" in meta_data:
                        metadata["version"] = meta_data["version"]
                    metadata["_meta"] = meta_data
                except Exception as e:
                    logger.warning(f"无法解析 _meta.json: {e}")

            # 确保元数据有必要字段
            if "name" not in metadata:
                metadata["name"] = re.sub(r'-[\d.]+$', '', skill_folder.name)
            if "description" not in metadata:
                metadata["description"] = ""
            if "tags" not in metadata:
                metadata["tags"] = []
            if "version" not in metadata:
                m = re.search(r'-([\d.]+)$', skill_folder.name)
                metadata["version"] = m.group(1) if m else "1.0"
            metadata["version"] = str(metadata["version"])

            # emoji: metadata.openclaw.emoji
            emoji = None
            try:
                emoji = metadata.get("metadata", {}).get("openclaw", {}).get("emoji")
            except Exception:
                emoji = None
            metadata["emoji"] = emoji

            # required_envs / primary_env: metadata.openclaw.requires.env / primaryEnv
            required_envs: list[str] = []
            primary_env: str | None = None
            try:
                oc = metadata.get("metadata", {}).get("openclaw", {}) or {}
                required_envs = list(oc.get("requires", {}).get("env", []) or [])
                primary_env = oc.get("primaryEnv")
            except Exception:
                pass
            metadata["required_envs"] = required_envs
            metadata["primary_env"] = primary_env

            # runtime 检测：requirements.txt / package.json
            runtime = {"python": False, "python_req": None, "node": False, "node_pkg": None}
            req_file = skill_folder / "requirements.txt"
            if req_file.exists():
                runtime["python"] = True
                runtime["python_req"] = str(req_file)
            pkg_file = skill_folder / "package.json"
            if pkg_file.exists():
                runtime["node"] = True
                runtime["node_pkg"] = str(pkg_file)
            metadata["runtime"] = runtime

            # 记录目录路径与内容路径
            metadata["dir_path"] = str(skill_folder)
            metadata["content_path"] = str(skill_md)

            # 同名技能后者覆盖前者
            self.metadata_index[metadata["name"]] = metadata

    def get_metadata(self, skill_name: str) -> dict[str, Any] | None:
        """获取技能元数据，不存在返回 None"""
        return self.metadata_index.get(skill_name)

    def get_full_content(self, skill_name: str) -> str | None:
        """按需加载技能全文（带缓存）：SKILL.md 前置 + 其他 *.md 按文件名字母序追加。"""
        if skill_name in self.full_content_cache:
            return self.full_content_cache[skill_name]

        metadata = self.get_metadata(skill_name)
        if not metadata:
            return None
        dir_path = metadata.get("dir_path")
        if not dir_path:
            return None

        skill_dir = Path(dir_path)
        if not skill_dir.exists():
            return None

        parts: list[str] = []
        # 1. SKILL.md（主文件，前置）
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            parts.append(skill_md.read_text(encoding="utf-8"))
        # 2. 其他 *.md（按文件名字母序追加）
        for md_file in sorted(skill_dir.glob("*.md")):
            if md_file.name == "SKILL.md":
                continue
            parts.append(f"\n\n---\n\n# {md_file.name}\n\n{md_file.read_text(encoding='utf-8')}")

        full_content = "\n".join(parts)
        self.full_content_cache[skill_name] = full_content
        return full_content

    def list_skills(self) -> list[dict[str, Any]]:
        """列出所有技能元数据"""
        return list(self.metadata_index.values())

    def get_skill_summary_text(self) -> str:
        """技能摘要（一行式，全部技能）。可用性过滤由 SkillManager 负责。"""
        skills = self.list_skills()
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

    def clear_cache(self) -> None:
        """清空全文缓存"""
        self.full_content_cache.clear()

    def reload(self) -> None:
        """scan + clear_cache（热加载入口）"""
        self.scan()
        self.clear_cache()
