import asyncio
import base64
import math
import os
import platform
import re
import shutil
import sqlite3
import threading
import time
import unicodedata
import uuid
from collections import defaultdict, deque
import random
from datetime import datetime, timedelta

import cv2
import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from ultralytics import YOLO

app = FastAPI(title="UTT SAFETY COMMAND CENTER")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
TEMP_DIR = os.path.join(BASE_DIR, "temp_videos")
os.makedirs(TEMP_DIR, exist_ok=True)
PREFER_CUDA = os.getenv("UTT_PREFER_CUDA", "1").strip().lower() not in {"0", "false", "no"}
runtime_state = {
    "device": "cpu",
    "device_detail": "CPUExecutionProvider",
    "provider": "pytorch",
    "warmup_done": False,
    "warmup_ms": None,
    "preferred_cuda": PREFER_CUDA,
    "torch_cuda_available": bool(torch.cuda.is_available()),
}

PPE_MODEL_PATH = os.path.join(MODELS_DIR, "best.pt")
SIGN_MODEL_PATH = os.path.join(MODELS_DIR, "cone_sign.pt")
DEFAULT_VIDEO_PATH = os.path.join(BASE_DIR, "video6677.mp4")

def get_vietnam_time():
    """Lấy thời gian hiện tại theo múi giờ Việt Nam (UTC+7)"""
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=7)))

if not os.path.exists(PPE_MODEL_PATH):
    PPE_MODEL_PATH = os.path.join(MODELS_DIR, "best.onnx")
if not os.path.exists(SIGN_MODEL_PATH):
    SIGN_MODEL_PATH = os.path.join(MODELS_DIR, "cone_sign.onnx")

if PPE_MODEL_PATH.endswith(".pt") and torch.cuda.is_available() and PREFER_CUDA:
    runtime_state["device"] = "cuda:0"
    runtime_state["device_detail"] = torch.cuda.get_device_name(0)
    runtime_state["provider"] = "pytorch-cuda"
elif PPE_MODEL_PATH.endswith(".pt"):
    runtime_state["device"] = "cpu"
    runtime_state["device_detail"] = "PyTorch CPU"
    runtime_state["provider"] = "pytorch-cpu"
else:
    runtime_state["device"] = "cpu"
    runtime_state["device_detail"] = "ONNX Runtime CPU"
    runtime_state["provider"] = "onnxruntime-cpu"

print("[AI] Loading models...")
model_ppe = YOLO(PPE_MODEL_PATH)
model_sign = YOLO(SIGN_MODEL_PATH)
if runtime_state["device"].startswith("cuda"):
    try:
        model_ppe.to(runtime_state["device"])
        model_sign.to(runtime_state["device"])
    except Exception as exc:
        runtime_state["device"] = "cpu"
        runtime_state["device_detail"] = f"GPU fallback to CPU: {exc}"
        runtime_state["provider"] = "pytorch-cpu"
print("[AI] Ready (PPE + Sign).")

DB_PATH = os.path.join(MODELS_DIR, "safety_logs.db")
VIOLATION_LOG_PATH = os.path.join(BASE_DIR, "violation_log.txt")

DEFAULT_DELAY_SEC = 3.0
DEFAULT_PIPELINE = "direct"
FRAME_RETENTION_SEC = 45.0
PPE_ALERT_DELAY_SEC = 2.0
PPE_ALERT_COOLDOWN_SEC = 2.0
SIGN_SCAN_INTERVAL_SEC = 60.0
PRIMARY_CAMERA_OPTIONS = {"1"}
PPE_TRACK_CONF = 0.25
WS_TRACK_CONF = 0.20
SIGN_CONF = 0.50
PPE_IMGSZ = 960
WS_INPUT_WIDTH = 512
PERSON_CONF_MIN = 0.45
HELMET_CONF_MIN = 0.35
VEST_CONF_MIN = 0.35
MIN_PERSON_HEIGHT_RATIO = 0.12
MIN_PERSON_AREA_RATIO = 0.02
FRAME_BLUR_MIN = 45.0
FRAME_MOTION_MAX = 26.0
FRAME_STALE_MAX_SEC = 0.45
DECISION_WINDOW_SEC = 2.0
DECISION_MIN_SAMPLES = 5
DECISION_MISSING_RATIO = 0.70
DECISION_CLEAR_RATIO = 0.35
DECISION_RECOVERY_SEC = 1.0
DECISION_MAX_TRACK_IDLE_SEC = 3.0

system_logs = []
decision_metrics = defaultdict(int)


def default_person_state():
    return {
        "last_alert": 0.0,
        "status": "ok",
        "samples": deque(maxlen=90),
        "missing_started_at": 0.0,
        "clear_started_at": 0.0,
        "last_seen": 0.0,
    }


person_states = defaultdict(default_person_state)
camera_states = defaultdict(lambda: {
    "last_sign_scan": 0.0,
    "roi_polygon": None,
    "last_points": [],
    "browser_frame": None,
    "browser_frame_source": "",
    "browser_frame_ts": 0.0,
    "last_gray": None,
    "last_motion": 0.0,
})

frame_db_lock = threading.Lock()
iphone_state_lock = threading.Lock()
sender_sessions_lock = threading.Lock()

iphone_stream_state = {
    "device_name": "iPhone (not connected)",
    "last_ts": 0.0,
    "captured_at": 0.0,
    "last_frame_jpg": None,
    "last_frame": None,
}
sender_sessions = {}
primary_camera_lock = threading.Lock()
primary_camera_state = {"cam_id": "1"}

PPE_CLASS_IDS = {
    "person": set(),
    "helmet": set(),
    "vest": set(),
    "no_helmet": set(),
    "no_vest": set(),
}



def init_db() -> None:
    print("[DB] Initializing database...")
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            track_id  INTEGER,
            type      TEXT,
            detail    TEXT,
            camera    TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS camera_frames (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            camera    TEXT,
            ts        REAL,
            frame_jpg BLOB
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_camera_ts ON camera_frames(camera, ts)")
    conn.commit()
    conn.close()


def normalize_name(name: str) -> str:
    raw = str(name).strip().lower().replace("-", " ").replace("_", " ")
    folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.split())


def is_person_class(class_name: str, class_idx: int) -> bool:
    return (
        "person" in class_name
        or "worker" in class_name
        or "human" in class_name
        or class_name == "people"
        or "nguoi" in class_name
        or "man" in class_name
        or "woman" in class_name
    )


def is_helmet_class(class_name: str) -> bool:
    return (
        "helmet" in class_name
        or "hardhat" in class_name
        or "hard hat" in class_name
        or class_name == "hat"
        or "mu" in class_name
    ) and "no " not in class_name and "without" not in class_name and "missing" not in class_name


def is_vest_class(class_name: str) -> bool:
    return (
        "vest" in class_name
        or "jacket" in class_name
        or "safety vest" in class_name
        or "ao" in class_name
        or "reflective" in class_name
        or "gile" in class_name
    ) and "no " not in class_name and "without" not in class_name and "missing" not in class_name


def is_no_helmet_class(class_name: str) -> bool:
    return (
        "no helmet" in class_name
        or "no hardhat" in class_name
        or "without helmet" in class_name
        or "missing helmet" in class_name
        or "khong mu" in class_name
        or "no mu" in class_name
    )


def is_no_vest_class(class_name: str) -> bool:
    return (
        "no vest" in class_name
        or "without vest" in class_name
        or "missing vest" in class_name
        or "no safety vest" in class_name
        or "khong ao" in class_name
        or "no ao" in class_name
        or "without jacket" in class_name
    )


