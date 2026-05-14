import gspread, os, json
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CONTENT_HEADERS = [
    "tên trang","ID","Video cần tải","Trạng thái","AI Agent",
    "Thời gian đăng","Nội dung lấy từ tiktok","Nội dung muốn thêm",
    "Nội Dung Sẽ Đăng","Bình luận Dưới video","Link bài đăng","ghi chú","Proxy"
]
PAGE_HEADERS = [
    "Tên trang","ID","Token","Proxy",
    "Kênh TikTok","Link chặn cuối","Số clip/ngày","Giờ chặn cuối"
]

def _get_client():
    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        raise RuntimeError("Thiếu GOOGLE_SERVICE_ACCOUNT_JSON")
    return gspread.authorize(creds)

class SheetsClient:
    def __init__(self, spreadsheet_id: str = ""):
        self._client = _get_client()
        self._sid = spreadsheet_id
        self._ss = None

    def _get_ss(self):
        if not self._ss and self._sid:
            self._ss = self._client.open_by_key(self._sid)
        return self._ss

    def get_or_create_user_sheet(self, email: str, name: str) -> str:
        title = f"CM Media — {email}"
        try:
            ss = self._client.open(title)
            return ss.id
        except gspread.SpreadsheetNotFound:
            ss = self._client.create(title)
            ss.share(email, perm_type='user', role='writer', notify=True,
                     email_message=f"Chào {name}! Sheet CM Media của bạn đã sẵn sàng.")
            ws = ss.sheet1
            ws.update_title("Content")
            ws.append_row(CONTENT_HEADERS)
            ws2 = ss.add_worksheet("Page", rows=100, cols=15)
            ws2.append_row(PAGE_HEADERS)
            return ss.id

    def _get_ws(self, name, headers):
        ss = self._get_ss()
        try:
            return ss.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = ss.add_worksheet(name, rows=1000, cols=len(headers)+2)
            ws.append_row(headers)
            return ws

    def _all_with_row(self, ws, headers):
        vals = ws.get_all_values()
        if len(vals) < 2: return []
        result = []
        for i, row in enumerate(vals[1:], start=2):
            padded = row + [""] * (len(headers) - len(row))
            result.append((i, dict(zip(headers, padded))))
        return result

    # Content
    def get_all_content_with_row(self):
        return self._all_with_row(self._get_ws("Content", CONTENT_HEADERS), CONTENT_HEADERS)

    def get_all_content(self):
        return [r for _, r in self.get_all_content_with_row()]

    def append_content_rows(self, rows: list):
        ws = self._get_ws("Content", CONTENT_HEADERS)
        body = [[r.get(h,"") for h in CONTENT_HEADERS] for r in rows]
        if body: ws.append_rows(body, value_input_option="USER_ENTERED")

    def reset_status(self, row_indices: list, new_status: str = "đợi đăng"):
        ws = self._get_ws("Content", CONTENT_HEADERS)
        col = CONTENT_HEADERS.index("Trạng thái") + 1
        for idx in row_indices:
            ws.update_cell(idx, col, new_status)

    def delete_rows(self, sheet_name: str, row_indices: list):
        ss = self._get_ss()
        ws = ss.worksheet(sheet_name)
        for idx in sorted(row_indices, reverse=True):
            ws.delete_rows(idx)

    # Pages
    def get_all_pages_with_row(self):
        return self._all_with_row(self._get_ws("Page", PAGE_HEADERS), PAGE_HEADERS)

    def get_all_pages(self):
        return [r for _, r in self.get_all_pages_with_row()]

    def append_page(self, data: dict):
        ws = self._get_ws("Page", PAGE_HEADERS)
        ws.append_row([data.get(h, data.get(k,"")) for h,k in [
            ("Tên trang","name"),("ID","pid"),("Token","token"),("Proxy","proxy"),
            ("Kênh TikTok","channels"),("Link chặn cuối","stop_links"),
            ("Số clip/ngày","clips"),("Giờ chặn cuối","end_time")
        ]])

    def update_page_row(self, row_idx: int, data: dict):
        ws = self._get_ws("Page", PAGE_HEADERS)
        vals = [data.get(h, data.get(k,"")) for h,k in [
            ("Tên trang","name"),("ID","pid"),("Token","token"),("Proxy","proxy"),
            ("Kênh TikTok","channels"),("Link chặn cuối","stop_links"),
            ("Số clip/ngày","clips"),("Giờ chặn cuối","end_time")
        ]]
        ws.update(f"A{row_idx}:H{row_idx}", [vals])
