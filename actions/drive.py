"""actions/drive.py — Google Drive (list / search / read / upload)."""
from googleapiclient.discovery import build

import google_oauth


def _service():
    creds = google_oauth.get_credentials()
    if not creds:
        raise RuntimeError(
            "Google is not authorized yet. Run 'google_auth' first.")
    return build("drive", "v3", credentials=creds)


TEXT_MIME = {
    "text/plain", "text/html", "text/csv",
    "application/pdf", "application/rtf",
    "text/markdown", "application/vnd.google-apps.document",
}
GOOGLE_DOC = "application/vnd.google-apps.document"
GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"


def drive_action(parameters: dict, response=None, player=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()
    try:
        svc = _service()

        if action in ("list", "recent"):
            q = params.get("query", "")
            query_str = f"name contains '{q}'" if q else ""
            results = svc.files().list(
                q=query_str or None,
                pageSize=int(params.get("max_results", 10) or 10),
                fields="files(id,name,mimeType,modifiedTime,size)",
                orderBy="modifiedTime desc",
            ).execute().get("files", [])
            if not results:
                return "No files found on Drive, sir."
            lines = ["📁 Drive files:"]
            for f in results:
                size = f.get("size", 0)
                size_s = f"{int(size) / 1024:.0f}KB" if size else ""
                kind = f["mimeType"].split(".")[-1]
                lines.append(f"• {f.get('name')}  ({kind}) {size_s}")
            return "\n".join(lines)

        if action == "search":
            q = str(params.get("query", "")).strip()
            if not q:
                return "I need a search query, sir."
            results = svc.files().list(
                q=f"name contains '{q}'",
                pageSize=10,
                fields="files(id,name,mimeType)",
            ).execute().get("files", [])
            if not results:
                return f"No Drive files matching '{q}', sir."
            lines = [f"Results for '{q}':"]
            for f in results:
                lines.append(f"• {f.get('name')}  (id: {f.get('id')})")
            return "\n".join(lines)

        if action in ("read", "view", "open"):
            file_id = str(params.get("file_id", "")).strip()
            if not file_id:
                return "I need file_id, sir. Use 'drive search' to find it."
            meta = svc.files().get(
                fileId=file_id, fields="name,mimeType,size").execute()
            mime = meta.get("mimeType", "")
            if mime == GOOGLE_DOC:
                exported = svc.files().export(
                    fileId=file_id, mimeType="text/plain").execute()
                return (f'📄 {meta.get("name")}:\n'
                        + (exported.decode("utf-8", errors="replace")[:3000]))
            if mime in TEXT_MIME:
                data = svc.files().get_media(fileId=file_id).execute()
                return (f'📄 {meta.get("name")}:\n'
                        + data.decode("utf-8", errors="replace")[:3000])
            return (f'📄 {meta.get("name")} ({mime}). '
                    "Not a text file — download it on the PC if needed.")

        if action in ("upload", "create", "new"):
            name = str(params.get("name", "")).strip()
            content = str(params.get("content", "")).strip()
            if not name:
                return "I need a file name, sir."
            if not content:
                return "I need the file content, sir."
            from googleapiclient.http import MediaIoBaseUpload
            import io
            media = MediaIoBaseUpload(
                io.BytesIO(content.encode("utf-8")),
                mimetype="text/plain", resumable=False)
            created = svc.files().create(
                body={"name": name, "mimeType": "text/plain"},
                media_body=media, fields="id,name").execute()
            return f'✅ Uploaded "{created.get("name")}" to Drive (id: {created.get("id")}).'

        return f"Unknown drive action: {action}. Use list | search | read | upload."
    except Exception as e:
        return f"Drive error: {e}"