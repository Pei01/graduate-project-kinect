from flask import Flask, request, jsonify
from flask_cors import CORS
from escpos.printer import Usb
from PIL import Image, ImageDraw, ImageFont
import datetime
import os

# --- 自動修正驅動問題 (避免 No backend available) ---
import usb.core
import usb.backend.libusb1
try:
    import libusb_package
    lib_path = libusb_package.find_library(candidate='libusb-1.0')
    if lib_path:
        backend = usb.backend.libusb1.get_backend(find_library=lambda x: lib_path)
    else:
        backend = None
except:
    backend = None
# ------------------------------------------------

app = Flask(__name__)
CORS(app)

# --- 設定參數 ---
VID = 0x1fc9
PID = 0x2016
EP_OUT = 0x03
EP_IN = 0x81

# --- 狗勾 ASCII Art ---
DOGE_ART = """
⠀⠀⠀⢠⡾⠲⠶⣤⣀⣠⣤⣤⣤⡿⠛⠿⡴⠾⠛⢻⡆⠀⠀⠀
⠀⠀⠀⣼⠁⠀⠀⠀⠉⠁⠀⢀⣿⠐⡿⣿⠿⣶⣤⣤⣷⡀⠀⠀
⠀⠀⠀⢹⡶⠀⠀⠀⠀⠀⠀⠈⢯⣡⣿⣿⣀⣸⣿⣦⢓⡟⠀⠀
⠀⠀⢀⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠹⣍⣭⣾⠁⠀⠀
⠀⣀⣸⣇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣸⣷⣤⡀
⠈⠉⠹⣏⡁⠀⢸⣿⠀⠀⠀⢀⡀⠀⠀⠀⣿⠆⠀⢀⣸⣇⣀⠀
⠀⠐⠋⢻⣅⣄⢀⣀⣀⡀⠀⠯⠽⠂⢀⣀⣀⡀⠀⣤⣿⠀⠉⠀
⠀⠀⠴⠛⠙⣳⠋⠉⠉⠙⣆⠀⠀⢰⡟⠉⠈⠙⢷⠟⠉⠙⠂⠀
⠀⠀⠀⠀⠀⢻⣄⣠⣤⣴⠟⠛⠛⠛⢧⣤⣤⣀⡾
"""

# --- 全域變數 ---
printer_device = None

def get_printer():
    """ 取得或重新建立印表機連線 """
    global printer_device
    if printer_device is not None:
        return printer_device

    try:
        print("嘗試建立 USB 連線...")
        # 加入 profile="TM-T88II" 消除寬度警告
        p = Usb(idVendor=VID, idProduct=PID, timeout=0, in_ep=EP_IN, out_ep=EP_OUT, profile="TM-T88II")
        printer_device = p
        print("連線成功！準備就緒。")
        return printer_device
    except Exception as e:
        print(f"連線失敗: {e}")
        return None

