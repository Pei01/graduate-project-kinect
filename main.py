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

# 裝置 handle 改為可變全域,讓 acquisition worker 能在 USB 斷線後完整重建
device = None
bodyTracker = None
device_lock = threading.Lock()

# 連續錯誤達到此閾值時觸發 device 完整重建(30fps 下約 2 秒)
DEVICE_REINIT_THRESHOLD = 60
# 重建失敗後的退避秒數,避免持續打 USB 子系統
DEVICE_REINIT_BACKOFF = 2.0


def _safe_close_device():
    """盡力釋放當前的 device / bodyTracker,任何例外都吞掉。
    pykinect_azure 在 handle 已壞掉時 close 也可能丟例外,但我們的目標就是丟掉它。"""
    global device, bodyTracker
    if bodyTracker is not None:
        for fn_name in ("destroy", "shutdown", "close"):
            fn = getattr(bodyTracker, fn_name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
                break
        bodyTracker = None
    if device is not None:
        for fn_name in ("close", "stop_cameras"):
            fn = getattr(device, fn_name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
        device = None


def init_kinect_device():
    """(重新)建立 device 與 body tracker。成功回傳 True。
    呼叫前會先把舊的 handle 釋放,避免 SDK 內部 device context 殘留。"""
    global device, bodyTracker
    with device_lock:
        _safe_close_device()
        # 給 USB 子系統一點時間重新枚舉裝置
        time.sleep(1.0)
        try:
            device = pykinect.start_device(config=device_config)
            bodyTracker = pykinect.start_body_tracker(pykinect.K4ABT_TRACKER_PROCESSING_MODE_GPU)
            print("✅ [Device] Kinect 裝置已就緒")
            return True
        except Exception as e:
            print(f"❌ [Device] 硬體啟動失敗: {e}")
            device = None
            bodyTracker = None
            return False


# 啟動裝置(初次)
init_kinect_device()

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


def _has_valid_handle(obj):
    """檢查 pykinect_azure 物件的底層 C handle 是否非 NULL。
    pykinect_azure 的 VERIFY 失敗時不會 raise，只會回傳一個 handle=0x0 的物件，
    必須主動驗證以避免後續 C API 拿到 NULL pointer。"""
    if obj is None:
        return False
    handle = getattr(obj, '_handle', None)
    if handle is None:
        handle = getattr(obj, 'handle', None)
    if handle is None:
        return False
    # ctypes c_void_p 的 NULL 表示為 .value == None 或 0；整數 0 也視為 NULL
    value = getattr(handle, 'value', handle)
    return bool(value)


def _trigger_device_reinit(reason):
    """連續錯誤太久時呼叫:完整重建 device,避免一直拿著壞 handle 重試。"""
    print(f"🔄 [Device] 偵測到裝置失聯({reason}),嘗試完整重建 Kinect...")
    with skeleton_condition:
        global latest_skeleton_3d
        latest_skeleton_3d = None
        skeleton_condition.notify_all()
    if not init_kinect_device():
        time.sleep(DEVICE_REINIT_BACKOFF)


def kinect_data_acquisition_worker():
    """【1. 資料獲取 Worker】負責抓取硬體數據，並通知偵測 workers"""
    global latest_skeleton_3d
    last_status = False
    last_frame_time = 0.0
    consecutive_errors = 0

    while True:
        # device 尚未就緒(初次失敗或剛被重建中):等待
        if device is None or bodyTracker is None:
            if not init_kinect_device():
                time.sleep(DEVICE_REINIT_BACKOFF)
                continue

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
            if not _has_valid_handle(capture):
                consecutive_errors += 1
                if consecutive_errors % 30 == 1:
                    print(f"⚠️ [Acquisition] capture handle 無效，略過此幀（連續 {consecutive_errors} 次）")
                if consecutive_errors >= DEVICE_REINIT_THRESHOLD:
                    _trigger_device_reinit("capture handle 持續無效")
                    consecutive_errors = 0
                    continue
                time.sleep(0.01)
                continue

            # 直接驗證深度影像物件的 C handle，比 to_numpy() 路徑更可靠
            # 避免 capture 帶著 NULL depth handle 進到 body tracker 觸發 image_get_buffer 錯誤
            depth_valid = False
            try:
                if hasattr(capture, 'get_depth_image_object'):
                    depth_obj = capture.get_depth_image_object()
                    depth_valid = _has_valid_handle(depth_obj)
                else:
                    ret, depth_img = capture.get_depth_image()
                    depth_valid = bool(ret) and depth_img is not None
            except Exception:
                depth_valid = False

            if not depth_valid:
                consecutive_errors += 1
                if consecutive_errors % 30 == 1:
                    print(f"⚠️ [Acquisition] 深度影像 handle 為 NULL，略過此幀（連續 {consecutive_errors} 次）")
                if consecutive_errors >= DEVICE_REINIT_THRESHOLD:
                    _trigger_device_reinit("深度影像 handle 持續為 NULL")
                    consecutive_errors = 0
                    continue
                time.sleep(0.01)
                continue

            # body tracker 內部 enqueue 仍可能因 SDK race 拿到 NULL depth handle 而失敗，
            # 而 pykinect_azure 的 VERIFY 不會 raise（只 print_stack），
            # 失敗時會回傳 handle=0x0 的 Frame，後續操作會持續觸發 k4a_image_t 0x0 錯誤。
            try:
                body_frame = bodyTracker.update(capture)
            except Exception as track_err:
                consecutive_errors += 1
                if consecutive_errors % 30 == 1:
                    print(f"⚠️ [Acquisition] body tracker update 例外（連續 {consecutive_errors} 次）: {track_err}")
                time.sleep(0.05)
                continue

            if not _has_valid_handle(body_frame):
                consecutive_errors += 1
                if consecutive_errors % 30 == 1:
                    print(f"⚠️ [Acquisition] body tracker 回傳無效 frame（內部 enqueue 失敗，連續 {consecutive_errors} 次）")
                if consecutive_errors >= DEVICE_REINIT_THRESHOLD:
                    _trigger_device_reinit("body tracker 持續回傳無效 frame")
                    consecutive_errors = 0
                    continue
                time.sleep(0.05)
                continue

            consecutive_errors = 0

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
            consecutive_errors += 1
            # 「device disconnected」「get_capture」「k4a_device」這類訊息代表 USB 已斷,
            # 不必等 60 幀,直接重建。
            hard_lost = any(s in err_msg for s in (
                "disconnected", "get_capture", "k4a_device", "device lost", "io_failure"
            ))
            if hard_lost:
                _trigger_device_reinit(f"硬體例外: {e}")
                consecutive_errors = 0
                continue
            if "enqueue" in err_msg or "timeout" in err_msg:
                # body tracker 佇列滿：略過此幀，等久一點讓 GPU 消化
                time.sleep(0.05)
            elif "failed" in err_msg or "invalid" in err_msg or "handle" in err_msg:
                # 無效 handle（深度影像為 null）：略過此幀
                time.sleep(0.02)
            else:
                if consecutive_errors % 30 == 1:
                    print(f"⚠️ [Acquisition] 例外錯誤（連續 {consecutive_errors} 次）: {e}")
                time.sleep(0.02)
            # 重置 skeleton，避免偵測 worker 使用過期資料
            if consecutive_errors >= 10:
                with skeleton_condition:
                    latest_skeleton_3d = None
                    skeleton_condition.notify_all()
            # 累積錯誤太多仍救不回來時:強制重建裝置
            if consecutive_errors >= DEVICE_REINIT_THRESHOLD:
                _trigger_device_reinit(f"連續 {consecutive_errors} 次例外")
                consecutive_errors = 0
        finally:
            if capture is not None:
                del capture
            if body_frame is not None:
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


def start_worker_with_watchdog(target, name):
    """啟動 worker thread，若意外死亡則自動重啟"""
    def watchdog():
        while True:
            t = threading.Thread(target=target, daemon=True, name=name)
            t.start()
            t.join()
            print(f"⚠️ [{name}] 執行緒意外結束，0.5 秒後重啟...")
            time.sleep(0.5)
    threading.Thread(target=watchdog, daemon=True, name=f"{name}-watchdog").start()


if __name__ == "__main__":
    start_worker_with_watchdog(kinect_data_acquisition_worker, "資料獲取")
    start_worker_with_watchdog(detect_hand_worker, "手勢偵測")

    print("🚀 Kinect 多功能伺服器已啟動...")
    print("- 執行緒 1: 資料獲取 (Condition 保護，notify_all 驅動偵測，watchdog 自動重啟)")
    print("- 執行緒 2: 手勢偵測 (舉雙手 / 舉單手，5 幀滑動平滑，watchdog 自動重啟)")

    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
