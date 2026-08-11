"use client";

import React, { useState, useEffect } from 'react';
import { UserCircle, Mail, Lock, ShieldCheck, Camera, CreditCard, Wallet, LogOut } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';

export default function AccountPage() {
  const { user, logout } = useAuth();
  const [profileData, setProfileData] = useState({
    fullName: '',
    email: '',
    profilePicture: null as string | null,
  });
  const [isUploading, setIsUploading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // Load profile data on mount
  useEffect(() => {
    async function fetchProfile() {
      try {
        const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'https://api.eepy.host'}/user/profile`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('eepy_token')}`,
          },
        });
        if (response.ok) {
          const data = await response.json();
          setProfileData({
            fullName: data.full_name || '',
            email: data.email,
            profilePicture: data.profile_picture,
          });
        }
      } catch (error) {
        console.error("Failed to fetch profile:", error);
      }
    }
    fetchProfile();
  }, []);

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'https://api.eepy.host'}/user/avatar`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('eepy_token')}`,
        },
        body: formData,
      });

      if (response.ok) {
        const data = await response.json();
        setProfileData(prev => ({ ...prev, profilePicture: data.profile_picture }));
      } else {
        alert("Failed to upload image");
      }
    } catch (error) {
      console.error("Upload error:", error);
      alert("An error occurred while uploading the image");
    } finally {
      setIsUploading(false);
    }
  };

  const handleSaveChanges = async () => {
    setIsSaving(true);
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'https://api.eepy.host'}/user/profile`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('eepy_token')}`,
        },
        body: JSON.stringify({ full_name: profileData.fullName }),
      });

      if (response.ok) {
        alert("Profile updated successfully!");
      } else {
        alert("Failed to save changes");
      }
    } catch (error) {
      console.error("Save error:", error);
      alert("An error occurred while saving");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-8">
      <header className="mb-8 flex justify-between items-center">
        <div>
          <h2 className="text-3xl font-bold font-console text-white">Account Profile</h2>
          <p className="text-gray-500 font-console text-sm mt-1 italic">Manage your identity and presence in the void.</p>
        </div>
        <button 
          onClick={logout}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-gray-400 hover:bg-red-500/10 hover:text-red-400 transition-all font-console text-xs border border-void-border"
        >
          <LogOut size={16} /> Sign Out
        </button>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Profile Sidebar */}
        <div className="p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl text-center space-y-6 h-fit sticky top-8">
          <div className="relative inline-block group">
            <div className={`p-1 rounded-full border-2 transition-colors ${profileData.profilePicture ? 'border-eepy-mint' : 'border-void-border'} overflow-hidden`}>
              {profileData.profilePicture ? (
                <img 
                  src={profileData.profilePicture} 
                  alt="Profile" 
                  className="w-32 h-32 rounded-full object-cover" 
                />
              ) : (
                <div className="w-32 h-32 rounded-full bg-void flex items-center justify-center text-eepy-lavender">
                  <UserCircle size={64} />
                </div>
              )}
            </div>
            <label className="absolute bottom-2 right-2 p-2 bg-void border border-void-border rounded-full text-white cursor-pointer hover:text-eepy-mint transition-colors shadow-lg">
              <Camera size={16} />
              <input type="file" accept="image/*" className="hidden" onChange={handleImageUpload} disabled={isUploading} />
            </label>
            {isUploading && (
              <div className="absolute inset-0 bg-void/50 rounded-full flex items-center justify-center backdrop-blur-sm">
                <div className="w-6 h-6 border-2 border-eepy-mint border-t-transparent rounded-full animate-spin" />
              </div>
            )}
          </div>
          <div className="space-y-1">
            <h3 className="text-xl font-bold font-console">{profileData.fullName || user?.username}</h3>
            <p className="text-gray-500 font-console text-xs italic uppercase tracking-widest">Verified Identity</p>
          </div>
          <div className="flex justify-center gap-2">
            <span className="px-2 py-1 bg-void border border-void-border text-[10px] font-console text-eepy-mint rounded uppercase tracking-tighter">Vibe Coder</span>
            <span className="px-2 py-1 bg-void border border-void-border text-[10px] font-console text-gray-600 rounded uppercase tracking-tighter">Beta Tester</span>
          </div>
        </div>

        {/* Settings Content */}
        <div className="lg:col-span-2 space-y-8">
          {/* Personal Information Section */}
          <div className="p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl space-y-6 backdrop-blur-sm relative overflow-hidden group">
            <div className="absolute top-0 left-0 w-1 h-full bg-eepy-lavender" />
            <h3 className="text-lg font-bold font-console text-eepy-lavender mb-4 flex items-center gap-2">
              <UserCircle size={18} /> Personal Information
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-2">
                <label className="text-[10px] font-console uppercase text-gray-500 ml-1">Full Name</label>
                <div className="relative">
                  <input 
                    type="text" 
                    placeholder="Enter your full name" 
                    className="w-full px-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm focus:border-eepy-lavender transition-colors outline-none"
                    value={profileData.fullName}
                    onChange={(e) => setProfileData({...profileData, fullName: e.target.value})}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-[10px] font-console uppercase text-gray-500 ml-1">Email Address</label>
                <div className="relative">
                  <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
                  <input readOnly value={profileData.email} className="w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm text-gray-500 cursor-not-allowed outline-none" />
                </div>
              </div>
            </div>
            <button 
              onClick={handleSaveChanges}
              disabled={isSaving}
              className={`px-6 py-2 bg-eepy-lavender text-void font-bold rounded-lg font-console text-xs transition-all shadow-[0_0_15px_rgba(195,177,225,0.3)] ${isSaving ? 'opacity-50 cursor-not-allowed' : 'hover:bg-opacity-90'}`}
            >
              {isSaving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>

          {/* Security Section */}
          <div className="p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl space-y-6 backdrop-blur-sm relative overflow-hidden group">
            <div className="absolute top-0 left-0 w-1 h-full bg-eepy-peach" />
            <h3 className="text-lg font-bold font-console text-eepy-peach mb-4 flex items-center gap-2">
              <Lock size={18} /> Security & Access
            </h3>
            <div className="space-y-4">
              <div className="relative space-y-2">
                <label className="text-[10px] font-console uppercase text-gray-500 ml-1">Current Password</label>
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
                  <input type="password" placeholder="••••••••" className="w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm focus:border-eepy-peach transition-colors outline-none" />
                </div>
              </div>
              <div className="relative space-y-2">
                <label className="text-[10px] font-console uppercase text-gray-500 ml-1">New Password</label>
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
                  <input type="password" placeholder="Enter new password" className="w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm focus:border-eepy-peach transition-colors outline-none" />
                </div>
              </div>
              <button className="px-6 py-2 bg-eepy-peach text-void font-bold rounded-lg font-console text-xs hover:bg-opacity-90 transition-all shadow-[0_0_15px_rgba(250,218,221,0.3)]">
                Update Password
              </button>
            </div>
          </div>

          {/* Billing & Payments Placeholder */}
          <div className="p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl space-y-6 backdrop-blur-sm relative overflow-hidden group">
            <div className="absolute top-0 left-0 w-1 h-full bg-eepy-mint" />
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-bold font-console text-eepy-mint flex items-center gap-2">
                <Wallet size={18} /> Billing & Subscription
              </h3>
              <span className="px-2 py-1 bg-void border border-void-border text-[10px] font-console text-gray-500 rounded uppercase">Plan: Free Tier</span>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="p-4 bg-void border border-void-border rounded-xl space-y-3 group hover:border-eepy-mint transition-colors">
                <div className="flex items-center gap-2 text-gray-400 font-console text-xs">
                  <CreditCard size={14} /> Payment Method
                </div>
                <p className="text-sm font-console text-gray-600 italic">No card on file.</p>
                <button className="w-full py-2 bg-void-surface border border-void-border rounded-lg text-[10px] font-console hover:bg-void-border transition-colors uppercase tracking-wider">
                  Add Payment Method
                </button>
              </div>
              <div className="p-4 bg-void border border-void-border rounded-xl space-y-3 group hover:border-eepy-mint transition-colors">
                <div className="flex items-center gap-2 text-gray-400 font-console text-xs">
                  <ShieldCheck size={14} /> Billing History
                </div>
                <p className="text-sm font-console text-gray-600 italic">No transactions yet.</p>
                <button className="w-full py-2 bg-void-surface border border-void-border rounded-lg text-[10px] font-console hover:bg-void-border transition-colors uppercase tracking-wider">
                  View Invoices
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
