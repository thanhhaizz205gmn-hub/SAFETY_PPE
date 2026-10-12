import os
import cv2
import time
import numpy as np
from ultralytics import YOLO

# --- CONFIGURATION ---
BASE_DIR = r"c:\Users\HaiK74\Desktop\VTV_2_UTT"
TEST_VIDEO_DIR = os.path.join(BASE_DIR, "test_video")
RESULT_VIDEO_DIR = os.path.join(BASE_DIR, "UTT_APP", "temp_videos")
MODELS_DIR = os.path.join(BASE_DIR, "UTT_APP", "models")

PPE_MODEL_PATH = os.path.join(MODELS_DIR, "best.pt")
if not os.path.exists(PPE_MODEL_PATH):
    PPE_MODEL_PATH = os.path.join(MODELS_DIR, "best.onnx")

os.makedirs(RESULT_VIDEO_DIR, exist_ok=True)

# --- HELPER FUNCTIONS ---
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
    return child_inside_person(child_box, person_box) or overlap_ratio(child_box, person_box) >= 0.10

def label_with_background(frame, text, top_left, color):
    x, y = top_left
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(frame, (x, y - th - 10), (x + tw + 10, y), color, -1)
    cv2.putText(frame, text, (x + 5, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

# --- MAIN ---
print(f"[BATCH TEST] Loading model: {PPE_MODEL_PATH}")
model = YOLO(PPE_MODEL_PATH)

target_videos = ["t5.mp4", "t6.mp4"]

for video_name in target_videos:
    video_path = os.path.join(TEST_VIDEO_DIR, video_name)
    output_path = os.path.join(RESULT_VIDEO_DIR, video_name) # Saving with same name in temp_videos
    
    if not os.path.exists(video_path):
        print(f"[ERROR] {video_name} not found in {TEST_VIDEO_DIR}")
        continue

    print(f"[TEST] Processing: {video_name} -> {output_path}")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[ERROR] Could not open video {video_path}")
        continue
        
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS) or 30
    
    out = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
    
    frame_count = 0
    start_time = time.time()
    
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        results = model(frame, conf=0.25, verbose=False)
        persons, helmets, vests = [], [], []
        
        if results[0].boxes is not None:
            for box_obj in results[0].boxes:
                cls_idx = int(box_obj.cls[0])
                cls_name = results[0].names[cls_idx].lower()
                box = box_obj.xyxy[0].tolist()
                
                if "person" in cls_name or "worker" in cls_name:
                    persons.append(box)
                elif "helmet" in cls_name or "hardhat" in cls_name:
                    helmets.append(box)
                    cv2.rectangle(frame, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (255, 255, 0), 2)
                elif "vest" in cls_name or "jacket" in cls_name:
                    vests.append(box)
                    cv2.rectangle(frame, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (0, 165, 255), 2)

        for pbox in persons:
            has_helmet = any(associated_to_person(h, pbox) for h in helmets)
            has_vest = any(associated_to_person(v, pbox) for v in vests)
            is_valid = has_helmet and has_vest
            color = (0, 255, 0) if is_valid else (0, 0, 255)
            cv2.rectangle(frame, (int(pbox[0]), int(pbox[1])), (int(pbox[2]), int(pbox[3])), color, 2)
            label_with_background(frame, "AN TOAN" if is_valid else "KHONG AN TOAN", (int(pbox[0]), int(pbox[1])), color)

        out.write(frame)
        frame_count += 1
        if frame_count % 30 == 0:
            print(f"  - Processed {frame_count} frames...", end='\r')

    cap.release()
    out.release()
    elapsed = time.time() - start_time
    print(f"\n[DONE] {video_name} processed in {elapsed:.2f}s.")

print("[ALL DONE] Batch test complete. Results in UTT_APP/temp_videos")
