"use client";

import React, { useState, useEffect } from 'react';
import { UserCircle, Mail, Lock, ShieldCheck, Camera, CreditCard, Wallet } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';

export default function AccountPage() {
  const { user } = useAuth();
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
      <header className="mb-8">
        <h2 className="text-3xl font-bold font-console text-white">Account Profile</h2>
        <p className="text-gray-500 font-console text-sm mt-1 italic\">Manage your identity and presence in the void.</p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Profile Sidebar */}\n        <div className=\"p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl text-center space-y-6 h-fit sticky top-8\">\n          <div className=\"relative inline-block group\">\n            <div className={\`p-1 rounded-full border-2 transition-colors \${profileData.profilePicture ? 'border-eepy-mint' : 'border-void-border'} overflow-hidden\`}>\n              {profileData.profilePicture ? (\n                <img \n                  src={profileData.profilePicture} \n                  alt=\"Profile\" \n                  className=\"w-32 h-32 rounded-full object-cover\" \n                />\n              ) : (\n                <div className=\"w-32 h-32 rounded-full bg-void flex items-center justify-center text-eepy-lavender\">\n                  <UserCircle size={64} />\n                </div>\n              )}\n            </div>\n            <label className=\"absolute bottom-2 right-2 p-2 bg-void border border-void-border rounded-full text-white cursor-pointer hover:text-eepy-mint transition-colors shadow-lg\">\n              <Camera size={16} />\n              <input type=\"file\" accept=\"image/*\" className=\"hidden\" onChange={handleImageUpload} disabled={isUploading} />\n            </label>\n            {isUploading && (\n              <div className=\"absolute inset-0 bg-void/50 rounded-full flex items-center justify-center backdrop-blur-sm\">\n                <div className=\"w-6 h-6 border-2 border-eepy-mint border-t-transparent rounded-full animate-spin\" />\n              </div>\n            )}\n          </div>\n          <div className=\"space-y-1\">\n            <h3 className=\"text-xl font-bold font-console\">{profileData.fullName || user?.username}</h3>\n            <p className=\"text-gray-500 font-console text-xs italic uppercase tracking-widest\">Verified Identity</p>\n          </div>\n          <div className=\"flex justify-center gap-2\">\n            <span className=\"px-2 py-1 bg-void border border-void-border text-[10px] font-console text-eepy-mint rounded uppercase tracking-tighter\">Vibe Coder</span>\n            <span className=\"px-2 py-1 bg-void border border-void-border text-[10px] font-console text-gray-600 rounded uppercase tracking-tighter\">Beta Tester</span>\n          </div>\n        </div>\n\n        {/* Settings Content */}\n        <div className=\"lg:col-span-2 space-y-8\">\n          {/* Personal Information Section */}\n          <div className=\"p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl space-y-6 backdrop-blur-sm relative overflow-hidden group\">\n            <div className=\"absolute top-0 left-0 w-1 h-full bg-eepy-lavender\" />\n            <h3 className=\"text-lg font-bold font-console text-eepy-lavender mb-4 flex items-center gap-2\">\n              <UserCircle size={18} /> Personal Information\n            </h3>\n            <div className=\"grid grid-cols-1 md:grid-cols-2 gap-6\">\n              <div className=\"space-y-2\">\n                <label className=\"text-[10px] font-console uppercase text-gray-500 ml-1\">Full Name</label>\n                <div className=\"relative\">\n                  <input \n                    type=\"text\" \n                    placeholder=\"Enter your full name\" \n                    className=\"w-full px-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm focus:border-eepy-lavender transition-colors outline-none\"\n                    value={profileData.fullName}\n                    onChange={(e) => setProfileData({...profileData, fullName: e.target.value})}\n                  />\n                </div>\n              </div>\n              <div className=\"space-y-2\">\n                <label className=\"text-[10px] font-console uppercase text-gray-500 ml-1\">Email Address</label>\n                <div className=\"relative\">\n                  <Mail size={16} className=\"absolute left-3 top-1/2 -translate-y-1/2 text-gray-600\" />\n                  <input readOnly value={profileData.email} className=\"w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm text-gray-500 cursor-not-allowed outline-none\" />\n                </div>\n              </div>\n            </div>\n            <button \n              onClick={handleSaveChanges}\n              disabled={isSaving}\n              className={\`px-6 py-2 bg-eepy-lavender text-void font-bold rounded-lg font-console text-xs transition-all shadow-[0_0_15px_rgba(195,177,225,0.3)] \${isSaving ? 'opacity-50 cursor-not-allowed' : 'hover:bg-opacity-90'}\`}\n            >\n              {isSaving ? 'Saving...' : 'Save Changes'}\n            </button>\n          </div>\n\n          {/* Security Section */}\n          <div className=\"p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl space-y-6 backdrop-blur-sm relative overflow-hidden group\">\n            <div className=\"absolute top-0 left-0 w-1 h-full bg-eepy-peach\" />\n            <h3 className=\"text-lg font-bold font-console text-eepy-peach mb-4 flex items-center gap-2\">\n              <Lock size={18} /> Security & Access\n            </h3>\n            <div className=\"space-y-4\">\n              <div className=\"relative space-y-2\">\n                <label className=\"text-[10px] font-console uppercase text-gray-500 ml-1\">Current Password</label>\n                <div className=\"relative\">\n                  <Lock size={16} className=\"absolute left-3 top-1/2 -translate-y-1/2 text-gray-600\" />\n                  <input type=\"password\" placeholder=\"••••••••\" className=\"w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm focus:border-eepy-peach transition-colors outline-none\" />\n                </div>\n              </div>\n              <div className=\"relative space-y-2\">\n                <label className=\"text-[10px] font-console uppercase text-gray-500 ml-1\">New Password</label>\n                <div className=\"relative\">\n                  <Lock size={16} className=\"absolute left-3 top-1/2 -translate-y-1/2 text-gray-600\" />\n                  <input type=\"password\" placeholder=\"Enter new password\" className=\"w-full pl-10 pr-4 py-3 bg-void border border-void-border rounded-xl font-console text-sm focus:border-eepy-peach transition-colors outline-none\" />\n                </div>\n              </div>\n              <button className=\"px-6 py-2 bg-eepy-peach text-void font-bold rounded-lg font-console text-xs hover:bg-opacity-90 transition-all shadow-[0_0_15px_rgba(250,218,221,0.3)]\">\n                Update Password\n              </button>\n            </div>\n          </div>\n\n          {/* Billing & Payments Placeholder */}\n          <div className=\"p-8 bg-void-surface border border-void-border rounded-eepy shadow-xl space-y-6 backdrop-blur-sm relative overflow-hidden group\">\n            <div className=\"absolute top-0 left-0 w-1 h-full bg-eepy-mint\" />\n            <div className=\"flex justify-between items-center mb-4\">\n              <h3 className=\"text-lg font-bold font-console text-eepy-mint flex items-center gap-2\">\n                <Wallet size={18} /> Billing & Subscription\n              </h3>\n              <span className=\"px-2 py-1 bg-void border border-void-border text-[10px] font-console text-gray-500 rounded uppercase\">Plan: Free Tier</span>\n            </div>\n            \n            <div className=\"grid grid-cols-1 md:grid-cols-2 gap-6\">\n              <div className=\"p-4 bg-void border border-void-border rounded-xl space-y-3 group hover:border-eepy-mint transition-colors\">\n                <div className=\"flex items-center gap-2 text-gray-400 font-console text-xs\">\n                  <CreditCard size={14} /> Payment Method\n                </div>\n                <p className=\"text-sm font-console text-gray-600 italic\">No card on file.</p>\n                <button className=\"w-full py-2 bg-void-surface border border-void-border rounded-lg text-[10px] font-console hover:bg-void-border transition-colors uppercase tracking-wider\">\n                  Add Payment Method\n                </button>\n              </div>\n              <div className=\"p-4 bg-void border border-void-border rounded-xl space-y-3 group hover:border-eepy-mint transition-colors\">\n                <div className=\"flex items-center gap-2 text-gray-400 font-console text-xs\">\n                  <ShieldCheck size={14} /> Billing History\n                </div>\n                <p className=\"text-sm font-console text-gray-600 italic\">No transactions yet.</p>\n                <button className=\"w-full py-2 bg-void-surface border border-void-border rounded-lg text-[10px] font-console hover:bg-void-border transition-colors uppercase tracking-wider\">\n                  View Invoices\n                </button>\n              </div>\n            </div>\n          </div>\n        </div>\n      </div>\n    </div>\n  );\n}\nEOF
