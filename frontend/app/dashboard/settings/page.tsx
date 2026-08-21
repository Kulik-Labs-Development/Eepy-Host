"use client";

import React from 'react';
import { Settings, Bell, Eye, ShieldCheck, Zap, Lock } from 'lucide-react';

// Squared retro toggle (visual placeholder, matching prior behavior).
function PixelToggle({ on, tint }: { on: boolean; tint: 'lilac' | 'sage' }) {
  const tintClasses =
    tint === 'lilac'
      ? { trackOn: 'border-eepy-lilac bg-eepy-lilac/20', knobOn: 'bg-eepy-lilac' }
      : { trackOn: 'border-eepy-sage bg-eepy-sage/20', knobOn: 'bg-eepy-sage' };
  return (
    <div
      className={`relative flex items-center w-12 h-6 border-2 px-0.5 transition-colors shrink-0 ${
        on ? tintClasses.trackOn : 'bg-night-deep border-night-border'
      }`}
    >
      <div
        className={`w-4 h-4 transition-transform duration-100 ${
          on ? `translate-x-6 ${tintClasses.knobOn}` : 'translate-x-0 bg-ink-dim'
        }`}
      />
    </div>
  );
}

export default function SettingsPage() {
  return (
    <div className="space-y-8 max-w-3xl mx-auto">
      <header className="mb-8">
        <h2 className="font-pixel font-bold text-3xl text-ink text-px-sm">System Settings</h2>
        <p className="text-ink-dim font-body text-sm mt-1">Fine-tune your cozy infrastructure.</p>
      </header>

      <div className="space-y-6">
        {/* General Section */}
        <div className="panel pixel-caps p-4 sm:p-6 md:p-8 space-y-6 [--cap:theme('colors.eepy.lilac')]">
          <div className="flex items-center gap-3 mb-2">
            <Settings size={20} className="text-eepy-lilac" />
            <h3 className="font-pixel font-bold text-lg text-ink">General Preferences</h3>
          </div>

          <div className="space-y-4">
            <div className="card flex items-center justify-between p-4 gap-4 hover:border-eepy-lilac/70 transition-colors">
              <div className="flex items-center gap-3 min-w-0">
                <Bell size={18} className="text-ink-faint shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-body text-ink font-semibold">Enable System Notifications</p>
                  <p className="text-xs font-body text-ink-dim italic">Get notified when servers enter deep sleep.</p>
                </div>
              </div>
              <PixelToggle on={false} tint="lilac" />
            </div>

            <div className="card flex items-center justify-between p-4 gap-4 hover:border-eepy-lilac/70 transition-colors">
              <div className="flex items-center gap-3 min-w-0">
                <Eye size={18} className="text-ink-faint shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-body text-ink font-semibold">Public Profile Visibility</p>
                  <p className="text-xs font-body text-ink-dim italic">Allow other vibe coders to see your public servers.</p>
                </div>
              </div>
              <PixelToggle on tint="lilac" />
            </div>
          </div>
        </div>

        {/* Security Section */}
        <div className="panel pixel-caps p-4 sm:p-6 md:p-8 space-y-6 [--cap:theme('colors.eepy.sage')]">
          <div className="flex items-center gap-3 mb-2">
            <ShieldCheck size={20} className="text-eepy-sage" />
            <h3 className="font-pixel font-bold text-lg text-ink">Security & Privacy</h3>
          </div>

          <div className="space-y-4">
            <div className="card flex items-center justify-between p-4 gap-4 hover:border-eepy-sage/70 transition-colors">
              <div className="flex items-center gap-3 min-w-0">
                <Lock size={18} className="text-ink-faint shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-body text-ink font-semibold">Force High-Entropy Keys</p>
                  <p className="text-xs font-body text-ink-dim italic">Automatically rotate secrets every 30 days.</p>
                </div>
              </div>
              <PixelToggle on={false} tint="sage" />
            </div>

            <div className="card flex items-center justify-between p-4 gap-4 hover:border-eepy-sage/70 transition-colors">
              <div className="flex items-center gap-3 min-w-0">
                <Zap size={18} className="text-ink-faint shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-body text-ink font-semibold">Optimize for Latency</p>
                  <p className="text-xs font-body text-ink-dim italic">Enable aggressive caching for streamable endpoints.</p>
                </div>
              </div>
              <PixelToggle on tint="sage" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
