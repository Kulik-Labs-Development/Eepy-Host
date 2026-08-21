"use client";

import React, { useState, useEffect } from 'react';
import { UserCircle, Mail, Lock, Camera, CreditCard, Wallet, LogOut } from 'lucide-react';
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
    <div className="space-y-8 max-w-6xl mx-auto">
      <header className="mb-8 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4">
        <div>
          <h2 className="font-pixel font-bold text-2xl sm:text-3xl text-ink text-px-sm">Account Profile</h2>
          <p className="text-ink-dim font-body text-sm mt-1">Manage your identity and presence in the night.</p>
        </div>
        <button
          onClick={logout}
          className="btn btn-danger px-4 py-2 text-xs shrink-0 self-start sm:self-auto"
        >
          <LogOut size={16} /> Sign Out
        </button>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Profile Sidebar */}
        <div className="panel pixel-caps p-4 sm:p-6 md:p-8 space-y-6 h-fit sm:sticky sm:top-8 [--cap:theme('colors.eepy.sage')] text-center">
          <div className="relative inline-block group">
            <div className={`well p-1.5 ${profileData.profilePicture ? 'border-eepy-sage' : ''}`}>
              {profileData.profilePicture ? (
                <img
                  src={profileData.profilePicture}
                  alt="Profile"
                  className="w-32 h-32 object-cover"
                  style={{ imageRendering: 'pixelated' }}
                />
              ) : (
                <div className="w-32 h-32 bg-night-deep flex items-center justify-center text-eepy-blush">
                  <UserCircle size={64} />
                </div>
              )}
            </div>
            <label className="btn-icon absolute -bottom-2 -right-2 cursor-pointer" title="Change avatar">
              <Camera size={16} />
              <input type="file" accept="image/*" className="hidden" onChange={handleImageUpload} disabled={isUploading} />
            </label>
            {isUploading && (
              <div className="absolute inset-0 bg-night-deep/60 flex items-center justify-center">
                <div className="w-6 h-6 border-2 border-eepy-sage border-t-transparent animate-spin" style={{ borderRadius: '2px' }} />
              </div>
            )}
          </div>
          <div className="space-y-1">
            <h3 className="font-pixel font-bold text-xl text-ink">{profileData.fullName || user?.username}</h3>
            <p className="text-ink-dim font-console text-[13px] uppercase tracking-widest">Verified Identity</p>
          </div>
          <div className="flex justify-center gap-2 flex-wrap">
            <span className="chip chip-blush">Vibe Coder</span>
            <span className="chip">Beta Tester</span>
          </div>
        </div>

        {/* Settings Content */}
        <div className="lg:col-span-2 space-y-8">
          {/* Personal Information Section */}
          <div className="panel pixel-caps p-4 sm:p-6 md:p-8 space-y-6 [--cap:theme('colors.eepy.blush')] relative overflow-hidden">
            <div className="absolute left-0 top-0 w-1.5 h-full bg-eepy-blush" />
            <h3 className="font-pixel font-bold text-lg text-eepy-blush mb-4 flex items-center gap-2">
              <UserCircle size={18} /> Personal Information
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6">
              <div className="space-y-2">
                <label className="label-pixel">Full Name</label>
                <input
                  type="text"
                  placeholder="Enter your full name"
                  className="input-pixel"
                  value={profileData.fullName}
                  onChange={(e) => setProfileData({ ...profileData, fullName: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <label className="label-pixel">Email Address</label>
                <div className="relative">
                  <Mail size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-dim" />
                  <input readOnly value={profileData.email} className="input-pixel pl-9" />
                </div>
              </div>
            </div>
            <button
              onClick={handleSaveChanges}
              disabled={isSaving}
              className="btn btn-blush px-6 py-2.5 text-xs"
            >
              {isSaving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>

          {/* Security Section */}
          <div className="panel pixel-caps p-4 sm:p-6 md:p-8 space-y-6 [--cap:theme('colors.eepy.amber')] relative overflow-hidden">
            <div className="absolute left-0 top-0 w-1.5 h-full bg-eepy-amber" />
            <h3 className="font-pixel font-bold text-lg text-eepy-amber mb-4 flex items-center gap-2">
              <Lock size={18} /> Security & Access
            </h3>
            <div className="space-y-5">
              <div className="space-y-2">
                <label className="label-pixel">Current Password</label>
                <div className="relative">
                  <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-dim" />
                  <input type="password" placeholder="••••••••" className="input-pixel pl-9" />
                </div>
              </div>
              <div className="space-y-2">
                <label className="label-pixel">New Password</label>
                <div className="relative">
                  <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-dim" />
                  <input type="password" placeholder="Enter new password" className="input-pixel pl-9" />
                </div>
              </div>
              <button className="btn btn-amber px-6 py-2.5 text-xs">
                Update Password
              </button>
            </div>
          </div>

          {/* Billing & Payments Placeholder */}
          <div className="panel pixel-caps p-4 sm:p-6 md:p-8 space-y-6 [--cap:theme('colors.eepy.sage')] relative overflow-hidden">
            <div className="absolute left-0 top-0 w-1.5 h-full bg-eepy-sage" />
            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-2 mb-4">
              <h3 className="font-pixel font-bold text-lg text-eepy-sage flex items-center gap-2">
                <Wallet size={18} /> Billing & Subscription
              </h3>
              <span className="chip">Plan: Free Tier</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="card p-4 space-y-3 group hover:border-eepy-sage/70 transition-colors">
                <div className="flex items-center gap-2 text-ink-faint font-console text-[15px]">
                  <CreditCard size={14} /> Payment Method
                </div>
                <p className="text-sm font-body text-ink-dim italic">No card on file.</p>
                <button className="btn btn-ghost w-full py-2 text-[11px] uppercase tracking-wider">
                  Add Payment Method
                </button>
              </div>
              <div className="card p-4 space-y-3 group hover:border-eepy-sage/70 transition-colors">
                <div className="flex items-center gap-2 text-ink-faint font-console text-[15px]">
                  <Wallet size={14} /> Billing History
                </div>
                <p className="text-sm font-body text-ink-dim italic">No transactions yet.</p>
                <button className="btn btn-ghost w-full py-2 text-[11px] uppercase tracking-wider">
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
