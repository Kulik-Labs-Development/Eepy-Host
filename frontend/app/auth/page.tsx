"use client";

import React, { useState } from 'react';
import { Moon, Lock, User, Mail, Loader2, Eye, EyeOff, Sparkles } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { getApiUrl } from '@/lib/api';
import { useRouter } from 'next/navigation';

export default function AuthPage() {
  const [isLoginMode, setIsLoginMode] = useState(true);
  const [formData, setFormData] = useState({ username: '', email: '', password: '' });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  
  const { login } = useAuth();
  const router = useRouter();

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');
    setSuccess(false);

    try {
      const apiUrl = getApiUrl();
      const endpoint = isLoginMode ? '/auth/login' : '/auth/signup';
      const response = await fetch(`${apiUrl}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!response.ok) {
        const data = await response.json();
        if (Array.isArray(data.detail)) {
          throw new Error(data.detail[0].msg || 'Validation failed');
        }
        throw new Error(data.detail || (isLoginMode ? 'Login failed' : 'Signup failed'));
      }

      const data = await response.json();

      if (isLoginMode) {
        login(data.access_token, data.user);
        router.push('/dashboard');
      } else {
        setSuccess(true);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 relative overflow-hidden bg-void">
      <div className={`absolute top-[-10%] ${isLoginMode ? 'left' : 'right'}[-10%] w-[40%] h-[40%] ${isLoginMode ? 'bg-eepy-lavender/5' : 'bg-eepy-peach/5'} blur-[120px] rounded-full`} />
      <div className={`absolute bottom-[-10%] ${isLoginMode ? 'right' : 'left'}[-10%] w-[40%] h-[40%] ${isLoginMode ? 'bg-eepy-mint/5' : 'bg-eepy-mint/5'} blur-[120px] rounded-full`} />

      <div className="z-10 w-full max-w-md space-y-8">
        <div className="text-center space-y-4">
          <div className="flex justify-center mb-6">
            <div className="p-4 bg-void-surface border border-void-border rounded-eepy shadow-[0_0_20px_rgba(195,177,225,0.1)] relative group">
              <Moon size={32} className={isLoginMode ? "text-eepy-lavender" : "text-eepy-peach"} />
              {!isLoginMode && <Sparkles size={14} className="absolute -top-1 -right-1 text-eepy-mint animate-pulse" />}
            </div>
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-white">
            {isLoginMode ? 'Welcome ' : 'Sync your '} <span className={`${isLoginMode ? 'text-eepy-lavender' : 'text-eepy-peach'} italic`}>{isLoginMode ? 'Back' : 'Vibe'}</span>
          </h1>
          <p className="text-gray-500 font-console text-sm">
            {isLoginMode 
              ? 'Enter your credentials to wake up.' 
              : 'Ready to connect your models to the world?'}
          </p>
        </div>

        {success ? (
          <div className="bg-void-surface border border-eepy-mint/30 p-8 rounded-eepy shadow-xl space-y-6 text-center backdrop-blur-sm animate-in fade-in zoom-in duration-300">
            <div className="flex justify-center mb-4">
              <div className="p-3 bg-eepy-mint/20 rounded-full text-eepy-mint">
                <Sparkles size={32} />
              </div>
            </div>
            <h2 className="text-2xl font-bold text-white font-console">Vibe Synced!</h2>
            <p className="text-gray-400 text-sm font-console">
              Your account has been successfully created in the void.
            </p>
            <button 
              onClick={() => { setSuccess(false); setIsLoginMode(true); }}
              className="w-full py-3 bg-eepy-mint text-void font-bold rounded-xl hover:bg-opacity-90 transition-all font-console"
            >
              Proceed to Login
            </button>
          </div>
        ) : (
          <form onSubmit={handleAuth} className="bg-void-surface border border-void-border p-8 rounded-eepy shadow-xl space-y-6 backdrop-blur-sm">
            {error && (
              <div className="p-3 bg-red-500/10 border border-red-500/20 text-red-400 text-xs font-console rounded-lg text-center">
                {error}
              </div>
            )}
            <div className="space-y-4">
              {!isLoginMode && (
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
              )}
              {!isLoginMode && (
                <div className="relative">
                  <Mail size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                  <input 
                    type="email" 
                    placeholder="Email Address" 
                    required
                    className="w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl focus:outline-none focus:border-eepy-lavender transition-colors font-console text-sm"
                    onChange={(e) => setFormData({...formData, email: e.target.value})}
                  />
                </div>
              )}
              {isLoginMode && (
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
              )}
              <div className="relative">
                <Lock size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                <input 
                  type={showPassword ? "text" : "password"} 
                  placeholder="Password" 
                  required
                  className="w-full pl-10 pr-12 py-3 bg-void border border-void-border rounded-xl focus:outline-none focus:border-eepy-lavender transition-colors font-console text-sm"
                  onChange={(e) => setFormData({...formData, password: e.target.value})}
                />
                <button 
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-eepy-lavender transition-colors"
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <button 
              disabled={isLoading}
              className={`w-full py-3 ${isLoginMode ? 'bg-eepy-lavender' : 'bg-eepy-peach'} text-void font-bold rounded-xl hover:bg-opacity-90 transition-all transform hover:scale-[1.02] shadow-[0_0_15px_rgba(195,177,225,0.3)] font-console flex items-center justify-center`}
            >
              {isLoading ? <Loader2 className="animate-spin mr-2" size={18} /> : (isLoginMode ? 'Wake Up' : 'Sync the Vibe')}
            </button>

            <div className="text-center text-sm text-gray-500 font-console">
              {isLoginMode 
                ? "Don't have an account? " 
                : "Already have an account? "}
              <button 
                type="button"
                onClick={() => { setIsLoginMode(!isLoginMode); setError(''); setSuccess(false); }}
                className={`text-eepy-lavender hover:underline ${!isLoginMode && 'text-eepy-peach'}`}
              >
                {isLoginMode ? 'Create one' : 'Log in'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
