from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Eepy Host API")

# CORS Configuration for Frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # We will restrict this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "status": "online", 
        "message": "Welcome to the Eepy Host API. Stay cozy."
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}
