// My MCP Servers - the user's active connections (unified proxy URL, live
// connection test, disconnect). Sibling nav section: the MCP Library at
// /dashboard/servers/library. Content lives in MCPServersPanel.

import MCPServersPanel from '@/src/components/MCPServersPanel';

export default function MyServersPage() {
  return <MCPServersPanel mode="mine" />;
}