def init_ppe_class_ids() -> None:
    names_map = model_ppe.names if isinstance(model_ppe.names, dict) else {i: n for i, n in enumerate(model_ppe.names)}
    for cls_idx, cls_name_raw in names_map.items():
        idx = int(cls_idx)
        cls_name = normalize_name(cls_name_raw)
        if is_person_class(cls_name, idx):
            PPE_CLASS_IDS["person"].add(idx)
        if is_helmet_class(cls_name):
            PPE_CLASS_IDS["helmet"].add(idx)
        if is_vest_class(cls_name):
            PPE_CLASS_IDS["vest"].add(idx)
        if is_no_helmet_class(cls_name):
            PPE_CLASS_IDS["no_helmet"].add(idx)
        if is_no_vest_class(cls_name):
            PPE_CLASS_IDS["no_vest"].add(idx)

    if not PPE_CLASS_IDS["person"]:
        PPE_CLASS_IDS["person"].add(0)

    print("[PPE Class Map]", {k: sorted(v) for k, v in PPE_CLASS_IDS.items()})


def append_violation_file(track_id: int, camera: str, violation: str, clock_time: str) -> None:
    line = f"{track_id} | {camera} | {violation} | {clock_time}\n"
    with open(VIOLATION_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


# Queue for background DB writes
log_queue = deque()
frame_queue = deque()

def db_worker():
    while True:
        try:
            # 1. Process Logs
            while log_queue:
                log_data = log_queue.popleft()
                try:
                    conn = sqlite3.connect(DB_PATH, timeout=20)
                    conn.execute("PRAGMA journal_mode=WAL;")
                    conn.execute(
                        "INSERT INTO logs (timestamp, track_id, type, detail, camera) VALUES (?,?,?,?,?)",
                        (log_data["timestamp"], log_data["track_id"], log_data["type"], log_data["detail"], log_data["camera"]),
                    )
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"[Worker Log Error] {e}")

            # 2. Process Frames
            while frame_queue:
                frame_data = frame_queue.popleft()
                try:
                    conn = sqlite3.connect(DB_PATH, timeout=20)
                    conn.execute("PRAGMA journal_mode=WAL;")
                    conn.execute("INSERT INTO camera_frames (camera, ts, frame_jpg) VALUES (?,?,?)", 
                                 (frame_data["camera"], frame_data["ts"], frame_data["payload"]))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    pass # Ignore frame write errors if too busy

            # 3. Cleanup old frames periodically
            if time.time() % 60 < 1.0:
                try:
                    cutoff = time.time() - FRAME_RETENTION_SEC
                    conn = sqlite3.connect(DB_PATH, timeout=20)
                    conn.execute("PRAGMA journal_mode=WAL;")
                    conn.execute("DELETE FROM camera_frames WHERE ts < ?", (cutoff,))
                    conn.commit()
                    conn.close()
                except:
                    pass

        except Exception as e:
            print(f"[Worker Global Error] {e}")
        
        time.sleep(0.1)

# Start background thread
threading.Thread(target=db_worker, daemon=True).start()

def add_log(track_id: int, violation_type: str, detail: str = "", camera: str = "CAM 01") -> None:
    now = get_vietnam_time()
    # Bao gồm cả ngày và giờ (Build 58)
    ts_full = now.strftime("%Y-%m-%d %H:%M:%S")
    
    log_queue.append({
        "timestamp": ts_full,
        "track_id": track_id,
        "type": violation_type,
        "detail": detail,
        "camera": camera
    })

    try:
        append_violation_file(track_id, camera, f"{violation_type}: {detail}", ts_full)
    except:
        pass

    system_logs.insert(0, {"time": ts_full, "id": track_id, "type": violation_type, "detail": detail, "camera": camera})
    if len(system_logs) > 100: system_logs.pop()


def box_center(box):
    return (float(box[0] + box[2]) / 2.0, float(box[1] + box[3]) / 2.0)


def child_inside_person(child_box, person_box):
    cx, cy = box_center(child_box)
    return person_box[0] <= cx <= person_box[2] and person_box[1] <= cy <= person_box[3]


def overlap_ratio(child_box, person_box):
    x_left = max(child_box[0], person_box[0])
    y_top = max(child_box[1], person_box[1])
    x_right = min(child_box[2], person_box[2])
    y_bottom = min(child_box[3], person_box[3])
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0
    inter = (x_right - x_left) * (y_bottom - y_top)
    child_area = max(1.0, (child_box[2] - child_box[0]) * (child_box[3] - child_box[1]))
    return inter / child_area


def associated_to_person(child_box, person_box):
    return child_inside_person(child_box, person_box) or overlap_ratio(child_box, person_box) >= 0.10


def point_in_polygon(point_xy, polygon):
    if not polygon:
        return True
    poly = np.array(polygon, dtype=np.int32)
    return cv2.pointPolygonTest(poly, point_xy, False) >= 0


def store_frame_in_db(camera: str, frame, ts: float) -> None:
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
    if not ok: return
    frame_queue.append({"camera": camera, "ts": ts, "payload": encoded.tobytes()})
    if len(frame_queue) > 50: frame_queue.popleft() # Limit queue size


def load_delayed_frame_from_db(camera: str, delay_sec: float):
    target_ts = time.time() - max(0.0, delay_sec)
    with frame_db_lock:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=20)
            conn.execute("PRAGMA journal_mode=WAL;")
            row = conn.execute(
                "SELECT frame_jpg FROM camera_frames WHERE camera = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                (camera, target_ts),
            ).fetchone()
            conn.close()
        except Exception:
            return None
    if not row:
        return None

    data = row[0]
    if not data:
        return None
    nparr = np.frombuffer(data, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)


def save_iphone_frame(frame, device_name: str = "", jpeg_bytes: bytes | None = None):
    with iphone_state_lock:
        if device_name:
            iphone_stream_state["device_name"] = device_name
        iphone_stream_state["last_ts"] = time.time()
        iphone_stream_state["last_frame"] = frame.copy()
        iphone_stream_state["last_frame_jpg"] = jpeg_bytes


def load_iphone_frame():
    with iphone_state_lock:
        ts = iphone_stream_state["last_ts"]
        # Nếu quá 5 giây không nhận được frame mới -> Coi như ngắt kết nối (Build 50)
        if time.time() - ts > 5.0:
            iphone_stream_state["last_frame_jpg"] = None
            iphone_stream_state["last_frame"] = None
            return None
        frame = iphone_stream_state["last_frame"]
    if frame is None:
        return None
    return frame.copy()


def get_iphone_device_name():
    with iphone_state_lock:
        return iphone_stream_state["device_name"], iphone_stream_state["last_ts"]


def get_iphone_captured_at():
    with iphone_state_lock:
        return float(iphone_stream_state.get("captured_at", 0.0) or 0.0)


def list_temp_video_files():
    exts = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    files = []
    for name in os.listdir(TEMP_DIR):
        full = os.path.join(TEMP_DIR, name)
        if not os.path.isfile(full):
            continue
        if os.path.splitext(name.lower())[1] not in exts:
            continue
        files.append(full)
    return files


def sanitize_upload_filename(filename: str, prefix: str) -> str:
    raw = os.path.basename(str(filename or "").strip())
    stem, ext = os.path.splitext(raw)
    ext = ext.lower()
    safe_stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("._-") or prefix
    return f"{prefix}_{int(time.time())}_{safe_stem}{ext}"


def get_primary_camera_id() -> str:
    with primary_camera_lock:
        cam_id = str(primary_camera_state.get("cam_id", "1"))
    return cam_id if cam_id in PRIMARY_CAMERA_OPTIONS else "1"


def set_primary_camera_id(cam_id: str) -> str:
    normalized = str(cam_id).strip()
    if normalized not in PRIMARY_CAMERA_OPTIONS:
        raise ValueError("primary camera must be '1' or '2'")
    with primary_camera_lock:
        primary_camera_state["cam_id"] = normalized
    return normalized


def get_primary_camera_label() -> str:
    return f"CAM {get_primary_camera_id().zfill(2)}"


def is_primary_camera(cam_id: str) -> bool:
    return str(cam_id).strip() == get_primary_camera_id()


def load_recent_logs_from_db(limit: int = 100):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cleanup_person_states(now_ts: float) -> None:
    stale_keys = [
        key for key, state in person_states.items()
        if state.get("last_seen", 0.0) > 0 and (now_ts - state.get("last_seen", 0.0)) > DECISION_MAX_TRACK_IDLE_SEC
    ]
    for key in stale_keys:
        person_states.pop(key, None)


