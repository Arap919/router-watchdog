"""SDK-backed stdio smoke test, using a fake SSH executable and no router."""
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import timedelta


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'Install mcp>=1.20,<2 for stdio integration')
class TestMCPStdio(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_measure_search_and_apply_gate(self):
        await self.run_flow('0')
        await self.run_flow('1')

    async def run_flow(self, capability):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server = pathlib.Path(__file__).resolve().parents[1] / 'tools/xkeen_mcp.py'
        with tempfile.TemporaryDirectory() as folder:
            ssh = pathlib.Path(folder) / 'ssh'
            ssh.write_text('#!' + sys.executable + '\n' + """import json, sys
command = sys.argv[-1]
if command.endswith('--get-config'):
    result = {'config': {'top_n': 7}, 'editable_fields': ['top_n'], 'secret_configured': True}
elif command.endswith('--select-node'):
    selection = json.load(sys.stdin)
    result = {'applied': True, 'selected_after': selection['node'], 'group': 'main'}
elif command.endswith('--update-config'):
    changes = json.load(sys.stdin)
    result = {'updated_fields': sorted(changes), 'cron_sync_required': 'schedule' in changes}
else:
    assert command in ('/opt/bin/router-watchdog --measure-selected --mcp-speed-profile',
                       '/opt/bin/router-watchdog --find-faster --mcp-speed-profile')
    result = {'applied': '--apply' in command,
              'current': {'node': 'A', 'mbps': 80, 'delay_ms': 20},
              'winner': {'node': 'B', 'mbps': 120, 'delay_ms': 30},
              'group': 'main', 'results': [{'node': 'A', 'mbps': 80}, {'node': 'B', 'mbps': 120}]}
print(json.dumps(result))
""")
            ssh.chmod(0o700)
            env = {**os.environ, 'PATH': folder + os.pathsep + os.environ.get('PATH', ''),
                   'XKEEN_SSH_HOST': 'fake-router', 'XKEEN_ALLOW_APPLY': capability}
            params = StdioServerParameters(command=sys.executable, args=[str(server)], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as client:
                    await client.initialize()
                    listed = await client.list_tools()
                    tools = {tool.name: tool for tool in listed.tools}
                    self.assertEqual(set(tools), {'measure_selected_node', 'find_faster_node',
                                                       'get_watchdog_config', 'update_watchdog_config', 'select_measured_node'})
                    self.assertFalse(tools['measure_selected_node'].annotations.readOnlyHint)
                    self.assertNotIn('apply', tools['find_faster_node'].inputSchema.get('properties', {}))
                    for name in ('measure_selected_node', 'find_faster_node'):
                        result = await client.call_tool(name, {})
                        self.assertFalse(result.isError)
                        self.assertEqual(result.structuredContent['current']['mbps'], 80)
                        self.assertFalse(result.structuredContent['applied'])
                    denied = await client.call_tool('select_measured_node', {'node': 'B'})
                    if capability == '0':
                        self.assertTrue(denied.isError)
                        self.assertIn('XKEEN_ALLOW_APPLY', denied.content[0].text)
                    else:
                        self.assertFalse(denied.isError)
                        self.assertEqual(denied.structuredContent['selected_after'], 'B')
                        self.assertTrue(denied.structuredContent['applied'])
                        repeated = await client.call_tool('select_measured_node', {'node': 'B'})
                        self.assertTrue(repeated.isError)
                    config = await client.call_tool('get_watchdog_config', {})
                    self.assertFalse(config.isError)
                    self.assertEqual(config.structuredContent['config'], {'top_n': 7})
                    updated = await client.call_tool('update_watchdog_config', {'changes': {'top_n': 3}})
                    self.assertFalse(updated.isError)
                    self.assertEqual(updated.structuredContent['updated_fields'], ['top_n'])
