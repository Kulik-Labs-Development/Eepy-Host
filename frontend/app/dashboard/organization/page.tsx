"use client";

import React from 'react';
import { Users, Server, Activity, ShieldAlert } from 'lucide-react';

export default function OrganizationPage() {
  // In a real app, this data would come from an API call to /api/superuser/users
  const mockUsers = [
    { id: 1, username: '[ROTATED_SUPERUSER_USERNAME]', role: 'superuser', servers: ['GitHub Explorer', 'DB Query Engine'], requests: 12450 },
    { id: 2, username: 'VibeCoder_99', role: 'user', servers: ['GitHub Explorer'], requests: 432 },
    { id: 3, username: 'CyberSleeper', role: 'user', servers: [], requests: 0 },
    { id: 4, username: 'NeonDreamer', role: 'user', servers: ['Secure Vault'], requests: 8912 },
  ];

  const totalPlatformRequests = mockUsers.reduce((acc, user) => acc + user.requests, 0);

  return (
    <div className="space-y-8">
      <header className="flex justify-between items-center mb-8">
        <div>
          <h2 className="text-3xl font-bold font-console text-white">Organization Hub</h2>
          <p className="text-gray-500 font-console text-sm mt-1 italic">Superuser Command Center & Analytics.</p>
        </div>
        <div className="px-4 py-2 bg-void-surface border border-eepy-lavender rounded-xl flex items-center gap-3 font-console shadow-[0_0_15px_rgba(195,177,225,0.2)]">
          <Activity size={18} className="text-eepy-lavender animate-pulse" />
          <span className="text-xs text-gray-400 uppercase tracking-widest">Live System Pulse</span>
        </div>
      </header>

      {/* Global Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
        {[
          { label: 'Total Active Users', value: mockUsers.length, icon: <Users size={24} />, color: 'text-eepy-lavender' },
          { label: 'Global Request Volume', value: totalPlatformRequests.toLocaleString(), icon: <Activity size={24} />, color: 'text-eepy-mint' },
          { label: 'System Health', value: 'Optimal', icon: <ShieldAlert size={24} />, color: 'text-eepy-peach' },
        ].map((stat, i) => (
          <div key={i} className="p-6 bg-void-surface border border-void-border rounded-eepy shadow-xl group hover:border-white transition-all">
            <div className={`${stat.color} mb-3`}>{stat.icon}</div>
            <p className="text-gray-500 font-console text-[10px] uppercase tracking-widest mb-1">{stat.label}</p>
            <h3 className="text-2xl font-bold font-console text-white">{stat.value}</h3>
          </div>
        ))}
      </div>

      {/* User Management Table */}
      <div className="bg-void-surface border border-void-border rounded-eepy shadow-xl overflow-hidden backdrop-blur-sm">
        <div className="p-6 border-b border-void-border flex justify-between items-center bg-void/50">
          <h3 className="font-bold font-console text-lg flex items-center gap-2">
            <Users size={20} className="text-eepy-lavender" /> User Directory
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left font-console text-sm">
            <thead className="bg-void/30 text-gray-500 uppercase text-[10px] tracking-widest">
              <tr>
                <th className="px-6 py-4 font-medium">User</th>
                <th className="px-6 py-4 font-medium">Role</th>
                <th className="px-6 py-4 font-medium">Deployed Servers</th>
                <th className="px-6 py-4 font-medium text-right">Total Requests</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-void-border">
              {mockUsers.map((user) => (
                <tr key={user.id} className="hover:bg-white/5 transition-colors group">
                  <td className="px-6 py-4 font-medium text-white">{user.username}</td>
                  <td className="px-6 py-4">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] uppercase ${
                      user.role === 'superuser' ? 'bg-eepy-lavender/20 text-eepy-lavender border border-eepy-lavender/30' : 'bg-gray-800 text-gray-400'
                    }`}>
                      {user.role}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex gap-1 flex-wrap">
                      {user.servers.length > 0 ? user.servers.map(s => (
                        <span key={s} className="px-2 py-0.5 bg-void border border-void-border text-[10px] text-gray-500 rounded">{s}</span>
                      )) : <span className="text-gray-700 italic text-[10px]">None</span>}
                    </div>
                  </td>
                  <td className="px-6 py-4 text-right font-mono text-eepy-mint">{user.requests.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
