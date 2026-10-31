"""Source provenance, data-only packaging and official-only update acceptance."""
import json
from pathlib import Path
import sys
import unittest

from test_codex_sync import GitFixture
import official
import upstream


class OfficialReferenceTests(GitFixture):
    def test_unchanged_source_is_idempotent_and_live_verifiable(self):
        root = self.repo / official.SNAPSHOT
        self.assertNotIn(b"\r\n", (root / "source.json").read_bytes())
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        report = official.refresh(self.repo, upstream=str(self.official))
        self.assertFalse(report["changed"])
        self.assertEqual(official.verify_live(self.repo, upstream=str(self.official))["commit"], report["commit"])
        self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_new_documentation_is_pinned_and_packaged_without_discovery_metadata(self):
        self.write(self.official, "skills/typesafe-ai/references/questions.md", "# Question Design\n")
        self.save(self.official)
        result = official.refresh(self.repo, upstream=str(self.official))
        self.assertTrue(result["changed"])
        self.assertEqual(result["commit"], upstream.git(self.official, "rev-parse", "HEAD"))
        package = official.reference_files(self.repo)
        self.assertNotIn("SKILL.md", package)
        self.assertTrue(all(Path(name).name.lower() != "skill.md" for name in package))
        body = official.source(self.repo, result["commit"])["SKILL.md"].decode().split("---", 2)[2].lstrip()
        self.assertTrue(package["guide.md"].decode().endswith(body))
        self.assertEqual(package["references/questions.md"], b"# Question Design\n")
        self.assertEqual(json.loads(package["source.json"])["commit"], result["commit"])

    def test_local_snapshot_edits_are_not_overwritten(self):
        path = self.repo / official.SNAPSHOT / "SKILL.md"
        path.write_bytes(path.read_bytes() + b"user edits\n")
        with self.assertRaisesRegex(upstream.StopUpdate, "hashes do not match"):
            official.refresh(self.repo, upstream=str(self.official))
        self.assertTrue(path.read_bytes().endswith(b"user edits\n"))

    def test_new_executable_resource_stops_before_replacing_snapshot(self):
        previous = official.checkout(self.repo)[0]
        self.write(self.official, "skills/typesafe-ai/scripts/setup.py", "raise RuntimeError('must not execute')\n")
        self.save(self.official)
        with self.assertRaisesRegex(upstream.StopUpdate, "unsupported"):
            official.refresh(self.repo, upstream=str(self.official))
        self.assertEqual(official.checkout(self.repo)[0], previous)

    def test_new_invocation_policy_is_not_automatically_adopted(self):
        self.write(self.official, "skills/typesafe-ai/agents/openai.yaml", "policy:\n  allow_implicit_invocation: true\n")
        self.save(self.official)
        with self.assertRaisesRegex(upstream.StopUpdate, "unsupported"):
            official.refresh(self.repo, upstream=str(self.official))

    def test_git_link_mode_is_rejected_without_following_it(self):
        blob = upstream.git(self.official, "rev-parse", "HEAD:skills/typesafe-ai/SKILL.md")
        upstream.git(self.official, "update-index", "--add", "--cacheinfo", "120000," + blob + ",skills/typesafe-ai/references/link.md")
        upstream.git(self.official, "commit", "-m", "Synthetic link mode")
        with self.assertRaisesRegex(upstream.StopUpdate, "linked"):
            official.refresh(self.repo, upstream=str(self.official))

    def test_executable_markdown_mode_is_rejected(self):
        upstream.git(self.official, "update-index", "--chmod=+x", "skills/typesafe-ai/SKILL.md")
        upstream.git(self.official, "commit", "-m", "Synthetic executable mode")
        with self.assertRaisesRegex(upstream.StopUpdate, "executable"):
            official.refresh(self.repo, upstream=str(self.official))

    def test_oversized_reference_is_rejected_before_adoption(self):
        self.write(self.official, "skills/typesafe-ai/references/large.md", "x" * (official.MAX_FILE + 1))
        self.save(self.official)
        with self.assertRaisesRegex(upstream.StopUpdate, "size limit"):
            official.refresh(self.repo, upstream=str(self.official))

    def test_changed_license_requires_manual_review(self):
        self.write(self.official, "skills/typesafe-ai/LICENSE", "Different license\n")
        self.save(self.official)
        with self.assertRaisesRegex(upstream.StopUpdate, "license changed"):
            official.refresh(self.repo, upstream=str(self.official))

    def test_history_rewrite_is_not_accepted(self):
        previous = official.checkout(self.repo)[0]
        upstream.git(self.official, "checkout", "--orphan", "rewritten")
        upstream.git(self.official, "add", ".")
        upstream.git(self.official, "commit", "-m", "Synthetic rewritten root")
        upstream.git(self.official, "branch", "-f", "main", "HEAD")
        with self.assertRaises(upstream.StopUpdate):
            official.refresh(self.repo, upstream=str(self.official))
        self.assertEqual(official.checkout(self.repo)[0], previous)

    def test_official_only_update_is_committed_by_the_fork_sync(self):
        self.write(self.official, "skills/typesafe-ai/references/new.md", "# Official Update\n")
        self.save(self.official)
        data = self.sync()
        self.assertEqual(data["changed"], "true")
        self.assertEqual(data["upstream"], self.base)
        self.assertEqual(data["official"], upstream.git(self.official, "rev-parse", "HEAD"))
        self.assertEqual(official.at_revision(self.repo, data["head"])[0]["commit"], data["official"])

    def test_path_traversal_nested_skill_and_reserved_names_are_rejected(self):
        for name in ("../SKILL.md", "references/../../x.md", "references/SKILL.md", "references/CON.md", "references/a\\b.md"):
            with self.subTest(path=name):
                self.assertFalse(official.allowed(name))
