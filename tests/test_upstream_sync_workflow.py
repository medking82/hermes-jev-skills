"""Offline checks of the sync trust boundary; no write tokens or hostile hooks."""
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import tempfile
import unittest

try:
    import yaml
except ImportError:
    yaml = None


@unittest.skipIf(yaml is None, 'workflow checks need the existing CI PyYAML dependency')
class UpstreamSyncWorkflowTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / '.github/workflows/codex-upstream-sync.yml'
        self.workflow = yaml.safe_load(path.read_text(encoding='utf-8'))
        self.jobs = self.workflow['jobs']

    def publisher(self):
        self.assertIn('publish', self.jobs, 'publishing must have its own fresh runner')
        return self.jobs['publish']

    def test_validation_keeps_full_checks_and_has_only_read_permissions(self):
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        validate = self.jobs['integrate']
        self.assertEqual(validate['permissions'], {'contents': 'read'})
        scripts = '\n'.join(step.get('run', '') for step in validate['steps'])
        self.assertIn('python -B codex/check.py --full', scripts)
        self.assertNotIn('git push', scripts)
        self.assertNotIn('gh auth', scripts)
        self.assertNotIn('github.token', str(validate))
        self.assertNotIn('secrets.', str(validate))
        self.assertNotIn('GH_TOKEN', str(validate))

    def test_publishing_needs_successful_validation_and_a_trusted_checkout(self):
        publish = self.publisher()
        self.assertEqual(publish['needs'], 'integrate')
        self.assertEqual(publish['if'], "needs.integrate.outputs.changed == 'true'")
        self.assertEqual(publish['runs-on'], 'ubuntu-latest')
        self.assertEqual(publish['permissions'], {'contents': 'write', 'pull-requests': 'write'})
        for job in self.jobs.values():
            checkout = job['steps'][0]
            self.assertEqual(checkout['uses'], 'actions/checkout@v4')
            self.assertEqual(checkout['with']['ref'], '${{ github.sha }}')
            self.assertIs(checkout['with']['persist-credentials'], False)
        self.assertEqual([step['uses'] for step in publish['steps'] if 'uses' in step],
                         ['actions/checkout@v4'])

    def test_only_pinned_commit_data_crosses_the_job_boundary(self):
        self.assertEqual(self.jobs['integrate'].get('outputs'), {
            'changed': '${{ steps.merge.outputs.changed }}',
            'upstream_sha': '${{ steps.merge.outputs.upstream_sha }}',
            'tree_sha': '${{ steps.merge.outputs.tree_sha }}',
        })
        publish = self.publisher()
        prepare = next(step for step in publish['steps'] if step.get('id') == 'prepare')
        self.assertEqual(prepare['env']['UPSTREAM_SHA'], '${{ needs.integrate.outputs.upstream_sha }}')
        self.assertEqual(prepare['env']['TREE_SHA'], '${{ needs.integrate.outputs.tree_sha }}')
        script = prepare['run']
        self.assertIn('[[ "$UPSTREAM_SHA" =~ ^[0-9a-f]{40}$ ]]', script)
        self.assertIn('[[ "$TREE_SHA" =~ ^[0-9a-f]{40}$ ]]', script)
        self.assertIn('git fetch --no-tags upstream "$UPSTREAM_SHA"', script)
        self.assertIn('git merge --no-edit "$UPSTREAM_SHA"', script)
        self.assertIn('test "$(git rev-parse HEAD^{tree})" = "$TREE_SHA"', script)
        self.assertNotIn('${{', script)
        actions = [step.get('uses', '') for job in self.jobs.values() for step in job['steps']]
        self.assertFalse(any(re.search(r'cache|download-artifact|upload-artifact', action) for action in actions))

    def test_publisher_does_not_execute_repository_code_or_read_upstream_pr_text(self):
        publish = self.publisher()
        prepare = next(step for step in publish['steps'] if step.get('id') == 'prepare')['run']
        self.assertLess(prepare.index('git config core.hooksPath /dev/null'), prepare.index('git merge'))
        self.assertLess(prepare.index('cp codex/upstream-pr.md'), prepare.index('git merge'))
        steps = [step for step in publish['steps'] if 'GH_TOKEN' in step.get('env', {})]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]['env']['GH_TOKEN'], '${{ github.token }}')
        self.assertIn('git -c core.hooksPath=/dev/null push --force-with-lease', steps[0]['run'])
        self.assertIn('--body-file "$RUNNER_TEMP/upstream-pr.md"', steps[0]['run'])
        scripts = '\n'.join(step.get('run', '') for step in publish['steps'])
        self.assertNotRegex(scripts, r'(?m)^\s*(python\S*|pip\S*|source|eval|bash|sh)\s')
        self.assertNotIn('codex/check.py', scripts)
        self.assertNotIn('scripts/check_release.py', scripts)

    @unittest.skipIf(os.name == 'nt', 'sync Bash checks run on the supported Unix CI platforms')
    @unittest.skipUnless(shutil.which('bash'), 'Bash syntax check needs bash')
    def test_all_inline_bash_parses_without_execution(self):
        for job in self.jobs.values():
            for step in job['steps']:
                if step.get('shell') == 'bash':
                    with self.subTest(step=step.get('name')):
                        result = subprocess.run(['bash', '--noprofile', '--norc', '-n'],
                            input=step['run'], text=True, capture_output=True)
                        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(os.name == 'nt', 'sync Bash checks run on the supported Unix CI platforms')
    @unittest.skipUnless(shutil.which('bash') and shutil.which('git'), 'local merge check needs Git and Bash')
    def test_fresh_publish_recreates_the_validated_benign_tree_and_keeps_trusted_pr_text(self):
        publish = self.publisher()
        prepare = next(step for step in publish['steps'] if step.get('id') == 'prepare')['run']
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upstream, checkout, runner = (root / name for name in ('upstream', 'checkout', 'runner'))
            upstream.mkdir(); runner.mkdir()
            env = {key: value for key, value in os.environ.items()
                   if key.upper() in ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'PATHEXT', 'HOME', 'USERPROFILE')}
            env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0')

            def git(folder, *args):
                result = subprocess.run(['git', '-c', 'core.hooksPath=' + os.devnull,
                    '-c', 'user.name=Sync Fixture', '-c', 'user.email=sync-fixture@example.invalid', *args],
                    cwd=folder, env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout.strip()

            git(upstream, 'init', '--initial-branch=main', '--template=' + str(runner))
            (upstream / 'codex').mkdir()
            (upstream / 'codex/upstream-pr.md').write_text('trusted baseline PR text\n', encoding='utf-8')
            git(upstream, 'add', '.')
            git(upstream, 'commit', '-m', 'trusted fixture baseline')
            git(root, 'clone', '--template=' + str(runner), upstream.as_posix(), checkout.as_posix())
            (upstream / 'ordinary-update.txt').write_text('benign upstream update\n', encoding='utf-8')
            (upstream / 'codex/upstream-pr.md').write_text('upstream PR text\n', encoding='utf-8')
            git(upstream, 'add', '.')
            git(upstream, 'commit', '-m', 'benign fixture update')
            env.update(UPSTREAM_SHA=git(upstream, 'rev-parse', 'HEAD'),
                       TREE_SHA=git(upstream, 'rev-parse', 'HEAD^{tree}'), RUNNER_TEMP=runner.as_posix())
            script = prepare.replace('https://github.com/kerpopule/hermes-jev-skills.git',
                                     shlex.quote(upstream.as_posix()))
            self.assertNotEqual(script, prepare)
            result = subprocess.run(['bash', '--noprofile', '--norc', '-c', script], cwd=checkout,
                                    env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(git(checkout, 'rev-parse', 'HEAD^{tree}'), env['TREE_SHA'])
            self.assertEqual((runner / 'upstream-pr.md').read_text(encoding='utf-8'), 'trusted baseline PR text\n')
            self.assertEqual((checkout / 'codex/upstream-pr.md').read_text(encoding='utf-8'), 'upstream PR text\n')
