import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from contract_web.runtime_manager import RuntimeManager, ROOT

class RuntimeRelocationTests(unittest.TestCase):
    def test_managed_checkout_move_preserves_session_and_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            old={'local':True,'skill_root':'/old/worktree/runtime','password':'private-fixture','url':'http://127.0.0.1:4096','work_root':'/stable/threads','source_root':'/stable/sources'}
            remote={'local':False,'skill_root':'/container/runtime','url':'http://external:4096'}
            path=root/'runtimes.json';path.write_text(json.dumps({'alice':old,'bob':remote}))
            manager=RuntimeManager(SimpleNamespace(store=SimpleNamespace(root=root)),None)
            actual=asyncio.run(manager.config({'username':'alice'}))
            self.assertEqual(actual,{**old,'skill_root':str(ROOT/'runtime')})
            saved=json.loads(path.read_text());self.assertEqual(saved['alice'],actual);self.assertEqual(saved['bob'],remote)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(asyncio.run(manager.config({'username':'bob'})),remote)
