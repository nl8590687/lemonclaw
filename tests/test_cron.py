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
channels.device.crontab unit tests

Covers weekday matching semantics, field validation and last_run_at
persistence. Every test uses an isolated temporary sqlite db.
"""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import channels.device.crontab as cron_mod
import dao.db as _db
from channels.device.crontab import CronTaskManager, parse_cron, validate_cron


SATURDAY = datetime(2026, 10, 24, 9, 0)
SUNDAY = datetime(2026, 10, 25, 9, 0)
MONDAY = datetime(2026, 10, 26, 9, 0)
TUESDAY = datetime(2026, 10, 27, 9, 0)
WEDNESDAY = datetime(2026, 10, 28, 9, 0)
FRIDAY = datetime(2026, 10, 30, 9, 0)


class _FakeClock:
    """Deterministic clock used to drive CronScheduler._loop in tests."""

    def __init__(self, times):
        self.times = times
        self.index = 0

    def now(self):
        return self.times[self.index]


class TestCronExpression(unittest.TestCase):
    def test_weekday_only_does_not_run_every_day(self):
        expr = parse_cron("0 9 * * 1")
        self.assertTrue(expr.matches(MONDAY))
        self.assertFalse(expr.matches(SATURDAY))
        self.assertFalse(expr.matches(SUNDAY))

    def test_weekday_range(self):
        expr = parse_cron("0 9 * * 1-5")
        self.assertTrue(expr.matches(MONDAY))
        self.assertFalse(expr.matches(SATURDAY))
        self.assertFalse(expr.matches(SUNDAY))

    def test_sunday_accepts_zero_and_seven(self):
        self.assertTrue(parse_cron("0 9 * * 0").matches(SUNDAY))
        self.assertTrue(parse_cron("0 9 * * 7").matches(SUNDAY))

    def test_day_of_month_only(self):
        expr = parse_cron("0 9 15 * *")
        self.assertTrue(expr.matches(datetime(2026, 10, 15, 9, 0)))
        self.assertFalse(expr.matches(datetime(2026, 10, 16, 9, 0)))

    def test_single_numeric_field_is_not_treated_as_open_ended_range(self):
        expr = parse_cron("5 9 * * *")
        self.assertTrue(expr.matches(datetime(2026, 10, 24, 9, 5)))
        self.assertFalse(expr.matches(datetime(2026, 10, 24, 9, 6)))
        self.assertEqual(expr.weekday, set(range(7)))

    def test_every_minute(self):
        expr = parse_cron("* * * * *")
        self.assertTrue(expr.matches(datetime(2026, 10, 24, 0, 0)))
        self.assertTrue(expr.matches(datetime(2026, 10, 24, 23, 59)))

    def test_minute_step(self):
        expr = parse_cron("*/15 * * * *")
        for minute in (0, 15, 30, 45):
            with self.subTest(minute=minute):
                self.assertTrue(expr.matches(datetime(2026, 10, 26, 9, minute)))
        self.assertFalse(expr.matches(datetime(2026, 10, 26, 9, 5)))

    def test_minute_list(self):
        expr = parse_cron("0,30 * * * *")
        self.assertTrue(expr.matches(datetime(2026, 10, 26, 9, 0)))
        self.assertTrue(expr.matches(datetime(2026, 10, 26, 9, 30)))
        self.assertFalse(expr.matches(datetime(2026, 10, 26, 9, 15)))

    def test_hour_range(self):
        expr = parse_cron("0 9-17 * * *")
        self.assertTrue(expr.matches(datetime(2026, 10, 26, 9, 0)))
        self.assertTrue(expr.matches(datetime(2026, 10, 26, 17, 0)))
        self.assertFalse(expr.matches(datetime(2026, 10, 26, 8, 0)))
        self.assertFalse(expr.matches(datetime(2026, 10, 26, 18, 0)))

    def test_day_of_month_list(self):
        expr = parse_cron("0 0 1,15 * *")
        self.assertTrue(expr.matches(datetime(2026, 10, 1, 0, 0)))
        self.assertTrue(expr.matches(datetime(2026, 10, 15, 0, 0)))
        self.assertFalse(expr.matches(datetime(2026, 10, 2, 0, 0)))

    def test_month_restriction(self):
        expr = parse_cron("0 0 * 12 *")
        self.assertTrue(expr.matches(datetime(2026, 12, 1, 0, 0)))
        self.assertFalse(expr.matches(datetime(2026, 11, 1, 0, 0)))

    def test_weekday_range_including_sunday_alias(self):
        expr = parse_cron("0 9 * * 5-7")
        self.assertTrue(expr.matches(FRIDAY))
        self.assertTrue(expr.matches(SATURDAY))
        self.assertTrue(expr.matches(SUNDAY))
        self.assertFalse(expr.matches(MONDAY))

    def test_both_restricted_is_or(self):
        expr = parse_cron("0 9 15 * 1")
        self.assertTrue(expr.matches(datetime(2026, 10, 15, 9, 0)))
        self.assertTrue(expr.matches(MONDAY))
        self.assertFalse(expr.matches(SATURDAY))

    def test_next_run_skips_to_monday(self):
        expr = parse_cron("0 9 * * 1")
        self.assertEqual(expr.next_run(datetime(2026, 10, 24, 10, 0)), MONDAY)

    def test_next_run_rolls_over_to_next_day(self):
        expr = parse_cron("59 23 * * *")
        self.assertEqual(
            expr.next_run(datetime(2026, 10, 26, 23, 59, 30)),
            datetime(2026, 10, 27, 23, 59),
        )

    def test_next_run_respects_day_of_month(self):
        expr = parse_cron("0 0 29 2 *")
        self.assertEqual(
            expr.next_run(datetime(2028, 2, 28, 0, 0)),
            datetime(2028, 2, 29, 0, 0),
        )

    def test_range_with_step(self):
        expr = parse_cron("0 9 * * 1-5/2")
        self.assertTrue(expr.matches(MONDAY))
        self.assertFalse(expr.matches(TUESDAY))
        self.assertTrue(expr.matches(WEDNESDAY))
        self.assertTrue(expr.matches(FRIDAY))

    def test_presets_map_to_standard_expressions(self):
        expected = {
            "@yearly": "0 0 1 1 *",
            "@annually": "0 0 1 1 *",
            "@monthly": "0 0 1 * *",
            "@weekly": "0 0 * * 0",
            "@daily": "0 0 * * *",
            "@hourly": "0 * * * *",
            "@minutely": "* * * * *",
        }
        for preset, expression in expected.items():
            with self.subTest(preset=preset):
                self.assertEqual(parse_cron(preset).expression, expression)

    def test_preset_is_case_insensitive(self):
        self.assertEqual(parse_cron("@DAILY").expression, "0 0 * * *")

    def test_weekly_preset_runs_on_sunday(self):
        expr = parse_cron("@weekly")
        self.assertTrue(expr.matches(datetime(2026, 10, 25, 0, 0)))
        self.assertFalse(expr.matches(datetime(2026, 10, 26, 0, 0)))

    def test_extra_whitespace_is_tolerated(self):
        expr = parse_cron("  0\t9   *  * 1  ")
        self.assertTrue(expr.matches(MONDAY))
        self.assertFalse(expr.matches(TUESDAY))

    def test_invalid_expressions_are_rejected(self):
        for expression in [
            "0 9 * *",
            "0 9 * * * *",
            "60 * * * *",
            "0 24 * * *",
            "0 0 0 * *",
            "0 0 * 13 *",
            "0 0 * * 8",
            "*/0 * * * *",
            "5-1 * * * *",
            "1,,2 * * * *",
            "a * * * *",
            "* * * * mon",
        ]:
            with self.subTest(expression=expression):
                valid, _ = validate_cron(expression)
                self.assertFalse(valid)


class TestCronMarkRun(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        _db._global_db_path = Path(self._tmpdir) / "test.db"

    def tearDown(self):
        _db._global_db_path = None

    def test_fire_records_last_run_at(self):
        manager = CronTaskManager(on_trigger=lambda text, images, context: "event-id")
        task = manager.create_task("ping", "0 9 * * 1")
        self.assertIsNone(manager.get_task(task.task_id).last_run_at)

        manager.scheduler._fire(task)

        stored = manager.get_task(task.task_id)
        self.assertIsNotNone(stored.last_run_at)
        self.assertIsNotNone(task.last_run_at)

    def test_failed_fire_does_not_record_last_run_at(self):
        def boom(text, images, context):
            raise RuntimeError("publish failed")

        manager = CronTaskManager(on_trigger=boom)
        task = manager.create_task("ping", "0 9 * * *")

        manager.scheduler._fire(task)

        self.assertIsNone(manager.get_task(task.task_id).last_run_at)


class TestCronScheduler(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        _db._global_db_path = Path(self._tmpdir) / "test.db"

    def tearDown(self):
        _db._global_db_path = None

    def test_check_and_run_only_fires_matching_tasks(self):
        calls = []

        def trigger(text, images, context):
            calls.append((text, context))
            return "event-id"

        manager = CronTaskManager(on_trigger=trigger)
        monday_task = manager.create_task("monday", "0 9 * * 1")
        manager.create_task("daily", "0 9 * * *")

        manager.scheduler._check_and_run(SATURDAY)
        self.assertEqual([text for text, _ in calls], ["daily"])

        calls.clear()
        manager.scheduler._check_and_run(MONDAY)
        self.assertEqual(sorted(text for text, _ in calls), ["daily", "monday"])
        monday_context = next(ctx for text, ctx in calls if text == "monday")
        self.assertEqual(monday_context["source"], "cron")
        self.assertEqual(monday_context["task_id"], monday_task.task_id)
        self.assertEqual(monday_context["cron_expression"], "0 9 * * 1")

    def test_check_and_run_skips_disabled_task(self):
        calls = []
        manager = CronTaskManager(on_trigger=lambda text, images, context: calls.append(text))
        task = manager.create_task("disabled", "0 9 * * *")
        task.enabled = False

        manager.scheduler._check_and_run(SATURDAY)

        self.assertEqual(calls, [])
        self.assertIsNone(manager.get_task(task.task_id).last_run_at)

    def test_one_failure_does_not_block_other_tasks(self):
        calls = []

        def trigger(text, images, context):
            calls.append(text)
            if text == "boom":
                raise RuntimeError("publish failed")
            return "event-id"

        manager = CronTaskManager(on_trigger=trigger)
        broken = manager.create_task("boom", "0 9 * * *")
        healthy = manager.create_task("ok", "0 9 * * *")

        manager.scheduler._check_and_run(SATURDAY)

        self.assertEqual(calls, ["boom", "ok"])
        self.assertIsNone(manager.get_task(broken.task_id).last_run_at)
        self.assertIsNotNone(manager.get_task(healthy.task_id).last_run_at)

    def test_fire_without_callback_does_not_record_last_run(self):
        manager = CronTaskManager()
        task = manager.create_task("ping", "0 9 * * *")

        manager.scheduler._fire(task)

        self.assertIsNone(manager.get_task(task.task_id).last_run_at)

    def test_loop_fires_once_per_minute(self):
        calls = []
        manager = CronTaskManager(
            on_trigger=lambda text, images, context: calls.append(text) or "event-id"
        )
        manager.create_task("ping", "* * * * *")
        scheduler = manager.scheduler
        clock = _FakeClock([
            datetime(2026, 10, 24, 9, 0, 0),
            datetime(2026, 10, 24, 9, 0, 30),
            datetime(2026, 10, 24, 9, 1, 0),
        ])

        def fake_wait(timeout=None):
            clock.index += 1
            if clock.index >= len(clock.times):
                scheduler._running = False
            return False

        scheduler._stop_event = MagicMock()
        scheduler._stop_event.is_set.return_value = False
        scheduler._stop_event.wait.side_effect = fake_wait

        with patch.object(cron_mod, "datetime", SimpleNamespace(now=clock.now)):
            scheduler._running = True
            scheduler._loop()

        self.assertEqual(calls, ["ping", "ping"])

    def test_start_and_stop_lifecycle(self):
        scheduler = CronTaskManager().scheduler
        scheduler._loop = MagicMock()

        scheduler.start()
        self.assertTrue(scheduler._running)
        self.assertIsNotNone(scheduler._thread)

        scheduler.stop()
        self.assertFalse(scheduler._running)


class TestCrontabInputWiring(unittest.TestCase):
    def test_write_message_publishes_scheduled_task_event(self):
        from channels.ins import crontab as ins_mod

        manager = MagicMock()
        bus = MagicMock()
        with patch.object(ins_mod, "get_cron_manager", return_value=manager), \
                patch.object(ins_mod, "get_bus", return_value=bus):
            channel = ins_mod.CrontabInput()
            event_id = channel._write_message(
                "hello", ["https://example.com/a.png"], {"source": "cron"}
            )

        manager.set_on_trigger.assert_called_once_with(channel._write_message)
        bus.publish.assert_called_once_with(
            context={"source": "cron"},
            event_type=ins_mod.EventType.SCHEDULED_TASK,
            content={"text": "hello", "images": ["https://example.com/a.png"]},
            priority=ins_mod.EventPriority.NORMAL,
        )
        self.assertIs(event_id, bus.publish.return_value)

    def test_run_starts_the_shared_manager(self):
        from channels.ins import crontab as ins_mod

        manager = MagicMock()
        with patch.object(ins_mod, "get_cron_manager", return_value=manager):
            channel = ins_mod.CrontabInput()
            channel.run()

        manager.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
