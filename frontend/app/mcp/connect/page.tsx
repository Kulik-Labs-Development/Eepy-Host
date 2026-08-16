// Connection wizard route - renders the Phase 5 MCPConnectionWizard for a given template
'use client';

import { Suspense, useState, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';
import MCPConnectionWizard from '../../../src/components/MCPConnectionWizard';

function MCPConnectContent() {
  const searchParams = useSearchParams();
  const templateId = searchParams.get('template_id') || 'happyfox';
  const [wizardOpen, setWizardOpen] = useState(true);

  const handleClose = useCallback(() => setWizardOpen(false), []);

  if (!wizardOpen) {
    return (
      <div className="p-8 font-mono bg-void min-h-screen text-white flex items-center justify-center">
        <div className="text-center text-surface-light/75">
          <p className="mb-4">Connection flow closed.</p>
          <a href="/mcp/library" className="text-eepy-lavender hover:text-eepy-peach underline">
            Back to MCP Library
          </a>
        </div>
      </div>
    );
  }

  return <MCPConnectionWizard templateId={templateId} onClose={handleClose} />;
}

export default function MCPConnectPage() {
  return (
    <Suspense
      fallback={
        <div className="p-8 font-mono bg-void min-h-screen text-white flex items-center justify-center">
          <div className="text-center text-surface-light/75">Loading...</div>
        </div>
      }
    >
      <MCPConnectContent />
    </Suspense>
  );
}
