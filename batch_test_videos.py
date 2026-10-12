import os
import cv2
import time
import unicodedata
import numpy as np
from ultralytics import YOLO

# --- CONFIGURATION ---
BASE_DIR = r"c:\Users\HaiK74\Desktop\VTV_2_UTT"
TEST_VIDEO_DIR = os.path.join(BASE_DIR, "test_video")
RESULT_VIDEO_DIR = os.path.join(BASE_DIR, "temp_videos")
MODELS_DIR = os.path.join(BASE_DIR, "UTT_APP", "models")

PPE_MODEL_PATH = os.path.join(MODELS_DIR, "best.pt")
if not os.path.exists(PPE_MODEL_PATH):
    PPE_MODEL_PATH = os.path.join(MODELS_DIR, "best.onnx")

os.makedirs(RESULT_VIDEO_DIR, exist_ok=True)

# --- HELPER FUNCTIONS (FROM app.py) ---
def normalize_name(name: str) -> str:
    raw = str(name).strip().lower().replace("-", " ").replace("_", " ")
    return raw

def is_person_class(class_name: str, class_idx: int) -> bool:
    return "person" in class_name or "worker" in class_name or class_idx == 1

def is_helmet_class(class_name: str) -> bool:
    return ("helmet" in class_name or "hardhat" in class_name or "hard hat" in class_name) and "no " not in class_name

def is_vest_class(class_name: str) -> bool:
    return ("vest" in class_name or "jacket" in class_name or "reflective" in class_name) and "no " not in class_name

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
    if x_right <= x_left or y_bottom <= y_top: return 0.0
    inter = (x_right - x_left) * (y_bottom - y_top)
    child_area = max(1.0, (child_box[2] - child_box[0]) * (child_box[3] - child_box[1]))
    return inter / child_area

def associated_to_person(child_box, person_box):
    w = person_box[2] - person_box[0]
    h = person_box[3] - person_box[1]
    exp_person = [person_box[0] - w*0.2, person_box[1] - h*0.2, person_box[2] + w*0.2, person_box[3] + h*0.2]
    return child_inside_person(child_box, exp_person) or overlap_ratio(child_box, exp_person) > 0.01

def label_with_background(frame, text, top_left, color):
    x, y = top_left
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(frame, (x, y - th - 10), (x + tw + 10, y), color, -1)
    cv2.putText(frame, text, (x + 5, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

# --- MAIN PROCESSING ---
print(f"[TEST] Loading model: {PPE_MODEL_PATH}")
model = YOLO(PPE_MODEL_PATH)

video_files = ["28s.mp4"]

for video_name in video_files:
    video_path = os.path.join(TEST_VIDEO_DIR, video_name)
    output_path = os.path.join(RESULT_VIDEO_DIR, f"result_{video_name}")
    
    print(f"[TEST] Processing: {video_name} -> {output_path}")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error opening video: {video_path}")
        continue
        
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0: fps = 30
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        # YOLO Inference
        results = model(frame, conf=0.02, verbose=False)
        
        persons, helmets, vests = [], [], []
        
        if results[0].boxes is not None:
            for box_obj in results[0].boxes:
                cls_idx = int(box_obj.cls[0])
                cls_name = results[0].names[cls_idx].lower()
                box = box_obj.xyxy[0].tolist()
                conf = float(box_obj.conf[0])
                
                if is_person_class(cls_name, cls_idx):
                    if conf >= 0.25:
                        persons.append(box)
                elif is_helmet_class(cls_name):
                    helmets.append(box)
                    cv2.rectangle(frame, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (255, 255, 0), 2)
                    label_with_background(frame, f"Helmet {conf:.0%}", (int(box[0]), int(box[1])), (255, 255, 0))
                elif is_vest_class(cls_name):
                    vests.append(box)
                    cv2.rectangle(frame, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (0, 165, 255), 2)
                    label_with_background(frame, f"Vest {conf:.0%}", (int(box[0]), int(box[1])), (0, 165, 255))

        # Overall Safety logic
        for pbox in persons:
            has_helmet = any(associated_to_person(h, pbox) for h in helmets)
            has_vest = any(associated_to_person(v, pbox) for v in vests)
            
            is_valid = has_helmet and has_vest
            color = (0, 255, 0) if is_valid else (0, 0, 255)
            
            if is_valid:
                label = "AN TOAN"
            else:
                missing = []
                if not has_helmet: missing.append("No Helmet")
                if not has_vest: missing.append("No Vest")
                label = f"KHONG AN TOAN - {', '.join(missing)}"
            
            cv2.rectangle(frame, (int(pbox[0]), int(pbox[1])), (int(pbox[2]), int(pbox[3])), color, 2)
            label_with_background(frame, label, (int(pbox[0]), int(pbox[1])), color)

        out.write(frame)
        frame_count += 1
        if frame_count % 100 == 0:
            print(f"  - Frame {frame_count} processed...")

    cap.release()
    out.release()
    print(f"[DONE] Saved: {output_path}")

print("\n[ALL DONE] All videos processed successfully.")
