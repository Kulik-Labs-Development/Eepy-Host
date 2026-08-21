"use client";

import React, { useState } from 'react';
import { Lock, User, Mail, Loader2, Eye, EyeOff, Sparkles } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { getApiUrl } from '@/lib/api';
import { useRouter } from 'next/navigation';
import PixelMoon from '@/src/components/PixelMoon';

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

  const switchMode = (mode: boolean) => {
    setIsLoginMode(mode);
    setError('');
    setSuccess(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 sm:p-6 relative">
      <div className="z-10 w-full max-w-md space-y-6">
        <div className="text-center space-y-3">
          <div className="flex justify-center mb-2">
            <PixelMoon size={72} />
          </div>
          <h1 className="font-pixel font-bold text-3xl sm:text-4xl text-px-sm">
            {isLoginMode ? (
              <>Welcome <span className="text-eepy-blush">Back</span></>
            ) : (
              <>Sync your <span className="text-eepy-amber">Vibe</span></>
            )}
          </h1>
          <p className="text-ink-faint font-body text-sm">
            {isLoginMode
              ? 'Enter your credentials to wake up.'
              : 'Ready to connect your models to the world?'}
          </p>
        </div>

        {success ? (
          <div className="panel pixel-caps p-6 sm:p-8 space-y-6 text-center [--cap:theme('colors.eepy.sage')]">
            <div className="flex justify-center mb-2">
              <div className="well p-4 text-eepy-sage">
                <Sparkles size={32} />
              </div>
            </div>
            <h2 className="font-pixel font-bold text-2xl text-ink">Vibe Synced!</h2>
            <p className="text-ink-faint text-sm">
              Your account has been tucked safely into the night.
            </p>
            <button
              onClick={() => { setSuccess(false); setIsLoginMode(true); }}
              className="btn btn-sage w-full py-3"
            >
              Proceed to Login
            </button>
          </div>
        ) : (
          <div className="panel pixel-caps p-5 sm:p-8 [--cap:theme('colors.eepy.pink')]">
            {/* Mode tabs — game-menu style */}
            <div className="well p-1.5 flex gap-1.5 mb-6">
              <button
                type="button"
                onClick={() => switchMode(true)}
                className={`flex-1 py-2 font-pixel font-bold text-sm transition-colors ${
                  isLoginMode ? 'bg-eepy-blush text-night-deep shadow-pixel-sm' : 'text-ink-faint hover:text-ink'
                }`}
              >
                Log In
              </button>
              <button
                type="button"
                onClick={() => switchMode(false)}
                className={`flex-1 py-2 font-pixel font-bold text-sm transition-colors ${
                  !isLoginMode ? 'bg-eepy-amber text-night-deep shadow-pixel-sm' : 'text-ink-faint hover:text-ink'
                }`}
              >
                Sign Up
              </button>
            </div>

            {error && (
              <div className="mb-5 p-3 bg-eepy-ember/10 border-2 border-eepy-ember/50 text-eepy-ember text-sm text-center font-body">
                {error}
              </div>
            )}

            <form onSubmit={handleAuth} className="space-y-5">
              <div className="space-y-4">
                {!isLoginMode && (
                  <div className="relative">
                    <User size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-dim" />
                    <input
                      type="text"
                      placeholder="Username"
                      required
                      className="input-pixel pl-9"
                      onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                    />
                  </div>
                )}
                {!isLoginMode && (
                  <div className="relative">
                    <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-dim" />
                    <input
                      type="email"
                      placeholder="Email Address"
                      required
                      className="input-pixel pl-9"
                      onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                    />
                  </div>
                )}
                {isLoginMode && (
                  <div className="relative">
                    <User size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-dim" />
                    <input
                      type="text"
                      placeholder="Username"
                      required
                      className="input-pixel pl-9"
                      onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                    />
                  </div>
                )}
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-dim" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    placeholder="Password"
                    required
                    className="input-pixel pl-9 pr-11"
                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-dim hover:text-eepy-blush transition-colors"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <button
                disabled={isLoading}
                className={`btn w-full py-3 text-base ${isLoginMode ? 'btn-blush' : 'btn-amber'}`}
              >
                {isLoading ? (
                  <Loader2 className="animate-spin" size={18} />
                ) : isLoginMode ? (
                  'Wake Up'
                ) : (
                  'Sync the Vibe'
                )}
              </button>
            </form>

            <div className="text-center text-sm text-ink-dim font-body mt-5">
              {isLoginMode ? "Don't have an account? " : 'Already have an account? '}
              <button
                type="button"
                onClick={() => switchMode(!isLoginMode)}
                className={`font-bold hover:underline ${isLoginMode ? 'text-eepy-blush' : 'text-eepy-amber'}`}
              >
                {isLoginMode ? 'Create one' : 'Log in'}
              </button>
            </div>
          </div>
        )}

        <p className="text-center text-ink-dim font-console text-[15px]">
          A quiet little server room, just for you.
        </p>
      </div>
    </div>
  );
}