def evaluate_frame_quality(frame, cam_id: str, captured_at: float | None = None):
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    state = camera_states[cam_id]
    prev_gray = state.get("last_gray")
    motion_score = 0.0
    if prev_gray is not None and prev_gray.shape == gray.shape:
        motion_score = float(np.mean(cv2.absdiff(gray, prev_gray)))
    state["last_gray"] = gray
    state["last_motion"] = motion_score

    frame_age = 0.0
    if captured_at and captured_at > 0:
        frame_age = max(0.0, time.time() - captured_at)

    quality = {
        "blur_score": blur_score,
        "motion_score": motion_score,
        "frame_age": frame_age,
        "usable": True,
        "reason": "",
        "frame_shape": (h, w),
    }

    if frame_age > FRAME_STALE_MAX_SEC:
        quality["usable"] = False
        quality["reason"] = "stale_frame"
        decision_metrics["stale_frame"] += 1
        return quality

    if blur_score < FRAME_BLUR_MIN:
        quality["usable"] = False
        quality["reason"] = "blur_frame"
        decision_metrics["blur_frame"] += 1
        return quality

    if motion_score > FRAME_MOTION_MAX:
        quality["usable"] = False
        quality["reason"] = "motion_frame"
        decision_metrics["motion_frame"] += 1
        return quality

    return quality


