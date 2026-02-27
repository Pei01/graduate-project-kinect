from flask import Flask 
from flask_socketio import SocketIO
import pykinect_azure as pykinect
import threading
import time
import numpy as np
import traceback 
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
device_config.depth_mode = pykinect.K4A_DEPTH_MODE_NFOV_UNBINNED
device_config.camera_fps = pykinect.K4A_FRAMES_PER_SECOND_15 

# 啟動裝置
try:
    device = pykinect.start_device(config=device_config)
    bodyTracker = pykinect.start_body_tracker(pykinect.K4ABT_TRACKER_PROCESSING_MODE_GPU)
except Exception as e:
    print(f"❌ 硬體啟動失敗: {e}")

# 全域狀態變數
latest_skeleton_3d = None 
isHandUp = False
isKicking = False 

def get_closest_body(body_frame):
    num_bodies = body_frame.get_num_bodies()
    if num_bodies == 0: return None
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
    """【1. 資料獲取 Worker】負責抓取硬體數據"""
    global latest_skeleton_3d 
    last_status = False
    while True:
        try:
            capture = device.update()
            body_frame = bodyTracker.update(capture)
            body_id = get_closest_body(body_frame) 

            if body_id is not None:
                body = body_frame.get_body(body_id)
                latest_skeleton_3d = body.numpy()
                if not last_status:
                    print("✅ [Acquisition] 偵測到人體目標")
                    last_status = True
            else:
                latest_skeleton_3d = None 
                if last_status:
                    print("❓ [Acquisition] 失去人體目標")
                    last_status = False
            
            del capture
            del body_frame
        except Exception:
            pass
        time.sleep(0.01)

def detect_hand_worker():
    """【2. 舉手偵測 Worker】單獨處理手部邏輯"""
    global isHandUp
    last_log_time = time.time()
    while True:
        skeleton = latest_skeleton_3d
        if skeleton is None:
            time.sleep(0.1)
            continue
        
        try:
            # Y 軸越小越高
            head_y = skeleton[pykinect.K4ABT_JOINT_HEAD, 1]
            l_hand_y = skeleton[pykinect.K4ABT_JOINT_HAND_LEFT, 1]
            r_hand_y = skeleton[pykinect.K4ABT_JOINT_HAND_RIGHT, 1]
            
            hand_up = (l_hand_y < head_y) and (r_hand_y < head_y)
            
            if hand_up and not isHandUp:
                isHandUp = True
                print(f"✋ [Event] 偵測到舉手")
                socketio.emit("hand_event", {"state": "up"}, namespace='/')
            elif not hand_up and isHandUp:
                isHandUp = False
                print("🤚 [Event] 手放下了")
                
        except Exception:
            pass
        time.sleep(0.05)

def detect_kick_worker():
    """【3. 踢腿偵測 Worker】單獨處理腿部邏輯"""
    global isKicking
    last_log_time = time.time()
    while True:
        skeleton = latest_skeleton_3d
        if skeleton is None:
            time.sleep(0.1)
            continue
            
        try:
            # 使用相對距離邏輯 (腳踝Y - 髖部Y)
            hip_y = skeleton[pykinect.K4ABT_JOINT_HIP_LEFT, 1] 
            l_ankle_y = skeleton[pykinect.K4ABT_JOINT_ANKLE_LEFT, 1]
            r_ankle_y = skeleton[pykinect.K4ABT_JOINT_ANKLE_RIGHT, 1]
            
            l_leg_dist = l_ankle_y - hip_y
            r_leg_dist = r_ankle_y - hip_y
            min_dist = min(l_leg_dist, r_leg_dist)
            
            # 定時輸出 Debug Log
            if time.time() - last_log_time > 2.0:
                print(f"DEBUG [Kick] 腿部相對距離: {min_dist:.0f}mm (目標 < 250mm)")
                last_log_time = time.time()

            # 踢腿門檻值 (mm)
            KICK_REL_THRESHOLD = 400
            kicking = (l_leg_dist < KICK_REL_THRESHOLD) or (r_leg_dist < KICK_REL_THRESHOLD)
            # 在 detect_hand_worker 內

            if kicking and not isKicking:
                isKicking = True
                leg = "left" if l_leg_dist < r_leg_dist else "right"
                print(f"🦵 [Event] 偵測到踢腿！ ({leg}) 相對高度差: {min_dist:.0f}mm")
                socketio.emit("kick_event", {"leg": leg}, namespace='/')
            elif not kicking and isKicking:
                # 緩衝區，回到 500mm 以外才重置
                if l_leg_dist > 700 and r_leg_dist > 700:
                    isKicking = False
                    print("✅ [Event] 雙腳已著地/重置")
                    
        except Exception:
            pass
        time.sleep(0.03)

if __name__ == "__main__":
    workers = [
        threading.Thread(target=kinect_data_acquisition_worker, daemon=True),
        threading.Thread(target=detect_hand_worker, daemon=True),
        threading.Thread(target=detect_kick_worker, daemon=True),
    ]
    
    for t in workers:
        t.start()
        
    print("🚀 Kinect 多功能伺服器已啟動...")
    print("- 執行緒 1: 資料獲取 (已加入人體鎖定 Log)")
    print("- 執行緒 2: 舉手偵測 (每 2s 輸出高度差)")
    print("- 執行緒 3: 踢腿偵測 (每 2s 輸出距離差)")
    
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)