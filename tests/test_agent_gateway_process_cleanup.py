from pathlib import Path
import subprocess
import unittest


class GatewayProcessCleanupTests(unittest.TestCase):
    def test_only_the_target_installed_listener_is_stopped(self):
        source = (Path(__file__).resolve().parents[1] / "scripts/install_agent_gateway_launch_agent.sh").read_text()
        self.assertNotIn("pkill -f 'sidecar_launch.py.*agent-gateway'", source)
        start = source.index("stop_stale_gateway_listener() {")
        function = source[start:source.index("\n}\n", start) + 3]
        # Exercise the actual shell function; kill is mocked, so no process is touched.
        script = function + r'''
PORT=8768
WRAPPER="/installed app/sidecar_launch.py"
lsof() { [ "$*" = "-nP -tiTCP:8768 -sTCP:LISTEN" ] || return 1; printf '101\n102\n103\n'; }
ps() {
  case "$*" in
    *101*) echo "python /installed app/sidecar_launch.py --db-path /db agent-gateway --port 8768" ;;
    *102*) echo "python /candidate/sidecar_launch.py --db-path /candidate/db agent-gateway --port 18868" ;;
    *103*) echo "python /installed app/sidecar_launch.py sidecar-server --port 8768" ;;
  esac
}
kill() { echo "stopped:$*"; }
stop_stale_gateway_listener
'''
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "stopped:101")
