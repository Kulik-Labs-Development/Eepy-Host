"use client";

import React, { useState, useEffect } from 'react';
import { Terminal, RefreshCw, Loader2, Trash2 } from 'lucide-react';
import { getApiUrl } from '@/lib/api';

interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
}

export default function DebugLogPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchLogs() {
    setIsLoading(true);
    setError(null);
    try {
      const apiUrl = getApiUrl();
      const response = await fetch(`${apiUrl}/superuser/logs`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('eepy_token')}`,
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch logs: ${response.statusText}`);
      }

      const data = await response.json();
      setLogs(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 5000); // Auto-refresh every 5 seconds
    return () => clearInterval(interval);
  }, []);

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'INFO': return 'text-eepy-mint';
      case 'WARNING': return 'text-eepy-peach';
      case 'ERROR': return 'text-red-500';
      case 'CRITICAL': return 'text-red-400 font-bold animate-pulse';
      default: return 'text-gray-400';
    }
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-8">
        <div>
          <h2 className="text-2xl sm:text-3xl font-bold font-console text-white flex items-center gap-3">
            <Terminal size={26} className="text-eepy-lavender sm:hidden" />
            <Terminal size={32} className="text-eepy-lavender hidden sm:block" /> Debug Log
          </h2>
          <p className="text-gray-500 font-console text-sm mt-1 italic">Real-time backend stream. Auto-refreshing every 5s.</p>
        </div>
        <div className="flex items-center gap-3 shrink-0 self-start sm:self-auto">
          <button 
            onClick={fetchLogs}
            disabled={isLoading}
            className="p-2 bg-void-surface border border-void-border rounded-lg text-gray-400 hover:text-eepy-lavender transition-colors"
            title="Force Refresh"
          >
            {isLoading ? <Loader2 size={18} className="animate-spin" /> : <RefreshCw size={18} />}
          </button>
        </div>
      </header>

      <div className="bg-black border-4 border-void-border rounded-eepy shadow-2xl overflow-hidden font-console">
        {/* Terminal Header */}
        <div className="bg-void-surface border-b border-void-border px-4 py-2 flex items-center justify-between">
          <div className="flex gap-2">
            <div className="w-3 h-3 rounded-full bg-red-500/50" />
            <div className="w-3 h-3 rounded-full bg-yellow-500/50" />
            <div className="w-3 h-3 rounded-full bg-green-500/50" />
          </div>
          <span className="text-[10px] text-gray-600 uppercase tracking-widest">eepy_backend_console</span>
        </div>

        {/* Terminal Body */}
        <div className="p-3 sm:p-4 h-[60vh] sm:h-[70vh] overflow-y-auto space-y-1 bg-black/90">
          {error ? (
            <div className="text-red-400 font-console text-sm p-4 border border-red-500/20 bg-red-500/5 rounded-lg">
              [ERROR] {error}
            </div>
          ) : logs.length === 0 && !isLoading ? (
            <div className="text-gray-600 italic text-sm p-4">No logs captured in buffer yet...</div>
          ) : (
            logs.map((log, i) => (
              <div key={i} className="flex flex-col sm:flex-row sm:gap-3 gap-0.5 text-xs leading-relaxed hover:bg-white/5 transition-colors px-2 py-0.5 group">
                <span className="text-gray-600 sm:shrink-0 whitespace-nowrap">
                  [{log.timestamp}] <span className={`${getLevelColor(log.level)} font-bold`}>{log.level}</span>
                </span>
                <span className="text-gray-300 break-all min-w-0">{log.message}</span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="flex justify-end">
        <p className="text-[10px] text-gray-600 font-console italic uppercase tracking-tighter">
          Buffer Capacity: 200 entries | Protocol: MemoryLogHandler v1.0
        </p>
      </div>
    </div>
  );
}
