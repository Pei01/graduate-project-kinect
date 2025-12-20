from flask import Flask 
from flask_socketio import SocketIO
import pykinect_azure as pykinect
import threading
import time
import numpy as np
import traceback # 新增: 用於顯示詳細錯誤
import math


app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- KINECT 追蹤常數 ---
# 握拳狀態常數
K4ABT_HAND_STATE_CLOSED = 2  
K4ABT_HAND_STATE_OPEN = 1    

# 初始化 SDK
pykinect.initialize_libraries(track_body=True)

# 攝影機設定
device_config = pykinect.default_configuration
device_config.color_resolution = pykinect.K4A_COLOR_RESOLUTION_1080P
device_config.color_format = pykinect.K4A_IMAGE_FORMAT_COLOR_BGRA32
device_config.depth_mode = pykinect.K4A_DEPTH_MODE_NFOV_UNBINNED


# 啟動裝置
device = pykinect.start_device(config=device_config)

# 啟動 body tracker
bodyTracker = pykinect.start_body_tracker()

# 全域狀態變數
isHandUp = False
latest_skeleton_3d = None 
latest_body_data = None

@app.route("/")
def index():
    return "Kinect Server Running"

def get_closest_body(body_frame):
    num_bodies = body_frame.get_num_bodies()
    if num_bodies == 0:
        return None
    
    min_z = float('inf')
    closest_id = None

    for body_id in range(num_bodies):
        body = body_frame.get_body(body_id)
        # body.numpy() 回傳的是關節數據，我們只需要 Spine Navel 的 Z 值
        skeleton_3d = body.numpy()
        spine_base_z = skeleton_3d[pykinect.K4ABT_JOINT_SPINE_NAVEL, 2]
        if spine_base_z < min_z:
            min_z = spine_base_z
            closest_id = body_id

    return closest_id

def kinect_data_acquisition_worker():
    """
    【1. 資料獲取 Worker】
    負責從硬體讀取數據，更新全域變數 latest_skeleton_3d 和 latest_hand_state
    """
    global latest_skeleton_3d, latest_body_data 
    
    while True:
        try:
            capture = device.update()
            body_frame = bodyTracker.update(capture)
            
            body_id = get_closest_body(body_frame) 

            if body_id is not None:
                body = body_frame.get_body(body_id)
                
                # 更新骨架數據 (numpy array)
                latest_skeleton_3d = body.numpy()
                
                # 更新 Body Info
                latest_body_data = {
                    "id": body_id,
                }

        except Exception as e:
            traceback.print_exc()  # 顯示詳細錯誤訊息
            pass

        time.sleep(0.01)

def detect_hand_up():
    """
    【2. 舉手偵測 Worker】
    """
    global isHandUp

    while True:
        skeleton_3d = latest_skeleton_3d

        if skeleton_3d is None:
            time.sleep(0.01)
            continue

        try:
            head_y = skeleton_3d[pykinect.K4ABT_JOINT_HEAD, 1]
            left_hand_y = skeleton_3d[pykinect.K4ABT_JOINT_HAND_LEFT, 1]
            right_hand_y = skeleton_3d[pykinect.K4ABT_JOINT_HAND_RIGHT, 1]

            # 注意：Azure Kinect Y 軸往下為正，數值越小越高
            left_hand_up = left_hand_y < head_y
            right_hand_up = right_hand_y < head_y
            hand_up = left_hand_up or right_hand_up

            if not hand_up and isHandUp:
                isHandUp = False

            if hand_up and not isHandUp:
                isHandUp = True
                socketio.emit("hand_event")

        except Exception as e:
            pass
            
        time.sleep(0.01)

def kinect_mapping_worker():
    """
    【3. 映射與控制 Worker】
    取得右手 3D 座標 -> 映射到 2D 螢幕範圍 -> 傳給前端
    """
    global latest_skeleton_3d 

    # 前端畫面尺寸（你可以修改）
    SCREEN_WIDTH = 396
    SCREEN_HEIGHT = 859

    # Kinect 空間 normalized 區間（你可以視實測修改）
    KINECT_X_MIN = -0.5
    KINECT_X_MAX = 0.5
    KINECT_Y_MIN = -0.3
    KINECT_Y_MAX = 0.3

    # smoothing 參數
    SMOOTH_FACTOR = 0.25
    smooth_x = 0
    smooth_y = 0

    while True:
        try:
            if latest_skeleton_3d is None:
                time.sleep(0.01)
                continue

            # 取得右手 3D 資料
            hand = latest_skeleton_3d[pykinect.K4ABT_JOINT_HAND_RIGHT]

            hand_x = hand[0] / 1000  # X 座標
            hand_y = hand[1] / 1000  # Y 座標
            hand_z = hand[2] / 1000  # Z 座標 (深度)

            # --- Normalize to 0~1 ---
            nx = (hand_x - KINECT_X_MIN) / (KINECT_X_MAX - KINECT_X_MIN)
            ny = (hand_y - KINECT_Y_MIN) / (KINECT_Y_MAX - KINECT_Y_MIN)

            nx = 1 - nx  # X 軸反轉

            # 限制在 0~1
            nx = max(0, min(1, nx))
            ny = max(0, min(1, ny))

            # --- Mapping to screen pixel ---
            screen_x = nx * SCREEN_WIDTH
            screen_y = ny * SCREEN_HEIGHT

            # --- smoothing ---
            smooth_x = smooth_x + (screen_x - smooth_x) * SMOOTH_FACTOR
            smooth_y = smooth_y + (screen_y - smooth_y) * SMOOTH_FACTOR

            # --- emit event to frontend ---
            socketio.emit("cursor_move", {
                "x": smooth_x,
                "y": smooth_y,
            })

        except Exception as e:
            print("[Mapping Error]", e)

        time.sleep(0.01)



if __name__ == "__main__":
    # 【1. 資料獲取 Worker】
    acquisition_thread = threading.Thread(target=kinect_data_acquisition_worker)
    acquisition_thread.daemon = True 
    acquisition_thread.start()
    
    # 【2. 舉手偵測 Worker】
    hand_up_thread = threading.Thread(target=detect_hand_up)
    hand_up_thread.daemon = True 
    hand_up_thread.start()

    # 【3. 映射與控制 Worker (新增)】
    mapping_thread = threading.Thread(target=kinect_mapping_worker)
    mapping_thread.daemon = True 
    mapping_thread.start()
    
    print("🚀 Server Started. Listening on port 5000...")
    
    # 啟動 Flask 應用
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)