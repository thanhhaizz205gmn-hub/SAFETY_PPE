import cv2
import os
from ultralytics import YOLO

# ==============================================================================
# CẤU HÌNH
# ==============================================================================
PPE_MODEL_PATH = 'best.pt'
CONE_MODEL_PATH = 'bestcone.pt'
PPE_CONFIDENCE = 0.4
CONE_CONFIDENCE = 0.4

# Danh sách các ảnh cần test (lấy từ request của người dùng)
IMAGE_FILES = [
    "z7812565905513_6d1bd57236e980184333551c44c9e394.jpg",
    "z7812565908219_9052b12dcc36c6a2e6601c9b977a03d1.jpg",
    "z7812565910940_f51e50820cdb8f0af43f214b96f9255a.jpg",
    "z7812565916956_1be9d81e114ec925ad19651dd782bc37.jpg",
    "z7812616716155_f94a257307a73739a61213068d6f0418.jpg",
    "shopping1(1).png",
    "shopping.webp",
    "shopping (1).png"
]

OUTPUT_DIR = "test_results"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# ==============================================================================
# UTILS
# ==============================================================================
def is_center_inside(inner_box, outer_box):
    """Kiểm tra xem tâm của inner_box có nằm trong outer_box hay không"""
    ix1, iy1, ix2, iy2 = inner_box
    ox1, oy1, ox2, oy2 = outer_box
    cx = (ix1 + ix2) / 2
    cy = (iy1 + iy2) / 2
    return (ox1 <= cx <= ox2) and (oy1 <= cy <= oy2)

# ==============================================================================
# MAIN
# ==============================================================================
def main():
    print("Đang tải các models...")
    model_ppe = YOLO(PPE_MODEL_PATH)
    model_cone = YOLO(CONE_MODEL_PATH)

    for img_name in IMAGE_FILES:
        img_path = img_name
        if not os.path.exists(img_path):
            print(f"Warning: Không tìm thấy file {img_path}")
            continue

        print(f"Đang xử lý: {img_name}")
        frame = cv2.imread(img_path)
        if frame is None:
            continue

        # 1. Quét Cone/ROI
        results_cone = model_cone(frame, conf=CONE_CONFIDENCE, verbose=False)
        cone_centers = []
        if results_cone[0].boxes is not None:
            for box in results_cone[0].boxes:
                cls_id = int(box.cls[0].item())
                cls_name = model_cone.names[cls_id].lower()
                if 'cone' in cls_name or 'sign' in cls_name:
                    bx1, by1, bx2, by2 = box.xyxy[0].tolist()
                    cx = (bx1 + bx2) / 2
                    cy = by2 # Chân cone
                    cone_centers.append((cx, cy))
                    cv2.rectangle(frame, (int(bx1), int(by1)), (int(bx2), int(by2)), (0, 255, 255), 2)
                    cv2.putText(frame, cls_name, (int(bx1), int(by1) - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # 2. Quét PPE
        results_ppe = model_ppe(frame, conf=PPE_CONFIDENCE, verbose=False)
        persons = []
        helmets = []
        vests = []

        if results_ppe[0].boxes is not None:
            for box in results_ppe[0].boxes:
                cls_id = int(box.cls[0].item())
                cls_name = model_ppe.names[cls_id].lower()
                if 'person' in cls_name:
                    persons.append(box)
                elif 'helmet' in cls_name or 'hat' in cls_name:
                    helmets.append(box)
                elif 'vest' in cls_name or 'jacket' in cls_name:
                    vests.append(box)

        # 3. Logic PPE cho từng người
        for p_box in persons:
            px1, py1, px2, py2 = p_box.xyxy[0].tolist()
            
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

            # Vẽ kết quả
            is_valid = has_helmet and has_vest
            color = (0, 255, 0) if is_valid else (0, 0, 255)
            
            missing = []
            if not has_helmet: missing.append("Mũ")
            if not has_vest: missing.append("Áo")
            
            status = "Hợp lệ" if is_valid else f"Thiếu: {', '.join(missing)}"
            
            cv2.rectangle(frame, (int(px1), int(py1)), (int(px2), int(py2)), color, 2)
            cv2.putText(frame, status, (int(px1), int(py1) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # 4. Vẽ Helmet/Vest box nhỏ
        for h_box in helmets:
            hx1, hy1, hx2, hy2 = h_box.xyxy[0].tolist()
            cv2.rectangle(frame, (int(hx1), int(hy1)), (int(hx2), int(hy2)), (255, 0, 0), 1)
        for v_box in vests:
            vx1, vy1, vx2, vy2 = v_box.xyxy[0].tolist()
            cv2.rectangle(frame, (int(vx1), int(vy1)), (int(vx2), int(vy2)), (0, 165, 255), 1)

        # Lưu ảnh kết quả
        output_path = os.path.join(OUTPUT_DIR, f"result_{img_name}")
        cv2.imwrite(output_path, frame)
        print(f"Đã lưu: {output_path}")

    print("\nHoàn thành! Kết quả được lưu trong thư mục 'test_results'.")

if __name__ == "__main__":
    main()
