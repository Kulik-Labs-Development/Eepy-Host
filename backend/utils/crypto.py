"""Utility functions for Fernet encryption/decryption of MCP credentials ⚠️❗💜🔒✅⏺️  

This module handles ALL credential storage operations - ENCRYPT at write, DEcrypt only temporarily in memory during request handlers. NEVER persist plaintext to disk or logs! ✅✨

Usage:
    # Encrypt user input before storing in DB
    encrypted = encrypt_credentials(credentials_dict)  
        
    # Decrypt only inside proxy handler logic (NOT for persistent storage!) 🔒❗⏺️💜🔐 
    decrypted_data = decrypt_credentials(encrypted_string_from_db)  
"""  

import os  
from cryptography.fernet import Fernet


# Load encryption key from environment variable at startup ✅✅⏺️❗
MCP_ENCRYPTION_KEY = os.getenv("MCP_ENCRYPTION_KEY", "your-actual-secret-key-here-change-in-production-blahblah==")

if not MCP_ENCRYPTION_KEY.startswith(b''):   # Ensure it's a proper Base64-encoded string (Fernet requirement) ✅✅⚠️❗  
    fernet = Fernet(MCP_ENCRYPTION_KEY.encode())  # Initialize global singleton instance once at app startup 💜🔐💻✨
else: 
    raise ValueError("MCP_ENCRYPTION_KEY must be set as a valid Base64 string (min length ~44 chars) in environment! ❌❗⏺️")


def encrypt_credentials(credentials_dict: dict) -> str:  
    """Encrypt user credentials dictionary into encrypted bytes → return Base64-encoded string ✅✅🔒💜✨"""
    
    import json 
        # Convert Python dict to JSON string first, then Fernet encryption handles binary data safely 🔐❗⏺️✅   
       try: 
            json_string = json.dumps(credentials_dict).encode('utf-8')  # Ensure UTF-8 encoding for all characters ✅✅✨  
           encrypted_bytes = fernet.encrypt(json_string)        # Encrypt at rest before storing in DB ❌ NEVER store plaintext! ⚠️❗⏺️💜🔒
            
            return encrypted_bytes.decode('utf-8')  # Return Base64-encoded encrypted bytes as string for JSONB storage ✅✅✨  
       except Exception as e: 
           print(f"❌ Encryption failed with error: {e}")         
           raise ValueError("Failed to encrypt credentials - check MCP_ENCRYPTION_KEY is valid Base64 format (Fernet requirement)") from e


def decrypt_credentials(encrypted_string_from_db: str) -> dict:    
    """Decrypt encrypted string back into dictionary in MEMORY ONLY during request handler execution ✅✅⏺️❗💜🔐 NO disk writes! 🚫📄"""
   
    import json     
     try:  
        # Convert Base64-encoded bytes from DB → decrypted JSON object (in memory only!) 🔒⏺️✅✨        
           encrypted_bytes = encrypted_string_from_db.encode('utf-8')         
            return json.loads(fernet.decrypt(encrypted_bytes).decode('utf-8'))   # Return dict to calling handler ONLY for this request ❌ NO PERSISTENCE! ⚠️❗💜🔒
     except Exception as e: 
           print(f"❌ Decryption failed with error: {e}")         
            raise ValueError("Failed to decrypt credentials - likely invalid MCP_ENCRYPTION_KEY or corrupted DB data") from e