def execute_print_job(user_name="工作到死的綠色狗勾"):
    global printer_device
    
    p = get_printer()
    if p is None:
        return False, "無法連接印表機"

    try:
        # ================= 繪圖邏輯開始 =================
        WIDTH = 576
        HEIGHT = 2000 # 開長一點，最後裁切
        image = Image.new('RGB', (WIDTH, HEIGHT), (255, 255, 255))
        draw = ImageDraw.Draw(image)

        # 1. 載入字體 (中文用微軟正黑，符號用 Segoe UI Symbol)
        try:
            path_msjh = "C:\\Windows\\Fonts\\msjh.ttc"
            path_symbol = "C:\\Windows\\Fonts\\seguisym.ttf"
            
            font_title = ImageFont.truetype(path_msjh, 42)
            font_header = ImageFont.truetype(path_msjh, 32)
            font_body = ImageFont.truetype(path_msjh, 24)
            font_bold = ImageFont.truetype(path_msjh, 26)
            font_small = ImageFont.truetype(path_msjh, 20)
            font_big_money = ImageFont.truetype(path_msjh, 48)
            # 狗勾專用字體
            font_doge = ImageFont.truetype(path_symbol, 28)
        except:
            print("字體載入失敗，請確認 Windows 字型資料夾")
            return False, "字體錯誤"

        # 輔助函式
        def draw_line(y_pos, style="="):
            text = "=" * 46 if style == "=" else "-" * 46
            draw.text((20, y_pos), text, font=font_body, fill=0)
            return y_pos + 30

        def draw_row(y_pos, label, amount, font=font_body):
            draw.text((25, y_pos), label, font=font, fill=0)
            w = draw.textlength(amount, font=font)
            draw.text((530 - w, y_pos), amount, font=font, fill=0)
            return y_pos + 35

        y = 30
        
        # --- (A) 標題 ---
        text = "[ 注 意 力 有 限 公 司 ]"
        w = draw.textlength(text, font=font_title)
        draw.text(((WIDTH - w)/2, y), text, font=font_title, fill=0)
        y += 60

        text = "薪 資 明 細 表"
        w = draw.textlength(text, font=font_header)
        draw.text(((WIDTH - w)/2, y), text, font=font_header, fill=0)
        y += 40
        y = draw_line(y, "=")

        # --- (B) 基本資料 ---
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        draw.text((25, y), f"列印日期: {now_str}", font=font_body, fill=0); y += 35
        draw.text((25, y), "使用者代碼: A-111590001", font=font_body, fill=0); y += 35
        
        # 這裡使用前端傳來的名字！
        draw.text((25, y), f"行為樣本: {user_name}", font=font_body, fill=0); y += 35
        
        draw.text((25, y), "所屬模組: 注意力產出單元", font=font_body, fill=0); y += 35
        draw.text((25, y), "計算期間: 2025/11/01 - 11/30", font=font_body, fill=0); y += 35
        y = draw_line(y, "="); y += 10

        # --- (C) 收入 ---
        draw.text((25, y), "【注 意 力 產 出 項 目】", font=font_bold, fill=0); y += 35
        y = draw_line(y, "-")
        
        income_items = [
            ("總停留時間 (達成率 83%)", "$  18,600"),
            ("播放影片數量 (完成率 78%)", "$   9,800"),
            ("互動流程完成 (完成率 71%)", "$   6,300"),
            ("內容重播次數 (回訪率 64%)", "$   3,200"),
            ("系統觸發事件數 (有效率 92%)", "$   1,750")
        ]
        for label, amt in income_items:
            y = draw_row(y, label, amt)
        
        y = draw_line(y, "-")
        y = draw_row(y, "產值小計", "$  39,650", font=font_bold); y += 20

        # --- (D) 支出 ---
        draw.text((25, y), "【資 料 處 理 與 平 台 成 本】", font=font_bold, fill=0); y += 35
        y = draw_line(y, "-")
        
        deduct_items = [
            ("系統運算與儲存費", "$  12,400"),
            ("演算法訓練分攤", "$   9,800"),
            ("第三方平台轉介費", "$   6,200"),
            ("注意力折舊", "$   7,900"),
            ("使用者體驗優化成本", "$   3,350")
        ]
        for label, amt in deduct_items:
            y = draw_row(y, label, amt)

        y = draw_line(y, "-")
        y = draw_row(y, "扣除小計", "$  39,650", font=font_bold); y += 20

        # --- (E) 實發金額 ---
        y = draw_line(y, "=")
        draw.text((25, y+5), "實 際 回 饋 金 額", font=font_header, fill=0)
        amt_str = "$        50"
        w = draw.textlength(amt_str, font=font_big_money)
        draw.text((530 - w, y-5), amt_str, font=font_big_money, fill=0)
        y += 60
        y = draw_line(y, "="); y += 20

        # --- (F) 備註 ---
        draw.text((25, y), "備註:", font=font_small, fill=0); y += 25
        notes = [
            "1. 本注意力產出已完成轉換與商業化流程。",
            "2. 相關資料持續用於優化預測模型。",
            "3. 使用者無法要求刪除或回收產出內容。",
            "4. 本單據不構成僱傭關係證明。",
            "5. 薪資旁邊地上請自行領取。"
        ]
        for note in notes:
            draw.text((25, y), note, font=font_small, fill=0)
            y += 25
        y += 20

        # --- (G) 簽名檔 ---
        footer = "** 感 謝 您 的 專 注 投 入 **"
        w = draw.textlength(footer, font=font_bold)
        draw.text(((WIDTH - w)/2, y), footer, font=font_bold, fill=0)
        y += 60
        
        sign = "_____________"
        w = draw.textlength(sign, font=font_body)
        draw.text(((WIDTH - w)/2, y), sign, font=font_body, fill=0)
        y += 30
        
        sign_txt = "(簽收欄)"
        w = draw.textlength(sign_txt, font=font_small)
        draw.text(((WIDTH - w)/2, y), sign_txt, font=font_small, fill=0)
        y += 40

        # --- (H) 狗勾 ASCII Art (使用特殊字體) ---
        # 計算置中
        bbox = draw.textbbox((0, 0), DOGE_ART, font=font_doge, spacing=0)
        doge_w = bbox[2] - bbox[0]
        doge_x = (WIDTH - doge_w) / 2
        
        draw.text((doge_x, y), DOGE_ART, font=font_doge, fill=0, spacing=0)
        y += (bbox[3] - bbox[1]) + 50 # 加上狗的高度

        # ================= 繪圖結束，開始列印 =================
        
        # 裁切圖片
        final_image = image.crop((0, 0, WIDTH, y))
        
        # 轉存預覽 (Debug 用)
        final_image.save("last_print_preview.png")

        print(f"正在列印: {user_name}")
        p.image(final_image)
        p.cut()
        
        # 保持連線，不 close
        return True, "列印成功"

    except Exception as e:
        print(f"列印中斷: {e}")
        try:
            p.close()
        except:
            pass
        printer_device = None
        return False, f"列印失敗: {str(e)}"

@app.route('/api/print', methods=['POST'])
def handle_print():
    # 強制讀取 JSON
    data = request.get_json(force=True)
    
    # 這裡接收前端傳來的文字，當作「使用者名字」
    # 如果前端沒傳，就用預設的「工作到死的綠色狗勾」
    user_name = data.get('message', '工作到死的綠色狗勾')
    if not user_name:
        user_name = '工作到死的綠色狗勾'
    
    success, info = execute_print_job(user_name)
    
    if success:
        return jsonify({"status": "success", "msg": "已加入佇列"})
    else:
        return jsonify({"status": "error", "msg": info}), 500

if __name__ == '__main__':
    # 預先連線
    # get_printer()
    
    # print("服務啟動中... Port: 4000")
    # # 使用 Port 4000 (依照您的設定)
    # app.run(host='0.0.0.0', port=4000, debug=False, threaded=True)

    execute_print_job()