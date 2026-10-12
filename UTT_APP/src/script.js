document.addEventListener("DOMContentLoaded", () => {
    const appState = {
        activePage: "home",
        activeCamera: { id: "1", name: "CAM 01 - Camera Dieu Hanh" },
        notifCount: 0,
        lastLogSignature: "",
        audioUnlocked: false,
        logTimer: null,
        theme: "light",
        isZoomed: false,
        delaySec: 3,
        senderSessionId: localStorage.getItem("utt_sender_session") || "",
        senderRunning: false,
        senderStream: null,
    };

    const navItems = document.querySelectorAll(".nav-item");
    const sections = document.querySelectorAll(".page-section");
    const notifBadge = document.getElementById("notif-count");
    const notifBtn = document.getElementById("btn-notifications");
    const statsTableBody = document.getElementById("stats-table-body");
    const activeCamLabel = document.getElementById("active-cam-label");
    const fileUpload = document.getElementById("file-upload");
    const uploadButton = document.getElementById("btn-upload-video");
    const openStatsButton = document.getElementById("btn-open-stats");
    const ppeAudio = document.getElementById("audio-warning");
    const alarmAudio = document.getElementById("audio-alarm");
    const startupOverlay = document.getElementById("startup-overlay");
    const btnStartApp = document.getElementById("btn-start-app");
    const themeToggle = document.getElementById("theme-toggle");
    const dashTotal = document.getElementById("dash-total");
    const dashPpe = document.getElementById("dash-ppe");

    const senderDeviceNameInput = document.getElementById("sender-device-name");
    const senderLoginButton = document.getElementById("btn-sender-login");
    const senderStartButton = document.getElementById("btn-sender-start");
    const senderStopButton = document.getElementById("btn-sender-stop");
    const senderStatusText = document.getElementById("sender-status-text");

    const mobileVideo = document.createElement("video");
    mobileVideo.setAttribute("playsinline", "");
    mobileVideo.muted = true;
    const senderCanvas = document.createElement("canvas");

    const audioState = { lockUntil: 0, timerId: null, pendingType: null };

    const setSenderStatus = (text) => {
        if (senderStatusText) senderStatusText.textContent = `Trạng thái CAM2 sender: ${text}`;
    };

    const applyTheme = (themeName) => {
        const normalized = themeName === "dark" ? "dark" : "light";
        document.documentElement.setAttribute("data-theme", normalized);
        localStorage.setItem("utt_theme", normalized);
        appState.theme = normalized;
        if (themeToggle) themeToggle.checked = normalized === "dark";
    };

    applyTheme(localStorage.getItem("utt_theme") || "light");
    if (themeToggle) themeToggle.addEventListener("change", () => applyTheme(themeToggle.checked ? "dark" : "light"));

    const showCameraBanner = (message) => {
        if (!cameraBanner) return;
        cameraBanner.textContent = message;
        cameraBanner.classList.remove("hidden");
    };

    const hideCameraBanner = () => {
        if (!cameraBanner) return;
        cameraBanner.classList.add("hidden");
    };

    const getActiveFilters = () => ["helmet", "vest", "sign"]
        .map((key) => document.getElementById(`filter-${key}`))
        .filter((el) => el && el.checked)
        .map((el) => el.id.replace("filter-", ""))
        .join(",");

    const hasFilterEnabled = (name) => Boolean(document.getElementById(`filter-${name}`)?.checked);

    const shouldNotifyByFilters = (log) => {
        const type = String(log.type || "").toUpperCase();
        const detail = String(log.detail || "").toLowerCase();
        if (type === "PPE") {
            const helmetMentioned = detail.includes("helmet");
            const vestMentioned = detail.includes("vest");
            if (helmetMentioned && !vestMentioned) return hasFilterEnabled("helmet");
            if (vestMentioned && !helmetMentioned) return hasFilterEnabled("vest");
            return hasFilterEnabled("helmet") || hasFilterEnabled("vest");
        }
        return true;
    };

    const playAlertSound = (type) => {
        if (!appState.audioUnlocked) return;
        const normalized = "PPE";
        const now = Date.now();
        if (now < audioState.lockUntil) {
            if (normalized === "FALL") audioState.pendingType = "FALL";
            else if (!audioState.pendingType) audioState.pendingType = "PPE";
            return;
        }

        ppeAudio.pause();
        alarmAudio.pause();
        ppeAudio.currentTime = 0;
        alarmAudio.currentTime = 0;

        const target = ppeAudio;
        target.play().catch(() => {});

        audioState.lockUntil = Date.now() + 1800;
        if (audioState.timerId) clearTimeout(audioState.timerId);
        audioState.timerId = setTimeout(() => {
            audioState.lockUntil = 0;
            if (audioState.pendingType) {
                const pending = audioState.pendingType;
                audioState.pendingType = null;
                playAlertSound(pending);
            }
        }, 1850);
    };

    const clearAlertEffects = () => {
        [1, 3, 4].forEach(id => {
            const card = document.getElementById(`card-cam-${id}`);
            if (card) card.classList.remove("flash-red");
        });
        if (notifBtn) notifBtn.classList.remove("bell-shake");
        if (notifBadge) notifBadge.classList.remove("pulse");
    };

    const processNotification = (log) => {
        if (!shouldNotifyByFilters(log)) return;
        
        const camStr = String(log.camera || "");
        let cardId = null;
        if (camStr.includes("01")) cardId = "card-cam-1";
        else if (camStr.includes("03")) cardId = "card-cam-3";
        else if (camStr.includes("04")) cardId = "card-cam-4";
        
        if (cardId) {
            const card = document.getElementById(cardId);
            if (card) card.classList.add("flash-red");
        }

        if (notifBtn) notifBtn.classList.add("bell-shake");

        appState.notifCount += 1;
        if (notifBadge) {
            notifBadge.textContent = String(appState.notifCount);
            notifBadge.classList.add("pulse");
        }

        playAlertSound(log.type || "PPE");
        if (navigator.vibrate) navigator.vibrate([180, 80, 180]);
        setTimeout(clearAlertEffects, 3000);
    };

    const updateStatsTable = (logs) => {
        if (statsTableBody) {
            statsTableBody.innerHTML = logs.slice(0, 15).map((log) => `
                <tr>
                    <td>${log.time || ""}</td>
                    <td style="font-weight:600">${log.camera || "CAM 01"}</td>
                    <td><span class="badge-warning">
                        [${log.id ?? "?"}] | ${log.type}: ${log.detail || ""}
                    </span></td>
                </tr>
            `).join("");
        }
        const sidebarList = document.getElementById("sidebar-log-list");
        if (sidebarList) {
            if (logs.length === 0) {
                sidebarList.innerHTML = '<li class="log-item empty">Hệ thống đang hoạt động ổn định...</li>';
            } else {
                sidebarList.innerHTML = logs.slice(0, 10).map((log) => `
                    <li class="log-item">
                        <strong style="color:var(--danger)">${log.camera || "CAM 01"}</strong>
                        <span>[${log.id ?? "?"}] ${log.type}: ${log.detail || ""}</span>
                        <small style="color:var(--text-muted)">${log.time || ""}</small>
                    </li>
                `).join("");
            }
        }
    };


    const fetchLogs = async () => {
        try {
            const response = await fetch("/api/logs");
            const data = await response.json();
            const logs = data.logs || [];
            if (logs.length > 0) {
                const newest = logs[0];
                const signature = `${newest.id}|${newest.time}|${newest.type}|${newest.detail}`;
                if (signature !== appState.lastLogSignature) {
                    appState.lastLogSignature = signature;
                    processNotification(newest);
                }
            }
            if (appState.activePage !== "stats") updateStatsTable(logs);
        } catch (error) {
            console.error("fetch logs error", error);
        }
    };

    const loadDashboard = async () => {
        try {
            const response = await fetch("/api/violations/dashboard");
            const data = await response.json();
            if (dashTotal) dashTotal.textContent = String(data.total || 0);
            if (dashPpe) dashPpe.textContent = String((data.by_type && data.by_type.PPE) || 0);
        } catch (error) {
            console.error("dashboard error", error);
        }
    };

    const loadDbHistory = async () => {
        try {
            const response = await fetch("/api/logs/history?limit=100");
            const rows = await response.json();
            if (!statsTableBody || !Array.isArray(rows)) return;
            statsTableBody.innerHTML = rows.map((row) => `
                <tr>
                    <td>${row.timestamp || row.time || ""}</td>
                    <td style="font-weight:600">${row.camera || "CAM 01"}</td>
                    <td><span class="badge-warning">
                        [${row.track_id ?? row.id ?? "?"}] | ${row.type}: ${row.detail || ""}
                    </span></td>
                </tr>
            `).join("");
        } catch (error) {
            console.error("history error", error);
        }
    };

    const navigateTo = (target) => {
        navItems.forEach((item) => item.classList.toggle("active", item.getAttribute("data-target") === target));
        sections.forEach((section) => section.classList.toggle("active", section.id === `section-${target}`));
        appState.activePage = target;
        if (target === "system") loadCameraList();
        if (target === "stats") {
            loadDashboard();
            loadDbHistory();
        }
    };

    navItems.forEach((item) => {
        item.addEventListener("click", (event) => {
            event.preventDefault();
            const target = item.getAttribute("data-target");
            if (target) navigateTo(target);
        });
    });

    if (openStatsButton) openStatsButton.addEventListener("click", () => navigateTo("stats"));

    const setZoomState = (isZoomed) => {
        appState.isZoomed = isZoomed;
    };

    const updateStreamUrl = () => {
        const filters = getActiveFilters();
        [1, 3, 4].forEach(id => {
            const img = document.getElementById(`stream-img-${id}`);
            if (img) {
                img.src = `/video_feed/${id}?filters=${filters}&pipeline=db_delay&delay_sec=${appState.delaySec}&t=${Date.now()}`;
            }
        });
    };

    ["helmet", "vest", "sign"].forEach((name) => {
        const el = document.getElementById(`filter-${name}`);
        if (el) el.addEventListener("change", updateStreamUrl);
    });


    const loadCameraList = async () => {
        const container = document.getElementById("system-cam-list");
        if (!container) return;

        container.innerHTML = '<p style="padding:20px; color:var(--text-muted)">Đang tải...</p>';
        try {
            const response = await fetch("/api/cameras");
            const cameras = await response.json();
            container.innerHTML = cameras.map((camera) => `
                <button class="cam-list-item glass cam-btn" type="button" data-id="${camera.id}" data-name="${camera.name}" data-status="${camera.status}">
                    <div class="ai-indicator ${(camera.status === "online" || camera.status === "available") ? "active" : ""}"></div>
                    <div class="cam-info">
                        <strong>${camera.name}</strong>
                        <small>${String(camera.status).toUpperCase()} | ${camera.device_name || "Unknown Device"}</small>
                    </div>
                    <i data-lucide="chevron-right" style="margin-left:auto; color:var(--text-muted)"></i>
                </button>
            `).join("");
            lucide.createIcons();

            container.querySelectorAll(".cam-btn").forEach((button) => {
                button.addEventListener("click", () => {
                    const status = String(button.getAttribute("data-status") || "").toLowerCase();
                    if (status !== "online" && status !== "available") {
                        showCameraBanner("Camera offline");
                        return;
                    }
                    const id = button.getAttribute("data-id") || "1";
                    const name = button.getAttribute("data-name") || "CAM";
                    appState.activeCamera = { id, name };
                    activeCamLabel.textContent = name.toUpperCase();
                    currentStreamTag.textContent = id === "2" ? "IPHONE STREAM" : (id === "3" ? "VIDEO LOOP" : "LIVE MONITORING");
                    updateStreamUrl();
                    navigateTo("home");
                });
            });
        } catch (error) {
            container.innerHTML = "<p style='padding:20px'>Lỗi tải camera list.</p>";
        }
    };

    if (uploadButton && fileUpload) uploadButton.addEventListener("click", () => fileUpload.click());
    if (fileUpload) {
        fileUpload.addEventListener("change", async () => {
            if (!fileUpload.files.length) return;
            const formData = new FormData();
            formData.append("file", fileUpload.files[0]);
            try {
                const response = await fetch("/api/upload_video", { method: "POST", body: formData });
                const data = await response.json();
                if (data.status === "success") {
                    appState.activeCamera = { id: "3", name: "CAM 03 - Video Da Ghi" };
                    activeCamLabel.textContent = "CAM 03 - VIDEO DA GHI";
                    currentStreamTag.textContent = "VIDEO LOOP";
                    updateStreamUrl();
                    navigateTo("home");
                }
            } catch (error) {
                alert("Lỗi tải video");
            } finally {
                fileUpload.value = "";
            }
        });
    }

    const getSenderDeviceName = () => {
        const value = (senderDeviceNameInput?.value || localStorage.getItem("utt_sender_device_name") || "").trim();
        return value || "iPhone Cong Truong";
    };

    const senderLogin = async () => {
        const deviceName = getSenderDeviceName();
        localStorage.setItem("utt_sender_device_name", deviceName);
        if (senderDeviceNameInput) senderDeviceNameInput.value = deviceName;

        const response = await fetch("/api/device_login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device_name: deviceName, platform: navigator.platform || "mobile" }),
        });
        const data = await response.json();
        if (data.status !== "success") throw new Error(data.message || "Login failed");

        appState.senderSessionId = data.session_id || "";
        localStorage.setItem("utt_sender_session", appState.senderSessionId);
        setSenderStatus(`đã đăng nhập: ${deviceName}`);
    };

    const senderLoop = async () => {
        if (!appState.senderRunning || !appState.senderStream) return;
        senderCanvas.width = 640;
        senderCanvas.height = 480;
        const ctx = senderCanvas.getContext("2d");
        ctx.drawImage(mobileVideo, 0, 0, 640, 480);
        const image = senderCanvas.toDataURL("image/jpeg", 0.62);

        try {
            await fetch("/api/iphone_ingest", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image, session_id: appState.senderSessionId, device_name: getSenderDeviceName() }),
            });
        } catch (error) {
            setSenderStatus(`lỗi gửi dữ liệu: ${error.message}`);
        }

        if (appState.senderRunning) setTimeout(senderLoop, 220);
    };

    const startSender = async () => {
        try {
            if (!appState.senderSessionId) await senderLogin();
            if (appState.senderRunning) return;
            const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
            appState.senderStream = stream;
            appState.senderRunning = true;
            mobileVideo.srcObject = stream;
            await mobileVideo.play();
            setSenderStatus("đang gửi camera trực tiếp về CAM2...");
            senderLoop();
        } catch (error) {
            setSenderStatus(`không thể bật camera: ${error.message}`);
        }
    };

    const stopSender = () => {
        appState.senderRunning = false;
        if (appState.senderStream) appState.senderStream.getTracks().forEach((track) => track.stop());
        appState.senderStream = null;
        setSenderStatus("đã dừng gửi");
    };

    if (senderDeviceNameInput) senderDeviceNameInput.value = localStorage.getItem("utt_sender_device_name") || "";
    setSenderStatus(appState.senderSessionId ? "đã có phiên đăng nhập" : "chưa đăng nhập");

    if (senderLoginButton) {
        senderLoginButton.addEventListener("click", async () => {
            try { await senderLogin(); }
            catch (error) { setSenderStatus(`đăng nhập thất bại: ${error.message}`); }
        });
    }
    if (senderStartButton) senderStartButton.addEventListener("click", startSender);
    if (senderStopButton) senderStopButton.addEventListener("click", stopSender);

    const unlockMonitoring = async () => {
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            if (audioContext.state === "suspended") await audioContext.resume();
            ppeAudio.muted = false;
            alarmAudio.muted = false;
            appState.audioUnlocked = true;
        } catch (error) {
            // Silently ignore if audio context can't start without user gesture
        }
        
        if (!appState.logTimer) {
            fetchLogs();
            appState.logTimer = setInterval(fetchLogs, 1500);
        }
    };

    const btnConnectWs = document.getElementById("btn-connect-ws");
    const localVideo = document.getElementById("local-video");
    const aiCanvas = document.getElementById("ai-canvas");
    let ctx = null;
    let ws = null;
    let aiStreamingActive = false;

    const syncCanvasSize = () => {
        if (!localVideo || !aiCanvas) return;
        const vw = localVideo.videoWidth || localVideo.clientWidth;
        const vh = localVideo.videoHeight || localVideo.clientHeight;
        if (vw > 0 && vh > 0 && (aiCanvas.width !== vw || aiCanvas.height !== vh)) {
            aiCanvas.width = vw;
            aiCanvas.height = vh;
        }
    };

    const drawAIDetections = (detections) => {
        if (!aiCanvas || !ctx) return;
        syncCanvasSize();
        ctx.clearRect(0, 0, aiCanvas.width, aiCanvas.height);

        detections.forEach(det => {
            const [x1, y1, x2, y2] = det.box;
            const bw = x2 - x1, bh = y2 - y1;

            let color, lineWidth, fontSize;

            if (det.type === "helmet") {
                color = "#00e5ff";      // cyan
                lineWidth = 2;
                fontSize = 12;
            } else if (det.type === "vest") {
                color = "#ff9800";     // orange
                lineWidth = 2;
                fontSize = 12;
            } else {
                // overall safety status — thicker box
                color = det.is_valid ? "#00e676" : "#ff1744";
                lineWidth = 3;
                fontSize = 14;
            }

            // Glow + box
            ctx.shadowColor = color;
            ctx.shadowBlur = det.type === "overall" ? 16 : 6;
            ctx.strokeStyle = color;
            ctx.lineWidth = lineWidth;
            ctx.strokeRect(x1, y1, bw, bh);
            ctx.shadowBlur = 0;

            // Label pill background
            const label = det.label;
            ctx.font = `bold ${fontSize}px 'Plus Jakarta Sans', sans-serif`;
            const textW = ctx.measureText(label).width;
            const pillH = fontSize + 8;
            const pillY = y1 > pillH + 2 ? y1 - pillH - 2 : y2 + 2;

            ctx.fillStyle = color;
            ctx.globalAlpha = 0.88;
            ctx.beginPath();
            ctx.roundRect?.(x1, pillY, textW + 10, pillH + 2, 4) || ctx.fillRect(x1, pillY, textW + 10, pillH + 2);
            ctx.fill();
            ctx.globalAlpha = 1.0;

            // Label text
            ctx.fillStyle = det.type === "overall" && det.is_valid ? "#000" : "#000";
            ctx.fillText(label, x1 + 5, pillY + pillH - 3);
        });
    };


    const startAIStreaming = async () => {
        if (aiStreamingActive) return;
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: 640 }, height: { ideal: 480 } }
            });
            localVideo.srcObject = stream;

            // Safe update for button
            const btn = document.getElementById("btn-connect-ws");
            if (btn) {
                btn.innerHTML = '<i data-lucide="check-circle"></i> <span>AI Đang chạy</span>';
                btn.style.animation = "none";
                btn.style.background = "var(--success, #27ae60)";
                if (window.lucide) lucide.createIcons();
            }

            // Initialize ctx after confirming canvas is in DOM
            ctx = aiCanvas.getContext("2d");

            // Connect WebSocket
            const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
            const wsUrl = `${protocol}//${window.location.host}/ws/ai`;
            console.log("[AI] Connecting to", wsUrl);
            ws = new WebSocket(wsUrl);

            ws.onopen = () => console.log("[AI] WebSocket Connected");
            ws.onerror = (e) => console.error("[AI] WebSocket Error:", e);
            ws.onclose = () => { console.log("[AI] WebSocket closed"); aiStreamingActive = false; };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.status === "ok") drawAIDetections(data.detections || []);
                } catch (e) { /* ignore bad JSON */ }
            };

            const captureCanvas = document.createElement("canvas");
            const captureCtx = captureCanvas.getContext("2d");
            aiStreamingActive = true;

            const sendFrame = () => {
                if (!aiStreamingActive) return;
                if (ws && ws.readyState === WebSocket.OPEN &&
                    localVideo.readyState >= 2 &&
                    localVideo.videoWidth > 0) {
                    captureCanvas.width = localVideo.videoWidth;
                    captureCanvas.height = localVideo.videoHeight;
                    captureCtx.drawImage(localVideo, 0, 0);
                    captureCanvas.toBlob((blob) => {
                        if (blob && ws.readyState === WebSocket.OPEN) ws.send(blob);
                    }, "image/jpeg", 0.6);
                }
                setTimeout(sendFrame, 120); // ~8 FPS
            };

            // Start immediately if video already has metadata, otherwise wait
            if (localVideo.readyState >= 1 && localVideo.videoWidth > 0) {
                syncCanvasSize();
                sendFrame();
            } else {
                localVideo.onloadedmetadata = () => {
                    syncCanvasSize();
                    sendFrame();
                };
            }

        } catch (err) {
            console.error("[AI] Camera error:", err);
            alert("Lỗi truy cập camera: " + err.message);
        }
    };

    if (btnConnectWs) btnConnectWs.addEventListener("click", startAIStreaming);

    // Generate 11 No-Signal Cameras for 4x3 Grid
    const loopContainer = document.getElementById("loop-cameras-container");
    const generateNoSignalCams = () => {
        if (!loopContainer) return;
        loopContainer.innerHTML = "";
        for (let i = 2; i <= 12; i++) {
            const card = document.createElement("div");
            card.className = "camera-card";
            card.innerHTML = `
                <div class="cam-info-top">
                    <span class="cam-tag">CAM ${String(i).padStart(2, '0')} - NO SIGNAL</span>
                    <span class="ai-indicator"></span>
                </div>
                <div class="no-signal-container">
                    <div class="no-signal-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    </div>
                    <span class="no-signal-text">No Signal</span>
                </div>
            `;
            loopContainer.appendChild(card);
        }
    };
    generateNoSignalCams();

    // Auto start monitoring
    unlockMonitoring();
    // One-time click to unlock audio (browser policy)
    document.addEventListener("click", unlockMonitoring, { once: true });
    document.addEventListener("touchstart", unlockMonitoring, { once: true, passive: true });

    loadDashboard();
    updateStreamUrl();
    lucide.createIcons();

    if ("serviceWorker" in navigator) {
        window.addEventListener("load", () => {
            navigator.serviceWorker.register("/sw.js").catch(() => {});
        });
    }
});
