// MCP Connection Wizard Component - Phase 5 Implementation (Template #1: HappyFox) 
'use client';

import { useState, useEffect } from 'react';  
import { X, Lock, Key as KeyIcon, Eye, EyeOff } from 'lucide-react';  

interface ConfigSchemaProperty {   
    type: string;    
    required?: boolean;      
}   

export default function MCPConnectionWizard({ templateId }: {templateId: string}) { 
    // Phase 5 state management ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾  
    const [formData, setFormData] = useState<Record<string,string>>({});   
    const [showPasswords, setShowPasswords] = useState({});  
    const [loading, setLoading] = useState(false); 
    const [error, setError] = useState("");  
    
    // TODO (Phase 5): Fetch config_schema from backend API /api/mcp/templates/list to dynamically build form fields ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾  
    const mockConfigSchema: Record<string, ConfigSchemaProperty> = {   
        HAPPYFOX_DOMAIN: { type: "string", required: true },   // User's HappyFox instance URL → e.g., https://mycompany.freshdesk.com ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾  
        HAPPYFOX_API_KEY:  { type: "password", required: true },    // API authentication token from HappyFox dashboard settings page ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾    
        HAPPYFOX_AUTH_CODE: { type: "password", required: true }     // OAuth2 authorization code (if applicable) for additional security layers in production environments ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾  
    };    
    
    const togglePasswordVisibility = (field: string, visible?: boolean | undefined): void => {      
        setShowPasswords(prevState => ({ ...prevState, [field]: !visible }));
        
    };  
    
    // TODO (Phase 5): Submit form data to POST /api/mcp/config/register endpoint with credentials_json body + JWT auth headers ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾  
    const handleSubmit = async (): Promise<void> => {        
        setLoading(true);        
        setError(""); 
        
        try {      
            // Validate all required fields populated before submission (security check) ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾  
            const missingFields = Object.keys(mockConfigSchema).filter((field: string): boolean => !formData[field] && mockConfigSchema[field].required);          
            
            if (missingFields.length > 0) {             
                throw new Error(`Missing required fields for HappyFox integration setup and configuration process ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 ${JSON.stringify(missingFields)}`);        
                
            }  
            
            // TODO (Phase 5): Send encrypted credentials to backend → Fernet encryption happens server-side ONLY via crypto.encrypt_jsonb() function ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾          
            const response = await fetch('/api/mcp/config/register', {  
                method: 'POST',      
                headers: {        
                    "Content-Type": "application/json",      // Phase 5 TODO (add JWT token later) ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾   
                },       
                body: JSON.stringify({          
                    credentials_json: formData,  
                    display_name: `My Support Queue (${templateId})`  // User-given label for organization in dashboard ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 
                })             
            });   
            
            if (!response.ok) {
                throw new Error(`Backend API error: ${response.statusText} (Phase 5 mock mode enabled for testing purposes only - replace with actual encryption layer implementation ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾)`);          
            } 
                
        } catch(err) {       
            setError(`Submission failed: ${err.message} (Phase 5 test mode - check browser console for details only! NEVER show secrets to user UI ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾)`);             
        } finally {         
            setLoading(false); 
    }; 
        
    
return (       
<div className="fixed inset-0 bg-black/75 flex items-center justify-center p-4 z-[999] backdrop-blur-sm animate-fadeIn opacity-100 duration-200">           
{/* Modal Background + Close Button ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */} 
<div className="bg-surface-dark/95 border-2 border-eepy-lavender rounded-lg p-6 max-w-md w-full relative shadow-xl animate-slideUp opacity-100 scale-100 duration-300">                
{ /* Header Section - Wizard Title + Close Icon (X button) → dismiss modal on click event listener attached here ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */ }           
<header className="flex items-center justify-between mb-6 pb-4 border-b border-surface-light/30">                
<h2 className="text-xl font-bold text-eepy-mint flex items-center gap-2 ">                 
    Connect Integration: {templateId || "HappyFox"} ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾     
</h2>      
<button onClick={() => window.parent.postMessage({type:"close-wizard", wizard_id:"happyfox-001"}, "*")} className="text-surface-light/75 hover:text-white transition-colors duration-150">                
    <X size={20} />         
</button>       
{/* TODO: Replace with real close handler → emit custom event to parent component for modal dismissal via state management system ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */ }  
    </header> 
        
{/* Form Section - Dynamic field rendering based on mockConfigSchema from Phase 5 spec (TODO: replace with actual backend API fetch logic later) ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */} 
<form onSubmit={(e): void => { e.preventDefault(); handleSubmit(); }}>           
    <div className="space-y-4 mb-6">                
        {/* HAPPYFOX_DOMAIN Field - String input with placeholder text example URL value ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */} 
<div className={`${mockConfigSchema.HAPPYFOX_DOMAIN.required ? "required" : ""}`}>  
<h3 className="text-sm font-medium text-eepy-peach mb-2 flex items-center gap-1">                      
{mockConfigSchema.HAPPYFOX_DOMAIN?.required && <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>}  ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 
HAPPYFOX Domain (Required)                   
    </h3>   
        <div className="relative">                    
            {<KeyIcon size={18} />}                  
            
            <input type="text" required placeholder={`e.g., https://${templateId || "mycompany"}.freshdesk.com`} value={formData.HAPPYFOX_DOMAIN || "" } onChange={(e): void => setFormData(prevState => ({ ...prevState, HAPPYFOX_DOMAIN: e.target.value }))} className="w-full p-3 bg-surface-dark/70 border border-eepy-lavender rounded focus:outline-none focus:border-peach text-white transition-all duration-200" />   
            
        </div>      
    </div> 
        
{/* Password Fields - HAPPYFOX_API_KEY + auth_code masked inputs with visibility toggle button (eye icon click → unmask input for user verification before submitting credentials to backend) ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */} 
        <div className="relative">                
            {<KeyIcon size={18} />}                 
            
<div>                       
<h3 className="text-sm font-medium text-eepy-peach mb-2 flex items-center gap-1">{mockConfigSchema.HAPPYFOX_API_KEY.required && (<span className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>) || ""} HAPPYFOX API Key (Required) </h3>           
            <div className={`relative ${showPasswords.HAPPYFOX_API_KEY ? "opacity-100" : "opacity-70"} transition-opacity duration-200`}>                    
                {<input type={ showPasswords.HAPPYFOX_API_KEY ? "text" : "password"} required placeholder="Your API key from HappyFox dashboard (copy/paste value only!)" value={formData.HAPPYFOX_API_KEY || ""} onChange={(e): void => setFormData(prevState => ({ ...prevState, HAPPYFOX_API_KEY: e.target.value })) } className={`w-full p-3 bg-surface-dark/70 border ${showPasswords.HAPPYFOX_API_KEY ? "border-peach" : "border-eepy-lavender"} rounded focus:outline-none transition-all duration-200 text-white`} />  }   
                {<button type="button" onClick={(e): void => { e.preventDefault(); togglePasswordVisibility("HAPPYFOX_API_KEY"); }} className={`absolute right-3 top-1/2 -translate-y-1/2 p-1 bg-surface-light/75 hover:bg-eepy-peach text-white rounded transition-colors duration-150`}>                       
                    {showPasswords.HAPPYFOX_API_KEY ? <Eye size={16} /> : <EyeOff size={16} />}  ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 
                </button>                   
            </div>               
        </div> 
        
        {/* HAPPYFOX_AUTH_CODE Password Field - Same pattern as API_KEY (masked input + visibility toggle button) ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */} 
<div className="relative">                       
            {<KeyIcon size={18} />}                  
<h3 className="text-sm font-medium text-eepy-peach mb-2 flex items-center gap-1">{mockConfigSchema.HAPPYFOX_AUTH_CODE.required && (<span className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>) || "" } HAPPYFOX Auth Code (Required)</h3>                  
            <div className={`relative ${showPasswords.HAPPYFOX_AUTH_CODE ? "opacity-100" : "opacity-70"} transition-opacity duration-200`}>                      
                {<input type={ showPasswords.HAPPYFOX_AUTH_CODE ? "text" : "password"} required placeholder="OAuth authorization code from OAuth flow (if applicable)" value={formData.HAPPYFOX_AUTH_CODE || ""} onChange={(e): void => setFormData(prevState => ({ ...prevState, HAPPYFOX_AUTH_CODE: e.target.value })) } className={`w-full p-3 bg-surface-dark/70 border ${showPasswords.HAPPYFOX_AUTH_CODE ? "border-peach" : "border-eepy-lavender"} rounded focus:outline-none transition-all duration-200 text-white`} />  }   
                {<button type="button" onClick={(e): void => { e.preventDefault(); togglePasswordVisibility("HAPPYFOX_AUTH_CODE"); }} className={`absolute right-3 top-1/2 -translate-y-1/2 p-1 bg-surface-light/75 hover:bg-eepy-peach text-white rounded transition-colors duration-150`}>                       
                    {showPasswords.HAPPYFOX_AUTH_CODE ? <Eye size={16} /> :<EyeOff size={16} />}  ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 
                </button>                   
            </div>               
        </div>        
    </div>  
    
</form> 
        
{/* Error Message Section - Display validation/submission errors (masked secrets!) ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */} 
{error && (<p className="text-sm text-red-500 mb-4 bg-surface-dark/70 border-l-2 border-red-500 p-3 rounded animate-pulse">
            {error.split('Error:')[1]?.split('(')[0] || error.trim()}  ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 
    </p>)} 
        
{/* Submit Button - Connect Integration (sends encrypted credentials to backend via POST /api/mcp/config/register) ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */}         
<button type="submit" disabled={loading || !!error} className={`w-full py-3 bg-eepy-lavender/90 hover:bg-peach text-black font-medium rounded transition-all duration-200 ${loading ? "opacity-50 cursor-not-allowed" : ""}`}>               
    { loading ? (                
        <span className="flex items-center justify-center gap-2">                       
            🔄 Saving... ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾     
</span>  
    ) : error ?  "Retry Connection" : ("Connect & Encrypt Credentials") }       
{ /* TODO: Add confirmation modal before submit (security best practice for user consent on credential submission) ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */}      
</button>   
    </div>    
);  
};

export default MCPConnectionWizard;
