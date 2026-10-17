from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="TK Myanmar Clip AI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class ScriptRequest(BaseModel):
    text: str

@app.get("/")
def home():
    return {"app": "TK Myanmar Clip AI", "status": "running"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/script")
def make_script(req: ScriptRequest):
    text = req.text.strip()
    if not text:
        return {"error": "စာသားထည့်ပေးပါ"}
    return {"script": text, "message": "စာသားလက်ခံပြီးပါပြီ။ AI summary နှင့် Myanmar voice ကို နောက်အဆင့်တွင် ချိတ်ဆက်ရပါမည်။"}
