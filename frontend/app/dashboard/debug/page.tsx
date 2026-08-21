"use client";

import React, { useState, useEffect } from 'react';
import { Terminal, RefreshCw, Loader2 } from 'lucide-react';
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
      case 'INFO': return 'text-eepy-sage';
      case 'WARNING': return 'text-eepy-amber';
      case 'ERROR': return 'text-eepy-ember';
      case 'CRITICAL': return 'text-eepy-ember font-bold animate-blink';
      default: return 'text-ink-faint';
    }
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <header className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-8">
        <div>
          <h2 className="font-pixel font-bold text-2xl sm:text-3xl text-ink text-px-sm flex items-center gap-3">
            <Terminal size={28} className="text-eepy-blush" /> Debug Log
          </h2>
          <p className="text-ink-dim font-body text-sm mt-1">Real-time backend stream. Auto-refreshing every 5s.</p>
        </div>
        <button
          onClick={fetchLogs}
          disabled={isLoading}
          className="btn-icon self-start sm:self-auto"
          title="Force Refresh"
        >
          {isLoading ? <Loader2 size={18} className="animate-spin" /> : <RefreshCw size={18} />}
        </button>
      </header>

      {/* Terminal window */}
      <div className="relative bg-night-deep border-2 border-night-border shadow-pixel-lg overflow-hidden font-console">
        {/* Terminal Header */}
        <div className="bg-night-surface border-b-2 border-night-line px-4 py-2.5 flex items-center justify-between">
          <div className="flex gap-2">
            <div className="w-3 h-3 bg-eepy-ember/70 border border-eepy-ember" />
            <div className="w-3 h-3 bg-eepy-amber/70 border border-eepy-amber" />
            <div className="w-3 h-3 bg-eepy-sage/70 border border-eepy-sage" />
          </div>
          <span className="text-[15px] text-ink-dim uppercase tracking-widest">eepy_backend_console</span>
        </div>

        {/* Terminal Body */}
        <div className="p-3 sm:p-4 h-[60vh] sm:h-[70vh] overflow-y-auto space-y-0.5 text-[16px] leading-relaxed bg-night-deep">
          {error ? (
            <div className="text-eepy-ember text-[16px] p-4 border-2 border-eepy-ember/50 bg-eepy-ember/10">
              [ERROR] {error}
            </div>
          ) : logs.length === 0 && !isLoading ? (
            <div className="text-ink-dim italic text-[16px] p-4">
              No logs captured in buffer yet...
              <span className="text-eepy-sage animate-blink not-italic">▮</span>
            </div>
          ) : (
            <>
              {logs.map((log, i) => (
                <div key={i} className="flex flex-col sm:flex-row sm:gap-3 gap-0.5 text-[16px] leading-relaxed hover:bg-eepy-blush/5 transition-colors px-2 py-0.5 group">
                  <span className="text-ink-dim sm:shrink-0 whitespace-nowrap">
                    [{log.timestamp}] <span className={`${getLevelColor(log.level)} font-bold`}>{log.level}</span>
                  </span>
                  <span className="text-ink-soft break-all min-w-0">{log.message}</span>
                </div>
              ))}
              <div className="px-2 pt-1">
                <span className="text-eepy-sage animate-blink">▮</span>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="flex justify-end">
        <p className="text-[13px] text-ink-dim font-console uppercase tracking-wider">
          Buffer Capacity: 200 entries | Protocol: MemoryLogHandler v1.0
        </p>
      </div>
    </div>
  );
}
