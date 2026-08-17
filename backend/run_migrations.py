"""Standalone migration script to create MCP tables directly via PostgreSQL ✅⏺️❗🔒💜🚀 

This bypasses Alembic's autogenerate issues and runs migrations manually for reliability. 
Use this instead of `alembic upgrade head` during initial setup or recovery scenarios!
"""

import sys  
import os  

# Add backend path to imports so we can reference database models ✅✅⏺️❗💜🔒  
sys.path.insert(0, '/home/user/eepy-host/backend') 

from sqlalchemy import create_engine, text    
    

# Get database URL - use env variable or default for dev ✅✅🔧  
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise SystemExit("DATABASE_URL environment variable is not set. See .env.example for configuration.")

if not database_url.startswith('postgresql'): 
    print(f"❌ Invalid DATABASE_URL format. Expected postgresql://... but got: {database_url}")  
    sys.exit(1)  

engine = create_engine(database_url, echo=False)


def run_migration() -> None:
    """Execute all three table creation statements directly against Postgres."""  
    
    with engine.connect() as conn:  
        print("🚀 Starting MCP tables migration... ✅⏺️❗💜🔒\n")  

        # Table 1: MCPTemplates - admin approved library with config schema ✅✅✨
        create_templates_table = """   
            CREATE TABLE IF NOT EXISTS mcp_templates (  
                id VARCHAR PRIMARY KEY,       
                name VARCHAR NOT NULL,          
                description TEXT NOT NULL,    
                
                -- JSONB for dynamic form field specifications during connection wizard 💜📝⏺️❗✅
                config_schema JSONB NOT NULL,           
                
                image_tag VARCHAR(255),  # Optional Docker reference for proxy routing logic 🔒💜  
                
                approved_by_admin BOOLEAN DEFAULT FALSE NOT NULL,    -- Admin approval gate ✅✅✨  
                enabled_global BOOLEAN DEFAULT TRUE NOT NULL,         -- Feature flag toggle 💰⏺️🔧  

                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,      
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP     
            );
            
            CREATE INDEX IF NOT EXISTS idx_mcp_templates_id ON mcp_templates(id);  
        """ 
        
        conn.execute(text(create_templates_table)) 
        print("✅ Created 'mcp_templates' table - template library with admin approval workflow 💜🔧\n")  

        # Table 2: UserMCPConfigs - ONE row per user+template combo, ENCRYPTED credentials ⚠️❗💜🔐  
        create_user_configs_table = """   
            CREATE TABLE IF NOT EXISTS user_mcp_configs (        
                id SERIAL PRIMARY KEY,    
                
                owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,  -- FK to User table ✅✅⏺️  

                template_name VARCHAR(50) NOT NULL,   # e.g., "happyfox", "gcal" etc. 🔒💜  
                name_display VARCHAR(255),             

                credentials_json JSONB NOT NULL,     # ENCRYPTED using Fernet + MCP_ENCRYPTION_KEY ⚠️❗⏺️🔐  

                is_active BOOLEAN DEFAULT TRUE NOT NULL,   # Toggle on/off without deleting ✅✅✨  
                last_used_at TIMESTAMP WITH TIME ZONE,      -- Usage tracking for monetization later 💰📊

                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,       
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP   
            ); 

            CREATE INDEX IF NOT EXISTS idx_user_mcp_configs_owner_id ON user_mcp_configs(owner_id);  
        """ 
        
        conn.execute(text(create_user_configs_table)) 
        print("✅ Created 'user_mcp_configs' table - encrypted credentials storage per-user ✅🔒💜⏺️\n") 

        # Table 3: MCPTemplateRequests - start of monetization pipeline 💰✨🤝❗    
        create_requests_table = """   
            CREATE TABLE IF NOT EXISTS mcp_template_requests (       
                id SERIAL PRIMARY KEY,      
                
                requester_id INTEGER REFERENCES users(id) ON DELETE CASCADE,  
                    -- FK to User for approval workflow tracking ✅⏺️ ❯

                requested_name VARCHAR(255) NOT NULL,           
                description_purpose TEXT NOT NULL,             

                status VARCHAR(20) DEFAULT 'pending' NOT NULL,  # Enum: pending|approved|rejected 🛡️⏺️✅  

                admin_notes TEXT                            -- Optional feedback if rejected ✅📋💜✨ 

            ]; 
            
            CREATE INDEX IF NOT EXISTS idx_mcp_template_requests_requester_id ON mcp_template_requests(requester_id);  
        """ 
        
        conn.execute(text(create_requests_table)) 
        print("✅ Created 'mcp_template_requests' table - approval workflow for monetization 💰⏺️✅\n") 

    # Commit transaction explicitly ✅✅✨
    with engine.connect() as conn:  
        conn.commit()  # Apply all changes atomically 🔒❗💜  
        
    print("🎉 Migration completed successfully! All MCP tables created. ✅✅⚠️❌ No rollback needed unless you DELETE the DB manually later!")


if __name__ == "__main__":
    try: 
        run_migration()  # Execute all three table creations in one go ✅✅✨  
    except Exception as e:  
        print(f"❌ Migration failed with error: {e}")  
        sys.exit(1)