def warmup_models() -> None:
    if runtime_state["warmup_done"]:
        return
    try:
        dummy = np.zeros((360, 640, 3), dtype=np.uint8)
        t0 = time.perf_counter()
        _ = model_sign(dummy, conf=SIGN_CONF, verbose=False)
        _ = model_ppe.track(dummy, persist=True, conf=PPE_TRACK_CONF, imgsz=PPE_IMGSZ, verbose=False, tracker="bytetrack.yaml")
        runtime_state["warmup_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        runtime_state["warmup_done"] = True
    except Exception as exc:
        runtime_state["warmup_done"] = False
        runtime_state["device_detail"] = f"{runtime_state['device_detail']} | warmup failed: {exc}"


def choose_loop_video_path():
    files = list_temp_video_files()
    if files:
        # Ưu tiên file mới nhất (dựa trên thời gian chỉnh sửa)
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return files[0]
    return DEFAULT_VIDEO_PATH

# --- HỆ THỐNG QUẢN LÝ 12 CAMERA ĐỒNG BỘ ---
_GLOBAL_SLOTS = {i: {"type": "loop", "frame": None, "session_id": None, "released_at": 0.0} for i in range(1, 13)}
_GLOBAL_LOCK = threading.Lock()
_LOOP_FRAMES = {i: None for i in range(1, 13)}

def get_slot_video_path(slot_id: int):
    """Tìm video trong thư mục camX tương ứng. CAM 1 là luồng live (0)"""
    if slot_id == 1:
        print(f"[DebugPath] Slot 1 -> Live Webcam (0)")
        return 0  # Luồng live trực tiếp từ webcam
        
    cam_dir = os.path.join(TEMP_DIR, f"cam{slot_id}")
    exts = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    if os.path.exists(cam_dir):
        files = [os.path.join(cam_dir, f) for f in os.listdir(cam_dir) 
                 if os.path.splitext(f.lower())[1] in exts]
        if files:
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            path = files[0]
            # CHỈ LOG KHI CÓ THAY ĐỔI HOẶC ĐỂ DEBUG
            if slot_id <= 3 or slot_id >= 10: 
                display_path = os.path.basename(path) if isinstance(path, str) else str(path)
                print(f"[DebugPath] Slot {slot_id} -> {display_path}")
            return path
    return DEFAULT_VIDEO_PATH

def background_loop_reader():
    """Luồng chạy ngầm tích hợp AI quét vòng tròn cho 12 camera (Tối ưu Build 56)"""
    global _LOOP_FRAMES
    caps = {i: None for i in range(1, 13)}
    current_paths = {i: None for i in range(1, 13)}
    path_cache = {i: {"path": None, "last_check": 0.0} for i in range(1, 13)}
    
    time.sleep(5) # Chờ app khởi động hoàn tất
    print("[MultiLoop] 12-Camera loop reader started (Optimized).")
    
    while True:
        now_ts = time.time()
        try:
            for i in range(1, 13):
                try:
                    # Tối ưu: Chỉ quét lại đường dẫn sau mỗi 30s
                    cache = path_cache[i]
                    if now_ts - cache["last_check"] > 30.0 or cache["path"] is None:
                        cache["path"] = get_slot_video_path(i)
                        cache["last_check"] = now_ts
                    
                    target_path = cache["path"]
                    
                    # Nếu đường dẫn thay đổi hoặc capture bị hỏng
                    if target_path != current_paths[i] or caps[i] is None:
                        if caps[i] is not None: caps[i].release()
                        if target_path == 0:
                            # Sử dụng CAP_DSHOW nếu trên Windows để giảm độ trễ
                            if platform.system() == "Windows":
                                caps[i] = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                            else:
                                caps[i] = cv2.VideoCapture(0)
                        else:
                            caps[i] = cv2.VideoCapture(target_path)
                        current_paths[i] = target_path
                    
                    if caps[i] is not None and caps[i].isOpened():
                        ret, frame = caps[i].read()
                        if not ret: # Reset video khi kết thúc
                            caps[i].set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ret, frame = caps[i].read()
                        
                        if ret and frame is not None:
                            # Cập nhật frame vào bộ nhớ dùng chung
                            _LOOP_FRAMES[i] = frame.copy()
                            
                    time.sleep(0.005) # Nghỉ cực ngắn để chuyển cam tiếp theo
                except: pass
            
            # Sau mỗi vòng quét, kiểm tra các session hết hạn
            stream_manager.check_dead_sessions()
            time.sleep(0.1) # Nghỉ nhẹ giữa các vòng lặp lớn
        except Exception as e:
            time.sleep(2)

# Thread start moved to end of file to prevent startup race conditions

class GlobalStreamManager:
    def __init__(self):
        self.instance_id = str(uuid.uuid4())[:8]
        print(f"[StreamManager] New Instance Created: {self.instance_id}")
        
    def set_live_frame(self, slot_id, frame, session_id):
        with _GLOBAL_LOCK:
            if 1 <= slot_id <= 12:
                # Strict ownership check
                slot = _GLOBAL_SLOTS[slot_id]
                if slot["session_id"] == session_id:
                    slot["frame"] = frame.copy()
                    slot["type"] = "live"

    def release_slot(self, session_id):
        with _GLOBAL_LOCK:
            for i in range(1, 13):
                if _GLOBAL_SLOTS[i]["session_id"] == session_id:
                    print(f"[StreamManager] Releasing Slot {i} for session {session_id[:8]}")
                    # CLEAR EVERYTHING IMMEDIATELY
                    _GLOBAL_SLOTS[i] = {
                        "type": "loop", 
                        "frame": None, 
                        "session_id": None,
                        "released_at": time.time()
                    }
                    camera_states[str(i)]["browser_frame"] = None

    def check_dead_sessions(self):
        now = time.time()
        with _GLOBAL_LOCK:
            for i in range(1, 13):
                slot = _GLOBAL_SLOTS[i]
                sid = slot["session_id"]
                if sid:
                    # Kiểm tra heartbeat trong sender_sessions
                    with sender_sessions_lock:
                        sess = sender_sessions.get(sid)
                        if not sess or (now - sess.get("last_seen", 0)) > 6.0:
                            print(f"[StreamManager] Session {sid[:8]} timed out. Releasing Slot {i}")
                            _GLOBAL_SLOTS[i] = {
                                "type": "loop", 
                                "frame": None, 
                                "session_id": None,
                                "released_at": now
                            }
                            camera_states[str(i)]["browser_frame"] = None

    def get_frame(self, slot_id):
        with _GLOBAL_LOCK:
            slot = _GLOBAL_SLOTS[slot_id]
            if slot["type"] == "live" and slot["frame"] is not None:
                return slot["frame"]
        return _LOOP_FRAMES.get(slot_id)

    def get_available_slot(self, session_id, device_name="Remote"):
        now = time.time()
        with _GLOBAL_LOCK:
            target_slot = -1
            # Tìm ô trống thực sự (không có session_id và đã qua thời gian chờ)
            for i in range(1, 13):
                slot = _GLOBAL_SLOTS[i]
                if slot["session_id"] is None and (now - slot["released_at"]) > 3.0:
                    target_slot = i
                    break
            
            # Nếu tất cả các ô đều đang chờ hoặc đầy, lấy ô cũ nhất (đã ngắt kết nối lâu nhất)
            if target_slot == -1:
                target_slot = 1
                min_release = now
                for i in range(1, 13):
                    if _GLOBAL_SLOTS[i]["session_id"] is None:
                        if _GLOBAL_SLOTS[i]["released_at"] < min_release:
                            min_release = _GLOBAL_SLOTS[i]["released_at"]
                            target_slot = i
            
            # Chiếm giữ ô
            _GLOBAL_SLOTS[target_slot] = {
                "type": "live", 
                "frame": None, 
                "session_id": session_id,
                "device_name": device_name,
                "released_at": 0.0
            }
            return target_slot

    def claim_fixed_slot(self, slot_id: int, session_id: str, device_name: str = "Remote"):
        now = time.time()
        with _GLOBAL_LOCK:
            if not (1 <= slot_id <= 12):
                return None, "Invalid slot"
            slot = _GLOBAL_SLOTS[slot_id]
            existing_sid = slot.get("session_id")
            if existing_sid and existing_sid != session_id:
                return None, f"CAM {slot_id:02d} is already in use"
            _GLOBAL_SLOTS[slot_id] = {
                "type": "live",
                "frame": None,
                "session_id": session_id,
                "device_name": device_name,
                "released_at": now,
            }
            return slot_id, ""

stream_manager = GlobalStreamManager()

def parse_violation_log(limit: int = 1000):
    if not os.path.exists(VIOLATION_LOG_PATH):
        return []
    rows = deque(maxlen=limit)
    with open(VIOLATION_LOG_PATH, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 4:
                continue
            rows.append({"id": parts[0], "camera": parts[1], "violation": parts[2], "time": parts[3]})
    return list(rows)


def build_roi_polygon(sign_points):
    if len(sign_points) < 3:
        return None
    points = np.array(sign_points, dtype=np.int32)
    hull = cv2.convexHull(points)
    return hull.reshape(-1, 2).tolist()


def roi_is_usable(roi_polygon, frame_shape):
    if not roi_polygon:
        return False
    h, w = frame_shape[:2]
    frame_area = float(w * h)
    if frame_area <= 0:
        return False
    poly = np.array(roi_polygon, dtype=np.int32)
    roi_area = float(abs(cv2.contourArea(poly)))
    return roi_area / frame_area >= 0.02


def render_roi_overlay(frame, roi_polygon):
    if not roi_polygon:
        return frame
    poly = np.array(roi_polygon, dtype=np.int32)
    overlay = frame.copy()
    cv2.fillPoly(overlay, [poly], (60, 140, 255))
    frame = cv2.addWeighted(overlay, 0.20, frame, 0.80, 0)
    cv2.polylines(frame, [poly], isClosed=True, color=(255, 230, 120), thickness=2)
    return frame


def draw_error_frame(message: str, width: int = 960, height: int = 540):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(frame, "CAMERA ERROR", (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
    cv2.putText(frame, message, (40, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 240, 240), 2)
    return frame


def label_with_background(frame, text, top_left, color):
    x, y = top_left
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.62, 2)
    y1 = max(0, y - th - 10)
    cv2.rectangle(frame, (x, y1), (x + tw + 10, y), color, -1)
    cv2.putText(frame, text, (x + 5, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)


def extract_person_id(box_obj, box_xyxy, index: int) -> int:
    if hasattr(box_obj, 'id') and box_obj.id is not None:
        try:
            return int(box_obj.id[0])
        except:
            pass
    return -1


def evaluate_ppe_detections(detection_result, show_helmet: bool, show_vest: bool):
    persons, helmets, vests, no_helmets, no_vests = [], [], [], [], []
    if detection_result[0].boxes is None:
        return [], helmets, vests

    for i, box_obj in enumerate(detection_result[0].boxes):
        cls_idx = int(box_obj.cls[0])
        cls_name = normalize_name(model_ppe.names[cls_idx])
        box = box_obj.xyxy[0].tolist()
        conf = float(box_obj.conf[0]) if hasattr(box_obj, "conf") and box_obj.conf is not None else 0.0

        if cls_idx in PPE_CLASS_IDS["person"] or is_person_class(cls_name, cls_idx):
            persons.append({"id": extract_person_id(box_obj, box, i), "box": box, "conf": conf})
        elif cls_idx in PPE_CLASS_IDS["helmet"] or is_helmet_class(cls_name):
            helmets.append({"box": box, "conf": conf})
        elif cls_idx in PPE_CLASS_IDS["vest"] or is_vest_class(cls_name):
            vests.append({"box": box, "conf": conf})
        elif cls_idx in PPE_CLASS_IDS["no_helmet"] or is_no_helmet_class(cls_name):
            no_helmets.append({"box": box, "conf": conf})
        elif cls_idx in PPE_CLASS_IDS["no_vest"] or is_no_vest_class(cls_name):
            no_vests.append({"box": box, "conf": conf})

    entries = []
    for p in persons:
        pbox = p["box"]
        has_helmet = any(h["conf"] >= HELMET_CONF_MIN and associated_to_person(h["box"], pbox) for h in helmets) if show_helmet else True
        has_vest = any(v["conf"] >= VEST_CONF_MIN and associated_to_person(v["box"], pbox) for v in vests) if show_vest else True
        if show_helmet and any(h["conf"] >= HELMET_CONF_MIN and associated_to_person(h["box"], pbox) for h in no_helmets):
            has_helmet = False
        if show_vest and any(v["conf"] >= VEST_CONF_MIN and associated_to_person(v["box"], pbox) for v in no_vests):
            has_vest = False

        missing = []
        if show_helmet and not has_helmet:
            missing.append("Helmet")
        if show_vest and not has_vest:
            missing.append("Vest")

        entries.append(
            {
                "id": p["id"],
                "box": pbox,
                "conf": p.get("conf", 0.0),
                "is_valid": len(missing) == 0,
                "missing": missing,
                "label": f"WORKER #{p['id']}" if len(missing) == 0 else "KHONG HOP LE",
            }
        )

    return entries, [h["box"] for h in helmets if h["conf"] >= HELMET_CONF_MIN], [v["box"] for v in vests if v["conf"] >= VEST_CONF_MIN]


def should_consider_person(entry, frame_shape):
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = entry["box"]
    person_h = max(1.0, float(y2 - y1))
    person_w = max(1.0, float(x2 - x1))
    area_ratio = (person_h * person_w) / max(1.0, float(h * w))
    height_ratio = person_h / max(1.0, float(h))
    return (
        entry.get("conf", 0.0) >= PERSON_CONF_MIN
        and height_ratio >= MIN_PERSON_HEIGHT_RATIO
        and area_ratio >= MIN_PERSON_AREA_RATIO
    )


def update_decision_state(cam_key: str, person_id: int, is_valid: bool, quality_ok: bool, now: float):
    state_key = f"{cam_key}:ppe:{person_id}"
    state = person_states[state_key]
    state["last_seen"] = now

    if not quality_ok:
        state["samples"].append({"ts": now, "status": "uncertain"})
    else:
        state["samples"].append({"ts": now, "status": "ok" if is_valid else "missing"})

    while state["samples"] and now - state["samples"][0]["ts"] > DECISION_WINDOW_SEC:
        state["samples"].popleft()

    usable_samples = [s for s in state["samples"] if s["status"] != "uncertain"]
    if len(usable_samples) < DECISION_MIN_SAMPLES:
        return {"emit_alert": False, "status": state["status"], "confidence": 0.0}

    missing_count = sum(1 for s in usable_samples if s["status"] == "missing")
    missing_ratio = missing_count / len(usable_samples)
    ok_ratio = 1.0 - missing_ratio

    if missing_ratio >= DECISION_MISSING_RATIO:
        if state["missing_started_at"] <= 0:
            state["missing_started_at"] = now
        if state["status"] == "ok":
            state["status"] = "suspect"
        elif state["status"] == "suspect" and (now - state["missing_started_at"]) >= PPE_ALERT_DELAY_SEC:
            state["status"] = "confirmed"
        state["clear_started_at"] = 0.0
    elif ok_ratio >= DECISION_CLEAR_RATIO:
        if state["clear_started_at"] <= 0:
            state["clear_started_at"] = now
        if state["status"] == "confirmed" and (now - state["clear_started_at"]) >= DECISION_RECOVERY_SEC:
            state["status"] = "cooldown"
        elif state["status"] in {"suspect", "cooldown"} and (now - state["clear_started_at"]) >= DECISION_RECOVERY_SEC:
            state["status"] = "ok"
            state["missing_started_at"] = 0.0
            state["clear_started_at"] = 0.0
    else:
        state["clear_started_at"] = 0.0

    emit_alert = False
    if state["status"] == "confirmed" and (now - state["last_alert"]) >= PPE_ALERT_COOLDOWN_SEC:
        state["last_alert"] = now
        emit_alert = True
        decision_metrics["confirmed_alerts"] += 1

    return {"emit_alert": emit_alert, "status": state["status"], "confidence": missing_ratio}


def process_sign_roi(frame, cam_id: str, show_sign: bool):
    state = camera_states[cam_id]
    now = time.time()
    if show_sign and (now - state["last_sign_scan"] >= SIGN_SCAN_INTERVAL_SEC):
        state["last_sign_scan"] = now
        result = model_sign(frame, conf=SIGN_CONF, verbose=False)
        points = []
        if result[0].boxes is not None:
            for b in result[0].boxes:
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                points.append([cx, cy])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 220), 2)
        state["last_points"] = points
        state["roi_polygon"] = build_roi_polygon(points)
        if not roi_is_usable(state["roi_polygon"], frame.shape):
            state["roi_polygon"] = None

    if state["roi_polygon"]:
        frame = render_roi_overlay(frame, state["roi_polygon"])
    return frame, state["roi_polygon"]


def process_ppe(frame, cam_id: str, show_helmet: bool, show_vest: bool, roi_polygon, captured_at: float | None = None):
    if not (show_helmet or show_vest):
        return frame

    now = time.time()
    frame_quality = evaluate_frame_quality(frame, cam_id, captured_at=captured_at)
    cleanup_person_states(now)

    results = model_ppe.track(frame, persist=True, conf=PPE_TRACK_CONF, imgsz=PPE_IMGSZ, verbose=False, tracker="bytetrack.yaml")
    entries, helmets, vests = evaluate_ppe_detections(results, show_helmet, show_vest)
    
    # Lọc bỏ các mục chưa có ID ổn định từ tracker
    entries = [e for e in entries if e["id"] > 0]

    if show_helmet:
        for box in helmets:
            x1, y1, x2, y2 = map(int, box)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (50, 220, 50), 2)
            label_with_background(frame, "HELMET", (x1, y1), (50, 220, 50))

    if show_vest:
        for box in vests:
            x1, y1, x2, y2 = map(int, box)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 170, 0), 2)
            label_with_background(frame, "VEST", (x1, y1), (255, 170, 0))

    for e in entries:
        pbox = e["box"]
        pid = e["id"]
        cx, cy = box_center(pbox)
        if roi_polygon and not point_in_polygon((cx, cy), roi_polygon):
            continue
        if not should_consider_person(e, frame.shape):
            decision_metrics["filtered_person"] += 1
            continue

        color = (0, 180, 0) if e["is_valid"] else (0, 0, 255)
        x1, y1, x2, y2 = map(int, pbox)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        
        # Ghi rõ ID lên nhãn của người
        label_text = f"WORKER #{pid}" if e["is_valid"] else f"VIOLATION #{pid}"
        label_with_background(frame, label_text, (x1, y1), color)

        decision = update_decision_state(str(cam_id), pid, e["is_valid"], frame_quality["usable"], now)
        if decision["status"] == "suspect":
            label_with_background(frame, "CHECKING...", (x1, max(0, y1 + 26)), (70, 120, 210))
        elif decision["status"] == "confirmed":
            label_with_background(frame, "CONFIRMED", (x1, max(0, y1 + 26)), (0, 0, 255))

        if decision["emit_alert"]:
            detail_msg = f"Missing {', '.join(e['missing'])}"
            add_log(pid, "PPE", detail_msg, camera=f"CAM {cam_id}")

    quality_text = f"blur:{frame_quality['blur_score']:.0f} motion:{frame_quality['motion_score']:.0f} age:{frame_quality['frame_age']:.2f}s"
    cv2.putText(frame, f"P:{len(entries)} H:{len(helmets)} V:{len(vests)}", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, quality_text, (12, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (210, 210, 210), 1)
    return frame




def resolve_source(cam_id: str):
    """Xác định nguồn video cho từng ô (Build 57)"""
    # 1. Ưu tiên luồng đẩy từ trình duyệt (Webcam/Upload)
    if camera_states[cam_id]["browser_frame"] is not None:
        return f"__BROWSER_STREAM_{cam_id}__", ""
    
    # 3. Mặc định: Trả về luồng video loop từ hệ thống 12 ô (Dùng chung cho cả CAM 01)
    # Điều này đảm bảo không bao giờ bị màn hình đen "Camera not found"
    return "__LOOP_STREAM__", ""


def probe_usb_camera():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        return False
    ok, _ = cap.read()
    cap.release()
    return bool(ok)


async def generate_frames(cam_id: str, active_filters: list, use_db_delay: bool = True, delay_sec: float = DEFAULT_DELAY_SEC):
    is_primary_cam = is_primary_camera(cam_id)
    interval = 0.12
    cap = None
    current_capture_key = None
    show_helmet = ("helmet" in active_filters) and is_primary_cam
    show_vest = ("vest" in active_filters) and is_primary_cam
    show_sign = ("sign" in active_filters) and is_primary_cam

    if is_primary_cam and camera_states[cam_id]["last_sign_scan"] == 0:
        camera_states[cam_id]["last_sign_scan"] = time.time() - SIGN_SCAN_INTERVAL_SEC

    try:
        while True:
            t0 = time.time()
            source, source_error = resolve_source(cam_id)
            is_iphone_stream = source == "__IPHONE_STREAM__"
            is_browser_stream = isinstance(source, str) and source.startswith("__BROWSER_STREAM_")
            is_loop_stream = source == "__LOOP_STREAM__"

            if is_iphone_stream or is_browser_stream or is_loop_stream:
                if cap is not None:
                    cap.release()
                    cap = None
                    current_capture_key = None
                interval = 0.05 # Tăng tốc độ mượt cho loop/iphone
            else:
                capture_key = f"{cam_id}:{source}"
                if cap is None or current_capture_key != capture_key:
                    if cap is not None:
                        cap.release()
                    if source == 0:
                        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                    else:
                        cap = cv2.VideoCapture(source)
                    current_capture_key = capture_key

                    if cap is not None and cap.isOpened():
                        fps = cap.get(cv2.CAP_PROP_FPS)
                        if not fps or math.isnan(fps):
                            fps = 25.0
                        if not is_primary_cam:
                            fps = min(fps, 12.0)
                        interval = 1.0 / fps

            if is_iphone_stream:
                frame = load_iphone_frame()
                captured_at = get_iphone_captured_at()
                if frame is None:
                    wait = draw_error_frame("Waiting for iPhone stream")
                    ok, buf = cv2.imencode(".jpg", wait)
                    if ok:
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                    await asyncio.sleep(interval)
                    continue
            elif is_browser_stream:
                frame = camera_states[cam_id]["browser_frame"]
                captured_at = float(camera_states[cam_id].get("browser_frame_ts", 0.0) or 0.0)
                if frame is None:
                    wait = draw_error_frame("Waiting for Browser stream")
                    ok, buf = cv2.imencode(".jpg", wait)
                    if ok:
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                    await asyncio.sleep(0.2)
                    continue
                browser_frame_source = camera_states[cam_id].get("browser_frame_source", "")
            elif is_loop_stream:
                # Lấy frame từ bộ nhớ vòng lặp (Build 57)
                frame = _LOOP_FRAMES.get(int(cam_id))
                captured_at = time.time()
                if frame is None:
                    await asyncio.sleep(0.1)
                    continue
            else:
                captured_at = None
                if source is None or cap is None or not cap.isOpened():
                    wait = draw_error_frame(source_error or "Camera not found")
                    ok, buf = cv2.imencode(".jpg", wait, [cv2.IMWRITE_JPEG_QUALITY, 40])
                    if ok:
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                    await asyncio.sleep(0.5)
                    continue
                ret, frame = cap.read()
                if not ret:
                    if isinstance(source, str):
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, frame = cap.read()
                        if not ret:
                            wait = draw_error_frame("Loop source unavailable")
                            ok, buf = cv2.imencode(".jpg", wait, [cv2.IMWRITE_JPEG_QUALITY, 40])
                            if ok:
                                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                            await asyncio.sleep(0.5)
                            continue
                    else:
                        cap.release()
                        cap = None
                        current_capture_key = None
                        wait = draw_error_frame("Camera reconnecting")
                        ok, buf = cv2.imencode(".jpg", wait, [cv2.IMWRITE_JPEG_QUALITY, 40])
                        if ok:
                            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                        await asyncio.sleep(0.5)
                        continue

            # Resize to optimize bandwidth
            h, w = frame.shape[:2]
            target_max_width = 720 if is_primary_cam else 640
            if w > target_max_width:
                new_h = int(h * (target_max_width / w))
                frame = cv2.resize(frame, (target_max_width, new_h))

            process_frame = frame
            if is_primary_cam and use_db_delay and not is_iphone_stream and not is_browser_stream:
                store_frame_in_db(cam_id, frame, time.time())
                delayed = load_delayed_frame_from_db(cam_id, delay_sec)
                if delayed is not None:
                    process_frame = delayed

            if is_primary_cam and not (is_browser_stream and browser_frame_source == "ws_live_annotated"):
                process_frame, roi_polygon = process_sign_roi(process_frame, cam_id, show_sign)
                process_frame = process_ppe(process_frame, cam_id, show_helmet, show_vest, roi_polygon, captured_at=captured_at)

            quality = 58 if is_primary_cam else 32
            ok, buf = cv2.imencode(".jpg", process_frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if ok:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"

            elapsed = time.time() - t0
            await asyncio.sleep(max(0.001, interval - elapsed))
    except asyncio.CancelledError:
        pass
    finally:
        if cap is not None:
            cap.release()


@app.get("/video_feed/{cam_id}")
async def video_feed(
    cam_id: str,
    filters: str = Query("helmet,vest,sign,pose"),
    pipeline: str = Query(DEFAULT_PIPELINE),
    delay_sec: float = Query(DEFAULT_DELAY_SEC, ge=0.0, le=15.0),
):
    active_filters = [f.strip() for f in filters.split(",") if f.strip()]
    use_db_delay = pipeline == "db_delay"
    return StreamingResponse(
        generate_frames(cam_id, active_filters, use_db_delay=use_db_delay, delay_sec=delay_sec),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.post("/api/device_login")
async def device_login(data: dict):
    device_name = str(data.get("device_name", "")).strip() or "iPhone"
    platform_name = str(data.get("platform", "mobile")).strip() or "mobile"
    session_id = str(uuid.uuid4())
    now = time.time()
    with sender_sessions_lock:
        sender_sessions[session_id] = {"device_name": device_name, "platform": platform_name, "last_seen": now}
    with iphone_state_lock:
        iphone_stream_state["device_name"] = device_name
    return {"status": "success", "session_id": session_id, "device_name": device_name, "platform": platform_name}


@app.websocket("/ws/ai")
async def websocket_ai(websocket: WebSocket):
    import asyncio
    await websocket.accept()
    
    # Lấy thông tin thiết bị từ query params (nếu có)
    query_params = websocket.query_params
    device_name = query_params.get("device", "Remote")
    fixed_slot = query_params.get("fixed_slot", "").strip()
    
    print(f"[WS/AI] Client connected: {device_name}")
    loop = asyncio.get_event_loop()

    # Tạo Session ID duy nhất cho kết nối này
    conn_id = str(uuid.uuid4())
    if fixed_slot:
        try:
            fixed_slot_id = int(fixed_slot)
        except ValueError:
            await websocket.send_json({"status": "error", "message": "invalid fixed_slot"})
            await websocket.close()
            return
        my_slot, err = stream_manager.claim_fixed_slot(fixed_slot_id, conn_id, device_name=device_name)
        if my_slot is None:
            await websocket.send_json({"status": "error", "message": err})
            await websocket.close()
            return
    else:
        my_slot = stream_manager.get_available_slot(conn_id, device_name=device_name)
    
    print(f"[WS/AI] Assigned Slot {my_slot} to session {conn_id}")

    def run_inference(jpeg_bytes: bytes):
        nparr = np.frombuffer(jpeg_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            return []

        h, w = frame.shape[:2]
        input_w = WS_INPUT_WIDTH
        input_h = max(1, int(h * (input_w / w)))
        proc = cv2.resize(frame, (input_w, input_h))
        scale_x = w / input_w
        scale_y = h / input_h

        persons, helmets, vests = [], [], []

        result = model_ppe.track(proc, persist=True, conf=WS_TRACK_CONF, imgsz=WS_INPUT_WIDTH, verbose=False, tracker="bytetrack.yaml")
        if result and result[0].boxes is not None:
            for box_obj in result[0].boxes:
                cls_idx = int(box_obj.cls[0])
                cls_name = normalize_name(model_ppe.names[cls_idx])
                conf = float(box_obj.conf[0])
                box = box_obj.xyxy[0].tolist()
                
                # Trích xuất ID ổn định (Build 51)
                p_id = -1
                if hasattr(box_obj, 'id') and box_obj.id is not None:
                    try: p_id = int(box_obj.id[0])
                    except: pass

                if is_person_class(cls_name, cls_idx):
                    persons.append({"box": box, "conf": conf, "id": p_id})
                elif is_helmet_class(cls_name):
                    helmets.append({"box": box, "conf": conf})
                elif is_vest_class(cls_name):
                    vests.append({"box": box, "conf": conf})

        output = []

        def scale_box(b):
            return [b[0]*scale_x, b[1]*scale_y, b[2]*scale_x, b[3]*scale_y]

        # --- Draw helmet boxes (cyan) ---
        for h_item in helmets:
            output.append({
                "box": scale_box(h_item["box"]),
                "label": f"Helmet {h_item['conf']:.0%}",
                "type": "helmet",
                "is_valid": True,
                "missing": [],
            })

        # --- Draw vest boxes (orange) ---
        for v_item in vests:
            output.append({
                "box": scale_box(v_item["box"]),
                "label": f"Vest {v_item['conf']:.0%}",
                "type": "vest",
                "is_valid": True,
                "missing": [],
            })

        frame_quality = evaluate_frame_quality(frame, str(my_slot), captured_at=None)
        now_ts = time.time()
        cleanup_person_states(now_ts)

        # --- Draw overall safety status box per person ---
        for p_item in persons:
            pbox = p_item["box"]
            if p_item.get("conf", 0.0) < PERSON_CONF_MIN:
                decision_metrics["ws_filtered_person"] += 1
                continue

            h_ratio = (pbox[3] - pbox[1]) / max(1.0, float(proc.shape[0]))
            a_ratio = ((pbox[3] - pbox[1]) * (pbox[2] - pbox[0])) / max(1.0, float(proc.shape[0] * proc.shape[1]))
            if h_ratio < MIN_PERSON_HEIGHT_RATIO or a_ratio < MIN_PERSON_AREA_RATIO:
                decision_metrics["ws_filtered_person"] += 1
                continue

            has_helmet = any(h["conf"] >= HELMET_CONF_MIN and associated_to_person(h["box"], pbox) for h in helmets)
            has_vest   = any(v["conf"] >= VEST_CONF_MIN and associated_to_person(v["box"], pbox) for v in vests)
            missing = []
            if not has_helmet:
                missing.append("Helmet")
            if not has_vest:
                missing.append("Vest")

            is_safe = len(missing) == 0
            status_label = "AN TOAN" if is_safe else f"THIEU: {', '.join(missing)}"
            
            primary_slot = int(get_primary_camera_id())
            if not is_safe and my_slot == primary_slot:
                # Sử dụng ID ổn định (nếu có) thay vì random
                p_id = p_item.get("id", random.randint(1000, 9999))
                cam_label = get_primary_camera_label()
                decision = update_decision_state(cam_label, p_id, is_safe, frame_quality["usable"], now_ts)
                if decision["status"] == "suspect":
                    status_label = f"CHECKING: {', '.join(missing)}"
                elif decision["status"] == "confirmed":
                    status_label = f"CONFIRMED: {', '.join(missing)}"
                if decision["emit_alert"]:
                    add_log(p_id, "PPE", f"Missing {', '.join(missing)}", camera=cam_label)

            output.append({
                "box": scale_box(pbox),
                "label": status_label,
                "type": "overall",
                "is_valid": is_safe,
                "missing": missing,
                "id": p_item.get("id", -1)
            })

        return output

    # Send assignment info to client immediately
    await websocket.send_json({"type": "assignment", "slot_id": my_slot})

    # Đăng ký kết nối vào registry để heartbeat không xóa (Build 52)
    with sender_sessions_lock:
        sender_sessions[conn_id] = {"device_name": device_name, "platform": "websocket", "last_seen": time.time()}

    try:
        while True:
            data = await websocket.receive_bytes()
            
            # Cập nhật nhịp đập cho session
            with sender_sessions_lock:
                if conn_id in sender_sessions:
                    sender_sessions[conn_id]["last_seen"] = time.time()

            # Run blocking YOLO inference
            detections = await loop.run_in_executor(None, run_inference, data)
            
            # Cập nhật frame mới nhất vào Stream Manager
            nparr = np.frombuffer(data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is not None:
                # Vẽ AI trực tiếp lên frame để mọi người cùng thấy (Server-Side Rendering)
                for det in detections:
                    x1, y1, x2, y2 = [int(v) for v in det["box"]]
                    color = (255, 229, 0) if det["type"] == "helmet" else (0, 152, 255) # Cyan/Orange in BGR
                    if det["type"] == "overall":
                        color = (118, 230, 0) if det["is_valid"] else (68, 23, 255) # Green/Red in BGR
                    
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, det["label"], (x1, y1-10 if y1>20 else y2+20), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                stream_manager.set_live_frame(my_slot, frame, conn_id)
                camera_states[str(my_slot)]["browser_frame"] = frame.copy()
                camera_states[str(my_slot)]["browser_frame_source"] = "ws_live_annotated"
                camera_states[str(my_slot)]["browser_frame_ts"] = time.time()

            await websocket.send_json({
                "status": "ok",
                "detections": detections,
                "slot_id": my_slot,
                "ts": time.time()
            })
    except WebSocketDisconnect:
        stream_manager.release_slot(conn_id)
        print(f"[WS/AI] Client {conn_id} disconnected from Slot {my_slot}")
    except Exception as e:
        stream_manager.release_slot(conn_id)
        print(f"[WS/AI Error] {e}")


@app.get("/api/video_feed/{slot_id}")
async def global_video_feed(slot_id: int):
    async def frame_generator():
        print(f"[Feed] Viewer attached to Slot {slot_id}")
        try:
            while True:
                frame = stream_manager.get_frame(slot_id)
                if frame is not None:
                    # Resize to optimized broadcast resolution
                    frame_small = cv2.resize(frame, (480, 270))
                    ret, buffer = cv2.imencode('.jpg', frame_small, [cv2.IMWRITE_JPEG_QUALITY, 35])
                    if ret:
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n'
                               b'Content-Length: ' + str(len(buffer)).encode() + b'\r\n\r\n' + 
                               buffer.tobytes() + b'\r\n')
                await asyncio.sleep(0.08)
        except Exception as e:
            print(f"[Feed] Slot {slot_id} viewer detached: {e}")

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, pre-check=0, post-check=0, max-age=0",
            "Pragma": "no-cache",
            "Connection": "close",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/upload_camera/{cam_id}")
async def upload_camera(cam_id: str, file: UploadFile = File(...)):
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is not None:
        camera_states[cam_id]["browser_frame"] = frame
        camera_states[cam_id]["browser_frame_source"] = "upload_camera"
        camera_states[cam_id]["browser_frame_ts"] = time.time()
    return {"status": "ok"}


@app.post("/api/upload_loop")
async def upload_loop(file: UploadFile = File(...)):
    try:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid video format"})
        
        filename = sanitize_upload_filename(file.filename, "loop_upload")
        save_path = os.path.join(TEMP_DIR, filename)
        
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        return {"status": "success", "filename": filename}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.post("/api/iphone_ingest")
async def iphone_ingest(data: dict):
    try:
        image_payload = data.get("image", "")
        device_name = str(data.get("device_name", "iPhone")).strip() or "iPhone"
        session_id = str(data.get("session_id", "")).strip()
        captured_at = float(data.get("captured_at", 0.0) or 0.0)
        if session_id:
            with sender_sessions_lock:
                sess = sender_sessions.get(session_id)
                if sess:
                    sess["last_seen"] = time.time()
                    device_name = sess.get("device_name", device_name)

        if not image_payload or "," not in image_payload:
            return JSONResponse(status_code=400, content={"status": "error", "message": "invalid image payload"})

        img_data = image_payload.split(",", 1)[1]
        img_bytes = base64.b64decode(img_data)
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            return JSONResponse(status_code=400, content={"status": "error", "message": "decode frame failed"})

        save_iphone_frame(frame, device_name=device_name, jpeg_bytes=img_bytes)
        with iphone_state_lock:
            iphone_stream_state["captured_at"] = captured_at if captured_at > 0 else time.time()
        return {
            "status": "success",
            "device_name": device_name,
            "received_at": time.time(),
            "primary_camera_id": get_primary_camera_id(),
            "is_primary_camera": is_primary_camera("2"),
        }
    except Exception as exc:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@app.post("/api/mobile_inference")
async def mobile_inference(data: dict):
    # Kept for backward compatibility with old frontend mode.
    try:
        image_payload = data.get("image", "")
        if not image_payload or "," not in image_payload:
            return {"status": "error", "message": "invalid image"}
        return {
            "status": "success",
            "violation": False,
            "detail": "",
            "new_alert": False,
            "annotated_frame": "",
            "ppe_boxes": [],
            "helmet_boxes": [],
            "vest_boxes": [],
            "fall_boxes": [],
            "frame_size": [640, 480],
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@app.post("/api/upload_video")
async def upload_video(file: UploadFile = File(...)):
    try:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid video format"})

        filename = sanitize_upload_filename(file.filename, "upload")
        file_path = os.path.join(TEMP_DIR, filename)
        with open(file_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)
        return {"filename": filename, "status": "success"}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"message": str(exc)})


@app.get("/api/cameras")
async def get_cameras():
    usb_online = probe_usb_camera()
    iphone_name, iphone_last_ts = get_iphone_device_name()
    iphone_online = (time.time() - iphone_last_ts) <= 8.0
    host_name = platform.node() or "Operator Machine"
    loop_path = choose_loop_video_path()
    loop_name = os.path.basename(loop_path) if loop_path else "No video"
    sender_active = iphone_online and bool(load_iphone_frame() is not None)
    primary_cam_id = get_primary_camera_id()

    return [
        {
            "id": "1",
            "name": "CAM 01 - Camera Dieu Hanh",
            "device_name": f"{host_name} - USB Camera 0",
            "status": "online" if usb_online else "offline",
            "kind": "direct_usb",
            "updated_at": time.time(),
            "is_primary_ai": primary_cam_id == "1",
        },
        {
            "id": "2",
            "name": "CAM 02 - iPhone Cong Truong",
            "device_name": iphone_name,
            "status": "streaming" if sender_active else ("online" if iphone_online else "offline"),
            "kind": "iphone_stream",
            "updated_at": iphone_last_ts,
            "is_primary_ai": primary_cam_id == "2",
        },
        {
            "id": "3",
            "name": "CAM 03 - Video Loop",
            "device_name": loop_name,
            "status": "online" if loop_path and os.path.exists(loop_path) else "offline",
            "kind": "recorded_loop",
            "updated_at": os.path.getmtime(loop_path) if loop_path and os.path.exists(loop_path) else 0,
            "is_primary_ai": False,
        },
        {
            "id": "4",
            "name": "CAM 04 - RTSP Realtime",
            "device_name": "HikVision RTSP",
            "status": "online",
            "kind": "rtsp_stream",
            "updated_at": time.time(),
            "is_primary_ai": False,
        },
    ]


@app.get("/api/settings")
async def get_settings():
    primary_id = get_primary_camera_id()
    return {
        "primary_camera_id": primary_id,
        "primary_camera_label": f"CAM {primary_id.zfill(2)}",
        "available_primary_cameras": sorted(PRIMARY_CAMERA_OPTIONS),
    }


@app.post("/api/settings/primary_camera")
async def update_primary_camera(data: dict):
    try:
        primary_id = set_primary_camera_id(data.get("primary_camera_id", "1"))
        return {
            "status": "success",
            "primary_camera_id": primary_id,
            "primary_camera_label": f"CAM {primary_id.zfill(2)}",
        }
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(exc)})


@app.get("/api/logs")
async def get_logs():
    """Chỉ lấy danh sách vi phạm thực tế từ bảng 'logs', bỏ qua heartbeat"""
    try:
        rows = load_recent_logs_from_db(limit=50)
        
        logs = []
        for r in rows:
            logs.append({
                "id": f"v_{r['id']}",
                "time": r["timestamp"].split()[-1] if " " in str(r["timestamp"]) else str(r["timestamp"]),
                "cam": str(r["camera"]),
                "camera": str(r["camera"]),
                "msg": f"{r['type']}: {r['detail']}",
                "detail": str(r["detail"]),
                "person_id": str(r["track_id"]) if r["track_id"] is not None else "N/A",
                "track_id": r["track_id"],
                "type": str(r["type"]),
            })
            
        return {"logs": logs}
    except Exception as e:
        print(f"[API Error] get_logs: {e}")
        return {"logs": []}


@app.get("/api/logs/history")
async def get_log_history(limit: int = 100):
    try:
        return load_recent_logs_from_db(limit=limit)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"message": str(exc)})


