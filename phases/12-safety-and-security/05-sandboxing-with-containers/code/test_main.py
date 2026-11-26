import shlex
import unittest

from main import CONFIGS, SandboxPolicy, docker_argv, lint, mount_src


def sev(cmd):
    return [s for s, _ in lint(shlex.split(cmd))]


class PolicyTests(unittest.TestCase):
    def test_policy_command_has_the_core_flags(self):
        a = docker_argv(SandboxPolicy(), ["true"])
        for flag in ("--read-only", "--rm", "--init"):
            self.assertIn(flag, a)
        self.assertEqual(a[a.index("--network") + 1], "none")
        self.assertEqual(a[a.index("--cap-drop") + 1], "ALL")
        self.assertEqual(a[a.index("--memory") + 1], a[a.index("--memory-swap") + 1])
        self.assertEqual(a[-1], "true")

    def test_policy_command_lints_clean(self):
        self.assertEqual(lint(docker_argv(SandboxPolicy(), ["true"])), [])
        self.assertEqual(lint(docker_argv(SandboxPolicy(runtime="runsc", workdir_writable=False), ["true"])), [])

    def test_read_only_workdir_and_runtime(self):
        a = docker_argv(SandboxPolicy(runtime="runsc", workdir_writable=False), ["true"])
        self.assertTrue(any(x.endswith(",readonly") for x in a))
        self.assertEqual(a[a.index("--runtime") + 1], "runsc")


class LintTests(unittest.TestCase):
    def test_mount_source_parsing(self):
        self.assertEqual(mount_src("/a:/b:ro"), "/a")
        self.assertEqual(mount_src("type=bind,src=/x,dst=/y"), "/x")
        self.assertEqual(mount_src("type=bind,source=/x,target=/y"), "/x")

    def test_each_critical_flag_is_caught(self):
        base = "docker run --network none --read-only --user 1 --cap-drop ALL --security-opt no-new-privileges --memory 1g --pids-limit 9 "
        for extra in ("--privileged", "-v /var/run/docker.sock:/var/run/docker.sock", "--network host",
                      "--pid host", "--cap-add SYS_ADMIN", "--security-opt seccomp=unconfined",
                      "-e GITHUB_TOKEN=x", "-v $HOME/.ssh:/k", "-v /:/host"):
            self.assertIn("critical", sev(base + extra + " img"), extra)

    def test_blog_command_has_no_critical_but_four_high(self):
        s = sev(CONFIGS["copied from a blog"])
        self.assertEqual((s.count("critical"), s.count("high")), (0, 4))

    def test_harmless_env_is_fine(self):
        self.assertEqual(lint(docker_argv(SandboxPolicy(env={"LANG": "C.UTF-8"}), ["true"])), [])


if __name__ == "__main__":
    unittest.main()
