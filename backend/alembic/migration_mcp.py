"""Migration script to add MCP tables - Manual implementation (auto-generate failed) ✅⏺️❗💜🔒"""  

from alembic import op  
import sqlalchemy as sa


def upgrade() -> None:
    """Create all three new database tables for HappyFox template integration."""    
        
    # Table 1: MCP Templates Library - admin approved, public view (with config schema) ✅✅⏺️❗📊💜      
    op.create_table(          
        'mcp_templates', 
        sa.Column('id', sa.String(), primary_key=True),  
        sa.Column('name', sa.String(), nullable=False),    
        sa.Column('description', sa.Text, nullable=False),   
        
        # Form field schema for credential entry during connection wizard ✅✅💜📝
        sa.Column('config_schema', sa.JSON(), nullable=False),      
        
        # Optional Docker reference if needed (for proxy routing logic)  
        sa.Column('image_tag', sa.String(), nullable=True),             
        
        # Approval workflow controls: admin gate + global enable/disable toggle ✅✅⏺️❗💰
        sa.Column('approved_by_admin', sa.Boolean, default=False, nullable=False),       
        sa.Column('enabled_global', sa.Boolean, default=True, nullable=False),         
        
        # Timestamps for audit trail and usage analytics 💰📊✨  
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()), 
        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now())          
    )
    
    op.create_index(op.f('ix_mcp_templates_id'), 'mcp_templates', ['id'], unique=False)  # Performance optimization ✅⚙️❗  
    print("✅ Created mcp_templates table - template library with approval workflow 💜🔧")  

    # Table 2: User MCP Configurations - ONE row per user + template combo, ENCRYPTED credentials at rest ⚠️🔒💜❗    
    op.create_table(          
        'user_mcp_configs', 
        sa.Column('id', sa.Integer(), primary_key=True),   
        
        # Foreign key to User table for ownership tracking ✅✅⏺️  
        sa.Column('owner_id', sa.Integer(), nullable=False,
                 foreign_keys=[op.f('users.id')]),  # Must exist before migration runs! ⚠️❗🔒  
    
        template_name = sa.Column(sa.String(), nullable=False),      
        name_display = sa.Column(sa.String()),                      
        
        # CRITICAL: ENCRYPTED JSONB column - NEVER store plaintext here ❌⏺️❗💜🔐  
        credentials_json = sa.Column(sa.JSON, nullable=False),    
        
        is_active = sa.Column(sa.Boolean, default=True, nullable=False),   # Toggle on/off without deleting ✅✅✨
        last_used_at = sa.Column(sa.DateTime(), nullable=True),             # Usage tracking for monetization later 💰📊  
        
        created_at = sa.Column(sa.DateTime(), default=sa.func.now()),       
        updated_at = sa.Column(sa.DateTime(), onupdate=sa.func.now())    
    )  
    
    op.create_index(op.f('ix_user_mcp_configs_owner_id'), 'user_mcp_configs', ['owner_id'], unique=False)  
    print("✅ Created user_mcp_configs table - encrypted credentials storage for each user ✅🔒💜⏺️")

    # Table 3: Template Request Pipeline - start of monetization flow 💰✨🤝❗    
    op.create_table(          
        'mcp_template_requests',      
        sa.Column('id', sa.Integer(), primary_key=True),  
        
        requester_id = sa.Column(sa.Integer(), nullable=False,
                               foreign_keys=[op.f('users.id')]),  # Reference to User ✅⏺️❗  

        requested_name = sa.Column(sa.String(), nullable=False),          
        description_purpose = sa.Column(sa.Text, nullable=False),          
        
        status = sa.Column(sa.String(), default='pending', nullable=False),  # 'pending' → 'approved'|'rejected' 🛡️⏺️✅  
        
        admin_notes = sa.Column(sa.Text()),                                   # Optional feedback if rejected ✅📋💜✨ 

    )  
    
    op.create_index(op.f('ix_mcp_template_requests_requester_id'), 'mcp_template_requests', ['requester_id'], unique=False)
    print("✅ Created mcp_template_requests table - approval workflow pipeline for monetization 💰⏺️✅")


def downgrade() -> None:  
    """Rollback all three tables (for dev testing only!) ⚠️❗🧪"""    
        op.drop_table('mcp_templates')
    print("⬇️ Dropped mcp_templates table")  
    
    op.drop_table('user_mcp_configs')      
    print("⬇️ Dropped user_mcp_configs table (credentials purged permanently ❌💜) ⚠️❗🔒 ") 
    
    op.drop_table('mcp_template_requests') 
    print("⬇️ Dropped mcp_template_requests table") 


if __name__ == '__main__':  
    try: 
        upgrade()  # Run migrations when executed directly ✅✅✨
    except Exception as e:          
        print(f"❌ Migration failed with error: {e}")           