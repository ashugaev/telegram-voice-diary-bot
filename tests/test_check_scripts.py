import builtins
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]


class SidecarScriptTests(unittest.TestCase):
    def run_check(self, directory, exit_code=0):
        shim = directory / "make"
        shim.write_text(
            '#!/usr/bin/env python3\nimport json, os, sys\n'
            'print(json.dumps(dict(os.environ)))\n'
            f'sys.exit({exit_code})\n'
        )
        shim.chmod(0o755)
        env = dict(os.environ, SPUR_SESSION_ARTIFACTS_DIR=str(directory),
            PATH=f"{directory}:{os.environ['PATH']}", OPENAI_API_KEY="must-not-leak",
            NOTION_TOKEN="must-not-leak", AI_PROVIDER="anthropic", UNRELATED_SECRET="must-not-leak")
        return subprocess.run(["bash", str(ROOT / "scripts/check-sidecar.sh")],
            cwd=ROOT, env=env, text=True, capture_output=True)

    def test_isolated_credentials_unique_state_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            states = []
            for _ in range(2):
                result = self.run_check(directory)
                self.assertEqual(result.returncode, 0, result.stderr)
                env = json.loads(result.stdout.splitlines()[0])
                self.assertEqual(env["OPENAI_API_KEY"], "test-openai-key")
                self.assertEqual(env["NOTION_TOKEN"], "test-notion-token")
                self.assertEqual(env["TELEGRAM_TOKEN"], "test-token")
                self.assertEqual(env["NOTION_DATABASE_ID"], "test-notion-db")
                self.assertEqual(env["AI_PROVIDER"], "openai")
                self.assertEqual(env["PYTHON_DOTENV_DISABLED"], "1")
                self.assertNotIn("UNRELATED_SECRET", env)
                state = Path(env["BOT_STATE_PATH"])
                self.assertTrue(state.is_relative_to(directory))
                self.assertTrue((state.parent / "offline.log").exists())
                states.append(state)
            self.assertNotEqual(*states)

    def test_failed_make_propagates_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_check(Path(tmp), exit_code=7)
        self.assertEqual(result.returncode, 7)
        self.assertNotIn("Offline validation passed", result.stdout)


class SpeechSmokeScriptTests(unittest.IsolatedAsyncioTestCase):
    def load_script(self):
        spec = importlib.util.spec_from_file_location("speech_smoke_check", ROOT / "scripts/speech-smoke.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    async def test_service_boundary_isolated_env_and_ogg_artifact(self):
        script = self.load_script()
        audio = b"OggS" + bytes(20) + b"OpusHead" + b"audio"
        async def fake_synthesize(text):
            self.assertEqual(text, "Test voice")
            self.assertEqual(os.environ["OPENAI_API_KEY"], "provided-test-key")
            self.assertEqual(os.environ["TELEGRAM_TOKEN"], "test-token")
            self.assertEqual(os.environ["NOTION_TOKEN"], "test-notion-token")
            self.assertEqual(os.environ["NOTION_DATABASE_ID"], "test-notion-db")
            self.assertEqual(os.environ["PYTHON_DOTENV_DISABLED"], "1")
            self.assertEqual(os.environ["AI_PROVIDER"], "openai")
            self.assertIn("speech.", os.environ["BOT_STATE_PATH"])
            return audio
        synthesize = AsyncMock(side_effect=fake_synthesize)
        client = SimpleNamespace(close=AsyncMock())
        module = SimpleNamespace(synthesize=synthesize, client=client)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(sys, "path", list(sys.path)), \
                patch.dict(os.environ, {"SPUR_SESSION_ARTIFACTS_DIR":tmp,
                    "OPENAI_API_KEY":"provided-test-key", "SPEECH_SMOKE_TEXT":"Test voice"}, clear=True), \
                patch.dict(sys.modules, {"services.speech":module}), \
                patch.object(script, "dotenv_values") as dotenv, \
                patch.object(builtins, "__import__", wraps=builtins.__import__) as imports:
            await script.main()
            outputs = list(Path(tmp).glob("speech.*/sample.ogg"))
            self.assertEqual(len(outputs), 1)
            self.assertEqual(outputs[0].read_bytes(), audio)
        synthesize.assert_awaited_once()
        client.close.assert_awaited_once()
        dotenv.assert_not_called()
        self.assertNotIn("bot", [call.args[0] for call in imports.call_args_list])

    async def test_invalid_audio_rejected_and_client_closed(self):
        script = self.load_script()
        client = SimpleNamespace(close=AsyncMock())
        module = SimpleNamespace(synthesize=AsyncMock(return_value=b"invalid"), client=client)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(sys, "path", list(sys.path)), \
                patch.dict(os.environ, {"SPUR_SESSION_ARTIFACTS_DIR":tmp, "OPENAI_API_KEY":"provided-test-key"}, clear=True), \
                patch.dict(sys.modules, {"services.speech":module}):
            with self.assertRaisesRegex(RuntimeError, "not an Ogg Opus"):
                await script.main()
            self.assertFalse(list(Path(tmp).glob("speech.*/sample.ogg")))
        client.close.assert_awaited_once()
