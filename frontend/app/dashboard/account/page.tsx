"use client";

import React from 'react';
import { UserCircle, Mail, Lock, ShieldCheck } from 'lucide-react';

export default function AccountPage() {
  return (
    <div className="space-y-8">
      <header className="mb-8">
        <h2 className="text-3xl font-bold font-console text-white">Account Profile</h2>
        <p className="text-gray-500 font-console text-sm mt-1 italic">Manage your identity in the void.</p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
        {/* Profile Sidebar */}
        <div className="p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl text-center space-y-6 h-fit">
          <div className="relative inline-block">
            <div className="p-6 bg-void rounded-full border-2 border-void-border text-eepy-lavender group hover:border-eepy-lavender transition-colors">
              <UserCircle size={64} />
            </div>
            <div className="absolute bottom-0 right-0 p-1 bg-void border border-void-border rounded-full text-eepy-mint">
               <ShieldCheck size={16} />
            </div>
          </div>
          <div>
            <h3 className="text-xl font-bold font-console">User Account</h3>
            <p className="text-gray-500 font-console text-xs italic uppercase tracking-widest mt-1">Verified Identity</p>
          </div>
          <button className="w-full py-2 bg-void border border-void-border rounded-lg text-xs font-console hover:bg-void-border transition-colors">
            Change Avatar
          </button>
        </div>

        {/* Settings Form */}
        <div className="md:col-span-2 space-y-6">
          <div className="p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl space-y-6 backdrop-blur-sm">
            <h3 className="text-lg font-bold font-console text-eepy-lavender mb-4">Personal Information</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-2">
                <label className="text-[10px] font-console uppercase text-gray-500 ml-1">Username</label>
                <div className="relative">
                  <UserCircle size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
                  <input readOnly value="[ROTATED_SUPERUSER_USERNAME]" className="w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm text-gray-500 cursor-not-allowed" />
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-[10px] font-console uppercase text-gray-500 ml-1">Email Address</label>
                <div className="relative">
                  <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
                  <input readOnly value="max@example.com" className="w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm text-gray-500 cursor-not-allowed" />
                </div>
              </div>
            </div>
          </div>

          <div className="p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl space-y-6 backdrop-blur-sm">
            <h3 className="text-lg font-bold font-console text-eepy-peach mb-4">Security</h3>
            <div className="space-y-4">
              <div className="relative">
                <label className="text-[10px] font-console uppercase text-gray-500 ml-1">Current Password</label>
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
                  <input type="password" placeholder="••••••••" className="w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm focus:border-eepy-peach transition-colors" />
                </div>
              </div>
              <div className="relative">
                <label className="text-[10px] font-console uppercase text-gray-500 ml-1">New Password</label>
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
                  <input type="password" placeholder="Enter new password" className="w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm focus:border-eepy-peach transition-colors" />
                </div>
              </div>
              <button className="px-6 py-2 bg-eepy-peach text-void font-bold rounded-lg font-console text-xs hover:bg-opacity-90 transition-all">
                Update Password
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
