import cv2
import pykinect_azure as pykinect

if __name__ == "__main__":
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

    cv2.namedWindow('Color image with skeleton', cv2.WINDOW_NORMAL)

    isLeftHandUp = False
    isRightHandUp = False

    while True:
        # 取得影像
        capture = device.update()
        body_frame = bodyTracker.update()

        ret_color, color_image = capture.get_color_image()
        if not ret_color:
            continue

        # --- 舉手偵測 ---
        for body_id in range(body_frame.get_num_bodies()):
            # joints in 3D (mm)
            skeleton_3d = body_frame.get_body(body_id).numpy()

            head_y = skeleton_3d[pykinect.K4ABT_JOINT_HEAD, 1]
            left_hand_y = skeleton_3d[pykinect.K4ABT_JOINT_HAND_LEFT, 1]
            right_hand_y = skeleton_3d[pykinect.K4ABT_JOINT_HAND_RIGHT, 1]
            left_shoulder_y = skeleton_3d[pykinect.K4ABT_JOINT_SHOULDER_LEFT, 1]
            right_shoulder_y = skeleton_3d[pykinect.K4ABT_JOINT_SHOULDER_RIGHT, 1]

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
                # cv2.putText(color_image, "Hand UP!", (50, 100),
                #             cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 3)

            if right_hand_up and not isRightHandUp:
                isRightHandUp = True
                print("Right Hand Up")
                # cv2.putText(color_image, "Hand UP!", (50, 100),
                #             cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 3)

        # --- 畫骨架 ---
        color_skeleton = body_frame.draw_bodies(color_image, pykinect.K4A_CALIBRATION_TYPE_COLOR)
        cv2.imshow('Color image with skeleton', color_skeleton)

        # 按 q 離開
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break