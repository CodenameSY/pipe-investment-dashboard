"""Durable state on an isolated Git branch; never print credentials or Git errors."""
import argparse
import os
from pathlib import Path
import subprocess

BRANCH = 'energy-brief-state'

def git(directory, *args, allowed=(0,)):
    result = subprocess.run(['git', '-C', str(directory), '-c', 'user.name=energy-brief-bot',
        '-c', 'user.email=energy-brief@users.noreply.github.com', *args],
        capture_output=True, text=True, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    if result.returncode not in allowed:
        raise RuntimeError('State Git operation failed; delivery stopped (details suppressed for secret safety)')
    return result

def prepare(root, target):
    root, target = Path(root).resolve(), Path(target).resolve()
    if target.parent != root or target.name != '.energy-state' or target.exists():
        raise RuntimeError('Expected a new .energy-state directory directly inside checkout')
    found = git(root, 'ls-remote', '--exit-code', '--heads', 'origin', BRANCH, allowed=(0, 2))
    if found.returncode == 0:
        git(root, 'fetch', 'origin', f'refs/heads/{BRANCH}')
        git(root, 'worktree', 'add', '--detach', str(target), 'FETCH_HEAD')
    else:
        git(root, 'worktree', 'add', '--detach', str(target), 'HEAD')
        git(target, 'switch', '--orphan', BRANCH)
        git(target, 'commit', '--allow-empty', '-m', 'Initialize energy brief state')
        git(target, 'push', 'origin', f'HEAD:refs/heads/{BRANCH}')

def persist_state(path):
    path = Path(path).resolve()
    if path.name != 'state.json' or path.parent.name != '.energy-state':
        raise RuntimeError('Unexpected durable state path')
    git(path.parent, 'add', '--', 'state.json')
    changed = git(path.parent, 'diff', '--cached', '--quiet', allowed=(0, 1))
    if changed.returncode == 1:
        git(path.parent, 'commit', '-m', 'Checkpoint energy brief delivery state')
    # Push even when unchanged: a prior commit may not yet exist remotely.
    git(path.parent, 'push', 'origin', f'HEAD:refs/heads/{BRANCH}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true', required=True)
    args = parser.parse_args()
    prepare(Path.cwd(), Path.cwd() / '.energy-state')
