// MCP Library - the browsable catalog of admin-approved integration templates
// (search, Connect wizard, superuser Tool Discovery). Sibling nav section:
// My MCP Servers at /dashboard/servers. Content lives in MCPServersPanel.

import MCPServersPanel from '@/src/components/MCPServersPanel';

export default function MCPLibraryPage() {
  return <MCPServersPanel mode="library" />;
}
