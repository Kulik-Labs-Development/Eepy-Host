"use client";

import React, { useState } from 'react';
import Link from 'next/link';
import { Moon, Lock, User, Loader2 } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { getApiUrl } from '@/lib/api';

export default function LoginPage() {
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');

    try {
      const apiUrl = getApiUrl();
      const response = await fetch(`${apiUrl}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Login failed');
      }

      const data = await response.json();
      login(data.access_token, data.user);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 relative overflow-hidden bg-void">
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-eepy-lavender/5 blur-[120px] rounded-full" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-eepy-mint/5 blur-[120px] rounded-full" />

      <div className="z-10 w-full max-w-md space-y-8">
        <div className="text-center space-y-4">
          <div className="flex justify-center mb-6">
            <div className="p-4 bg-void-surface border border-void-border rounded-eepy shadow-[0_0_20px_rgba(195,177,225,0.1)]">
              <Moon size={32} className="text-eepy-lavender" />
            </div>
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-white">
            Welcome <span className="text-eepy-lavender italic">Back</span>
          </h1>
          <p className="text-gray-500 font-console text-sm">Enter your credentials to wake up.</p>
        </div>

        <form onSubmit={handleLogin} className="bg-void-surface border border-void-border p-8 rounded-eepy shadow-xl space-y-6 backdrop-blur-sm">
          {error && (
            <div className="p-3 bg-red-500/10 border border-red-500/20 text-red-400 text-xs font-console rounded-lg text-center">
              {error}
            </div>
          )}
          <div className="space-y-4">
            <div className="relative">
              <User size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input 
                type="text" 
                placeholder="Username" 
                required
                className="w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl focus:outline-none focus:border-eepy-lavender transition-colors font-console text-sm"
                onChange={(e) => setFormData({...formData, username: e.target.value})}
              />
            </div>
            <div className="relative">
              <Lock size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input 
                type="password" 
                placeholder="Password" 
                required
                className="w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl focus:outline-none focus:border-eepy-lavender transition-colors font-console text-sm"
                onChange={(e) => setFormData({...formData, password: e.target.value})}
              />
            </div>
          </div>

          <button 
            disabled={isLoading}
            className="w-full py-3 bg-eepy-lavender text-void font-bold rounded-xl hover:bg-opacity-90 transition-all transform hover:scale-[1.02] shadow-[0_0_15px_rgba(195,177,225,0.3)] font-console flex items-center justify-center"
          >
            {isLoading ? <Loader2 className="animate-spin mr-2" size={18} /> : 'Wake Up'}
          </button>

          <div className="text-center text-sm text-gray-500 font-console">
            Don't have an account? <Link href="/signup" className="text-eepy-lavender hover:underline">Create one</Link>
          </div>
        </form>
      </div>
    </div>
  );
}
