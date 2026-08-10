# 🌙 Eepy Host

**Powerful infrastructure, wrapped in a soft blanket of simplicity.**

Eepy Host is the ultimate playground for the **Vibe Coder**. It is a cozy, tech-forward hosting platform designed for the Model Context Protocol (MCP), allowing users to pick from pre-configured servers and connect their AI models to the world of information. Designed for privacy and focus, it's best paired with self-hosted LLM interfaces like Open WebUI for a fully private stack.
 
---

## ✨ Key Features

- **Multi-Tier Role Hierarchy**: 
  - `User`: Manage your own account and server configurations.
  - `Admin`: User permissions + administrative oversight of standard accounts.
  - `Superuser`: Full "God Mode" visibility across all accounts, including Admins.
- **The MCP Engine**: Pick from a library of pre-programmed servers and input your own API keys/secrets securely to extend your AI's capabilities.
- **Streamable HTTP Core**: Built for the high-performance requirements of modern AI context streaming.
- **Cozy Tech Aesthetic**: A "Void & Neon" interface combining deep charcoal voids with lavender, mint, and peach accents—designed to reduce noise and enhance flow.

## 🛠️ Technical Stack

- **Frontend**: [Next.js](https://nextjs.org/) + [Tailwind CSS](https://tailwindcss.com/)
- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) (Python)
- **Database**: [PostgreSQL](https://www.postgresql.org/)
- **Security**: Direct `bcrypt` hashing & JWT-based RBAC
- **Deployment**: Docker Compose $\rightarrow$ Portainer via GHCR

---

## 🚀 Quick Start (Portainer/Docker)

### Prerequisites
- A running instance of Portainer or Docker Compose.
- Access to the `ghcr.io` registry.

### Deployment Steps
1. **Clone or copy** the `docker-compose.yml` file from this repository.
2. **Deploy as a Stack**: Paste the compose file into your Portainer stack editor.
3. **Launch**: Click "Deploy the stack."

The services will automatically pull the latest optimized images from the GitHub Container Registry:
- `ghcr.io/kulik-labs-development/eepy-host-backend:latest`
- `ghcr.io/kulik-labs-development/eepy-host-frontend:latest`

**Default Access:**
- Frontend: `http://<your-ip>:3000`
- Backend API: `http://<your-ip>:8000`

---

## 🗺️ Roadmap

### Phase 1: Core Infrastructure ✅
- [x] Multi-stage Docker builds.
- [x] CI/CD pipeline via GitHub Actions $\rightarrow$ GHCR.
- [x] "Void & Cozy" Design System implementation.
- [x] Base landing page and networking.

### Phase 2: The Auth Shell ✅
- [x] PostgreSQL User & Role schema.
- [x] JWT-based authentication logic (with direct `bcrypt` bytes truncation).
- [x] RBAC (Role-Based Access Control) middleware.
- [x] High-vibe Login/Signup UI screens with password visibility toggles.

### Phase 3: Admin & Management (Next Up) 🌙
- [ ] Superuser Dashboard (Global visibility).
- [ ] Admin User management tools.
- [ ] Role promotion/demotion workflows.

### Phase 4: MCP Configuration Engine
- [ ] Pre-programmed server library.
- [ ] User settings input for API tokens.
- [ ] Dummy server integration for UI testing.

---

*Stay cozy.* 🌙
