import cv2
import os
from ultralytics import YOLO

# ==============================================================================
# CẤU HÌNH
# ==============================================================================
MODEL_PATH = 'tuthenga.pt'
VIDEO_PATH = 'video7.mp4'
OUTPUT_PATH = 'video7_tuthenga_result.mp4'
CONFIDENCE = 0.5

def main():
    # 1. Tải mô hình
    if not os.path.exists(MODEL_PATH):
        print(f"Error: Không tìm thấy mô hình tại {MODEL_PATH}")
        return
    
    print(f"Đang tải mô hình: {MODEL_PATH}")
    model = YOLO(MODEL_PATH)

    # 2. Mở video
    if not os.path.exists(VIDEO_PATH):
        print(f"Error: Không tìm thấy video tại {VIDEO_PATH}")
        return
    
    cap = cv2.VideoCapture(VIDEO_PATH)
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # 3. Khởi tạo VideoWriter
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(OUTPUT_PATH, fourcc, fps, (width, height))

    print(f"Đang xử lý video {VIDEO_PATH}...")
    print("Nhấn 'q' để dừng quá trình xử lý.")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # 4. Chạy inference (sử dụng track để mượt mà hơn)
        results = model.track(frame, persist=True, conf=CONFIDENCE, verbose=False)

        # 5. Vẽ kết quả lên frame
        # results[0].plot() trả về frame đã được vẽ sẵn box/label
        annotated_frame = results[0].plot()

        # 6. Hiển thị và lưu
        cv2.imshow("Test Tu The Nga - Video 7", annotated_frame)
        out.write(annotated_frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # 7. Giải phóng tài nguyên
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    
    print(f"\nHoàn thành! Video kết quả đã được lưu tại: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
