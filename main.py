from flask import Flask 
from flask_socketio import SocketIO
import pykinect_azure as pykinect
import threading
import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- KINECT 追蹤常數 ---
# 握拳狀態常數
K4ABT_HAND_STATE_CLOSED = 2  
K4ABT_HAND_STATE_OPEN = 1    

# 螢幕或目標畫面的尺寸
SCREEN_WIDTH = 573
SCREEN_HEIGHT = 859

# Kinect 追蹤空間的有效範圍（mm，用於座標轉換）
KINECT_X_MIN = -500  
KINECT_X_MAX = 500   
KINECT_Y_MIN = -200  
KINECT_Y_MAX = 200 

# 初始化 SDK
pykinect.initialize_libraries(track_body=True)

# 攝影機設定
device_config = pykinect.default_configuration
device_config.color_resolution = pykinect.K4A_COLOR_RESOLUTION_1080P
device_config.color_format = pykinect.K4A_IMAGE_FORMAT_COLOR_BGRA32
device_config.depth_mode = pykinect.K4A_DEPTH_MODE_WFOV_2X2BINNED

# 啟動裝置
device = pykinect.start_device(config=device_config)

# 啟動 body tracker
bodyTracker = pykinect.start_body_tracker()

isHandUp = False
is_hand_closed = False

latest_skeleton_3d = None 
latest_body_data = None

@app.route("/")
def index():
    return "Kinect Server Running"


def kinect_data_acquisition_worker():
    global latest_skeleton_3d, latest_body_data
    
    while True:
        print(latest_skeleton_3d)
        try:
            capture = device.update()
            body_frame = bodyTracker.update(capture)
            
            body_id = get_closest_body(body_frame) 

            if body_id is not None:
                body = body_frame.get_body(body_id)
                skeleton_3d = body.numpy()

                latest_skeleton_3d = skeleton_3d
                latest_body_data = {
                    "id": body_id,
                }

        except Exception as e:
            pass

        time.sleep(0.01)

def get_closest_body(body_frame):
    num_bodies = body_frame.get_num_bodies()
    if num_bodies == 0:
        return None
    
    min_z = float('inf')
    closest_id = None

    for body_id in range(num_bodies):
        skeleton_3d = body_frame.get_body(body_id).numpy()
        spine_base_z = skeleton_3d[pykinect.K4ABT_JOINT_SPINE_NAVEL, 2]
        if spine_base_z < min_z:
            min_z = spine_base_z
            closest_id = body_id

    return closest_id

def map_to_screen(kinect_x, kinect_y):
    # 步驟 1: 計算正規化到 [-1, 1] 的 X 軸
    x_range = KINECT_X_MAX - KINECT_X_MIN
    x_mid = (KINECT_X_MAX + KINECT_X_MIN) / 2
    x_clamped = max(KINECT_X_MIN, min(KINECT_X_MAX, kinect_x))
    x_centered = x_clamped - x_mid
    x_normalized_centered = x_centered / (x_range / 2) # 範圍 [-1, 1]
    
    
    # 步驟 2: 計算正規化到 [-1, 1] 的 Y 軸
    y_range = KINECT_Y_MAX - KINECT_Y_MIN
    y_mid = (KINECT_Y_MAX + KINECT_Y_MIN) / 2
    y_clamped = max(KINECT_Y_MIN, min(KINECT_Y_MAX, kinect_y))
    y_centered = y_clamped - y_mid
    y_normalized_centered = y_centered / (y_range / 2) # 範圍 [-1, 1]
    
    
    # 步驟 3: 將 [-1, 1] 映射到像素偏移量
    
    # X 軸偏移量：[-1, 1] 映射到 [-SCREEN_WIDTH/2, SCREEN_WIDTH/2]
    # 我們需要反轉 X 軸：Kinect X 正值 (相機右側) 應對應螢幕 X 負偏移量 (左側)
    screen_offset_x = int(-x_normalized_centered * (SCREEN_WIDTH / 2))
    
    # Y 軸偏移量：[-1, 1] 映射到 [-SCREEN_HEIGHT/2, SCREEN_HEIGHT/2]
    screen_offset_y = int(y_normalized_centered * (SCREEN_HEIGHT / 2))
    
    
    # 輸出：現在輸出的是【距離中心的偏移量】
    return screen_offset_x, screen_offset_y


def kinect_mapping_worker():
    is_closed_previous = False 

    while True:
        skeleton_3d = latest_skeleton_3d
        # body_data = latest_body_data

        # if skeleton_3d is None or body_data is None:
        #     continue
        if skeleton_3d is None:
            continue

        try:
            # hand_state_value = body_data["hand_state_right"]
            # is_closed_current = (hand_state_value == pykinect.K4ABT_HAND_STATE_CLOSED)

            # --- 1. 位置 Mapping ---
            # 獲取右手 3D 座標 (我們仍然使用右手)
            right_hand_3d = skeleton_3d[pykinect.K4ABT_JOINT_HAND_RIGHT]
            right_hand_x = right_hand_3d[0]
            right_hand_y = right_hand_3d[1]
            
            # 座標轉換：將 3D 座標轉換為 2D 螢幕像素座標 (0~SCREEN_WIDTH/HEIGHT)
            screen_x, screen_y = map_to_screen(right_hand_x, right_hand_y)

            socketio.emit("cursor_move", {
                "x": screen_x,
                "y": screen_y,
                # "is_closed": is_closed_current # 傳送當前狀態
            })

            # # --- 4. 傳送點擊事件（狀態邊緣觸發）---
            
            # # 從未握拳到握拳 (Click Down Event)
            # if is_closed_current and not is_closed_previous:
            #     print(f"Mapping: Hand CLOSED (Click Trigger)")
            #     socketio.emit("click_event", {"action": "down", "x": screen_x, "y": screen_y})
                
            # # 從握拳到未握拳 (Click Up Event)
            # elif not is_closed_current and is_closed_previous:
            #     print("Mapping: Hand OPENED (Release Trigger)")
            #     socketio.emit("click_event", {"action": "up", "x": screen_x, "y": screen_y})
                
            # # 更新狀態
            # is_closed_previous = is_closed_current
                
        except Exception as e:
            pass

        time.sleep(0.01)

def detect_hand_up():
    global isHandUp

    while True:
        skeleton_3d = latest_skeleton_3d

        if skeleton_3d is None:
            continue

        try:
            head_y = skeleton_3d[pykinect.K4ABT_JOINT_HEAD, 1]
            left_hand_y = skeleton_3d[pykinect.K4ABT_JOINT_HAND_LEFT, 1]
            right_hand_y = skeleton_3d[pykinect.K4ABT_JOINT_HAND_RIGHT, 1]

            # 注意：Y 軸往下，數值小 = 高
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

if __name__ == "__main__":
    # 【1. 資料獲取 Worker】：負責與硬體溝通，將最新資料寫入 latest_body_frame
    acquisition_thread = threading.Thread(target=kinect_data_acquisition_worker)
    acquisition_thread.daemon = True 
    acquisition_thread.start()
    
    # 【2. 處理 Worker】：讀取 latest_body_frame 進行舉手偵測
    hand_up_thread = threading.Thread(target=detect_hand_up)
    hand_up_thread.daemon = True 
    hand_up_thread.start()
    
    # 【3. 處理 Worker】：讀取 latest_body_frame 進行座標映射與握拳偵測
    mapping_thread = threading.Thread(target=kinect_mapping_worker)
    mapping_thread.daemon = True 
    mapping_thread.start()
    
    # 啟動 Flask 應用
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)