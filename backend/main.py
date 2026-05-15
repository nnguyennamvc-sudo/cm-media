from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os, json, httpx
from dotenv import load_dotenv
from jose import jwt, JWTError
from datetime import datetime, timedelta
 
load_dotenv()
 
from sheets import SheetsClient
 
app = FastAPI(title="CM Media API")
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)
 
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
JWT_SECRET = os.getenv("JWT_SECRET", "cm_media_secret_2024")
 
def create_token(payload: dict) -> str:
    data = {**payload, "exp": datetime.utcnow() + timedelta(days=30)}
    return jwt.encode(data, JWT_SECRET, algorithm="HS256")
 
def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token không hợp lệ")
 
async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    return decode_token(auth[7:])
 
def get_sheets(user=Depends(get_current_user)) -> SheetsClient:
    sid = user.get("sheet_id")
    if not sid:
        raise HTTPException(status_code=400, detail="Chưa có sheet")
    return SheetsClient(sid)
 
# ── Google One Tap OAuth ──────────────────────────────────────────────────────
@app.post("/auth/google-onetap")
async def google_onetap(request: Request):
    body = await request.json()
    credential = body.get("credential")
    if not credential:
        raise HTTPException(400, "Thiếu credential")
    async with httpx.AsyncClient() as client:
        res = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": credential}
        )
        info = res.json()
    if "error" in info or "email" not in info:
        raise HTTPException(401, "Token Google không hợp lệ")
    email = info["email"]
    name = info.get("name", email)
    picture = info.get("picture", "")
    sc = SheetsClient()
    sheet_id = sc.get_or_create_user_sheet(email, name)
    payload = {
        "sub": email, "email": email, "name": name,
        "picture": picture, "sheet_id": sheet_id,
        "trial_days_left": 7, "plan": "trial"
    }
    token = create_token(payload)
    return {"token": token, "user": payload}
 
@app.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return user
 
# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.get("/dashboard")
async def dashboard(sc: SheetsClient = Depends(get_sheets)):
    content = sc.get_all_content()
    pages = sc.get_all_pages()
    now = datetime.now()
    stats = {"total": len(content), "success": 0, "posting": 0, "pending": 0, "failed": 0, "stuck": 0}
    for r in content:
        s = r.get("Trạng thái", "").lower()
        if s == "thành công": stats["success"] += 1
        elif s == "đang đăng": stats["posting"] += 1
        elif s in ("đợi đăng", "chờ"):
            try:
                import re
                parts = [int(x) for x in re.findall(r'\d+', str(r.get("Thời gian đăng","")))]
                if len(parts) >= 6:
                    d = datetime(parts[2],parts[1],parts[0],parts[3],parts[4],parts[5])
                    if d < now: stats["stuck"] += 1; continue
            except: pass
            stats["pending"] += 1
        elif s in ("thất bại","lỗi"): stats["failed"] += 1
    pages_out = []
    for p in pages:
        posted = sum(1 for r in content if r.get("tên trang")==p.get("Tên trang") and r.get("Trạng thái","").lower()=="thành công")
        pages_out.append({
            "name": p.get("Tên trang",""), "pid": p.get("ID",""),
            "followers": 0, "fans": 0, "reach": 0, "impressions": 0,
            "posted": posted
        })
    return {"stats": stats, "pages": pages_out}
 
# ── Pages ─────────────────────────────────────────────────────────────────────
@app.get("/pages")
async def list_pages(sc: SheetsClient = Depends(get_sheets)):
    rows = sc.get_all_pages_with_row()
    return [{"_row": ri, "id": i, **r} for i,(ri,r) in enumerate(rows)]
 
class PageData(BaseModel):
    name: str = ""
    pid: str = ""
    token: str = ""
    proxy: str = ""
    channels: str = ""
    stop_links: str = ""
    clips: int = 5
    end_time: str = ""
 
@app.post("/pages")
async def create_page(data: PageData, sc: SheetsClient = Depends(get_sheets)):
    sc.append_page(data.dict())
    return {"ok": True}
 
@app.put("/pages/{row_idx}")
async def update_page(row_idx: int, data: PageData, sc: SheetsClient = Depends(get_sheets)):
    sc.update_page_row(row_idx, data.dict())
    return {"ok": True}
 
@app.delete("/pages/{row_idx}")
async def delete_page(row_idx: int, sc: SheetsClient = Depends(get_sheets)):
    sc.delete_rows("Page", [row_idx])
    return {"ok": True}
 
# ── Content ───────────────────────────────────────────────────────────────────
@app.get("/content")
async def list_content(
    page_name: str = "", status: str = "", search: str = "",
    sc: SheetsClient = Depends(get_sheets)
):
    rows = sc.get_all_content_with_row()
    filtered = []
    for ri, r in rows:
        if page_name and r.get("tên trang","") != page_name: continue
        if status and r.get("Trạng thái","").lower() != status.lower(): continue
        if search and search.lower() not in json.dumps(r, ensure_ascii=False).lower(): continue
        filtered.append({"_row": ri,
            "page": r.get("tên trang",""), "pid": r.get("ID",""),
            "url": r.get("Video cần tải",""), "status": r.get("Trạng thái",""),
            "ai": r.get("AI Agent",""), "time": r.get("Thời gian đăng",""),
            "noi_dung_them": r.get("Nội dung muốn thêm",""),
            "noi_dung_dang": r.get("Nội Dung Sẽ Đăng",""),
            "binh_luan": r.get("Bình luận Dưới video",""),
            "link_dang": r.get("Link bài đăng",""),
            "ghi_chu": r.get("ghi chú",""), "proxy": r.get("Proxy","")
        })
    return {"rows": filtered, "total": len(filtered)}
 
class AddContentReq(BaseModel):
    rows: List[dict]
 
class DeleteReq(BaseModel):
    rows: List[int]
 
class ResetReq(BaseModel):
    rows: List[int]
    new_status: str = "đợi đăng"
 
@app.post("/content")
async def add_content(req: AddContentReq, sc: SheetsClient = Depends(get_sheets)):
    sc.append_content_rows(req.rows)
    return {"ok": True, "added": len(req.rows)}
 
@app.delete("/content")
async def delete_content(req: DeleteReq, sc: SheetsClient = Depends(get_sheets)):
    sc.delete_rows("Content", req.rows)
    return {"ok": True}
 
@app.post("/content/reset")
async def reset_content(req: ResetReq, sc: SheetsClient = Depends(get_sheets)):
    sc.reset_status(req.rows, req.new_status)
    return {"ok": True}
 
@app.get("/ping")
async def ping():
    return {"ok": True, "message": "CM Media API đang chạy!"}
 
