import time
import uuid

import httpx

base = "http://127.0.0.1:8080"
c = httpx.Client(timeout=60)
print("sqli_login", c.post(base + "/api/v1/auth/login", json={"username": "' OR 1=1 -- ", "password": "x"}).status_code)
tok = c.post(base + "/api/v1/auth/login", json={"username": "admin", "password": "Admin@12345"}).json()["data"]["access_token"]
h = {"Authorization": f"Bearer {tok}"}
print("sqli_search", c.get(base + "/api/v1/rag/search", params={"q": "'; DROP TABLE kb_file; --"}, headers=h).status_code)
print("sqli_title", c.post(base + "/api/v1/conversations", json={"title": "<img src=x onerror=alert(1)> ' OR 1=1"}, headers=h).status_code)
bad = c.post(base + "/api/v1/kb/files", headers=h, files={"file": ("evil.php", b"<?php echo 1;?>", "application/x-php")})
print("upload_php", bad.status_code)
name = f"p8-bypass-{uuid.uuid4().hex[:6]}.php.pdf"
up = c.post(base + "/api/v1/kb/files", headers=h, files={"file": (name, b"<?php echo 1;?>", "application/pdf")})
print("upload_double_ext", up.status_code, up.text[:120])
fid = up.json()["data"]["id"] if up.status_code == 200 else None
if fid:
    row = None
    for _ in range(30):
        row = next(x for x in c.get(base + "/api/v1/kb/files", params={"size": 100}, headers=h).json()["data"]["items"] if x["id"] == fid)
        if row["parse_status"] in ("success", "failed"):
            break
        time.sleep(2)
    print("double_ext_status", row["parse_status"])
    c.delete(base + f"/api/v1/kb/files/{fid}", headers=h)
print("download_traversal", c.get(base + "/api/v1/kb/files/../../etc/passwd/download", headers=h).status_code)
