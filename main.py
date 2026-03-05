from flask import Flask
from flask_socketio import SocketIO
import pykinect_azure as pykinect
import threading
import collections
import time
import numpy as np
import math

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# --- 初始化 SDK ---
try:
    pykinect.initialize_libraries(track_body=True)
except Exception as e:
    print(f"❌ SDK 初始化失敗: {e}")

# 攝影機優化設定
device_config = pykinect.default_configuration
device_config.color_resolution = pykinect.K4A_COLOR_RESOLUTION_720P
device_config.depth_mode = pykinect.K4A_DEPTH_MODE_NFOV_2X2BINNED
device_config.camera_fps = pykinect.K4A_FRAMES_PER_SECOND_30

# 啟動裝置
try:
    device = pykinect.start_device(config=device_config)
    bodyTracker = pykinect.start_body_tracker(pykinect.K4ABT_TRACKER_PROCESSING_MODE_GPU)
except Exception as e:
    print(f"❌ 硬體啟動失敗: {e}")

# 骨架數據共享（Condition 保護，解決 race condition 與 GIL 競爭）
skeleton_condition = threading.Condition()
latest_skeleton_3d = None

isHandUp = False
isKicking = False

# 多幀平滑設定
SMOOTH_WINDOW = 5     # 滑動窗口幀數
SMOOTH_THRESHOLD = 3  # 需幾幀確認才觸發

# 踢腿門檻（mm）
KICK_REL_THRESHOLD = 400    # 觸發：腳踝與髖部垂直距離小於此值
KICK_RESET_THRESHOLD = 600  # 重置：兩腳都須大於此值（縮小滯後帶，原為 700mm）


def get_closest_body(body_frame):
    num_bodies = body_frame.get_num_bodies()
    if num_bodies == 0:
        return None
    min_z = float('inf')
    closest_id = None
    for body_id in range(num_bodies):
        body = body_frame.get_body(body_id)
        skeleton_3d = body.numpy()
        spine_z = skeleton_3d[pykinect.K4ABT_JOINT_SPINE_NAVEL, 2]
        if spine_z < min_z:
            min_z = spine_z
            closest_id = body_id
    return closest_id


def kinect_data_acquisition_worker():
    """【1. 資料獲取 Worker】負責抓取硬體數據，並通知偵測 workers"""
    global latest_skeleton_3d
    last_status = False
    while True:
        try:
            capture = device.update()
            body_frame = bodyTracker.update(capture)
            body_id = get_closest_body(body_frame)

            with skeleton_condition:
                if body_id is not None:
                    body = body_frame.get_body(body_id)
                    latest_skeleton_3d = body.numpy().copy()
                    if not last_status:
                        print("✅ [Acquisition] 偵測到人體目標")
                        last_status = True
                else:
                    latest_skeleton_3d = None
                    if last_status:
                        print("❓ [Acquisition] 失去人體目標")
                        last_status = False
                # 通知所有等待的偵測 workers 有新幀到來
                skeleton_condition.notify_all()

            del capture
            del body_frame
        except Exception:
            pass


def detect_hand_worker():
    """【2. 舉手偵測 Worker】event-driven，有新幀才處理"""
    global isHandUp
    hand_states = collections.deque(maxlen=SMOOTH_WINDOW)

    while True:
        with skeleton_condition:
            # 等待新幀（最多 200ms 避免永久阻塞）
            skeleton_condition.wait(timeout=0.2)
            skeleton = latest_skeleton_3d.copy() if latest_skeleton_3d is not None else None

        if skeleton is None:
            hand_states.clear()
            continue

        try:
            # Y 軸越小越高
            head_y = skeleton[pykinect.K4ABT_JOINT_HEAD, 1]
            l_hand_y = skeleton[pykinect.K4ABT_JOINT_HAND_LEFT, 1]
            r_hand_y = skeleton[pykinect.K4ABT_JOINT_HAND_RIGHT, 1]

            # 任一手高於頭部即算舉手（修正：原為 AND，要求雙手同時舉起，過於嚴格）
            hand_up_raw = (l_hand_y < head_y) or (r_hand_y < head_y)
            hand_states.append(hand_up_raw)

            # 多幀確認，避免骨架雜訊造成誤觸發
            confirmed_up = sum(hand_states) >= SMOOTH_THRESHOLD

            if confirmed_up and not isHandUp:
                isHandUp = True
                print("✋ [Event] 偵測到舉手")
                socketio.emit("hand_event", {"state": "up"}, namespace='/')
            elif not confirmed_up and isHandUp:
                isHandUp = False
                print("🤚 [Event] 手放下了")

        except Exception:
            pass


def detect_kick_worker():
    """【3. 踢腿偵測 Worker】event-driven，有新幀才處理"""
    global isKicking
    kick_states = collections.deque(maxlen=SMOOTH_WINDOW)
    last_log_time = time.time()

    while True:
        with skeleton_condition:
            skeleton_condition.wait(timeout=0.2)
            skeleton = latest_skeleton_3d.copy() if latest_skeleton_3d is not None else None

        if skeleton is None:
            kick_states.clear()
            continue

        try:
            # Y 軸向下為正；踢腿時腳踝上升，ankle_y 減小，dist 縮小
            hip_y = skeleton[pykinect.K4ABT_JOINT_HIP_LEFT, 1]
            l_ankle_y = skeleton[pykinect.K4ABT_JOINT_ANKLE_LEFT, 1]
            r_ankle_y = skeleton[pykinect.K4ABT_JOINT_ANKLE_RIGHT, 1]

            l_leg_dist = l_ankle_y - hip_y
            r_leg_dist = r_ankle_y - hip_y
            min_dist = min(l_leg_dist, r_leg_dist)

            # 定時輸出 Debug Log（門檻值與 log 一致）
            if time.time() - last_log_time > 2.0:
                print(f"DEBUG [Kick] 腿部相對距離: {min_dist:.0f}mm (觸發門檻 < {KICK_REL_THRESHOLD}mm)")
                last_log_time = time.time()

            kick_raw = (l_leg_dist < KICK_REL_THRESHOLD) or (r_leg_dist < KICK_REL_THRESHOLD)
            kick_states.append(kick_raw)

            # 多幀確認踢腿
            confirmed_kick = sum(kick_states) >= SMOOTH_THRESHOLD

            if confirmed_kick and not isKicking:
                isKicking = True
                leg = "left" if l_leg_dist < r_leg_dist else "right"
                print(f"🦵 [Event] 偵測到踢腿！({leg}) 相對高度差: {min_dist:.0f}mm")
                socketio.emit("kick_event", {"leg": leg}, namespace='/')
            elif not confirmed_kick and isKicking:
                if l_leg_dist > KICK_RESET_THRESHOLD and r_leg_dist > KICK_RESET_THRESHOLD:
                    isKicking = False
                    print("✅ [Event] 雙腳已著地/重置")

        except Exception:
            pass


if __name__ == "__main__":
    workers = [
        threading.Thread(target=kinect_data_acquisition_worker, daemon=True),
        threading.Thread(target=detect_hand_worker, daemon=True),
        threading.Thread(target=detect_kick_worker, daemon=True),
    ]

    for t in workers:
        t.start()

    print("🚀 Kinect 多功能伺服器已啟動...")
    print("- 執行緒 1: 資料獲取 (Condition 保護，notify_all 驅動偵測)")
    print("- 執行緒 2: 舉手偵測 (任一手 OR 邏輯 + 5 幀滑動平滑)")
    print("- 執行緒 3: 踢腿偵測 (5 幀滑動平滑 + 縮小滯後帶)")

    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
