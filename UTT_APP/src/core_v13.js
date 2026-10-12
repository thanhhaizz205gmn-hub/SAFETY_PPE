document.addEventListener("DOMContentLoaded", () => {
    const BUILD_VERSION = "15.7";
    const LOG_POLL_INTERVAL_MS = 2500;
    const SENDER_FRAME_INTERVAL_MS = 120;
    const GRID_MOBILE_BREAKPOINT = 768;
    const DESKTOP_CAM_COUNT = 12;
    const MOBILE_CAM_COUNT = 6;
    const LOOP_SLOT_IDS = Array.from({ length: DESKTOP_CAM_COUNT }, (_, index) => index + 1);

    const appState = {
        activePage: "home",
        notifCount: 0,
        lastLogSignature: "",
        theme: "light",
        audioUnlocked: false,
        logTimer: null,
        cameras: [],
        mySlot: null,
        aiStreamingActive: false,
        liveStream: null,
        liveWs: null,
        liveSendTimer: null,
        liveAwaitingResult: false,
        senderSessionId: localStorage.getItem("utt_sender_session") || "",
        senderDeviceName: localStorage.getItem("utt_sender_device_name") || "",
        senderRunning: false,
        senderStream: null,
        senderTimer: null,
        senderFacingMode: "environment",
        overlayVisible: false,
        primaryCameraId: "1",
        senderInFlight: false,
        senderLatestImage: "",
        lastRenderedLogSignature: "",
        runtimeTimer: null,
        viewMode: localStorage.getItem("utt_view_mode") || "focus",
        streamUrlCache: {},
        heroRemoteReady: false,
    };

    const navItems = Array.from(document.querySelectorAll(".nav-item"));
    const sections = Array.from(document.querySelectorAll(".page-section"));
    const activeCamLabel = document.getElementById("active-cam-label");
    const notifBadge = document.getElementById("notif-count");
    const notifButton = document.getElementById("btn-notifications");
    const connectButton = document.getElementById("btn-connect-ws");
    const uploadLoopButton = document.getElementById("btn-upload-loop");
    const uploadVideoButton = document.getElementById("btn-upload-video");
    const openStatsButton = document.getElementById("btn-open-stats");
    const uploadInput = document.getElementById("video-upload-input");
    const cameraGrid = document.getElementById("loop-cameras-container");
    const mobileHeroCamera = document.getElementById("mobile-hero-camera");
    const mobileHeroRemote = document.getElementById("mobile-hero-remote");
    const mobileHeroLocal = document.getElementById("mobile-hero-local");
    const systemCamList = document.getElementById("system-cam-list");
    const statsTableBody = document.getElementById("stats-table-body");
    const dashTotal = document.getElementById("dash-total");
    const dashPpe = document.getElementById("dash-ppe");
    const sidebarLogList = document.getElementById("sidebar-log-list");
    const themeToggle = document.getElementById("theme-toggle");
    const localVideo = document.getElementById("local-video");
    const aiCanvas = document.getElementById("ai-canvas");
    const aiCanvasCtx = aiCanvas ? aiCanvas.getContext("2d") : null;
    const warningAudio = document.getElementById("audio-warning");
    const alarmAudio = document.getElementById("audio-alarm");
    const senderDeviceNameInput = document.getElementById("sender-device-name");
    const senderLoginButton = document.getElementById("btn-sender-login");
    const senderStartButton = document.getElementById("btn-sender-start");
    const senderStopButton = document.getElementById("btn-sender-stop");
    const senderStatusText = document.getElementById("sender-status-text");
    const mobileSenderOverlay = document.getElementById("mobile-sender-overlay");
    const mobilePreviewContainer = document.getElementById("mobile-preview-container");
    const senderStatusOverlay = document.getElementById("sender-status-text-overlay");
    const senderToggleLargeButton = document.getElementById("btn-sender-toggle-large");
    const senderFlipButton = document.getElementById("btn-sender-flip");
    const bottomNavBotButton = document.getElementById("ai-status-indicator");
    const primaryCameraBadge = document.getElementById("primary-cam-badge");
    const primaryCameraStatus = document.getElementById("primary-camera-status");
    const runtimeStatusText = document.getElementById("runtime-status-text");
    const primaryCameraSummary = document.getElementById("primary-cam-summary");
    const viewFocusButton = document.getElementById("btn-view-focus");
    const viewWallButton = document.getElementById("btn-view-wall");
    const runtimeHealthDevice = document.getElementById("runtime-health-device");
    const runtimeHealthWarmup = document.getElementById("runtime-health-warmup");
    const runtimeHealthPrimary = document.getElementById("runtime-health-primary");
    const runtimeHealthModel = document.getElementById("runtime-health-model");
    const mobileCamLegendText = document.getElementById("mobile-cam-legend-text");
    const mobileCamDebug = document.getElementById("mobile-cam-debug");
    const mobileCamDebug2 = document.getElementById("mobile-cam-debug-2");
    const mobileHeroRemoteLabel = document.getElementById("mobile-hero-remote-label");
    const mobileHeroLocalLabel = document.getElementById("mobile-hero-local-label");
    const senderCanvas = document.createElement("canvas");
    const senderCanvasCtx = senderCanvas.getContext("2d");
    const captureCanvas = document.createElement("canvas");
    const captureCanvasCtx = captureCanvas.getContext("2d");

    function getPrimaryCameraLabel() {
        return "CAM 01";
    }

    function isPrimaryCamera(camId) {
        return String(camId) === String(appState.primaryCameraId);
    }

    function applyTheme(themeName) {
        const normalized = themeName === "dark" ? "dark" : "light";
        document.documentElement.setAttribute("data-theme", normalized);
        localStorage.setItem("utt_theme", normalized);
        appState.theme = normalized;
        if (themeToggle) themeToggle.checked = normalized === "dark";
    }

    function setNotifCount(count) {
        appState.notifCount = Math.max(0, Number(count) || 0);
        if (notifBadge) notifBadge.textContent = String(appState.notifCount);
    }

    function setSenderStatus(text, tone = "idle") {
        const normalized = String(text || "").trim() || "sẵn sàng";
        const content = `Trạng thái PHONE sender CAM 01: ${normalized}`;
        if (senderStatusText) senderStatusText.textContent = content;
        if (senderStatusOverlay) senderStatusOverlay.textContent = normalized.toUpperCase();

        const isActive = tone === "running";
        const isError = tone === "error";
        if (senderToggleLargeButton) {
            senderToggleLargeButton.classList.toggle("btn-success", isActive);
            senderToggleLargeButton.classList.toggle("btn-danger", isError);
        }
    }

    function showToast(message, tone = "info") {
        const toast = document.createElement("div");
        toast.className = `app-toast ${tone}`;
        toast.textContent = message;
        toast.style.cssText = [
            "position:fixed",
            "right:20px",
            "bottom:20px",
            "z-index:3000",
            "padding:10px 16px",
            "border-radius:999px",
            "font-size:12px",
            "font-weight:700",
            "color:#fff",
            `background:${tone === "error" ? "#c62828" : tone === "success" ? "#1b8f4d" : "#0d7ce8"}`,
            "box-shadow:0 12px 24px rgba(0,0,0,0.18)",
        ].join(";");
        document.body.appendChild(toast);
        window.setTimeout(() => toast.remove(), 2600);
    }

    function updateHeaderStatus(text) {
        const el = document.getElementById("yolo-status-text");
        if (el) el.textContent = text;
    }

    function updatePrimaryCameraUi() {
        const label = getPrimaryCameraLabel();
        appState.primaryCameraId = "1";
        if (primaryCameraBadge) primaryCameraBadge.textContent = "AI PRIMARY: CAM 01";
        if (primaryCameraStatus) primaryCameraStatus.textContent = "AI chủ lực hiện tại: CAM 01 cố định.";
        if (primaryCameraSummary) primaryCameraSummary.textContent = "GPU-first • Phone path locked to CAM 01 • Low-latency";
        if (runtimeHealthPrimary) runtimeHealthPrimary.textContent = label;
        if (mobileCamLegendText) {
            mobileCamLegendText.textContent = appState.aiStreamingActive
                ? "Bạn đang xem trực tiếp khung PHONE/AI realtime của CAM 01."
                : "Đây là khung camera chính cho PHONE và AI realtime.";
        }
        updateHeaderStatus(`SYSTEM ACTIVE • ${label}`);
    }

    function updateViewModeUi() {
        if (cameraGrid) {
            cameraGrid.classList.toggle("view-focus", appState.viewMode === "focus");
            cameraGrid.classList.toggle("view-wall", appState.viewMode === "wall");
        }
        if (viewFocusButton) viewFocusButton.classList.toggle("active", appState.viewMode === "focus");
        if (viewWallButton) viewWallButton.classList.toggle("active", appState.viewMode === "wall");
    }

    function setViewMode(mode) {
        appState.viewMode = mode === "wall" ? "wall" : "focus";
        localStorage.setItem("utt_view_mode", appState.viewMode);
        updateViewModeUi();
        renderGrid();
    }

    function updateRuntimeUi(runtime) {
        if (!runtimeStatusText || !runtime) return;
        const device = runtime.device || "cpu";
        const provider = runtime.provider || "runtime";
        const detail = runtime.device_detail || "";
        const warmup = runtime.warmup_done ? `warmup ${runtime.warmup_ms}ms` : "warmup pending";
        runtimeStatusText.textContent = `AI runtime: ${device} | ${provider} | ${detail} | ${warmup}`;
        if (runtimeHealthDevice) runtimeHealthDevice.textContent = detail || device;
        if (runtimeHealthWarmup) runtimeHealthWarmup.textContent = runtime.warmup_done ? `${runtime.warmup_ms} ms` : "Pending";
        if (runtimeHealthModel) runtimeHealthModel.textContent = provider;
    }

    function getActiveFilters() {
        return ["helmet", "vest", "sign"]
            .map((name) => document.getElementById(`filter-${name}`))
            .filter((checkbox) => checkbox && checkbox.checked)
            .map((checkbox) => checkbox.id.replace("filter-", ""));
    }

    function isMobileViewport() {
        return window.innerWidth <= GRID_MOBILE_BREAKPOINT;
    }

    function isPortraitMobileViewport() {
        return isMobileViewport() && window.innerHeight >= window.innerWidth;
    }

    function shouldUseMobileHeroCamera() {
        return isMobileViewport() && appState.viewMode === "focus";
    }

    function ensureSingleCam1Card() {
        const cards = Array.from(document.querySelectorAll('[id="card-cam-1"]'));
        if (cards.length <= 1) return;
        const keeper = localVideo?.closest(".camera-card") || cards[0];
        cards.forEach((card) => {
            if (card !== keeper) card.remove();
        });
    }

    function getVisibleCameraCount() {
        if (shouldUseMobileHeroCamera()) return 1;
        if (isMobileViewport() && appState.viewMode === "focus") return 1;
        return isMobileViewport() ? MOBILE_CAM_COUNT : DESKTOP_CAM_COUNT;
    }

    function getCamStreamUrl(slotId) {
        const params = new URLSearchParams();
        params.set("filters", getActiveFilters().join(",") || "helmet,vest,sign");
        params.set("pipeline", "direct");
        params.set("delay_sec", "0");
        return `/video_feed/${slotId}?${params.toString()}`;
    }

    function padCameraId(id) {
        return String(id).padStart(2, "0");
    }

    function updateMobileHeroDebug(extra = "") {
        if (!mobileCamDebug2) return;
        const remoteLoaded = mobileHeroRemote && mobileHeroRemote.getAttribute("data-loaded") === "yes" ? "yes" : "no";
        const localReady = (mobileHeroLocal && mobileHeroLocal.srcObject) || (localVideo && localVideo.srcObject) ? "yes" : "no";
        const slot = appState.mySlot ? String(appState.mySlot) : "?";
        mobileCamDebug2.textContent = `remoteLoaded=${remoteLoaded} | localReady=${localReady} | slot=${slot}${extra ? ` | ${extra}` : ""}`;
    }

    function syncMobileHeroShell() {
        if (!mobileHeroCamera || !mobileHeroRemote || !mobileHeroLocal) return;
        const useHero = shouldUseMobileHeroCamera();
        if (!useHero) {
            mobileHeroCamera.style.display = "none";
            mobileHeroRemote.style.display = "none";
            mobileHeroRemote.removeAttribute("src");
            mobileHeroRemote.removeAttribute("data-loaded");
            mobileHeroLocal.style.display = "none";
            mobileHeroLocal.srcObject = null;
            if (mobileHeroRemoteLabel) mobileHeroRemoteLabel.style.display = "none";
            if (mobileHeroLocalLabel) mobileHeroLocalLabel.style.display = "none";
            return;
        }

        mobileHeroCamera.style.display = "block";
        if (mobileHeroRemoteLabel) mobileHeroRemoteLabel.style.display = "inline-flex";
        if (mobileHeroLocalLabel) mobileHeroLocalLabel.style.display = "inline-flex";

        if (localVideo && localVideo.srcObject && mobileHeroLocal.srcObject !== localVideo.srcObject) {
            mobileHeroLocal.srcObject = localVideo.srcObject;
        }
        if (mobileHeroLocal.srcObject) {
            mobileHeroLocal.style.display = "block";
            mobileHeroLocal.play().catch(() => {});
        } else {
            mobileHeroLocal.style.display = "none";
        }

        if (appState.aiStreamingActive) {
            const source = `${getCamStreamUrl(1)}&t=${Date.now()}`;
            mobileHeroRemote.style.display = "block";
            mobileHeroRemote.setAttribute("data-loaded", "loading");
            mobileHeroRemote.src = source;
            mobileHeroRemote.onload = () => {
                mobileHeroRemote.setAttribute("data-loaded", "yes");
                mobileHeroLocal.classList.remove("hero-local-feed");
                mobileHeroLocal.classList.add("local-preview");
                if (mobileCamDebug) mobileCamDebug.textContent = "Hero source: REMOTE live feed | Inset: LOCAL preview";
                updateMobileHeroDebug("remote=onload");
            };
            mobileHeroRemote.onerror = () => {
                mobileHeroRemote.setAttribute("data-loaded", "error");
                mobileHeroLocal.classList.add("hero-local-feed");
                mobileHeroLocal.classList.remove("local-preview");
                if (mobileCamDebug) mobileCamDebug.textContent = "Hero source: LOCAL fallback | Remote unavailable";
                updateMobileHeroDebug("remote=error");
            };
            if (mobileHeroRemote.getAttribute("data-loaded") !== "yes") {
                mobileHeroLocal.classList.add("hero-local-feed");
                mobileHeroLocal.classList.remove("local-preview");
                if (mobileCamDebug) mobileCamDebug.textContent = "Hero source: waiting | Local shown full-size";
            }
        } else {
            mobileHeroRemote.style.display = "none";
            mobileHeroRemote.removeAttribute("src");
            mobileHeroRemote.removeAttribute("data-loaded");
            mobileHeroLocal.classList.add("hero-local-feed");
            mobileHeroLocal.classList.remove("local-preview");
            if (mobileCamDebug) mobileCamDebug.textContent = "Hero source: LOCAL only";
        }
        updateMobileHeroDebug("hero-sync");
    }

    function renderGrid() {
        if (!cameraGrid) return;
        if (isMobileViewport()) {
            appState.viewMode = "focus";
        }
        ensureSingleCam1Card();

        const previousCards = new Map();
        document.querySelectorAll(".camera-card[data-slot-id]").forEach((card) => {
            previousCards.set(card.getAttribute("data-slot-id"), card);
        });

        const fragment = document.createDocumentFragment();
        const visibleCount = getVisibleCameraCount();
        const useHero = shouldUseMobileHeroCamera() && Boolean(mobileHeroCamera);
        for (let slotId = 1; slotId <= visibleCount; slotId += 1) {
            let card = previousCards.get(String(slotId));
            if (!card) {
                card = document.createElement("div");
                card.className = slotId === 1 ? "camera-card active-ai" : "camera-card";
                card.id = `card-cam-${slotId}`;
                card.setAttribute("data-slot-id", String(slotId));
                card.innerHTML = `
                    <div class="cam-info-top">
                        <span class="cam-tag"></span>
                        <span class="ai-indicator pulse"></span>
                    </div>
                    <div class="stream-container${slotId === 1 ? " local-stream" : ""}">
                        ${slotId === 1
                            ? '<video id="local-video" autoplay playsinline muted class="stream-view" style="display:none;"></video><img id="remote-view-1" data-src="/api/video_feed/1" class="stream-view" alt="Camera 01"><canvas id="ai-canvas" class="ai-overlay-canvas"></canvas>'
                            : `<img data-src="/api/video_feed/${slotId}" class="stream-view lazy-slot" alt="Camera ${padCameraId(slotId)}">`}
                    </div>
                `;
            }

            const tag = card.querySelector(".cam-tag");
            if (tag) {
                const primarySuffix = isPrimaryCamera(slotId) ? " - PHONE AI PRIMARY" : " - REMOTE";
                tag.innerHTML = isPrimaryCamera(slotId)
                    ? `<i data-lucide="zap" style="color:var(--primary); width:14px;"></i> CAM ${padCameraId(slotId)}${primarySuffix}`
                    : `CAM ${padCameraId(slotId)}${primarySuffix}`;
            }

            if (!(useHero && slotId === 1)) fragment.appendChild(card);
        }

        cameraGrid.innerHTML = "";
        cameraGrid.appendChild(fragment);
        updateViewModeUi();

        if (useHero) {
            cameraGrid.style.display = "none";
            if (mobileHeroCamera) mobileHeroCamera.style.display = "block";
            if (mobileCamLegendText) {
                mobileCamLegendText.textContent = appState.aiStreamingActive
                    ? "Khung lớn là LIVE AI từ server. Ô nhỏ là preview local của phone."
                    : "Khung lớn sẽ hiển thị CAM 01 từ web-live khi có tín hiệu.";
            }
        } else if (mobileHeroCamera) {
            mobileHeroCamera.style.display = "";
            cameraGrid.style.display = "";
        }
        syncMobileHeroShell();

        const liveContainer =
            document.querySelector(`#card-cam-${appState.mySlot || 1} .stream-container`) ||
            document.querySelector("#card-cam-1 .stream-container");
        if (liveContainer && localVideo && aiCanvas) {
            const remoteImg = liveContainer.querySelector("img");
            const isMobileHeroLivePhone = appState.aiStreamingActive && shouldUseMobileHeroCamera() && Number(appState.mySlot || 1) === 1;
            if (isMobileHeroLivePhone) {
                if (remoteImg) {
                    remoteImg.style.display = "block";
                    remoteImg.src = `${getCamStreamUrl(1)}&t=${Date.now()}`;
                    remoteImg.classList.add("hero-live-feed");
                }
                localVideo.classList.add("local-preview");
                localVideo.style.display = "block";
                aiCanvas.style.display = "none";
            } else {
                liveContainer.appendChild(localVideo);
                liveContainer.appendChild(aiCanvas);
                if (remoteImg) {
                    remoteImg.style.display = appState.aiStreamingActive ? "none" : "block";
                    remoteImg.classList.remove("hero-live-feed");
                }
                localVideo.classList.remove("local-preview");
            }
        }

        document.querySelectorAll(".lazy-slot, #remote-view-1").forEach((img) => {
            if (!(img instanceof HTMLImageElement)) return;
            const slotCard = img.closest(".camera-card");
            const slotId = slotCard?.getAttribute("data-slot-id") || "1";
            const source = getCamStreamUrl(slotId);
            const cacheKey = `${slotId}:${source}`;
            const isMobileHeroLivePhone = appState.aiStreamingActive && shouldUseMobileHeroCamera() && Number(slotId) === 1;
            if (isMobileHeroLivePhone) {
                img.style.display = "block";
                img.classList.add("hero-live-feed");
                if (appState.streamUrlCache[slotId] !== cacheKey) {
                    img.src = `${source}&t=${Date.now()}`;
                    appState.streamUrlCache[slotId] = cacheKey;
                }
                return;
            }
            if (!appState.aiStreamingActive || Number(slotId) !== Number(appState.mySlot || 1)) {
                if (appState.streamUrlCache[slotId] !== cacheKey) {
                    img.src = source;
                    appState.streamUrlCache[slotId] = cacheKey;
                }
                img.style.display = "block";
            }
        });

        if (window.lucide) window.lucide.createIcons();
    }

    function syncCanvasSize() {
        if (!localVideo || !aiCanvas) return;
        const width = localVideo.clientWidth || localVideo.videoWidth;
        const height = localVideo.clientHeight || localVideo.videoHeight;
        if (!width || !height) return;
        if (aiCanvas.width !== width || aiCanvas.height !== height) {
            aiCanvas.width = width;
            aiCanvas.height = height;
        }
    }

    function getVideoCoverMetrics() {
        if (!localVideo || !aiCanvas) return null;
        const videoWidth = localVideo.videoWidth || 0;
        const videoHeight = localVideo.videoHeight || 0;
        const boxWidth = aiCanvas.width || localVideo.clientWidth || 0;
        const boxHeight = aiCanvas.height || localVideo.clientHeight || 0;
        if (!videoWidth || !videoHeight || !boxWidth || !boxHeight) return null;

        const scale = Math.max(boxWidth / videoWidth, boxHeight / videoHeight);
        const drawWidth = videoWidth * scale;
        const drawHeight = videoHeight * scale;
        const offsetX = (boxWidth - drawWidth) / 2;
        const offsetY = (boxHeight - drawHeight) / 2;

        return { scale, drawWidth, drawHeight, offsetX, offsetY, boxWidth, boxHeight };
    }

    function drawAIDetections(detections) {
        if (!aiCanvasCtx || !aiCanvas) return;
        syncCanvasSize();
        aiCanvasCtx.clearRect(0, 0, aiCanvas.width, aiCanvas.height);
        const metrics = getVideoCoverMetrics();
        if (!metrics) return;

        detections.forEach((det) => {
            const [x1, y1, x2, y2] = det.box || [];
            if ([x1, y1, x2, y2].some((value) => typeof value !== "number")) return;

            const drawX1 = x1 * metrics.scale + metrics.offsetX;
            const drawY1 = y1 * metrics.scale + metrics.offsetY;
            const drawX2 = x2 * metrics.scale + metrics.offsetX;
            const drawY2 = y2 * metrics.scale + metrics.offsetY;
            const width = drawX2 - drawX1;
            const height = drawY2 - drawY1;
            const color = det.type === "helmet"
                ? "#00e5ff"
                : det.type === "vest"
                    ? "#ff9800"
                    : det.is_valid
                        ? "#16c96b"
                        : "#ff3b30";

            aiCanvasCtx.strokeStyle = color;
            aiCanvasCtx.lineWidth = det.type === "overall" ? 3 : 2;
            aiCanvasCtx.shadowColor = color;
            aiCanvasCtx.shadowBlur = det.type === "overall" ? 12 : 6;
            aiCanvasCtx.strokeRect(drawX1, drawY1, width, height);
            aiCanvasCtx.shadowBlur = 0;

            const label = String(det.label || "").trim();
            if (!label) return;

            aiCanvasCtx.font = "bold 12px 'Plus Jakarta Sans', sans-serif";
            const labelWidth = aiCanvasCtx.measureText(label).width;
            const labelX = drawX1;
            const labelY = drawY1 > 20 ? drawY1 - 18 : drawY2 + 4;

            aiCanvasCtx.fillStyle = color;
            aiCanvasCtx.fillRect(labelX, labelY, labelWidth + 12, 18);
            aiCanvasCtx.fillStyle = "#06101d";
            aiCanvasCtx.fillText(label, labelX + 6, labelY + 13);
        });
    }

    function playAlertSound(logType) {
        if (!appState.audioUnlocked || !warningAudio) return;
        const target = String(logType || "").toUpperCase() === "FALL" && alarmAudio ? alarmAudio : warningAudio;
        try {
            target.pause();
            target.currentTime = 0;
            void target.play();
        } catch (error) {
            console.error("[audio] play failed", error);
        }
    }

    function flashNotificationUi() {
        if (notifButton) notifButton.classList.add("bell-shake");
        if (notifBadge) notifBadge.classList.add("pulse");
        window.setTimeout(() => {
            if (notifButton) notifButton.classList.remove("bell-shake");
            if (notifBadge) notifBadge.classList.remove("pulse");
        }, 1800);
    }

    function renderSidebarLogs(logs) {
        if (!sidebarLogList) return;
        if (!Array.isArray(logs) || logs.length === 0) {
            sidebarLogList.innerHTML = '<li class="log-item empty">Hệ thống đang hoạt động ổn định...</li>';
            appState.lastRenderedLogSignature = "";
            return;
        }

        const renderSignature = logs.slice(0, 10).map((log) => `${log.id}|${log.time}|${log.msg || log.detail || ""}`).join("||");
        if (renderSignature === appState.lastRenderedLogSignature) {
            return;
        }
        appState.lastRenderedLogSignature = renderSignature;

        sidebarLogList.classList.add("updating");
        sidebarLogList.innerHTML = logs.slice(0, 10).map((log) => `
            <li class="log-item">
                <strong style="color:var(--danger)">${log.camera || log.cam || "CAM 01"}</strong>
                <span>[${log.track_id ?? log.person_id ?? "?"}] ${log.type || "PPE"}: ${log.detail || log.msg || ""}</span>
                <small style="color:var(--text-muted)">${log.time || log.timestamp || ""}</small>
            </li>
        `).join("");
        const firstItem = sidebarLogList.querySelector(".log-item");
        if (firstItem) firstItem.classList.add("log-fresh");
        window.setTimeout(() => sidebarLogList.classList.remove("updating"), 180);
    }

    function renderStatsTable(rows) {
        if (!statsTableBody) return;
        if (!Array.isArray(rows) || rows.length === 0) {
            statsTableBody.innerHTML = '<tr><td colspan="3" style="padding:16px; color:var(--text-muted)">Chưa có dữ liệu vi phạm.</td></tr>';
            return;
        }

        statsTableBody.innerHTML = rows.map((row) => {
            const timestamp = row.timestamp || row.time || "";
            const camera = row.camera || row.cam || "CAM 01";
            const type = row.type || "PPE";
            const detail = row.detail || row.violation || row.msg || "";
            const trackId = row.track_id ?? row.person_id ?? row.id ?? "?";
            return `
                <tr>
                    <td>${timestamp}</td>
                    <td><span class="badge-cam">${camera}</span></td>
                    <td><span class="badge-warning">[${trackId}] ${type}: ${detail}</span></td>
                </tr>
            `;
        }).join("");
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
    }

    async function refreshLogs() {
        try {
            const data = await fetchJson("/api/logs");
            const logs = Array.isArray(data.logs) ? data.logs : [];
            renderSidebarLogs(logs);

            if (logs.length > 0) {
                const newest = logs[0];
                const signature = `${newest.id}|${newest.time}|${newest.msg}`;
                const expectedCam = getPrimaryCameraLabel();
                if (signature !== appState.lastLogSignature && String(newest.camera || newest.cam || "") === expectedCam) {
                    appState.lastLogSignature = signature;
                    setNotifCount(appState.notifCount + 1);
                    flashNotificationUi();
                    playAlertSound(newest.type);
                }
            }

            if (appState.activePage === "stats") {
                renderStatsTable(logs.slice(0, 20).map((row) => ({
                    timestamp: row.time,
                    camera: row.cam,
                    type: row.type === "violation" ? "PPE" : row.type,
                    detail: row.msg,
                    track_id: row.person_id,
                })));
            }
        } catch (error) {
            console.error("[logs] refresh failed", error);
        }
    }

    async function loadDashboard() {
        try {
            const data = await fetchJson("/api/violations/dashboard");
            if (dashTotal) dashTotal.textContent = String(data.total || 0);
            if (dashPpe) dashPpe.textContent = String((data.by_type && data.by_type.PPE) || 0);
        } catch (error) {
            console.error("[stats] dashboard failed", error);
        }
    }

    async function loadSettings() {
        try {
            const data = await fetchJson("/api/settings");
            appState.primaryCameraId = String(data.primary_camera_id || "1");
            updatePrimaryCameraUi();
            renderGrid();
        } catch (error) {
            console.error("[settings] load failed", error);
        }
    }

    async function loadRuntimeInfo() {
        try {
            const data = await fetchJson("/api/model_info");
            updateRuntimeUi(data.runtime);
        } catch (error) {
            console.error("[runtime] load failed", error);
        }
    }

    async function loadLogHistory() {
        try {
            const rows = await fetchJson("/api/logs/history?limit=100");
            renderStatsTable(rows);
        } catch (error) {
            console.error("[stats] history failed", error);
            renderStatsTable([]);
        }
    }

    async function loadCameraList() {
        if (!systemCamList) return;
        systemCamList.innerHTML = '<p style="padding:20px; color:var(--text-muted)">Đang tải camera...</p>';
        try {
            const cameras = await fetchJson("/api/cameras");
            appState.cameras = Array.isArray(cameras) ? cameras : [];
            systemCamList.innerHTML = appState.cameras.map((camera) => `
                <div class="cam-list-item glass">
                    <div class="ai-indicator ${(camera.status === "online" || camera.status === "streaming") ? "active" : ""}"></div>
                    <div class="cam-info">
                        <strong>${camera.name}${camera.is_primary_ai ? " • AI PRIMARY" : ""}</strong>
                        <small>${String(camera.status || "unknown").toUpperCase()} | ${camera.device_name || "Unknown Device"}</small>
                    </div>
                </div>
            `).join("");
            if (window.lucide) window.lucide.createIcons();
        } catch (error) {
            systemCamList.innerHTML = '<p style="padding:20px; color:var(--danger)">Không tải được danh sách camera.</p>';
            console.error("[cameras] load failed", error);
        }
    }

    function navigateTo(target) {
        appState.activePage = target;
        navItems.forEach((item) => item.classList.toggle("active", item.dataset.target === target));
        sections.forEach((section) => section.classList.toggle("active", section.id === `section-${target}`));

        if (target === "system") {
            void loadCameraList();
        } else if (target === "stats") {
            void loadDashboard();
            void loadLogHistory();
        }
    }

    function updateConnectButton() {
        if (!connectButton) return;
        if (appState.aiStreamingActive) {
            connectButton.innerHTML = '<i data-lucide="stop-circle"></i><span>Dừng Live Camera</span>';
            connectButton.classList.add("btn-success");
        } else {
            connectButton.innerHTML = '<i data-lucide="camera"></i><span>Phát Live Camera</span>';
            connectButton.classList.remove("btn-success");
        }
        if (window.lucide) window.lucide.createIcons();
    }

    function resetLiveCanvas() {
        if (!aiCanvasCtx || !aiCanvas) return;
        aiCanvasCtx.clearRect(0, 0, aiCanvas.width, aiCanvas.height);
    }

    function relocateLiveNodes() {
        const isMobileHeroLivePhone = appState.aiStreamingActive && shouldUseMobileHeroCamera() && Number(appState.mySlot || 1) === 1;

        if (isMobileHeroLivePhone && mobileHeroRemote && mobileHeroLocal) {
            mobileHeroRemote.style.display = "block";
            mobileHeroRemoteLabel.style.display = "inline-flex";
            mobileHeroLocalLabel.style.display = "inline-flex";
            mobileHeroRemote.setAttribute("data-loaded", "loading");
            mobileHeroRemote.src = `${getCamStreamUrl(1)}&t=${Date.now()}`;
            mobileHeroRemote.onload = () => {
                mobileHeroRemote.setAttribute("data-loaded", "yes");
                updateMobileHeroDebug("remote=onload");
            };
            mobileHeroRemote.onerror = () => {
                mobileHeroRemote.setAttribute("data-loaded", "error");
                updateMobileHeroDebug("remote=error");
            };
            mobileHeroLocal.style.display = "block";
            if (localVideo?.srcObject && mobileHeroLocal.srcObject !== localVideo.srcObject) {
                mobileHeroLocal.srcObject = localVideo.srcObject;
                mobileHeroLocal.play().catch(() => {});
            }
            if (mobileCamDebug) mobileCamDebug.textContent = "Hero source: REMOTE live feed | Inset: LOCAL preview";
            updateMobileHeroDebug("hero-live");
            return;
        }

        if (mobileHeroRemote) {
            mobileHeroRemote.style.display = "none";
            mobileHeroRemote.removeAttribute("src");
            mobileHeroRemote.removeAttribute("data-loaded");
        }
        if (mobileHeroLocal) {
            mobileHeroLocal.style.display = "none";
            mobileHeroLocal.srcObject = null;
        }
        if (mobileHeroRemoteLabel) mobileHeroRemoteLabel.style.display = "none";
        if (mobileHeroLocalLabel) mobileHeroLocalLabel.style.display = "none";
        updateMobileHeroDebug("hero-off");

        const targetSlot = appState.aiStreamingActive ? (appState.mySlot || 1) : 1;
        const targetContainer = document.querySelector(`#card-cam-${targetSlot} .stream-container`);
        const defaultContainer = document.querySelector("#card-cam-1 .stream-container");
        const container = targetContainer || defaultContainer;
        if (!container || !localVideo || !aiCanvas) return;

        const remoteImg = container.querySelector("img");
        container.appendChild(localVideo);
        container.appendChild(aiCanvas);
        if (remoteImg) {
            remoteImg.style.display = appState.aiStreamingActive ? "none" : "block";
            remoteImg.classList.remove("hero-live-feed");
        }
        localVideo.classList.remove("local-preview");
        localVideo.classList.remove("hero-local-feed");
        if (mobileCamDebug) mobileCamDebug.textContent = "Hero source: GRID/default";

        document.querySelectorAll("#loop-cameras-container .camera-card").forEach((card) => {
            const slotId = Number(card.getAttribute("data-slot-id") || "0");
            card.classList.toggle("active-ai-streaming", appState.aiStreamingActive && slotId === Number(appState.mySlot || 1));
            const img = card.querySelector("img");
            if (img) {
                img.style.display = appState.aiStreamingActive && slotId === Number(appState.mySlot || 1) ? "none" : "block";
            }
        });
    }

    function stopLiveStreaming(reason = "stopped") {
        appState.aiStreamingActive = false;
        appState.liveAwaitingResult = false;

        if (appState.liveSendTimer) {
            window.clearTimeout(appState.liveSendTimer);
            appState.liveSendTimer = null;
        }

        if (appState.liveWs) {
            try {
                appState.liveWs.onclose = null;
                appState.liveWs.close();
            } catch (error) {
                console.error("[live] ws close failed", error);
            }
            appState.liveWs = null;
        }

        if (appState.liveStream) {
            appState.liveStream.getTracks().forEach((track) => track.stop());
            appState.liveStream = null;
        }

        if (localVideo) {
            localVideo.pause();
            localVideo.srcObject = null;
            localVideo.style.display = "none";
            localVideo.classList.remove("local-preview");
            localVideo.classList.remove("hero-local-feed");
        }
        if (mobileHeroRemote) {
            mobileHeroRemote.style.display = "none";
            mobileHeroRemote.removeAttribute("src");
            mobileHeroRemote.removeAttribute("data-loaded");
        }
        if (mobileHeroLocal) {
            mobileHeroLocal.pause();
            mobileHeroLocal.srcObject = null;
            mobileHeroLocal.style.display = "none";
        }
        if (mobileHeroRemoteLabel) mobileHeroRemoteLabel.style.display = "none";
        if (mobileHeroLocalLabel) mobileHeroLocalLabel.style.display = "none";

        if (aiCanvas) aiCanvas.style.display = "none";
        appState.mySlot = null;
        resetLiveCanvas();
        relocateLiveNodes();
        renderGrid();
        updateMobileHeroDebug("stopped");
        updateConnectButton();
        activeCamLabel.textContent = "CAM 01";
        if (mobileCamLegendText) {
            mobileCamLegendText.textContent = "Đây là khung camera chính cho PHONE và AI realtime.";
        }
        updateHeaderStatus(reason === "error" ? "LIVE ERROR" : "SYSTEM ACTIVE");
    }

    function scheduleLiveFrameSend() {
        if (!appState.aiStreamingActive || !appState.liveWs || appState.liveWs.readyState !== WebSocket.OPEN || !localVideo) {
            return;
        }

        if (!appState.liveAwaitingResult && localVideo.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && localVideo.videoWidth > 0) {
            const targetWidth = 640;
            const scale = targetWidth / localVideo.videoWidth;
            const targetHeight = Math.max(1, Math.round(localVideo.videoHeight * scale));
            captureCanvas.width = targetWidth;
            captureCanvas.height = targetHeight;
            captureCanvasCtx.drawImage(localVideo, 0, 0, captureCanvas.width, captureCanvas.height);
            captureCanvas.toBlob((blob) => {
                if (blob && appState.liveWs && appState.liveWs.readyState === WebSocket.OPEN) {
                    appState.liveAwaitingResult = true;
                    appState.liveWs.send(blob);
                }
            }, "image/jpeg", 0.34);
        }

        appState.liveSendTimer = window.setTimeout(scheduleLiveFrameSend, 30);
    }

    async function startLiveStreaming() {
        if (appState.aiStreamingActive) {
            stopLiveStreaming();
            return;
        }
        if (appState.senderRunning) {
            showToast("PHONE sender CAM 01 đang chạy. Hãy dừng sender trước khi bật live.", "error");
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "environment" },
                audio: false,
            });

            appState.liveStream = stream;
            localVideo.srcObject = stream;
            localVideo.style.display = "block";
            aiCanvas.style.display = "block";
            await localVideo.play();
            syncCanvasSize();

            const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
            const isPhoneViewport = /iPhone|Android/i.test(navigator.userAgent) || window.innerWidth <= GRID_MOBILE_BREAKPOINT;
            const deviceName = encodeURIComponent(`${isPhoneViewport ? "Phone-CAM01" : "Desktop"}-${BUILD_VERSION}`);
            const ws = new WebSocket(`${protocol}//${window.location.host}/ws/ai?device=${deviceName}&fixed_slot=1`);

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                appState.liveAwaitingResult = false;
                if (data.type === "assignment") {
                    appState.mySlot = Number(data.slot_id || 1);
                    activeCamLabel.textContent = "CAM 01";
                    if (isPhoneViewport) setViewMode("focus");
                    if (mobileCamLegendText) {
                        mobileCamLegendText.textContent = "Đang xem trực tiếp khung PHONE/AI realtime của CAM 01.";
                    }
                    relocateLiveNodes();
                    renderGrid();
                }
                if (data.status === "error") {
                    showToast(data.message || "Không thể chiếm CAM 01 cho phone.", "error");
                    stopLiveStreaming("error");
                    return;
                }
                if (data.status === "ok") {
                    drawAIDetections(Array.isArray(data.detections) ? data.detections : []);
                }
            };

            ws.onopen = () => {
                appState.aiStreamingActive = true;
                appState.liveWs = ws;
                syncMobileHeroShell();
                relocateLiveNodes();
                updateConnectButton();
                updateHeaderStatus("LIVE STREAMING");
                scheduleLiveFrameSend();
            };

            ws.onerror = () => {
                appState.liveAwaitingResult = false;
                showToast("Kết nối AI realtime bị lỗi.", "error");
                stopLiveStreaming("error");
            };

            ws.onclose = () => {
                appState.liveAwaitingResult = false;
                if (appState.aiStreamingActive) {
                    stopLiveStreaming("error");
                }
            };
        } catch (error) {
            console.error("[live] start failed", error);
            showToast(`Không thể bật live camera: ${error.message}`, "error");
            stopLiveStreaming("error");
        }
    }

    function ensureSenderVideoMounted() {
        if (!localVideo || !aiCanvas) return;
        if (appState.overlayVisible && mobilePreviewContainer) {
            mobilePreviewContainer.appendChild(localVideo);
            mobilePreviewContainer.appendChild(aiCanvas);
        } else {
            relocateLiveNodes();
        }
    }

    function updateSenderButtons() {
        const isRunning = appState.senderRunning;
        if (senderStartButton) senderStartButton.disabled = isRunning;
        if (senderStopButton) senderStopButton.disabled = !isRunning;
        if (senderToggleLargeButton) {
            senderToggleLargeButton.innerHTML = isRunning
                ? '<i data-lucide="video-off"></i> DỪNG GỬI'
                : '<i data-lucide="video"></i> BẮT ĐẦU GỬI';
        }
        if (window.lucide) window.lucide.createIcons();
    }

    function getSenderDeviceName() {
        const value = (senderDeviceNameInput?.value || appState.senderDeviceName || "").trim();
        return value || "iPhone Cong Truong";
    }

    async function senderLogin() {
        const deviceName = getSenderDeviceName();
        appState.senderDeviceName = deviceName;
        localStorage.setItem("utt_sender_device_name", deviceName);
        if (senderDeviceNameInput) senderDeviceNameInput.value = deviceName;

        const data = await fetchJson("/api/device_login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                device_name: deviceName,
                platform: /iPhone|Android/i.test(navigator.userAgent) ? "mobile_web" : "desktop_web",
            }),
        });

        appState.senderSessionId = data.session_id || "";
        localStorage.setItem("utt_sender_session", appState.senderSessionId);
        setSenderStatus(`đã đăng nhập: ${deviceName}`, "idle");
        return data;
    }

    async function stopSender() {
        appState.senderRunning = false;
        appState.senderInFlight = false;
        appState.senderLatestImage = "";
        if (appState.senderTimer) {
            window.clearTimeout(appState.senderTimer);
            appState.senderTimer = null;
        }
        if (appState.senderStream) {
            appState.senderStream.getTracks().forEach((track) => track.stop());
            appState.senderStream = null;
        }
        if (!appState.aiStreamingActive) {
            if (localVideo) {
                localVideo.pause();
                localVideo.srcObject = null;
                localVideo.style.display = "none";
            }
            if (aiCanvas) aiCanvas.style.display = "none";
            ensureSenderVideoMounted();
        }
        setSenderStatus("đã dừng gửi", "idle");
        updateSenderButtons();
    }

    async function flushSenderFrame() {
        if (!appState.senderRunning || appState.senderInFlight || !appState.senderLatestImage) return;
        appState.senderInFlight = true;
        const image = appState.senderLatestImage;
        appState.senderLatestImage = "";

        try {
            const data = await fetchJson("/api/iphone_ingest", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    image,
                    session_id: appState.senderSessionId,
                    device_name: getSenderDeviceName(),
                    captured_at: Date.now() / 1000,
                }),
            });
            if (data.primary_camera_id) {
                appState.primaryCameraId = String(data.primary_camera_id);
                updatePrimaryCameraUi();
            }
            setSenderStatus(`đang gửi stream PHONE vào CAM 01 từ ${getSenderDeviceName()}`, "running");
        } catch (error) {
            console.error("[sender] ingest failed", error);
            setSenderStatus(`lỗi gửi dữ liệu: ${error.message}`, "error");
        } finally {
            appState.senderInFlight = false;
            if (appState.senderRunning && appState.senderLatestImage) {
                void flushSenderFrame();
            }
        }
    }

    async function senderLoop() {
        if (!appState.senderRunning || !localVideo || !senderCanvasCtx) return;

        if (localVideo.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && localVideo.videoWidth > 0) {
            senderCanvas.width = 640;
            senderCanvas.height = 480;
            senderCanvasCtx.drawImage(localVideo, 0, 0, 640, 480);
            appState.senderLatestImage = senderCanvas.toDataURL("image/jpeg", 0.38);
            void flushSenderFrame();
        }

        if (appState.senderRunning) {
            appState.senderTimer = window.setTimeout(senderLoop, SENDER_FRAME_INTERVAL_MS);
        }
    }

    async function startSender() {
        if (appState.senderRunning) return;
        if (appState.aiStreamingActive) {
            showToast("Live Camera CAM 01 đang chạy. Hãy dừng live trước khi bật PHONE sender.", "error");
            return;
        }
        try {
            if (!appState.senderSessionId) {
                await senderLogin();
            }
            const stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: appState.senderFacingMode,
                    width: { ideal: 1280 },
                    height: { ideal: 720 },
                },
                audio: false,
            });

            appState.senderStream = stream;
            appState.senderRunning = true;
            appState.senderInFlight = false;
            appState.senderLatestImage = "";
            localVideo.srcObject = stream;
            localVideo.style.display = "block";
            aiCanvas.style.display = "none";
            await localVideo.play();
            ensureSenderVideoMounted();
            setSenderStatus(`đang gửi stream PHONE vào CAM 01 từ ${getSenderDeviceName()}`, "running");
            updateSenderButtons();
            void senderLoop();
        } catch (error) {
            console.error("[sender] start failed", error);
            setSenderStatus(`không thể bật camera: ${error.message}`, "error");
            updateSenderButtons();
        }
    }

    async function flipSenderCamera() {
        appState.senderFacingMode = appState.senderFacingMode === "environment" ? "user" : "environment";
        if (!appState.senderRunning) return;
        await stopSender();
        await startSender();
    }

    function setOverlayVisible(visible) {
        appState.overlayVisible = visible;
        if (!mobileSenderOverlay) return;
        mobileSenderOverlay.style.display = visible ? "flex" : "none";
        ensureSenderVideoMounted();
    }

    function initEvents() {
        navItems.forEach((item) => {
            item.addEventListener("click", (event) => {
                event.preventDefault();
                const target = item.dataset.target;
                if (target) navigateTo(target);
            });
        });

        if (themeToggle) {
            themeToggle.addEventListener("change", () => applyTheme(themeToggle.checked ? "dark" : "light"));
        }

        if (openStatsButton) {
            openStatsButton.addEventListener("click", () => navigateTo("stats"));
        }

        if (viewFocusButton) {
            viewFocusButton.addEventListener("click", () => setViewMode("focus"));
        }

        if (viewWallButton) {
            viewWallButton.addEventListener("click", () => setViewMode("wall"));
        }

        if (connectButton) {
            connectButton.addEventListener("click", () => {
                void startLiveStreaming();
            });
        }

        if (uploadLoopButton) {
            uploadLoopButton.addEventListener("click", () => uploadInput?.click());
        }

        if (uploadVideoButton) {
            uploadVideoButton.addEventListener("click", () => uploadInput?.click());
        }

        if (uploadInput) {
            uploadInput.addEventListener("change", async () => {
                const file = uploadInput.files?.[0];
                if (!file) return;
                const formData = new FormData();
                formData.append("file", file);
                try {
                    const data = await fetchJson("/api/upload_loop", {
                        method: "POST",
                        body: formData,
                    });
                    showToast(`Đã tải video: ${data.filename || file.name}`, "success");
                    renderGrid();
                    void loadCameraList();
                } catch (error) {
                    console.error("[upload] failed", error);
                    showToast(`Tải video thất bại: ${error.message}`, "error");
                } finally {
                    uploadInput.value = "";
                }
            });
        }

        ["helmet", "vest", "sign"].forEach((filterName) => {
            const checkbox = document.getElementById(`filter-${filterName}`);
            if (checkbox) {
                checkbox.addEventListener("change", () => renderGrid());
            }
        });

        if (senderLoginButton) {
            senderLoginButton.addEventListener("click", () => {
                void senderLogin().catch((error) => {
                    console.error("[sender] login failed", error);
                    setSenderStatus(`đăng nhập thất bại: ${error.message}`, "error");
                });
            });
        }

        if (senderStartButton) {
            senderStartButton.addEventListener("click", () => {
                void startSender();
            });
        }

        if (senderStopButton) {
            senderStopButton.addEventListener("click", () => {
                void stopSender();
            });
        }

        if (senderToggleLargeButton) {
            senderToggleLargeButton.addEventListener("click", () => {
                if (appState.senderRunning) {
                    void stopSender();
                } else {
                    void startSender();
                }
            });
        }

        if (senderFlipButton) {
            senderFlipButton.addEventListener("click", () => {
                void flipSenderCamera();
            });
        }

        if (bottomNavBotButton) {
            bottomNavBotButton.addEventListener("click", () => {
                setOverlayVisible(true);
            });
        }

        if (mobileSenderOverlay) {
            const closeButton = mobileSenderOverlay.querySelector(".btn-circle");
            if (closeButton) {
                closeButton.addEventListener("click", () => setOverlayVisible(false));
            }
        }

        document.addEventListener("click", () => {
            if (!appState.audioUnlocked) {
                appState.audioUnlocked = true;
                showToast("Âm thanh cảnh báo đã sẵn sàng.", "success");
            }
        }, { once: true });

        window.addEventListener("resize", () => {
            renderGrid();
            syncCanvasSize();
        });

        window.addEventListener("beforeunload", () => {
            stopLiveStreaming();
            void stopSender();
        });
    }

    function registerServiceWorker() {
        return;
    }

    async function boot() {
        applyTheme(localStorage.getItem("utt_theme") || "light");
        if (window.innerWidth <= GRID_MOBILE_BREAKPOINT) {
            appState.viewMode = "focus";
        }
        if (senderDeviceNameInput) {
            senderDeviceNameInput.value = appState.senderDeviceName;
        }
        setNotifCount(0);
        setSenderStatus(appState.senderSessionId ? "đã có phiên đăng nhập" : "chưa đăng nhập", "idle");
        updatePrimaryCameraUi();
        updateSenderButtons();
        updateConnectButton();
        await loadSettings();
        navigateTo("home");
        void refreshLogs();
        appState.logTimer = window.setInterval(() => {
            void refreshLogs();
        }, LOG_POLL_INTERVAL_MS);
        void loadDashboard();
        void loadRuntimeInfo();
        appState.runtimeTimer = window.setInterval(() => {
            void loadRuntimeInfo();
        }, 15000);
        registerServiceWorker();
        updateHeaderStatus("SYSTEM ACTIVE");
        if (window.lucide) window.lucide.createIcons();
        console.log(`[UTT] frontend booted v${BUILD_VERSION}`);
    }

    initEvents();
    void boot();
});
