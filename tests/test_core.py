import os
import sys
import tempfile
import unittest
import subprocess
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from omarchy_synchro.core import SynchroError, apply_restore, collect_plugins, commit_snapshot, parse_allowlist, plugin_seed_plan, restore_plan, save_selection, secret_reason, seed_stage_plan, snapshot, validate_remote, validate_repo_path
from omarchy_synchro.cli import QML_OUTPUT_LIMIT, encode_qml_payload, qml_safe_payload


class SafetyTests(unittest.TestCase):
    def test_qml_output_is_structurally_bounded(self):
        hostile={"error":"<img src='https://example.invalid/track'>" * 10000,"dirtyFiles":["x" * 10000] * 1000}
        encoded=encode_qml_payload(hostile)
        self.assertLessEqual(len(encoded.encode("utf-8")),QML_OUTPUT_LIMIT)
        self.assertLessEqual(len(qml_safe_payload(hostile)["dirtyFiles"]),201)

    def test_qml_untrusted_sinks_are_plain_and_streamed(self):
        project=Path(__file__).resolve().parents[1]
        overlay=(project/"SynchroOverlay.qml").read_text()
        bar=(project/"BarWidget.qml").read_text()
        self.assertNotIn("StdioCollector",overlay)
        self.assertNotIn("StdioCollector",bar)
        for binding in ("text: root.repository;", "text: root.origin ||", "text: root.message;", "text: outputPanel.content ||"):
            line=next(line for line in overlay.splitlines() if binding in line)
            self.assertIn("textFormat: Text.PlainText",line)

    def test_shell_wrapper_resolves_symlink_install(self):
        project=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            link=Path(tmp)/"plugin"
            link.symlink_to(project, target_is_directory=True)
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

    def test_restore_rejects_saved_and_destination_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); home=root/"home"; repo=root/"repo"; outside=root/"outside"
            home.mkdir(); outside.mkdir(); (repo/".git").mkdir(parents=True)
            saved=repo/"portable/home/.config/app.conf"; saved.parent.mkdir(parents=True); saved.write_text("saved")
            (home/".config").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(SynchroError): restore_plan(repo,home)
            (home/".config").unlink(); saved.unlink(); saved.symlink_to(outside/"secret")
            (outside/"secret").write_text("outside")
            with self.assertRaises(SynchroError): restore_plan(repo,home)

    def test_restore_revalidates_paths_before_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); home=root/"home"; repo=root/"repo"; outside=root/"outside"
            home.mkdir(); outside.mkdir(); (repo/".git").mkdir(parents=True)
            saved=repo/"portable/home/.config/app.conf"; saved.parent.mkdir(parents=True); saved.write_text("saved")
            plan=restore_plan(repo,home)
            saved.unlink(); saved.symlink_to(outside/"secret"); (outside/"secret").write_text("outside")
            with self.assertRaises(SynchroError): apply_restore(plan,home,repo)
            self.assertFalse((home/".config/app.conf").exists())

    def test_large_files_never_enter_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); home=root/"home"; repo=root/"repo"
            home.mkdir(); repo.mkdir(); (repo/".git").mkdir(); (repo/"policy").mkdir()
            (repo/"policy/allowlist.tsv").write_text("portable\t.config/large.conf\n")
            source=home/".config/large.conf"; source.parent.mkdir(parents=True); source.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
            summary,changes=snapshot(repo,home,True)
            self.assertEqual(summary["files"],0)
            self.assertFalse((repo/"portable/home/.config/large.conf").exists())

    def test_snapshot_rejects_symlinked_allowlist_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); home=root/"home"; repo=root/"repo"; outside=root/"outside"
            home.mkdir(); repo.mkdir(); outside.mkdir(); (repo/".git").mkdir(); (repo/"policy").mkdir()
            (repo/"policy/allowlist.tsv").write_text("portable\t.config/app.conf\n")
            (home/".config").symlink_to(outside, target_is_directory=True); (outside/"app.conf").write_text("outside")
            with self.assertRaises(SynchroError): snapshot(repo,home,False)

    def test_plugin_manifest_captures_declarations_not_worktrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); home=root/"home"; plugin=home/".config/omarchy/plugins/example.widget"
            plugin.mkdir(parents=True); (plugin/"manifest.json").write_text('{"id":"example.widget","name":"Example","version":"1.2.3"}')
            subprocess.run(["git","init","-q",str(plugin)],check=True)
            subprocess.run(["git","-C",str(plugin),"remote","add","origin","https://github.com/example/widget.git"],check=True)
            shell=home/".config/omarchy/shell.json"
            shell.write_text('{"bar":{"layout":{"left":[],"center":[],"right":[{"id":"example.widget","rate":5}]}},"plugins":[]}')
            plugins=collect_plugins(home,shell)
            self.assertEqual(plugins[0]["source"],"https://github.com/example/widget.git")
            self.assertEqual(plugins[0]["placement"]["settings"],{"rate":5})
            self.assertNotIn("workingTree",plugins[0])

    def test_plugin_seed_is_preview_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); repo=root/"repo"; home=root/"home"; (repo/"manifests").mkdir(parents=True); home.mkdir()
            (repo/"manifests/plugins.json").write_text('{"schema":1,"plugins":[{"id":"example.widget","source":"https://github.com/example/widget.git","enabled":true}]}')
            plan=plugin_seed_plan(repo,home)
            self.assertEqual(plan["mode"],"preview"); self.assertEqual(plan["actions"][0]["state"],"missing")
            self.assertFalse((home/".config").exists())

    def test_snapshot_cli_reports_pending_git_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); home=root/"home"; plugin=root/"plugin"; repo=root/"repo"
            home.mkdir(); plugin.mkdir(); repo.mkdir(); subprocess.run(["git","init","-q","-b","main",str(repo)],check=True)
            (repo/"policy").mkdir(); (repo/"policy/allowlist.tsv").write_text("portable\t.config/app.conf\n")
            for name in ("portable","device","manifests","metadata"): (repo/name).mkdir()
            (repo/"pending.txt").write_text("review me")
            status=__import__('omarchy_synchro.core',fromlist=['repository_status']).repository_status(repo)
            self.assertIn("?? pending.txt",status["dirtyFiles"])

    def test_repository_status_streams_and_bounds_dirty_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)/"repo"; subprocess.run(["git","init","-q","-b","main",str(repo)],check=True)
            for number in range(350): (repo/f"pending-{number:03}.txt").write_text("x")
            status=__import__('omarchy_synchro.core',fromlist=['repository_status']).repository_status(repo)
            self.assertEqual(status["dirtyFileCount"],350)
            self.assertEqual(len(status["dirtyFiles"]),200)
            self.assertTrue(status["dirtyFilesTruncated"])

    def test_commit_stages_only_managed_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)/"repo"; subprocess.run(["git","init","-q","-b","main",str(repo)],check=True)
            subprocess.run(["git","-C",str(repo),"config","user.name","Test"],check=True)
            subprocess.run(["git","-C",str(repo),"config","user.email","test@example.invalid"],check=True)
            (repo/"manifests").mkdir(); (repo/"manifests/plugins.json").write_text('{"schema":1,"plugins":[]}')
            (repo/"unrelated.txt").write_text("do not commit")
            result=commit_snapshot(repo,"Update snapshot")
            self.assertTrue(result["commit"])
            tree=subprocess.run(["git","-C",str(repo),"ls-tree","-r","--name-only","HEAD"],text=True,capture_output=True,check=True).stdout
            self.assertIn("manifests/plugins.json",tree); self.assertNotIn("unrelated.txt",tree)
            self.assertIn("?? unrelated.txt",subprocess.run(["git","-C",str(repo),"status","--short"],text=True,capture_output=True,check=True).stdout)

    def test_seed_restore_stage_is_read_only_and_informative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); repo=root/"repo"; home=root/"home"; home.mkdir(); subprocess.run(["git","init","-q",str(repo)],check=True)
            saved=repo/"portable/home/.config/app.conf"; saved.parent.mkdir(parents=True); saved.write_text("saved")
            report=seed_stage_plan(repo,home,"restore")
            self.assertEqual(report["mode"],"dry-run"); self.assertEqual(report["changes"],1); self.assertTrue(report["lines"])
            self.assertFalse((home/".config").exists())


if __name__ == "__main__": unittest.main()
