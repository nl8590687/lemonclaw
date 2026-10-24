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

import argparse
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version


def _get_version() -> str:
    try:
        return version("lemonclaw")
    except PackageNotFoundError:
        return '1.1.0'


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='lemonclaw',
        description='Run the LemonClaw personal AI agent.',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {_get_version()}',
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    build_parser().parse_args(argv)

    from config import get_global_config
    from loop import loop_forever, start_event_source

    get_global_config()
    start_event_source()
    loop_forever()


if __name__ == '__main__':
    main()
