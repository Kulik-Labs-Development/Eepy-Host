"use client";

import React, { useState, useEffect } from 'react';
import { Users, Activity, ShieldAlert, RefreshCw, Loader2, Search, ChevronDown, Trash2 } from 'lucide-react';
import { getApiUrl } from '@/lib/api';

interface PlatformUser {
  id: number;
  username: string;
  email: string;
  full_name: string | null;
  role: string;
  total_requests: number;
  created_at: string;
}

export default function OrganizationPage() {
  const [users, setUsers] = useState<PlatformUser[]>([]);
  const [filteredUsers, setFilteredUsers] = useState<PlatformUser[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatingUserId, setUpdatingUserId] = useState<number | null>(null);
  const [deletingUserId, setDeletingUserId] = useState<number | null>(null);

  async function fetchUsers() {
    setIsLoading(true);
    setError(null);
    try {
      const apiUrl = getApiUrl();
      const response = await fetch(`${apiUrl}/superuser/users`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('eepy_token')}`,
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch users: ${response.statusText}`);
      }

      const data = await response.json();
      setUsers(data);
      setFilteredUsers(data);
    } catch (err: any) {
      setError(err.message);
      console.error("Organization Hub Error:", err);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    fetchUsers();
  }, []);

  useEffect(() => {
    const filtered = users.filter(u =>
      u.username.toLowerCase().includes(searchQuery.toLowerCase()) ||
      u.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (u.full_name && u.full_name.toLowerCase().includes(searchQuery.toLowerCase()))
    );
    setFilteredUsers(filtered);
  }, [searchQuery, users]);

  async function updateRole(userId: number, newRole: string) {
    setUpdatingUserId(userId);
    try {
      const apiUrl = getApiUrl();
      const response = await fetch(`${apiUrl}/superuser/users/${userId}/role?role=${newRole}`, {
        method: 'PATCH',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('eepy_token')}`,
        },
      });

      if (!response.ok) throw new Error("Failed to update role");

      setUsers(prev => prev.map(u => u.id === userId ? { ...u, role: newRole } : u));
      setFilteredUsers(prev => prev.map(u => u.id === userId ? { ...u, role: newRole } : u));
    } catch (err: any) {
      alert(`Error updating role: ${err.message}`);
    } finally {
      setUpdatingUserId(null);
    }
  }

  async function deleteUser(userId: number, username: string) {
    if (!confirm(`Are you absolutely sure you want to purge user ${username} from the void? This action cannot be undone.`)) return;

    setDeletingUserId(userId);
    try {
      const apiUrl = getApiUrl();
      const response = await fetch(`${apiUrl}/superuser/users/${userId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('eepy_token')}`,
        },
      });

      if (!response.ok) throw new Error("Failed to delete user");

      setUsers(prev => prev.filter(u => u.id !== userId));
      setFilteredUsers(prev => prev.filter(u => u.id !== userId));
    } catch (err: any) {
      alert(`Error deleting user: ${err.message}`);
    } finally {
      setDeletingUserId(null);
    }
  }

  const totalPlatformRequests = users.reduce((acc, user) => acc + user.total_requests, 0);

  const roleSelect = (user: PlatformUser) => (
    <div className="relative group/select">
      <select
        value={user.role}
        onChange={(e) => updateRole(user.id, e.target.value)}
        disabled={updatingUserId === user.id}
        className={`appearance-none pl-3 pr-7 py-1.5 text-[11px] uppercase font-pixel font-bold cursor-pointer transition-colors outline-none border-2 bg-night-deep ${
          user.role === 'superuser'
            ? 'text-eepy-lilac border-eepy-lilac/60 bg-eepy-lilac/10'
            : 'text-ink-faint border-night-border'
        } hover:border-eepy-blush disabled:opacity-50 [&>option]:bg-night-deep [&>option]:text-ink`}
      >
        <option value="user">USER</option>
        <option value="superuser">SUPERUSER</option>
      </select>
      <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none opacity-60" />
    </div>
  );

  const deleteButton = (user: PlatformUser, className: string) => (
    <button
      onClick={() => deleteUser(user.id, user.username)}
      disabled={deletingUserId === user.id}
      className={`p-2 text-ink-dim hover:text-eepy-ember transition-colors disabled:opacity-50 ${className}`}
      title="Delete User"
    >
      {deletingUserId === user.id ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
    </button>
  );

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      <header className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-8">
        <div>
          <h2 className="font-pixel font-bold text-2xl sm:text-3xl text-ink text-px-sm">Organization Hub</h2>
          <p className="text-ink-dim font-body text-sm mt-1">Superuser Command Center & Analytics.</p>
        </div>
        <div className="flex items-center gap-3 shrink-0 self-start sm:self-auto">
          <button
            onClick={fetchUsers}
            disabled={isLoading}
            className="btn-icon"
            title="Refresh User List"
          >
            {isLoading ? <Loader2 size={18} className="animate-spin" /> : <RefreshCw size={18} />}
          </button>
          <span className="chip chip-lilac">
            <Activity size={14} className="animate-led shrink-0" />
            Live System Pulse
          </span>
        </div>
      </header>

      {/* Global Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 sm:gap-6 mb-12">
        {[
          { label: 'Total Active Users', value: users.length, icon: <Users size={22} />, tint: 'text-eepy-lilac', cap: "[--cap:theme('colors.eepy.lilac')]" },
          { label: 'Global Request Volume', value: totalPlatformRequests.toLocaleString(), icon: <Activity size={22} />, tint: 'text-eepy-sage', cap: "[--cap:theme('colors.eepy.sage')]" },
          { label: 'System Health', value: 'Optimal', icon: <ShieldAlert size={22} />, tint: 'text-eepy-amber', cap: "[--cap:theme('colors.eepy.amber')]" },
        ].map((stat, i) => (
          <div key={i} className={`panel pixel-caps p-4 sm:p-6 ${stat.cap} hover:border-eepy-blush/50 transition-colors min-w-0`}>
            <div className={`${stat.tint} mb-3`}>{stat.icon}</div>
            <p className="font-pixel text-[11px] uppercase tracking-widest text-ink-dim mb-1">{stat.label}</p>
            <h3 className="font-pixel font-bold text-xl sm:text-2xl text-ink break-all">{stat.value}</h3>
          </div>
        ))}
      </div>

      {/* User Management */}
      <div className="panel overflow-hidden">
        <div className="p-4 sm:p-6 border-b-2 border-night-line flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 bg-night-deep/40">
          <h3 className="font-pixel font-bold text-lg flex items-center gap-2 text-ink shrink-0">
            <Users size={20} className="text-eepy-lilac" /> User Directory
          </h3>
          <div className="relative w-full">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-dim" />
            <input
              type="text"
              placeholder="Search usernames, emails..."
              className="input-pixel pl-9 py-2.5 text-sm"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>
        {error ? (
          <div className="p-12 text-center space-y-4">
            <p className="text-eepy-ember font-body text-sm">{error}</p>
            <button onClick={fetchUsers} className="btn btn-ghost px-4 py-2 text-xs">Try Again</button>
          </div>
        ) : isLoading && users.length === 0 ? (
          <div className="p-12 text-center flex flex-col items-center gap-4">
            <Loader2 size={32} className="text-eepy-lilac animate-spin" />
            <p className="text-ink-faint font-body text-sm italic">Scanning the night for users...</p>
          </div>
        ) : (
          <>
            {/* Desktop table */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left font-body text-sm">
                <thead className="bg-night-deep/40 text-ink-dim uppercase text-[11px] font-pixel tracking-widest">
                  <tr>
                    <th className="px-6 py-4 font-bold">User</th>
                    <th className="px-6 py-4 font-bold">Role</th>
                    <th className="px-6 py-4 font-bold">Email</th>
                    <th className="px-6 py-4 font-bold text-right">Total Requests</th>
                    <th className="px-6 py-4 font-bold text-center w-20">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-night-line">
                  {filteredUsers.map((user) => (
                    <tr key={user.id} className="hover:bg-eepy-blush/5 transition-colors group">
                      <td className="px-6 py-4">
                        <div className="flex flex-col">
                          <span className="font-bold text-ink font-pixel text-[13px] tracking-wide">{user.username}</span>
                          <span className="text-xs text-ink-dim italic truncate max-w-xs">{user.full_name || 'No full name set'}</span>
                        </div>
                      </td>
                      <td className="px-6 py-4">{roleSelect(user)}</td>
                      <td className="px-6 py-4 text-ink-faint break-all">{user.email}</td>
                      <td className="px-6 py-4 text-right font-console text-[16px] text-eepy-sage">{user.total_requests.toLocaleString()}</td>
                      <td className="px-6 py-4 text-center">{deleteButton(user, 'inline-block')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile card list */}
            <div className="md:hidden divide-y divide-night-line">
              {filteredUsers.length === 0 ? (
                <div className="p-8 text-center text-ink-dim font-body text-sm italic">No users match &ldquo;{searchQuery}&rdquo;.</div>
              ) : (
                filteredUsers.map((user) => (
                  <div key={user.id} className="p-4 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <span className="font-bold text-ink block truncate font-pixel text-[13px] tracking-wide">{user.username}</span>
                        <span className="text-xs text-ink-dim italic block truncate">{user.full_name || 'No full name set'}</span>
                      </div>
                      {deleteButton(user, 'shrink-0')}
                    </div>
                    <div className="text-xs text-ink-faint break-all min-w-0">{user.email}</div>
                    <div className="flex items-center justify-between gap-3">
                      {roleSelect(user)}
                      <span className="font-console text-[15px] text-eepy-sage whitespace-nowrap">
                        {user.total_requests.toLocaleString()} req
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
