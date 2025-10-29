from flask import Flask 
from flask_socketio import SocketIO
import pykinect_azure as pykinect

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")


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

isLeftHandUp = False
isRightHandUp = False

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
        skeleton_3d = body_frame.get_body(body_id).numpy()
        spine_base_z = skeleton_3d[pykinect.K4ABT_JOINT_SPINE_BASE, 2]
        if spine_base_z < min_z:
            min_z = spine_base_z
            closest_id = body_id

    return closest_id

def detect_hand_up():
    global isLeftHandUp, isRightHandUp
    while True:
        capture = device.update()
        # 取得影像
        body_frame = bodyTracker.update(capture)

        # --- 舉手偵測 ---
        body_id = get_closest_body(body_frame)

        # joints in 3D (mm)
        skeleton_3d = body_frame.get_body(body_id).numpy()

        head_y = skeleton_3d[pykinect.K4ABT_JOINT_HEAD, 1]
        left_hand_y = skeleton_3d[pykinect.K4ABT_JOINT_HAND_LEFT, 1]
        right_hand_y = skeleton_3d[pykinect.K4ABT_JOINT_HAND_RIGHT, 1]

        # 注意：Y 軸往下，數值小 = 高
        left_hand_up = left_hand_y < head_y
        right_hand_up = right_hand_y < head_y


        if not left_hand_up and isLeftHandUp:
            isLeftHandUp = False

        if not right_hand_up and isRightHandUp:
            isRightHandUp = False

        if left_hand_up and not isLeftHandUp:
            isLeftHandUp = True
            print("Left Hand Up")
            socketio.emit("hand_event", {"side": "left"})

        if right_hand_up and not isRightHandUp:
            isRightHandUp = True
            print("Right Hand Up")
            socketio.emit("hand_event", {"side": "right"})

if __name__ == "__main__":
    socketio.start_background_task(detect_hand_up)
    socketio.run(app, host="0.0.0.0", port=5000)