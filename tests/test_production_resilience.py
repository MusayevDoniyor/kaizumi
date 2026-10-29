"""Tests for production hardening, audio resilience, human confirmation gate, and security."""
import unittest
import asyncio
from unittest.mock import MagicMock, patch

from actions import desktop
from safety import needs_confirmation, issue_confirmation_token, Risk, classify


class ProductionSafetyTest(unittest.TestCase):
    def test_cmd_control_is_high_risk(self):
        self.assertEqual(classify("cmd_control", {"command": "dir"}), Risk.HIGH)

    def test_file_controller_delete_is_high_risk(self):
        self.assertEqual(classify("file_controller", {"action": "delete", "path": "file.txt"}), Risk.HIGH)

    def test_desktop_control_exec_free(self):
        # desktop_control should handle declarative commands safely
        res = desktop.desktop_control({"action": "stats"})
        self.assertIn("Desktop stats", res)

    def test_desktop_task_dispatcher(self):
        res = desktop.desktop_control({"action": "task", "task": "show me my desktop files"})
        self.assertTrue("Desktop" in res or "Contents" in res or "Empty" in res)


class AudioHardwareResilienceTest(unittest.TestCase):
    def test_listen_audio_does_not_crash_when_sounddevice_is_none(self):
        import main
        ui_mock = MagicMock()
        live = main.KaizumiLive(ui_mock)

        # Patch sd to None and ensure _listen_audio doesn't raise
        with patch.object(main, "sd", None):
            async def run():
                task = asyncio.create_task(live._listen_audio())
                await asyncio.sleep(0.05)
                self.assertFalse(task.done())
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            asyncio.run(run())

    def test_play_audio_does_not_crash_when_sounddevice_is_none(self):
        import main
        ui_mock = MagicMock()
        live = main.KaizumiLive(ui_mock)
        live.audio_in_queue = asyncio.Queue()

        with patch.object(main, "sd", None):
            async def run():
                task = asyncio.create_task(live._play_audio())
                live.audio_in_queue.put_nowait(b"\x00" * 100)
                await asyncio.sleep(0.05)
                self.assertFalse(task.done())
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            asyncio.run(run())


class HumanConsentVerificationTest(unittest.TestCase):
    def test_confirm_without_human_approval_is_blocked(self):
        import main
        ui_mock = MagicMock()
        live = main.KaizumiLive(ui_mock)

        tok = issue_confirmation_token("cmd_control", {"command": "dir"})
        # LLM attempts to re-invoke tool with token but human has NOT said yes
        async def run():
            res = await live._dispatch_tool("cmd_control", {"command": "dir", "confirm": True, "confirm_token": tok})
            self.assertTrue("Action blocked: human user has not verbally approved this yet" in str(res.content) or
                            "Permission not granted yet" in str(res.content))

        asyncio.run(run())

    def test_confirm_with_human_approval_proceeds(self):
        import main
        ui_mock = MagicMock()
        live = main.KaizumiLive(ui_mock)

        tok = issue_confirmation_token("cmd_control", {"command": "dir"})
        # Human explicitly says yes
        live._mark_human_confirmed()

        async def run():
            # Mock cmd_control to avoid actually executing
            with patch.dict(live._tool_handlers, {"cmd_control": (lambda a: "Success", 10)}):
                res = await live._dispatch_tool("cmd_control", {"command": "dir", "confirm": True, "confirm_token": tok})
                self.assertEqual(res.content, "Success")

        asyncio.run(run())

    def test_two_pending_requests_approve_one_other_remains_blocked(self):
        """Simulate two pending high-risk requests (Action A & Action B).
        When the human approves Action A, ONLY Action A must execute.
        Action B must remain strictly blocked (neither token nor human flag leaks)."""
        import main
        ui_mock = MagicMock()
        live = main.KaizumiLive(ui_mock)

        # Issue tokens for two separate high-risk actions
        tok_a = issue_confirmation_token("cmd_control", {"command": "dir"})
        tok_b = issue_confirmation_token("file_controller", {"action": "delete", "path": "test.txt"})

        executed = []
        handlers = {
            "cmd_control": (lambda a: executed.append("A") or "Ran A", 10),
            "file_controller": (lambda a: executed.append("B") or "Ran B", 10),
        }

        async def run():
            with patch.dict(live._tool_handlers, handlers):
                # Human verbally approves Action A
                live._mark_human_confirmed()

                # Action A executes with its valid token
                res_a = await live._dispatch_tool(
                    "cmd_control",
                    {"command": "dir", "confirm": True, "confirm_token": tok_a}
                )
                self.assertEqual(res_a.content, "Ran A")
                self.assertEqual(executed, ["A"])

                # Action B is attempted (either with tok_b or forged tok_a)
                # Since human consent was consumed by Action A and reset to False, Action B is blocked!
                res_b = await live._dispatch_tool(
                    "file_controller",
                    {"action": "delete", "path": "test.txt", "confirm": True, "confirm_token": tok_b}
                )
                self.assertTrue(
                    "Action blocked: human user has not verbally approved this yet" in str(res_b.content) or
                    "confirmation required" in str(res_b.content)
                )
                # Ensure Action B was NEVER executed
                self.assertEqual(executed, ["A"])

                # Attempting to replay tok_a against Action B also fails
                res_b_replay = await live._dispatch_tool(
                    "file_controller",
                    {"action": "delete", "path": "test.txt", "confirm": True, "confirm_token": tok_a}
                )
                self.assertEqual(executed, ["A"])

        asyncio.run(run())


class TelegramNullCheckTest(unittest.TestCase):
    def test_telegram_loop_exits_cleanly_if_chat_id_is_none(self):
        import main
        ui_mock = MagicMock()
        live = main.KaizumiLive(ui_mock)
        live.telegram_token = "123:ABC"
        live.telegram_chat = None

        async def run():
            task = asyncio.create_task(live._telegram_loop())
            await asyncio.sleep(0.05)
            # Should have exited cleanly because chat_id is missing
            self.assertTrue(task.done())

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
