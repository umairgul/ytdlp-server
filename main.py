from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
import yt_dlp
import json
import os
import asyncio
import re
import uuid

app = FastAPI()

app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")

origins = [
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class FetchRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    video_id: str
    format_id: str
    title: str = None
    extension: str = None
    unique_id: str = None

# fetch info endpoint
@app.post("/fetch")
def fetchInfo(request: FetchRequest):
    if not request.url:
        return {"error": "URL is required"}

    url = request.url
    format_values = list()

    unique_id = str(uuid.uuid4())

    fetch_opts = {
        "quite": True,
        "skip_download": True,
        "writeinfojson": True,
        "overwrite": True,
        "outtmpl" : f"{unique_id}.%(ext)s",
    }

    try:
        with yt_dlp.YoutubeDL(fetch_opts) as ydl:
            ydl.download([url])
            try:
                with open(f"{unique_id}.info.json", "r", encoding="utf8") as info_file:
                    video_info = json.load(info_file)
            except FileNotFoundError as error:
                return {"error": str(error)}

            if 'formats' in video_info:
                for fmt in video_info.get('formats'):
                    if fmt.get('height') and fmt.get('vcodec') != 'none' and fmt.get('ext') != 'mp4':
                        format_values.append({"format_id": f"{fmt.get('format_id')}", "text": f"{fmt.get('format_note')} | {fmt.get('fps', 'N/A')} fps | Resolution: {fmt.get('resolution', 'N/A')}", "height": fmt.get('height')})

                if len(format_values) == 0:
                    for fmt in video_info.get('formats'):
                        if fmt.get('height') and fmt.get('vcodec') != 'none':
                            format_values.append({"format_id": f"{fmt.get('format_id')}", "text": f"{fmt.get('format_note')} | {fmt.get('fps', 'N/A')} fps | Resolution: {fmt.get('resolution', 'N/A')}", "height": fmt.get('height')})
                # print(format_values)
                return {
                    "id": video_info.get('id', ''),
                    "title": video_info.get('title', ''),
                    "extension": video_info.get('ext'),
                    "thumbnail": video_info.get('thumbnail', ''),
                    "formats": format_values,
                    "unique_id": unique_id,
                }
            else:
                return {"error": "No formats found in video info"}
    except Exception as error:
        return {"error": str(error)}

@app.post("/download")
def downloadVideo(request: DownloadRequest):
    if not request.video_id or not request.format_id:
        return {"error": "Video ID and format are required"}

    format_id = request.format_id
    unique_id = request.unique_id
    title = sanitize_filename(request.title)
    extension = sanitize_filename(request.extension)

    file_path = os.getcwd()

    ydl_opts = {
        "load_info_filename": True,
        'format': f'{format_id}+bestaudio/{format_id}+best[acodec!=none]/best',
        'outtmpl': f"{file_path}/downloads/{title}.{extension}",
        'progress_hooks': [download_progress_hook],
        'postprocessor_hooks': [download_postprocessor_hook],
        'quiet': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download_with_info_file(f"{file_path}/{unique_id}.info.json")
            return {
                "status": "success",
                "message": "Download completed",
                "file_path": url_for('downloads', path=f"/downloads/{title}.{extension}")
            }
        except Exception as error:
            return {"error": str(error)}

@app.get("/progress")
async def progress_stream(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break

            yield {
                "event": "progress",
                "data": json.dumps(progress_data)
            }
            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())

#hooks
progress_data = {
    "status": "idle",
    "percent": 0.0,
    "message": "Waiting..."
}

def download_progress_hook(p):
    if p['status'] == 'finished':
        progress_data["status"] = "finished"
        progress_data["percent"] = 100.0
        progress_data["message"] = "Download completed, Finishing"
    elif p['status'] == 'downloading':
        total_bytes = p.get('total_bytes') or p.get('total_bytes_estimate')
        downloaded_bytes = p.get('downloaded_bytes')

        percent_downloaded = 0
        if total_bytes:
            percent_downloaded = (downloaded_bytes / total_bytes) * 100

        progress_data["status"] = "downloading"
        progress_data["percent"] = round(percent_downloaded, 2)
        progress_data["message"] = "Downloading..."

def download_postprocessor_hook(p):
    if p['status'] == 'finished':
        progress_data["status"] = "finished"
        progress_data["percent"] = 100.0
        progress_data["message"] = "Download completed"
#end hooks
def sanitize_filename(filename):
    filename = re.sub(r'[<>:"/\\|?*\s]', '_', filename)
    filename = re.sub(r'_+', '_', filename)  # Replace multiple underscores with single
    filename = filename.strip(' ._')
    return filename