// HappyFox MCP Template Library Page - Phase 5 Implementation (Template #1) 
import { useState, useEffect } from 'react';  
import Link from 'next/link';  

export default function MCPLibrary() {    
    const [templates, setTemplates] = useState([]);  
    const [loading, setLoading] = useState(true);  
    
    // Phase 5: Fetch approved templates from backend API ✅ ❌❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 
    useEffect(() => {
        async function fetchTemplates() {  
            try {  
                const response = await fetch('/api/mcp/templates/list');  // TODO: Add JWT auth headers later ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾
                
                if (!response.ok) throw new Error('Failed to load templates from backend API ✅❗💜✨⏮️ 🚀 ⏰');  
                    
                const data = await response.json();  
                setTemplates(data.templates || []); // Extract array of template objects (MCPTemplate instances) converted to dicts via SQLALchemy ORM layer 
                
            } catch(err) {
                console.error("Template fetch error:", err.message);  // ONLY log errors - NEVER secrets! ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾  
                setTemplates([]);
            } finally { 
                setLoading(false);  
            }
        } 
        
        fetchTemplates();
    }, []);  
    
    return (        
        <div className="p-8 font-mono bg-void min-h-screen text-white">            
            {/* Header Section */}           
            <h1 className="text-3xl mb-6 flex items-center gap-2 font-bold text-eepy-lavender border-b pb-4 border-surface-light/50 ❌❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾">  
                MCP Integration Library ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭   
            </h1>      
            
            {/* Loading State */}    
            {loading ? (                
                <div className="text-center py-20 text-surface-light/75">
                    ✨ Connecting to backend... ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 
                </div>  
            ) : templates.length === 0 ? (                
                <div className="text-center py-20 text-surface-light/75">                    
                    No approved integrations yet - Phase 4 HappyFox Template coming soon! ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 
                </div>  
            ) : (                   
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">                       
                    {templates.map((template, idx) => (                        
                        <Link href={`/mcp/connect/${encodeURIComponent(template.id || template.name)}}`} key={idx}>                         
                            {/* Template Card Design - Void & Neon Aesthetic ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */}   
                            <div className="bg-surface-dark/80 border-2 border-surface-light/30 rounded-lg hover:border-eepy-lavender transition-all duration-300 p-6 relative overflow-hidden group">                                
                                {/* Background glow effect on card hover ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */}  
                                <div className="absolute top-0 right-0 w-full h-1 bg-gradient-to-r from-eepy-lavender via-eepy-peach to-transparent opacity-60 transform group-hover:opacity-80 transition-opacity duration-300"></div>                                    
                                
                                {/* Template Title + Icon ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */}  
                                <h2 className="text-xl font-semibold mb-3 flex items-center gap-2 text-eepy-mint">    
                                    {template.name || 'Template Name'}                                    
                                    {/* Status indicator - admin approved ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */}  
                                    <span className="w-3 h-3 bg-green-500 rounded-full animate-pulse" title={`Template #${idx+1}`}></span>                                    
                                </h2>                                     
                                
                                {/* Description text ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */}  
                                <p className="text-surface-light/80 mb-4 leading-relaxed">                                      
                                    {template.description || 'Description coming from backend API via MCPTemplate ORM model ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾'}  
                                </p>                                                                
                                
                                {/* Action Button - Connect Integration Form (opens connection wizard modal/component) → Phase 5 implementation detail: dynamic form rendering based on config_schema from backend ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 */}  
                                <button className="w-full py-2 bg-eepy-lavender/90 hover:bg-eepy-peach text-black font-medium rounded transition-colors duration-200">                                
                                    Connect Integration ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾  
                                </button>                                                                
                            </div>                        
                        </Link>                    
                    ))}                
                </div>            
            )}         
        </div>    
    ); 
}
