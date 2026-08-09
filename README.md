# 🌙 Eepy Host

**Powerful infrastructure, wrapped in a soft blanket of simplicity.**

Eepy Host is a cozy, tech-forward hosting platform designed for the Model Context Protocol (MCP). It allows users to deploy and configure streamable HTTP MCP servers with their own API tokens, all managed through a high-contrast "Void & Neon" interface.

---

## ✨ Key Features

- **Multi-Tier Role Hierarchy**: 
  - `User`: Manage your own account and server configurations.
  - `Admin`: User permissions + administrative oversight of standard accounts.
  - `Superuser`: Full "God Mode" visibility across all accounts, including Admins.
- **Custom MCP Configurations**: Pick from pre-programmed servers and input your own API keys/secrets securely.
- **Streamable HTTP Core**: Built for the high-performance requirements of modern AI context streaming.
- **Cozy Tech Aesthetic**: A dark-mode interface combining deep charcoal "voids" with lavender, mint, and peach accents.

## 🛠️ Technical Stack

- **Frontend**: [Next.js](https://nextjs.org/) + [Tailwind CSS](https://tailwindcss.com/)
- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) (Python)
- **Database**: [PostgreSQL](https://www.postgresql.org/)
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

### Phase 2: The Auth Shell (In Progress) 🌙
- [ ] PostgreSQL User & Role schema.
- [ ] JWT-based authentication logic.
- [ ] RBAC (Role-Based Access Control) middleware.
- [ ] Cozy Login/Signup UI screens.

### Phase 3: Admin & Management
- [ ] Superuser Dashboard (Global visibility).
- [ ] Admin User management tools.
- [ ] Role promotion/demotion workflows.

### Phase 4: MCP Configuration Engine
- [ ] Pre-programmed server library.
- [ ] User settings input for API tokens.
- [ ] Dummy server integration for UI testing.

---

*Stay cozy.* 🌙