@app.get("/api/violations/dashboard")
async def get_violations_dashboard(limit: int = 5000):
    db_rows = load_recent_logs_from_db(limit=max(1, min(limit, 5000)))
    rows = [
        {
            "id": row["id"],
            "camera": row["camera"],
            "violation": f"{row['type']}: {row['detail']}",
            "time": row["timestamp"],
            "track_id": row["track_id"],
            "type": row["type"],
            "detail": row["detail"],
        }
        for row in reversed(db_rows)
    ]
    if not rows:
        rows = parse_violation_log(limit=max(1, min(limit, 5000)))
    by_camera = defaultdict(int)
    by_type = defaultdict(int)

    for row in rows:
        by_camera[row["camera"]] += 1
        v_type = row["violation"].split(":")[0].strip()
        by_type[v_type] += 1

    return {
        "total": len(rows),
        "by_camera": dict(sorted(by_camera.items(), key=lambda item: item[1], reverse=True)),
        "by_type": dict(sorted(by_type.items(), key=lambda item: item[1], reverse=True)),
        "recent": list(reversed(rows[-20:])),
        "log_file": VIOLATION_LOG_PATH,
    }


@app.get("/api/roi/{cam_id}")
async def get_roi(cam_id: str):
    state = camera_states[cam_id]
    return {
        "cam_id": cam_id,
        "last_sign_scan_at": state["last_sign_scan"],
        "roi_polygon": state["roi_polygon"],
        "points": state["last_points"],
        "interval_sec": SIGN_SCAN_INTERVAL_SEC,
    }


