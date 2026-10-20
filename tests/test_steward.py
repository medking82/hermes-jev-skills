from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import Mock,patch
from jevkit import steward

class StewardTests(unittest.TestCase):
    def test_fleet_usage_aggregates_metadata_without_private_labels(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'logs').mkdir()
            rows=[dict(ts=100,feature='private-client-fixture-name',status='ok',cost_usd=0.1,input_tokens=2,shadow=True,action='private-fixture-action'),
                  dict(ts=101,feature='video_qa',status='pending',usage_event='attempt',attempt_id='f'*32)]
            (root/'logs/jev-ledger.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            result=steward.usage_totals([root],since=0)
            self.assertEqual(result['totals']['calls'],2)
            self.assertFalse(result['totals']['estimated_cost_complete'])
            self.assertNotIn('private-client-fixture-name',str(result))
            self.assertNotIn('private-fixture-action',str(result))
            self.assertEqual(result['totals']['unresolved_attempts'],1)
            self.assertEqual(result['totals']['unknown_cost_rows'],1)

    def test_refresh_gates_never_execute_installer(self):
        cases=('dirty','ci','tests','no_auto','dry')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);run=Mock()
                p=dict(checkout_at_main=True,checkout_dirty=case=='dirty',installed_matches_checkout=False,matches_main=False)
                if case=='no_auto':(root/'NO_AUTO_INSTALL').write_text('fixture')
                with patch('jevkit.provenance.check_install',return_value=p):
                    state=steward.install_state('a'*40,{'status':'failure' if case=='ci' else 'success'},
                        {'status':'red' if case=='tests' else 'green'},repo=root,home=root,switches=root,
                        git=Mock(),run=run,dry=case=='dry')
                run.assert_not_called();self.assertFalse(state['main_match'])
                self.assertIn('action',state)

    def test_verified_refresh_is_root_only_and_rechecks(self):
        p=dict(checkout_at_main=True,checkout_dirty=False,installed_matches_checkout=False,matches_main=False)
        done={**p,'installed_matches_checkout':True,'matches_main':True}
        with tempfile.TemporaryDirectory() as folder, patch('jevkit.provenance.check_install',side_effect=[p,done]) as inspect:
            run=Mock(return_value=(0,'',''))
            state=steward.install_state('a'*40,{'status':'success'},{'status':'green'},repo=folder,home=folder,switches=folder,git=Mock(),run=run)
            self.assertEqual(inspect.call_count,2);run.assert_called_once()
            self.assertEqual(run.call_args.args[0],['/usr/bin/python3','install.py','--hermes-root-only','--enable','none'])
            self.assertTrue(state['main_match']);self.assertTrue(state['switches_unchanged'])

    def test_verified_refresh_preserves_other_agent_installs_and_profiles(self):
        from test_install import CONFIG, run_installer

        def snapshot(folder):
            return {p.relative_to(folder).as_posix():
                    ('link', str(p.readlink())) if p.is_symlink() else
                    ('file', hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) if p.is_file() else ('dir',)
                    for p in folder.rglob('*')}

        with tempfile.TemporaryDirectory() as temporary:
            user = Path(temporary)
            home = user / '.hermes'
            fixtures = {
                '.hermes/config.yaml': CONFIG,
                '.hermes/jev/state.json': '{"routing":"off"}',
                '.hermes/profiles/other/config.yaml': CONFIG,
                '.hermes/profiles/other/bin/jev': 'existing lane command',
                '.claude/skills/jev-search/SKILL.md': 'existing Claude skill',
                '.claude/agents/jev-lane-small.md': 'existing user agent',
                '.claude/CLAUDE.md': 'existing Claude instructions',
                '.codex/skills/jev/SKILL.md': 'unified Codex entrypoint',
                '.codex/config.toml': 'model = "user-selected"\n',
                '.codex/hooks.json': '{"hooks":{}}',
                '.codex/backups/retired/jev-search/SKILL.md': 'retired skill',
                '.agents/skills/unrelated/SKILL.md': 'unrelated shared skill',
                '.local/bin/jev': 'existing user command',
            }
            for name, content in fixtures.items():
                target = user / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding='utf-8')
            protected = [user / name for name in ('.claude', '.codex', '.agents', '.local')]
            protected.append(home / 'profiles')
            before = [snapshot(folder) for folder in protected]
            config = (home / 'config.yaml').read_bytes()
            reports = []

            def run(argv, *, cwd, timeout, env):
                self.assertEqual(Path(cwd), Path(__file__).resolve().parents[1])
                self.assertEqual(argv[:2], ['/usr/bin/python3', 'install.py'])
                self.assertEqual(Path(env['HERMES_HOME']), home)
                code, report = run_installer(argv[2:], user, hermes_home=home)
                reports.append(report)
                return code, '', ''

            pending = dict(checkout_at_main=True, checkout_dirty=False,
                           installed_matches_checkout=False, matches_main=False)
            done = {**pending, 'installed_matches_checkout': True, 'matches_main': True}
            with patch.object(Path, 'home', return_value=user), \
                    patch('jevkit.provenance.check_install', side_effect=[pending, done]):
                state = steward.install_state('a' * 40, {'status': 'success'}, {'status': 'green'},
                    repo=Path(__file__).resolve().parents[1], home=home, switches=home / 'jev',
                    git=Mock(), run=run)
            self.assertEqual([snapshot(folder) for folder in protected], before)
            self.assertEqual((home / 'config.yaml').read_bytes(), config)
            self.assertEqual(reports[0]['scope'], 'hermes-root-only')
            self.assertEqual(reports[0]['skill_folders'], [])
            self.assertEqual(reports[0]['hermes']['profiles'], 0)
            self.assertEqual((home / 'plugins/hermes-jev/jevkit/steward.py').read_bytes(),
                             Path(steward.__file__).read_bytes())
            self.assertTrue((home / 'bin/jev').exists())
            self.assertEqual(state['action'], 'refreshed')
            self.assertTrue(state['switches_unchanged'])

    def test_provenance_failure_cannot_install(self):
        with tempfile.TemporaryDirectory() as folder, patch('jevkit.provenance.check_install',side_effect=ValueError('fixture invalid identity')):
            run=Mock()
            state=steward.install_state('a'*40,{'status':'success'},{'status':'green'},repo=folder,home=folder,switches=folder,git=Mock(),run=run)
            run.assert_not_called();self.assertFalse(state['main_match'])

    def test_matching_feature_checkout_cannot_claim_main_or_install(self):
        self.assertIsNotNone(steward,'Missing checked stewardship adapter')
        p=dict(checkout_at_main=False,checkout_dirty=False,installed_matches_checkout=True,
               matches_main=False,checkout_sha='f'*40,main_sha='a'*40)
        run=Mock(); git=Mock()
        with tempfile.TemporaryDirectory() as folder, patch('jevkit.provenance.check_install',return_value=p):
            state=steward.install_state('a'*40,{'status':'success'},{'status':'green'},
                repo=Path(folder),home=Path(folder),switches=Path(folder),git=git,run=run)
        run.assert_not_called()
        self.assertFalse(state['main_match'])
        self.assertTrue(state['in_sync'])
        self.assertNotIn('matches main',steward.describe_install(state))
