// MCP Connection Wizard Component - Phase 5 Implementation (Template #1: HappyFox)
'use client';

import { useState } from 'react';
import { X, Key as KeyIcon, Eye, EyeOff } from 'lucide-react';

interface ConfigSchemaProperty {
    type: string;
    required?: boolean;
}

interface Props {
    templateId: string;
    onClose?: () => void;
}

export default function MCPConnectionWizard({ templateId, onClose }: Props) {
    // Phase 5 state management
    const [formData, setFormData] = useState<Record<string, string>>({});
    const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");

    // TODO (Phase 5): Fetch config_schema from backend API /api/mcp/templates/list to dynamically build form fields
    const mockConfigSchema: Record<string, ConfigSchemaProperty> = {
        HAPPYFOX_DOMAIN: { type: "string", required: true },
        HAPPYFOX_API_KEY: { type: "password", required: true },
        HAPPYFOX_AUTH_CODE: { type: "password", required: true }
    };

    const togglePasswordVisibility = (field: string): void => {
        setShowPasswords(prevState => ({ ...prevState, [field]: !prevState[field] }));
    };

    const handleWizardClose = (): void => {
        if (onClose) {
            onClose();
        } else {
            window.parent.postMessage({ type: "close-wizard", wizard_id: "happyfox-001" }, "*");
        }
    };

    // TODO (Phase 5): Submit form data to POST /api/mcp/config/register endpoint with credentials_json body + JWT auth headers
    const handleSubmit = async (): Promise<void> => {
        setLoading(true);
        setError("");

        try {
            // Validate all required fields populated before submission (security check)
            const missingFields = Object.keys(mockConfigSchema).filter((field: string): boolean => !formData[field] && !!mockConfigSchema[field].required);

            if (missingFields.length > 0) {
                throw new Error(`Missing required fields: ${JSON.stringify(missingFields)}`);
            }

            // TODO (Phase 5): Send encrypted credentials to backend -> Fernet encryption happens server-side ONLY via crypto.encrypt_jsonb()
            const response = await fetch('/api/mcp/config/register', {
                method: 'POST',
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    credentials_json: formData,
                    display_name: `My Support Queue (${templateId})`
                })
            });

            if (!response.ok) {
                throw new Error(`Backend API error: ${response.statusText}`);
            }
        } catch (err) {
            // ONLY log errors - NEVER secrets!
            setError(`Submission failed: ${err instanceof Error ? err.message : String(err)}`);
        } finally {
            setLoading(false);
        }
    };

    const setField = (field: string, value: string): void => {
        setFormData(prevState => ({ ...prevState, [field]: value }));
    };

    return (
        <div className="fixed inset-0 bg-black/75 flex items-center justify-center p-4 z-[999] backdrop-blur-sm">
            {/* Modal panel */}
            <div className="bg-surface-dark/95 border-2 border-eepy-lavender rounded-lg p-6 max-w-md w-full relative shadow-xl">
                {/* Header */}
                <header className="flex items-center justify-between mb-6 pb-4 border-b border-surface-light/30">
                    <h2 className="text-xl font-bold text-eepy-mint flex items-center gap-2">
                        Connect Integration: {templateId || "HappyFox"}
                    </h2>
                    <button onClick={handleWizardClose} className="text-surface-light/75 hover:text-white transition-colors duration-150">
                        <X size={20} />
                    </button>
                </header>

                {/* Form */}
                <form onSubmit={(e): void => { e.preventDefault(); handleSubmit(); }}>
                    <div className="space-y-4 mb-6">
                        {/* HAPPYFOX_DOMAIN Field */}
                        <div>
                            <h3 className="text-sm font-medium text-eepy-peach mb-2 flex items-center gap-1">
                                {mockConfigSchema.HAPPYFOX_DOMAIN?.required && <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>}
                                HAPPYFOX Domain (Required)
                            </h3>
                            <div className="relative">
                                <KeyIcon size={18} />
                                <input
                                    type="text"
                                    required
                                    placeholder={`e.g., https://${templateId || "mycompany"}.happyfox.com`}
                                    value={formData.HAPPYFOX_DOMAIN || ""}
                                    onChange={(e): void => setField("HAPPYFOX_DOMAIN", e.target.value)}
                                    className="w-full p-3 bg-surface-dark/70 border border-eepy-lavender rounded focus:outline-none focus:border-peach text-white transition-all duration-200"
                                />
                            </div>
                        </div>

                        {/* HAPPYFOX_API_KEY Field (masked input + visibility toggle) */}
                        <div>
                            <h3 className="text-sm font-medium text-eepy-peach mb-2 flex items-center gap-1">
                                {mockConfigSchema.HAPPYFOX_API_KEY.required && (<span className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>)}
                                HAPPYFOX API Key (Required)
                            </h3>
                            <div className={`relative ${showPasswords.HAPPYFOX_API_KEY ? "opacity-100" : "opacity-70"} transition-opacity duration-200`}>
                                <KeyIcon size={18} />
                                <input
                                    type={showPasswords.HAPPYFOX_API_KEY ? "text" : "password"}
                                    required
                                    placeholder="Your API key from HappyFox dashboard (copy/paste value only!)"
                                    value={formData.HAPPYFOX_API_KEY || ""}
                                    onChange={(e): void => setField("HAPPYFOX_API_KEY", e.target.value)}
                                    className={`w-full p-3 bg-surface-dark/70 border ${showPasswords.HAPPYFOX_API_KEY ? "border-peach" : "border-eepy-lavender"} rounded focus:outline-none transition-all duration-200 text-white`}
                                />
                                <button
                                    type="button"
                                    onClick={(e): void => { e.preventDefault(); togglePasswordVisibility("HAPPYFOX_API_KEY"); }}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 p-1 bg-surface-light/75 hover:bg-eepy-peach text-white rounded transition-colors duration-150"
                                >
                                    {showPasswords.HAPPYFOX_API_KEY ? <Eye size={16} /> : <EyeOff size={16} />}
                                </button>
                            </div>
                        </div>

                        {/* HAPPYFOX_AUTH_CODE Field (masked input + visibility toggle) */}
                        <div>
                            <h3 className="text-sm font-medium text-eepy-peach mb-2 flex items-center gap-1">
                                {mockConfigSchema.HAPPYFOX_AUTH_CODE.required && (<span className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>)}
                                HAPPYFOX Auth Code (Required)
                            </h3>
                            <div className={`relative ${showPasswords.HAPPYFOX_AUTH_CODE ? "opacity-100" : "opacity-70"} transition-opacity duration-200`}>
                                <KeyIcon size={18} />
                                <input
                                    type={showPasswords.HAPPYFOX_AUTH_CODE ? "text" : "password"}
                                    required
                                    placeholder="OAuth authorization code from OAuth flow (if applicable)"
                                    value={formData.HAPPYFOX_AUTH_CODE || ""}
                                    onChange={(e): void => setField("HAPPYFOX_AUTH_CODE", e.target.value)}
                                    className={`w-full p-3 bg-surface-dark/70 border ${showPasswords.HAPPYFOX_AUTH_CODE ? "border-peach" : "border-eepy-lavender"} rounded focus:outline-none transition-all duration-200 text-white`}
                                />
                                <button
                                    type="button"
                                    onClick={(e): void => { e.preventDefault(); togglePasswordVisibility("HAPPYFOX_AUTH_CODE"); }}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 p-1 bg-surface-light/75 hover:bg-eepy-peach text-white rounded transition-colors duration-150"
                                >
                                    {showPasswords.HAPPYFOX_AUTH_CODE ? <Eye size={16} /> : <EyeOff size={16} />}
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Error Message Section (no secrets shown) */}
                    {error && (
                        <p className="text-sm text-red-500 mb-4 bg-surface-dark/70 border-l-2 border-red-500 p-3 rounded">
                            {error}
                        </p>
                    )}

                    {/* Submit Button */}
                    <button
                        type="submit"
                        disabled={loading || !!error}
                        className={`w-full py-3 bg-eepy-lavender/90 hover:bg-peach text-black font-medium rounded transition-all duration-200 ${loading ? "opacity-50 cursor-not-allowed" : ""}`}
                    >
                        {loading ? "Saving..." : (error ? "Retry Connection" : "Connect & Encrypt Credentials")}
                    </button>
                </form>
            </div>
        </div>
    );
}