@app.get("/api/model_info")
async def get_model_info():
    return {
        "ppe_names": model_ppe.names,
        "sign_names": model_sign.names,
        "ppe_path": PPE_MODEL_PATH,
        "sign_path": SIGN_MODEL_PATH,
        "runtime": runtime_state,
        "thresholds": {
            "ppe_track_conf": PPE_TRACK_CONF,
            "ws_track_conf": WS_TRACK_CONF,
            "sign_conf": SIGN_CONF,
            "ppe_imgsz": PPE_IMGSZ,
            "ws_input_width": WS_INPUT_WIDTH,
            "ppe_alert_delay_sec": PPE_ALERT_DELAY_SEC,
            "ppe_alert_cooldown_sec": PPE_ALERT_COOLDOWN_SEC,
            "sign_scan_interval_sec": SIGN_SCAN_INTERVAL_SEC,
            "person_conf_min": PERSON_CONF_MIN,
            "helmet_conf_min": HELMET_CONF_MIN,
            "vest_conf_min": VEST_CONF_MIN,
            "frame_blur_min": FRAME_BLUR_MIN,
            "frame_motion_max": FRAME_MOTION_MAX,
            "frame_stale_max_sec": FRAME_STALE_MAX_SEC,
            "decision_window_sec": DECISION_WINDOW_SEC,
            "decision_min_samples": DECISION_MIN_SAMPLES,
            "decision_missing_ratio": DECISION_MISSING_RATIO,
        },
        "decision_metrics": dict(decision_metrics),
    }


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "primary_camera_id": get_primary_camera_id(),
        "runtime": runtime_state,
        "decision_metrics": dict(decision_metrics),
        "models": {
            "ppe_path": PPE_MODEL_PATH,
            "sign_path": SIGN_MODEL_PATH,
        },
    }

