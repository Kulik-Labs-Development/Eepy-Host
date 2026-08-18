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
        className={`appearance-none pl-3 pr-7 py-1.5 rounded-full text-[10px] uppercase cursor-pointer transition-all outline-none ${
          user.role === 'superuser' 
            ? 'bg-eepy-lavender/20 text-eepy-lavender border border-eepy-lavender/30' 
            : 'bg-gray-800 text-gray-400 border border-transparent'
        } hover:border-white disabled:opacity-50`}
      >
        <option value="user">USER</option>
        <option value="superuser">SUPERUSER</option>
      </select>
      <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none opacity-50" />
    </div>
  );

  const deleteButton = (user: PlatformUser, className: string) => (
    <button 
      onClick={() => deleteUser(user.id, user.username)}
      disabled={deletingUserId === user.id}
      className={`p-2 text-gray-500 hover:text-red-400 transition-colors disabled:opacity-50 ${className}`}
      title="Delete User"
    >
      {deletingUserId === user.id ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
    </button>
  );

  return (
    <div className="space-y-8">
      <header className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-8">
        <div>
          <h2 className="text-2xl sm:text-3xl font-bold font-console text-white">Organization Hub</h2>
          <p className="text-gray-500 font-console text-sm mt-1 italic">Superuser Command Center & Analytics.</p>
        </div>
        <div className="flex items-center gap-3 shrink-0 self-start sm:self-auto">
          <button 
            onClick={fetchUsers}
            disabled={isLoading}
            className="p-2 bg-void-surface border border-void-border rounded-lg text-gray-400 hover:text-eepy-lavender transition-colors"
            title="Refresh User List"
          >
            {isLoading ? <Loader2 size={18} className="animate-spin" /> : <RefreshCw size={18} />}
          </button>
          <div className="px-4 py-2 bg-void-surface border border-eepy-lavender rounded-xl flex items-center gap-3 font-console shadow-[0_0_15px_rgba(195,177,225,0.2)]">
            <Activity size={18} className="text-eepy-lavender animate-pulse shrink-0" />
            <span className="text-xs text-gray-400 uppercase tracking-widest whitespace-nowrap">Live System Pulse</span>
          </div>
        </div>
      </header>

      {/* Global Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 sm:gap-6 mb-12">
        {[
          { label: 'Total Active Users', value: users.length, icon: <Users size={24} />, color: 'text-eepy-lavender' },
          { label: 'Global Request Volume', value: totalPlatformRequests.toLocaleString(), icon: <Activity size={24} />, color: 'text-eepy-mint' },
          { label: 'System Health', value: 'Optimal', icon: <ShieldAlert size={24} />, color: 'text-eepy-peach' },
        ].map((stat, i) => (
          <div key={i} className="p-4 sm:p-6 bg-void-surface border border-void-border rounded-eepy shadow-xl group hover:border-white transition-all min-w-0">
            <div className={`${stat.color} mb-3`}>{stat.icon}</div>
            <p className="text-gray-500 font-console text-[10px] uppercase tracking-widest mb-1">{stat.label}</p>
            <h3 className="text-xl sm:text-2xl font-bold font-console text-white break-all">{stat.value}</h3>
          </div>
        ))}
      </div>

      {/* User Management */}
      <div className="bg-void-surface border border-void-border rounded-eepy shadow-xl overflow-hidden backdrop-blur-sm">
        <div className="p-4 sm:p-6 border-b border-void-border flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 bg-void/50">
          <h3 className="font-bold font-console text-lg flex items-center gap-2 shrink-0">
            <Users size={20} className="text-eepy-lavender" /> User Directory
          </h3>
          <div className="relative w-full">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input 
              type="text" 
              placeholder="Search usernames, emails..." 
              className="w-full pl-10 pr-4 py-2 bg-void border border-void-border rounded-xl font-console text-sm focus:border-eepy-lavender transition-colors outline-none text-white"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>
        {error ? (
          <div className="p-12 text-center space-y-4">
            <p className="text-red-400 font-console text-sm">{error}</p>
            <button onClick={fetchUsers} className="px-4 py-2 bg-void border border-void-border rounded-lg text-xs font-console hover:bg-void-border transition-colors">Try Again</button>
          </div>
        ) : isLoading && users.length === 0 ? (
          <div className="p-12 text-center flex flex-col items-center gap-4">
            <Loader2 size={32} className="text-eepy-lavender animate-spin" />
            <p className="text-gray-500 font-console text-sm italic">Scanning the void for users...</p>
          </div>
        ) : (
          <>
            {/* Desktop table */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left font-console text-sm">
                <thead className="bg-void/30 text-gray-500 uppercase text-[10px] tracking-widest">
                  <tr>
                    <th className="px-6 py-4 font-medium">User</th>
                    <th className="px-6 py-4 font-medium">Role</th>
                    <th className="px-6 py-4 font-medium">Email</th>
                    <th className="px-6 py-4 font-medium text-right">Total Requests</th>
                    <th className="px-6 py-4 font-medium text-center w-20">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-void-border">
                  {filteredUsers.map((user) => (
                    <tr key={user.id} className="hover:bg-white/5 transition-colors group">
                      <td className="px-6 py-4">
                        <div className="flex flex-col">
                          <span className="font-medium text-white">{user.username}</span>
                          <span className="text-[10px] text-gray-500 italic truncate max-w-xs">{user.full_name || 'No full name set'}</span>
                        </div>
                      </td>
                      <td className="px-6 py-4">{roleSelect(user)}</td>
                      <td className="px-6 py-4 text-gray-400 break-all">{user.email}</td>
                      <td className="px-6 py-4 text-right font-mono text-eepy-mint">{user.total_requests.toLocaleString()}</td>
                      <td className="px-6 py-4 text-center">{deleteButton(user, 'inline-block')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile card list */}
            <div className="md:hidden divide-y divide-void-border">
              {filteredUsers.length === 0 ? (
                <div className="p-8 text-center text-gray-600 font-console text-sm italic">No users match “{searchQuery}”.</div>
              ) : (
                filteredUsers.map((user) => (
                  <div key={user.id} className="p-4 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <span className="font-medium text-white block truncate">{user.username}</span>
                        <span className="text-[10px] text-gray-500 italic block truncate">{user.full_name || 'No full name set'}</span>
                      </div>
                      {deleteButton(user, 'shrink-0')}
                    </div>
                    <div className="text-xs text-gray-400 break-all min-w-0">{user.email}</div>
                    <div className="flex items-center justify-between gap-3">
                      {roleSelect(user)}
                      <span className="font-mono text-xs text-eepy-mint whitespace-nowrap">
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
