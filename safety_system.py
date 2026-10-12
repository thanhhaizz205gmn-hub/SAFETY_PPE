import cv2
import math
import time
import pandas as pd
import pygame
from collections import defaultdict
from ultralytics import YOLO
import os

# ==============================================================================
# HẰNG SỐ CẤU HÌNH (Dễ dàng chỉnh sửa)
# ==============================================================================
PPE_CHECK_TIME = 1           # Thời gian (s) thiếu PPE liên tục để bị coi là "Không hợp lệ"
PPE_WARNING_COOLDOWN = 10    # Thời gian (s) chờ giữa 2 lần cảnh báo PPE cho cùng 1 ID
VALID_IGNORE_TIME = 180      # Thời gian (s) bỏ qua check nếu đã từng xác nhận đủ đồ (Tránh spam do khuất tầm nhìn)
ROI_VIOLATION_TIME = 5       # Thời gian (s) người "Không hợp lệ" đứng trong vùng cấm
CONE_SCAN_INTERVAL = 60      # Tần suất quét model cone/sign (s)
PIXEL_PER_METER = 50         # Tỉ lệ quy đổi: Số pixel tương đương 1 mét (Thay đổi theo camera)
ROI_RADIUS_METER = 2         # Bán kính vùng cấm tính bằng mét
PERSPECTIVE_RATIO = 0.4      # Tỉ lệ làm bẹt vùng ROI (y_radius / x_radius) để tạo cảm giác 3D trên mặt đất

PPE_MODEL_PATH = 'best.pt'
CONE_MODEL_PATH = 'bestcone.pt'
PPE_CONFIDENCE = 0.5         # Ngưỡng tin cậy (confidence) của model bảo hộ (Chỉnh lên/xuống để lọc nhiễu)
CONE_CONFIDENCE = 0.5        # Ngưỡng tin cậy (confidence) của model vùng cấm

VIDEO_PATH = 'video7.mp4'     # Điền đường dẫn file video hoặc số 0 nếu dùng webcam
OUTPUT_VIDEO_PATH = 'video7fulltest.mp4'

WARNING_PPE_SOUND = 'warning.wav'  # File âm thanh cảnh báo thiếu PPE (Đảm bảo file này tồn tại)
WARNING_ROI_SOUND = 'alarm.wav'    # File âm thanh cảnh báo xâm nhập (Đảm bảo file này tồn tại)
LOG_FILE = 'violation_log.csv'
# ==============================================================================

# Khởi tạo âm thanh bằng Pygame
pygame.mixer.init()
def play_sound(sound_path):
    if os.path.exists(sound_path):
        # Dùng Sound để có thể phát âm thanh đè lên nhau và không bị chặn luồng chính
        pygame.mixer.Sound(sound_path).play()
    else:
        print(f"Warning: Không tìm thấy file âm thanh {sound_path}")

LOG_HEADER = "Timestamp,Track_ID,Violation_Type"

def check_and_fix_log_file():
    """Kiểm tra và khởi tạo lại file log nếu file bị xóa hoặc bị làm rỗng"""
    write_header = False
    if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
        write_header = True
    else:
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
                if first_line != LOG_HEADER:
                    write_header = True
        except:
            write_header = True
            
    if write_header:
        # Tạo mới/Ghi đè file với header chuẩn, xóa sạch các dòng trống do người dùng xóa nhầm
        df = pd.DataFrame(columns=['Timestamp', 'Track_ID', 'Violation_Type'])
        df.to_csv(LOG_FILE, index=False)

# Chạy kiểm tra lúc khởi động
check_and_fix_log_file()

def log_violation(track_id, violation_type):
    # Luôn kiểm tra trước khi ghi để đảm bảo nếu user vừa xóa nội dung file lúc script đang chạy thì vẫn phục hồi được
    check_and_fix_log_file()
    
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    new_log = pd.DataFrame([{'Timestamp': timestamp, 'Track_ID': track_id, 'Violation_Type': violation_type}])
    new_log.to_csv(LOG_FILE, mode='a', header=False, index=False)
    print(f"[LOG] {timestamp} - ID: {track_id} - {violation_type}")

class PersonState:
    def __init__(self):
        # State PPE
        self.missing_ppe_start_time = None
        self.is_valid = True
        self.last_full_ppe_time = -999999 # Lưu thời điểm gần nhất có đủ đồ bảo hộ
        self.last_ppe_warning_time = -999999 # Lưu thời điểm cảnh báo PPE gần nhất
        
        # State ROI
        self.roi_intrusion_start_time = None
        self.roi_violation_logged = False

def is_center_inside(inner_box, outer_box):
    """Kiểm tra xem tâm của inner_box có nằm trong outer_box hay không"""
    ix1, iy1, ix2, iy2 = inner_box
    ox1, oy1, ox2, oy2 = outer_box
    cx = (ix1 + ix2) / 2
    cy = (iy1 + iy2) / 2
    return (ox1 <= cx <= ox2) and (oy1 <= cy <= oy2)