@app.get("/api/diagnostic/loop")
async def diagnostic_loop():
    return {
        "loop_frames_status": {i: ("Ready" if _LOOP_FRAMES[i] is not None else "Empty") for i in range(1, 13)},
        "global_slots": {i: {"type": _GLOBAL_SLOTS[i]["type"], "has_session": _GLOBAL_SLOTS[i]["session_id"] is not None} for i in range(1, 13)},
        "temp_dir_exists": os.path.exists(TEMP_DIR),
        "default_video_exists": os.path.exists(DEFAULT_VIDEO_PATH),
    }


init_db()
init_ppe_class_ids()
warmup_models()
# Start background loop ONLY after models are warmed up (Build 59)
threading.Thread(target=background_loop_reader, daemon=True).start()

@app.get("/")
async def root():
    # Force serve the latest dashboard.html content directly to bypass cache
    dashboard_path = os.path.join(BASE_DIR, "dashboard.html")
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content)
    return HTMLResponse("Dashboard not found.")

app.mount("/css", StaticFiles(directory=os.path.join(BASE_DIR, "css")), name="css")
app.mount("/src", StaticFiles(directory=os.path.join(BASE_DIR, "src")), name="src")
app.mount("/assets", StaticFiles(directory=os.path.join(BASE_DIR, "assets")), name="assets")
app.mount("/temp_videos", StaticFiles(directory=TEMP_DIR), name="temp_videos")
app.mount("/", StaticFiles(directory=BASE_DIR), name="static")


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=5001, reload=False, log_level="info")
