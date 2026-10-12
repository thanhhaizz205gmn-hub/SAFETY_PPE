# Real-Time AI Safety & PPE Violation Detection System (UTT APP)

[![Python](https://img.shields.io/badge/Python-3.10-blue?style=for-the-badge&logo=python)](https://python.org)
[![YOLOv8](https://img.shields.io/badge/Model-YOLOv8%20%7C%20Ultralytics-00FFFF?style=for-the-badge)](https://ultralytics.com)
[![OpenCV](https://img.shields.io/badge/Vision-OpenCV-green?style=for-the-badge&logo=opencv)](https://opencv.org)
[![Docker](https://img.shields.io/badge/Container-Docker-2496ED?style=for-the-badge&logo=docker)](https://www.docker.com/)

> **An intelligent Computer Vision surveillance platform for real-time safety compliance monitoring, PPE (Personal Protective Equipment) verification, restricted hazard zone tracking, and fall detection.**

---

## Key Features

1. **PPE Compliance Detection**:
   - Real-time multi-class detection (hard hats, safety vests, boots) with adaptive confidence filtering.
   - Smart temporal cooldowns to prevent alarm fatigue and false positives from occlusion.

2. **3D Perspective Hazard Zone (Cone & Sign Tracking)**:
   - Dynamic scanning of safety cones and barrier signposts (`cone_sign.pt`).
   - Perspective-adjusted elliptical ground mapping (Perspective Ratio 0.4, configurable meter-to-pixel ratio) creating realistic 3D exclusion zones.

3. **Fall & Posture Anomaly Detection**:
   - Integrated custom pose classifier (`tuthenga.pt`) detecting sudden collapses and falls.

4. **Instant Audio-Visual Alerts & Incident Logging**:
   - Low-latency acoustic warning dispatcher (Pygame concurrent audio mixer).
   - Structured audit trails written to SQLite database (`safety_logs.db`) and timestamped CSV loggers.

5. **Web Analytics Dashboard & PWA**:
   - Progressive Web App dashboard monitoring live safety violations, camera feeds, and daily compliance rates.

---

## Getting Started

### 1. Local Environment
```bash
# Clone the repository
git clone https://github.com/thanhhaizz205gmn-hub/UTT_APP.git
cd UTT_APP

# Install dependencies
pip install -r requirements.txt

# Run Safety Monitoring System
python safety_system.py
```

### 2. Launching Web App / Dashboard
```bash
cd UTT_APP
python app.py
```

---

## Tech Stack

- **Computer Vision & Deep Learning**: Ultralytics YOLOv8, OpenCV, PyTorch
- **Audio & Alerting**: Pygame Mixer, Threaded Audio Drivers
- **Data Persistence**: SQLite, Pandas
- **Web Interface**: Python Web Framework, HTML5/CSS3 PWA, Chart.js
- **Containerization**: Docker, Docker Compose

---

## Author

- **Do Thanh Hai** - *Computer Vision & AI Systems Developer*
- **Institution:** University of Transport Technology (UTT)
- **GitHub:** [@thanhhaizz205gmn-hub](https://github.com/thanhhaizz205gmn-hub)
