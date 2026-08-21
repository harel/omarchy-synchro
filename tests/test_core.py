import os
import sys
import tempfile
import unittest
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from omarchy_synchro.core import SynchroError, parse_allowlist, restore_plan, save_selection, secret_reason, snapshot, validate_remote, validate_repo_path


class SafetyTests(unittest.TestCase):
    def test_shell_wrapper_resolves_symlink_install(self):
        project=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            link=Path(tmp)/"plugin"
            link.symlink_to(project/"omarchy-shell/harel.omarchy-synchro", target_is_directory=True)
            result=subprocess.run([str(link/"cli.sh"),"--help"],text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_path_rejects_plugin_and_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); plugin=root/"plugin"; plugin.mkdir(); home=root/"home"; home.mkdir()
            for target in (plugin, plugin/"config", home):
                with self.assertRaises(SynchroError): validate_repo_path(target, plugin, home)

    def test_remote_validation(self):
        for valid in ("git@github.com:user/repo.git", "ssh://git@github.com/user/repo.git", "https://github.com/user/repo.git"):
            self.assertEqual(validate_remote(valid), valid)
        for invalid in ("https://user:token@github.com/u/r.git", "https://user@github.com/u/r.git", "git://github.com/u/r", "file:///tmp/r", "https://x/r?token=a"):
            with self.assertRaises(SynchroError): validate_remote(invalid)

    def test_secret_exclusions(self):
        for value in (".ssh/id_ed25519", ".gnupg/private-keys-v1.d/x", ".config/app/.env", ".config/keyring/a", ".config/app/token.json", ".config/omarchy/plugins/x/file"):
            self.assertIsNotNone(secret_reason(__import__('pathlib').PurePosixPath(value)))

    def test_snapshot_isolation_and_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); home=root/"home"; plugin=root/"plugin"; repo=root/"repo"
            home.mkdir(); plugin.mkdir(); repo.mkdir(); (repo/".git").mkdir(); (repo/"policy").mkdir()
            (repo/"policy/allowlist.tsv").write_text("portable\t.config/app\n")
            (home/".config/app").mkdir(parents=True); (home/".config/app/good.conf").write_text("ok")
            (home/".config/app/.env").write_text("SECRET=x")
            (home/".config/app/innocent-name.conf").write_text("api_key=definitely-secret")
            nested=home/".config/app/nested"; nested.mkdir(); (nested/".git").mkdir(); (nested/"tracked").write_text("no")
            summary, changes=snapshot(repo,home,False)
            self.assertEqual(summary["files"],1); self.assertTrue(changes); self.assertFalse((repo/"portable").exists())
            snapshot(repo,home,True)
            self.assertTrue((repo/"portable/home/.config/app/good.conf").exists())
            self.assertFalse((repo/"portable/home/.config/app/.env").exists())
            self.assertFalse((repo/"portable/home/.config/app/innocent-name.conf").exists())
            self.assertFalse((repo/"portable/home/.config/app/nested/tracked").exists())
            self.assertFalse((plugin/"portable").exists())

    def test_restore_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); home=root/"home"; repo=root/"repo"; home.mkdir(); (repo/".git").mkdir(parents=True)
            source=repo/"portable/home/.config/app/config"; source.parent.mkdir(parents=True); source.write_text("x")
            plan=restore_plan(repo,home)
            self.assertEqual(len(plan),1); self.assertFalse((home/".config").exists())


if __name__ == "__main__": unittest.main()
