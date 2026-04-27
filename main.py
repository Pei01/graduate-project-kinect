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

isBothHandsUp = False
isSingleHandUp = False

# 多幀平滑設定
SMOOTH_WINDOW = 5     # 滑動窗口幀數
SMOOTH_THRESHOLD = 3  # 需幾幀確認才觸發

FRAME_INTERVAL = 1.0 / 30  # 幀率限制，對應設定的 30fps



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
    last_frame_time = 0.0

    while True:
        # 幀率限制：確保不超過 30fps，避免 body tracker enqueue 佇列滿溢
        now = time.time()
        elapsed = now - last_frame_time
        if elapsed < FRAME_INTERVAL:
            time.sleep(FRAME_INTERVAL - elapsed)
        last_frame_time = time.time()

        capture = None
        body_frame = None
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

        except Exception as e:
            err_msg = str(e).lower()
            if "enqueue" in err_msg or "timeout" in err_msg:
                # body tracker 佇列滿：略過此幀，等久一點讓 GPU 消化
                time.sleep(0.05)
            # 其他錯誤靜默略過
        finally:
            del capture
            del body_frame


def detect_hand_worker():
    """【2. 手勢偵測 Worker】偵測舉雙手 / 舉單手，event-driven"""
    global isBothHandsUp, isSingleHandUp
    both_hands_states = collections.deque(maxlen=SMOOTH_WINDOW)
    single_hand_states = collections.deque(maxlen=SMOOTH_WINDOW)

    while True:
        with skeleton_condition:
            skeleton_condition.wait(timeout=0.2)
            skeleton = latest_skeleton_3d.copy() if latest_skeleton_3d is not None else None

        if skeleton is None:
            both_hands_states.clear()
            single_hand_states.clear()
            continue

        try:
            # Y 軸越小越高
            head_y = skeleton[pykinect.K4ABT_JOINT_HEAD, 1]
            l_hand_y = skeleton[pykinect.K4ABT_JOINT_HAND_LEFT, 1]
            r_hand_y = skeleton[pykinect.K4ABT_JOINT_HAND_RIGHT, 1]

            l_up = l_hand_y < head_y
            r_up = r_hand_y < head_y

            # 雙手同時高於頭
            both_hands_raw = l_up and r_up
            # 僅一手高於頭（XOR）
            single_hand_raw = l_up != r_up

            both_hands_states.append(both_hands_raw)
            single_hand_states.append(single_hand_raw)

            confirmed_both = sum(both_hands_states) >= SMOOTH_THRESHOLD
            confirmed_single = sum(single_hand_states) >= SMOOTH_THRESHOLD

            # 舉雙手事件
            if confirmed_both and not isBothHandsUp:
                isBothHandsUp = True
                print("🙌 [Event] 偵測到舉雙手")
                socketio.emit("both_hands_event", {"state": "up"}, namespace='/')
            elif not confirmed_both and isBothHandsUp:
                isBothHandsUp = False
                print("🤚 [Event] 雙手放下")

            # 舉單手事件（雙手同時舉起時不觸發）
            if confirmed_single and not confirmed_both and not isSingleHandUp:
                isSingleHandUp = True
                side = "left" if l_up else "right"
                print(f"✋ [Event] 偵測到舉單手 ({side})")
                socketio.emit("single_hand_event", {"side": side}, namespace='/')
            elif (not confirmed_single or confirmed_both) and isSingleHandUp:
                isSingleHandUp = False
                print("🤚 [Event] 單手放下")

        except Exception:
            pass


if __name__ == "__main__":
    workers = [
        threading.Thread(target=kinect_data_acquisition_worker, daemon=True),
        threading.Thread(target=detect_hand_worker, daemon=True),
    ]

    for t in workers:
        t.start()

    print("🚀 Kinect 多功能伺服器已啟動...")
    print("- 執行緒 1: 資料獲取 (Condition 保護，notify_all 驅動偵測)")
    print("- 執行緒 2: 手勢偵測 (舉雙手 / 舉單手，5 幀滑動平滑)")

    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
