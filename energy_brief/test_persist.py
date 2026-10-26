import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from energy_brief.persist import git, prepare, persist_state


class PersistenceTests(unittest.TestCase):
    def test_state_survives_fresh_checkout_without_changing_main(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            remote, checkout, fresh = root / 'remote.git', root / 'checkout', root / 'fresh'
            subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
            result = subprocess.run(['git', 'clone', str(remote), str(checkout)], capture_output=True)
            if result.returncode and os.name == 'nt' and b'NtCreateDirectoryObject' in result.stderr:
                self.skipTest('Windows sandbox blocks Git local transport; integration runs in Linux CI')
            result.check_returncode()
            (checkout / 'keep.txt').write_text('unchanged', encoding='utf-8')
            git(checkout, 'add', 'keep.txt')
            git(checkout, 'commit', '-m', 'fixture')
            git(checkout, 'push', 'origin', 'HEAD')
            original = git(checkout, 'rev-parse', 'HEAD').stdout.strip()
            prepare(checkout, checkout / '.energy-state')
            state = checkout / '.energy-state/state.json'
            state.write_text(json.dumps({'pending': 'test'}), encoding='utf-8')
            persist_state(state)
            self.assertEqual(original, git(checkout, 'rev-parse', 'HEAD').stdout.strip())
            self.assertEqual('unchanged', (checkout / 'keep.txt').read_text())
            self.assertFalse((state.parent / 'keep.txt').exists())
            subprocess.run(['git', 'clone', str(remote), str(fresh)], check=True, capture_output=True)
            prepare(fresh, fresh / '.energy-state')
            self.assertEqual({'pending': 'test'}, json.loads((fresh / '.energy-state/state.json').read_text()))

    def test_reject_non_state_path(self):
        with self.assertRaises(RuntimeError):
            persist_state(Path('unrelated.json'))


if __name__ == '__main__':
    unittest.main()
