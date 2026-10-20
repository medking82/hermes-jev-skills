import contextlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from jevkit import provenance


def archive(files):
    data=io.BytesIO()
    with tarfile.open(fileobj=data,mode='w') as tar:
        for name,body in files.items():
            item=tarfile.TarInfo(name);item.size=len(body);tar.addfile(item,io.BytesIO(body))
    return data.getvalue()

class ProvenanceTests(unittest.TestCase):
    @contextlib.contextmanager
    def fixture(self,feature=True,dirty=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo=root/'repo';repo.mkdir();home=root/'home'
            main='1'*40;head='2'*40 if feature else main
            old={'jevkit/a.py':b'value=1\n','hermes/plugin/hermes-jev/__init__.py':b'# plugin\n','skills/jev-demo/SKILL.md':b'# demo\n'}
            current={**old,'jevkit/a.py':b'value=2\n'} if feature else old
            for name,body in current.items():
                path=provenance._installed_path(home,name);assert path is not None
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
            def git(repo,*args):
                if args==('rev-parse','HEAD'):return head.encode()
                if args[0]=='archive':return archive(old if args[1]==main else current)
                if args[0]=='status':return b' M jevkit/a.py' if dirty else b''
                raise AssertionError(args)
            with patch.object(provenance,'_git',side_effect=git):yield repo,home,main,head

    def test_external_skill_inventory_is_bounded_and_does_not_follow_foreign_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'skill';(root/'references').mkdir(parents=True)
            (root/'SKILL.md').write_text('fixture skill')
            (root/'references/safe.md').write_text('fixture reference')
            outside=Path(tmp)/'outside.md';outside.write_text('must not be read')
            (root/'references/foreign.md').symlink_to(outside)
            with patch.object(provenance,'_git',side_effect=OSError('no git fixture')):
                first=provenance.external_skill(root)
                self.assertEqual(first['files'],2)
                self.assertEqual(first['foreign_links'],1)
                self.assertIsNone(first['source_sha'])
                (root/'references/safe.md').write_text('updated fixture reference')
                self.assertNotEqual(first['fingerprint'],provenance.external_skill(root)['fingerprint'])
                self.assertNotIn('must not be read',str(first))

    def test_explicit_shared_home_allows_installer_copied_skill_links(self):
        with self.fixture(feature=False) as (repo,home,main,head):
            child=home.parent/'child';(child/'skills').mkdir(parents=True)
            (child/'skills/jev').symlink_to(home/'skills/jev',target_is_directory=True)
            for name in ('jevkit/a.py','hermes/plugin/hermes-jev/__init__.py'):
                path=provenance._installed_path(child,name);source=provenance._installed_path(home,name)
                assert path is not None and source is not None
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(source.read_bytes())
            self.assertFalse(provenance.check_install(repo,child,main)['installed_matches_checkout'])
            report=provenance.check_install(repo,child,main,shared_homes=[home])
            self.assertTrue(report['installed_matches_checkout'])
            self.assertTrue(report['matches_main'])
            (child/'skills/jev').unlink()
            target=child/'skills/jev/jev-demo/SKILL.md';target.parent.mkdir(parents=True)
            foreign=home.parent/'foreign.md';foreign.write_bytes((home/'skills/jev/jev-demo/SKILL.md').read_bytes())
            target.symlink_to(foreign)
            self.assertFalse(provenance.check_install(repo,child,main,shared_homes=[home])['installed_matches_checkout'])

    def test_matching_feature_install_is_not_published_main(self):
        with self.fixture() as (repo,home,main,head):
            r=provenance.check_install(repo,home,main)
            self.assertTrue(r['installed_matches_checkout']);self.assertFalse(r['installed_matches_main'])
            self.assertFalse(r['checkout_at_main']);self.assertFalse(r['matches_main'])
            self.assertEqual(r['checkout_sha'],head)
            self.assertNotIn('matches main',provenance.describe(r))

    def test_clean_matching_main_is_distinct(self):
        with self.fixture(feature=False) as (repo,home,main,head):
            r=provenance.check_install(repo,home,main)
            self.assertTrue(r['matches_main']);self.assertEqual(r['loaded_runtime'],'unverified')

    def test_dirty_checkout_is_not_verified_main(self):
        with self.fixture(feature=False,dirty=True) as (repo,home,main,head):
            r=provenance.check_install(repo,home,main)
            self.assertTrue(r['installed_matches_main']);self.assertFalse(r['matches_main'])

    def test_missing_skill_cannot_match_install(self):
        with self.fixture(feature=False) as (repo,home,main,head):
            (home/'skills/jev/jev-demo/SKILL.md').unlink()
            r=provenance.check_install(repo,home,main)
            self.assertFalse(r['installed_matches_checkout']);self.assertFalse(r['matches_main'])

    def test_invalid_revision_not_repaired_or_passed_to_git(self):
        with patch.object(provenance,'_git') as git:
            with self.assertRaises(ValueError):provenance.check_install(Path('.'),Path('.'),'main')
            git.assert_not_called()

    def test_unverified_description_is_explicit(self):
        self.assertEqual(provenance.describe(None),'installed provenance unavailable; runtime unverified')
