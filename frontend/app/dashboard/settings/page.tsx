"use client";

import React from 'react';
import { Settings, Bell, Eye, ShieldCheck, Zap, Lock } from 'lucide-react';

export default function SettingsPage() {
  return (
    <div className="space-y-8">
      <header className="mb-8">
        <h2 className="text-3xl font-bold font-console text-white">System Settings</h2>
        <p className="text-gray-500 font-console text-sm mt-1 italic">Fine-tune your cozy infrastructure.</p>
      </header>

      <div className="max-w-3xl space-y-6">
        {/* General Section */}
        <div className="p-4 sm:p-6 md:p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl space-y-6 backdrop-blur-sm">
          <div className="flex items-center gap-3 mb-4">
            <Settings size={20} className="text-eepy-lavender" />
            <h3 className="text-lg font-bold font-console text-white">General Preferences</h3>
          </div>
          
          <div className="space-y-6">
             <div className="flex items-center justify-between p-4 bg-void border border-void-border rounded-xl group hover:border-eepy-lavender transition-colors">
                <div className="flex items-center gap-3">
                  <Bell size={18} className="text-gray-500" />
                  <div>
                    <p className="text-sm font-console text-white">Enable System Notifications</p>
                    <p className="text-[10px] font-console text-gray-600 italic">Get notified when servers enter deep sleep.</p>
                  </div>
                </div>
                <div className="w-12 h-6 bg-void-border rounded-full relative cursor-pointer transition-colors group-hover:bg-eepy-lavender/30">
                  <div className="absolute right-1 top-1 w-4 h-4 bg-gray-700 rounded-full" />
                </div>
             </div>

             <div className="flex items-center justify-between p-4 bg-void border border-void-border rounded-xl group hover:border-eepy-lavender transition-colors">
                <div className="flex items-center gap-3">
                  <Eye size={18} className="text-gray-500" />
                  <div>
                    <p className="text-sm font-console text-white">Public Profile Visibility</p>
                    <p className="text-[10px] font-console text-gray-600 italic">Allow other vibe coders to see your public servers.</p>
                  </div>
                </div>
                <div className="w-12 h-6 bg-eepy-lavender rounded-full relative cursor-pointer transition-colors">
                  <div className="absolute right-1 top-1 w-4 h-4 bg-white rounded-full" />
                </div>
             </div>
          </div>
        </div>

        {/* Security Section */}
        <div className="p-4 sm:p-6 md:p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl space-y-6 backdrop-blur-sm">
          <div className="flex items-center gap-3 mb-4">
            <ShieldCheck size={20} className="text-eepy-mint" />
            <h3 className="text-lg font-bold font-console text-white">Security & Privacy</h3>
          </div>

          <div className="space-y-6">
             <div className="flex items-center justify-between p-4 bg-void border border-void-border rounded-xl group hover:border-eepy-mint transition-colors">
                <div className="flex items-center gap-3">
                  <Lock size={18} className="text-gray-500" />
                  <div>
                    <p className="text-sm font-console text-white">Force High-Entropy Keys</p>
                    <p className="text-[10px] font-console text-gray-600 italic">Automatically rotate secrets every 30 days.</p>
                  </div>
                </div>
                <div className="w-12 h-6 bg-void-border rounded-full relative cursor-pointer transition-colors group-hover:bg-eepy-mint/30">
                  <div className="absolute right-1 top-1 w-4 h-4 bg-gray-700 rounded-full" />
                </div>
             </div>

             <div className="flex items-center justify-between p-4 bg-void border border-void-border rounded-xl group hover:border-eepy-mint transition-colors">
                <div className="flex items-center gap-3">
                  <Zap size={18} className="text-gray-500" />
                  <div>
                    <p className="text-sm font-console text-white">Optimize for Latency</p>
                    <p className="text-[10px] font-console text-gray-600 italic">Enable aggressive caching for streamable endpoints.</p>
                  </div>
                </div>
                <div className="w-12 h-6 bg-eepy-mint rounded-full relative cursor-pointer transition-colors">
                  <div className="absolute right-1 top-1 w-4 h-4 bg-white rounded-full" />
                </div>
             </div>
          </div>
        </div>
      </div>
    </div>
  );
}
