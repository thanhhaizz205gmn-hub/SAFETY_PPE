import os
import shutil
from ultralytics import YOLO

def convert_models():
    # 1. Danh sách các mô hình cần chuyển đổi (Đảm bảo các file .pt này nằm cùng thư mục với file script)
    models_to_convert = ['best.pt', 'cone_sign.pt', 'tuthenga.pt']
    output_dir = 'UTT_APP/models'
    
    # 2. Đảm bảo thư mục đầu ra tồn tại
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"📁 Đã tạo thư mục: {output_dir}")

    for model_name in models_to_convert:
        if os.path.exists(model_name):
            print(f"\n--- 🚀 Đang bắt đầu chuyển đổi: {model_name} ---")
            
            try:
                # Load model PyTorch
                model = YOLO(model_name)
                
                # Export sang ONNX với cấu hình tối ưu cho Safari/iOS
                # opset=12: Tương thích tốt nhất với ONNX Runtime Web
                # simplify=True: Tăng tốc độ inference trên mobile
                onnx_path = model.export(
                    format='onnx', 
                    opset=12, 
                    simplify=True,
                    imgsz=640
                )
                
                # Tên file onnx mặc định mà YOLO export ra
                default_onnx_name = model_name.replace('.pt', '.onnx')
                target_path = os.path.join(output_dir, default_onnx_name)
                
                # 3. Di chuyển file vào thư mục đích (Ghi đè nếu đã tồn tại)
                if os.path.exists(default_onnx_name):
                    shutil.move(default_onnx_name, target_path)
                    print(f"✅ Thành công: {model_name} -> {target_path}")
                else:
                    # Trường hợp YOLO export ra đường dẫn khác
                    shutil.move(onnx_path, target_path)
                    print(f"✅ Thành công: {onnx_path} -> {target_path}")

            except Exception as e:
                print(f"❌ Lỗi khi chuyển đổi {model_name}: {e}")
            
        else:
            print(f"⚠️ Cảnh báo: Không tìm thấy file {model_name} trong thư mục hiện tại.")

if __name__ == "__main__":
    # Đảm bảo bạn đã cài đặt: pip install ultralytics onnx onnxscript onnx-simplifier
    convert_models()
    print("\n--- ✨ Hoàn tất quá trình chuyển đổi cho hệ thống UTT AI SAFETY ---")