import cv2
import numpy as np
from ultralytics import YOLO
import time
import os
import winsound # Thư viện phát âm báo trên Windows

# Đường dẫn file
PPE_MODEL_PATH = r"c:\Users\HaiK74\Desktop\VTV_2_UTT\best.pt"
SIGN_MODEL_PATH = r"c:\Users\HaiK74\Desktop\VTV_2_UTT\cone_sign.pt"
VIDEO_PATH = r"c:\Users\HaiK74\Desktop\VTV_2_UTT\video7.mp4"

def build_roi_polygon(points):
    if len(points) < 3: return None
    pts = np.array(points, dtype=np.int32)
    return cv2.convexHull(pts)

def is_point_in_poly(point, poly):
    if poly is None: return True # Nếu không có ROI thì coi như trong vùng (tùy chọn)
    return cv2.pointPolygonTest(poly, (float(point[0]), float(point[1])), False) >= 0

def main():
    print("--- ĐANG KHỞI CHẠY TEST PPE + ROI ---")
    
    # 1. Load mô hình
    print("Đang nạp mô hình PPE...")
    model_ppe = YOLO(PPE_MODEL_PATH)
    print("Đang nạp mô hình ROI...")
    model_sign = YOLO(SIGN_MODEL_PATH)
    
    cap = cv2.VideoCapture(VIDEO_PATH)
    cv2.namedWindow("UTT SAFETY - ROI + PPE MONITOR", cv2.WINDOW_NORMAL)

    last_beep_time = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break

        display_frame = frame.copy()
        h, w = frame.shape[:2]

        # 2. Nhận diện ROI (Lấy điểm sát mặt đất)
        res_sign = model_sign(frame, conf=0.4, verbose=False)
        roi_points = []
        if res_sign[0].boxes:
            for b in res_sign[0].boxes:
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                # Lấy điểm chính giữa đáy cọc tiêu để sát mặt đất (Build 53)
                roi_points.append([(x1+x2)//2, y2])
                cv2.rectangle(display_frame, (x1,y1), (x2,y2), (0, 255, 255), 1)
                cv2.circle(display_frame, ((x1+x2)//2, y2), 4, (0, 255, 255), -1)

        hull = build_roi_polygon(roi_points)
        if hull is not None:
            overlay = display_frame.copy()
            cv2.fillPoly(overlay, [hull], (255, 150, 0))
            display_frame = cv2.addWeighted(overlay, 0.25, display_frame, 0.75, 0)
            cv2.polylines(display_frame, [hull], True, (255, 255, 0), 2)

        # 3. Nhận diện PPE
        res_ppe = model_ppe(frame, conf=0.3, verbose=False)
        persons, helmets, vests = [], [], []
        if res_ppe[0].boxes:
            for b in res_ppe[0].boxes:
                cls = int(b.cls[0])
                box = b.xyxy[0].tolist()
                if cls == 0: persons.append(box)
                elif cls == 1: helmets.append(box)
                elif cls == 2: vests.append(box)

        # 4. Kiểm tra từng người dựa trên vị trí bàn chân
        violation_detected = False
        for p in persons:
            px1, py1, px2, py2 = map(int, p)
            # Lấy vị trí bàn chân (Chính giữa đáy khung người)
            feet_x, feet_y = (px1 + px2) // 2, py2
            
            # Kiểm tra bàn chân có trong ROI mặt đất không
            in_roi = is_point_in_poly((feet_x, feet_y), hull)
            
            # Logic kiểm tra PPE
            has_helmet = any(max(px1,h[0]) < min(px2,h[2]) and max(py1,h[1]) < min(py2,h[3]) for h in helmets)
            has_vest = any(max(px1,v[0]) < min(px2,v[2]) and max(py1,v[1]) < min(py2,v[3]) for v in vests)
            is_valid = has_helmet and has_vest
            
            color = (0, 255, 0)
            label = "WORKER"
            
            if in_roi:
                if not is_valid:
                    color = (0, 0, 255)
                    label = "!!! DANGER !!!"
                    violation_detected = True
                else:
                    label = "SAFE AREA"
            
            # Vẽ khung và đánh dấu vị trí bàn chân đang kiểm tra
            cv2.rectangle(display_frame, (px1, py1), (px2, py2), color, 2)
            cv2.circle(display_frame, (feet_x, feet_y), 6, color, -1) 
            cv2.putText(display_frame, label, (px1, py1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # 5. Phát âm báo nếu có vi phạm (giới hạn tần suất kêu)
        if violation_detected and (time.time() - last_beep_time > 1.0):
            winsound.Beep(1000, 300) # Tần số 1000Hz, thời gian 300ms
            last_beep_time = time.time()

        cv2.imshow("UTT SAFETY - ROI + PPE MONITOR", display_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'): break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
