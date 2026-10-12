import cv2
from ultralytics import YOLO
import os

# 1. Cấu hình đường dẫn
MODEL_PPE = 'best.pt'
MODEL_CONE = 'bestcone.pt'
MODEL_FALL = 'tuthenga.pt'
VIDEO_PATH = 'video7.mp4'

# Kiểm tra file tồn tại
for f in [MODEL_PPE, MODEL_CONE, MODEL_FALL, VIDEO_PATH]:
    if not os.path.exists(f):
        print(f"Lỗi: Không tìm thấy file {f}")
        # Thử tìm trong thư mục cha nếu đang ở VTV_PWA
        if os.path.exists(f'../{f}'):
             if f == 'best.pt': MODEL_PPE = '../best.pt'
             if f == 'bestcone.pt': MODEL_CONE = '../bestcone.pt'
             if f == 'tuthenga.pt': MODEL_FALL = '../tuthenga.pt'
             if f == 'video7.mp4': VIDEO_PATH = '../video7.mp4'

# 2. Load Models
print("--- Đang nạp các mô hình AI... ---")
model_ppe = YOLO(MODEL_PPE)
model_cone = YOLO(MODEL_CONE)
model_fall = YOLO(MODEL_FALL)

# 3. Xử lý Video
cap = cv2.VideoCapture(VIDEO_PATH)
if not cap.isOpened():
    print("Lỗi: Không thể mở video.")
    exit()

print(f"--- Đang test trên: {VIDEO_PATH} (Nhấn 'Q' để thoát) ---")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Kết thúc video.")
        break

    # -- Model 1: PPE (Màu Xanh lá) --
    res_ppe = model_ppe(frame, conf=0.3, verbose=False)
    for b in res_ppe[0].boxes:
        x1, y1, x2, y2 = map(int, b.xyxy[0])
        lbl = model_ppe.names[int(b.cls[0])]
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f"PPE:{lbl}", (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

    # -- Model 2: CONE (Màu Vàng) --
    res_cone = model_cone(frame, conf=0.5, verbose=False)
    for b in res_cone[0].boxes:
        x1, y1, x2, y2 = map(int, b.xyxy[0])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
        cv2.putText(frame, "CONE", (x1, y2 + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)

    # -- Model 3: FALL (Màu Đỏ) --
    res_fall = model_fall(frame, conf=0.3, verbose=False)
    for b in res_fall[0].boxes:
        x1, y1, x2, y2 = map(int, b.xyxy[0])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
        cv2.putText(frame, "!!! TE NGA !!!", (x1, y1 - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # Show result
    cv2.imshow('UTT SAFETY - 3 MODELS TEST', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("Đã đóng chương trình test.")