def main():
    print("Đang tải các models...")
    model_ppe = YOLO(PPE_MODEL_PATH)
    model_cone = YOLO(CONE_MODEL_PATH)
    
    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print(f"Error: Không thể mở nguồn video {VIDEO_PATH}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or math.isnan(fps):
        fps = 30.0 # Giá trị mặc định nếu không đọc được FPS
        
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Setup Video Writer để xuất video xem lại (Tùy chọn)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(OUTPUT_VIDEO_PATH, fourcc, fps, (width, height))

    # Quản lý trạng thái theo Track ID
    person_states = defaultdict(PersonState)
    
    cone_centers = []
    # Ép buộc hệ thống phải quét cone ngay ở frame đầu tiên
    last_cone_scan_time = -CONE_SCAN_INTERVAL 
    
    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_count += 1
        
        # Sử dụng thời gian quy đổi từ frame video thay vì time.time()
        # Điều này giúp logic không bị sai lệch nếu máy tính xử lý nhanh hoặc chậm hơn thời gian thực
        current_time = frame_count / fps 
        
        # ----------------------------------------------------------------------
        # 1. XỬ LÝ ROI (Quét model bestcone mỗi 60s một lần)
        # ----------------------------------------------------------------------
        if current_time - last_cone_scan_time >= CONE_SCAN_INTERVAL:
            print(f"[{current_time:.1f}s] Đang quét vị trí Cone/Sign mới...")
            # Quét tĩnh nên không cần tracking
            results_cone = model_cone(frame, conf=CONE_CONFIDENCE, verbose=False)
            cone_centers.clear()
            
            if results_cone[0].boxes is not None:
                for box in results_cone[0].boxes:
                    cls_id = int(box.cls[0].item())
                    cls_name = model_cone.names[cls_id].lower()
                    
                    if 'cone' in cls_name or 'sign' in cls_name:
                        cx = (box.xyxy[0][0].item() + box.xyxy[0][2].item()) / 2
                        cy = box.xyxy[0][3].item() # Tính từ đáy (chân) của cone/sign chạm đất
                        cone_centers.append((cx, cy))
            
            last_cone_scan_time = current_time

        # Vẽ các vùng ROI đã lưu trên màn hình dưới dạng hình elip bẹt
        roi_radius_pixel = int(ROI_RADIUS_METER * PIXEL_PER_METER)
        roi_y_radius_pixel = int(roi_radius_pixel * PERSPECTIVE_RATIO)
        for cx, cy in cone_centers:
            cv2.ellipse(frame, (int(cx), int(cy)), (roi_radius_pixel, roi_y_radius_pixel), 0, 0, 360, (0, 255, 255), 2)
            cv2.putText(frame, "ROI / Cam vao", (int(cx) - 40, int(cy) - roi_y_radius_pixel - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

        # ----------------------------------------------------------------------
        # 2. XỬ LÝ PPE (Sử dụng tracking để định danh ID)
        # ----------------------------------------------------------------------
        results_ppe = model_ppe.track(frame, conf=PPE_CONFIDENCE, persist=True, tracker="botsort.yaml", verbose=False)
        
        persons = []
        helmets = []
        vests = []
        
        if results_ppe[0].boxes is not None:
            for box in results_ppe[0].boxes:
                cls_id = int(box.cls[0].item())
                cls_name = model_ppe.names[cls_id].lower()
                
                # Phân loại box theo tên class
                if 'person' in cls_name:
                    track_id = int(box.id[0].item()) if box.id is not None else None
                    persons.append((box, track_id))
                elif 'helmet' in cls_name or 'hat' in cls_name:
                    helmets.append(box)
                elif 'vest' in cls_name or 'jacket' in cls_name:
                    vests.append(box)

        # Duyệt qua các đối tượng Person đã được track để tính toán logic
        for p_box, track_id in persons:
            if track_id is None:
                continue # Bỏ qua nếu người chưa được gán ID từ tracker
                
            state = person_states[track_id]
            px1, py1, px2, py2 = p_box.xyxy[0].tolist()
            p_feet_x, p_feet_y = (px1 + px2) / 2, py2 # Dùng toạ độ bàn chân (đáy bounding box)
            
            # Kiểm tra xem tâm của Mũ/Áo có nằm trong Bbox của người hay không (IOV cơ bản)
            has_helmet = False
            for h_box in helmets:
                if is_center_inside(h_box.xyxy[0].tolist(), [px1, py1, px2, py2]):
                    has_helmet = True
                    break
                    
            has_vest = False
            for v_box in vests:
                if is_center_inside(v_box.xyxy[0].tolist(), [px1, py1, px2, py2]):
                    has_vest = True
                    break
                    
            # Cập nhật thời điểm gần nhất có đủ đồ bảo hộ
            if has_helmet and has_vest:
                state.last_full_ppe_time = current_time

            # Nếu ID này đã được xác nhận đủ PPE trong 3 phút qua, tự động bỏ qua (coi như có đủ đồ) để tránh spam
            if current_time - state.last_full_ppe_time < VALID_IGNORE_TIME:
                has_helmet = True
                has_vest = True
                    
            # ------------------------------------------------------------------
            # Logic tính toán thời gian PPE
            # ------------------------------------------------------------------
            missing_items = []
            if not has_helmet: missing_items.append("Helmet")
            if not has_vest: missing_items.append("Vest")
            missing_text = "Thiếu " + " & ".join(missing_items) if missing_items else ""

            if has_helmet and has_vest:
                # Nếu đã đội đủ Mũ và Áo, thiết lập người này là Hợp lệ
                state.missing_ppe_start_time = None
                state.is_valid = True
            else:
                if state.missing_ppe_start_time is None:
                    state.missing_ppe_start_time = current_time
                    
                # Tính thời gian đã thiếu
                duration_missing = current_time - state.missing_ppe_start_time
                if duration_missing >= PPE_CHECK_TIME:
                    # Bị coi là không hợp lệ do thiếu đồ bảo hộ quá thời gian quy định
                    state.is_valid = False
                    
                    # Cảnh báo tức thì nếu đã qua thời gian chờ cooldown (10s)
                    if current_time - state.last_ppe_warning_time >= PPE_WARNING_COOLDOWN:
                        play_sound(WARNING_PPE_SOUND)
                        log_violation(track_id, missing_text)
                        
                        # Cập nhật lại mốc thời gian cảnh báo
                        state.last_ppe_warning_time = current_time
                            
            # ------------------------------------------------------------------
            # Logic Xâm nhập ROI (5 giây)
            # ------------------------------------------------------------------
            in_roi = False
            for cx, cy in cone_centers:
                # Kiểm tra xem điểm (p_feet_x, p_feet_y) có nằm trong hình elip không
                # Phương trình elip: (x-cx)^2 / a^2 + (y-cy)^2 / b^2 <= 1
                dx = p_feet_x - cx
                dy = p_feet_y - cy
                if (dx ** 2) / (roi_radius_pixel ** 2) + (dy ** 2) / (roi_y_radius_pixel ** 2) <= 1:
                    in_roi = True
                    break
            
            # Chỉ cảnh báo nếu người này KHÔNG HỢP LỆ và ĐANG Ở TRONG ROI
            if not state.is_valid and in_roi:
                if state.roi_intrusion_start_time is None:
                    # Bắt đầu tính giờ xâm nhập
                    state.roi_intrusion_start_time = current_time
                else:
                    duration_intrusion = current_time - state.roi_intrusion_start_time
                    if duration_intrusion >= ROI_VIOLATION_TIME:
                        # Ở trong vùng cấm lâu hơn thời gian cho phép
                        if not state.roi_violation_logged:
                            play_sound(WARNING_ROI_SOUND)
                            log_violation(track_id, "Xâm nhập vùng cấm")
                            state.roi_violation_logged = True
            else:
                # Nếu không trong ROI hoặc trở thành người Hợp lệ thì reset bộ đếm ROI
                state.roi_intrusion_start_time = None
                state.roi_violation_logged = False

            # ------------------------------------------------------------------
            # Visualization - Vẽ Box và Trạng thái lên màn hình
            # ------------------------------------------------------------------
            color = (0, 255, 0) if state.is_valid else (0, 0, 255) # Xanh: Hợp lệ, Đỏ: Không hợp lệ
            
            # Cập nhật text hiển thị để ghi rõ thiếu cái gì
            if state.is_valid:
                status_text = "Valid"
            else:
                status_text = f"Invalid ({missing_text})"
                
            # Vẽ Bounding Box quanh người và đánh dấu bàn chân
            cv2.rectangle(frame, (int(px1), int(py1)), (int(px2), int(py2)), color, 2)
            cv2.circle(frame, (int(p_feet_x), int(p_feet_y)), 5, color, -1) # Chấm tròn ở chân
            cv2.putText(frame, f"ID:{track_id} {status_text}", (int(px1), int(py1) - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                        
            # Cảnh báo trên màn hình nếu vi phạm ROI
            if state.roi_violation_logged:
                cv2.putText(frame, "INTRUSION WARNING!", (int(px1), int(py1) - 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        
        # (Tuỳ chọn) Vẽ Bounding box cho Mũ và Áo
        for h_box in helmets:
            hx1, hy1, hx2, hy2 = h_box.xyxy[0].tolist()
            cv2.rectangle(frame, (int(hx1), int(hy1)), (int(hx2), int(hy2)), (255, 0, 0), 1) # Xanh dương
        for v_box in vests:
            vx1, vy1, vx2, vy2 = v_box.xyxy[0].tolist()
            cv2.rectangle(frame, (int(vx1), int(vy1)), (int(vx2), int(vy2)), (0, 165, 255), 1) # Cam

        # Hiển thị frame lên màn hình
        cv2.imshow("Safety Monitor System", frame)
        out.write(frame)

        # Nhấn 'q' để thoát
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Dọn dẹp tài nguyên
    cap.release()
    out.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
