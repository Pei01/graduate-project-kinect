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

# --- 全域變數 ---
printer_device = None

# --- 等級對應資料 ---
GRADE_INFO = {
    'A': {
        'name': '榮譽終身奴隸',
        'desc_lines': ['你就是一台會呼吸的印鈔機！', '你的血汗淚，剛好夠我買下私人飛機～✈️✈️']
    },
    'B': {
        'name': '過勞模範員工',
        'desc_lines': ['你的視網膜已經過熱，但請繼續保持，', '老闆的新跑車靠你了！']
    },
    'C': {
        'name': '責任制社畜',
        'desc_lines': ['表現平庸，乖乖貢獻眼球，', '就是你這種人撐起了我們的股價。']
    },
    'D': {
        'name': '免洗實習生',
        'desc_lines': ['隨用隨丟，你的注意力', '比便利商店的塑膠袋還廉價。']
    },
    'E': {
        'name': '試用期淘汰者',
        'desc_lines': ['連被我們利用的價值都沒有，滾吧。']
    }
}

def get_grade(watched_percent):
    if watched_percent >= 80:
        return 'A'
    elif watched_percent >= 60:
        return 'B'
    elif watched_percent >= 40:
        return 'C'
    elif watched_percent >= 20:
        return 'D'
    else:
        return 'E'

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

def execute_print_job(watch_seconds=10, watched_percent=50):
    global printer_device

    p = get_printer()
    if p is None:
        return False, "無法連接印表機"

    try:
        # ================= 繪圖邏輯開始 =================
        WIDTH = 576
        HEIGHT = 2000
        image = Image.new('RGB', (WIDTH, HEIGHT), (255, 255, 255))
        draw = ImageDraw.Draw(image)

        try:
            path_msjh = "C:\\Windows\\Fonts\\msjh.ttc"
            font_title = ImageFont.truetype(path_msjh, 42)
            font_header = ImageFont.truetype(path_msjh, 32)
            font_body = ImageFont.truetype(path_msjh, 24)
            font_bold = ImageFont.truetype(path_msjh, 26)
            font_small = ImageFont.truetype(path_msjh, 20)
            font_big_money = ImageFont.truetype(path_msjh, 48)
        except:
            print("字體載入失敗，請確認 Windows 字型資料夾")
            return False, "字體錯誤"

        def draw_line(y_pos, style="="):
            text = "=" * 46 if style == "=" else "-" * 46
            draw.text((20, y_pos), text, font=font_body, fill=0)
            return y_pos + 30

        def draw_row(y_pos, label, amount, font=font_body):
            draw.text((25, y_pos), label, font=font, fill=0)
            w = draw.textlength(amount, font=font)
            draw.text((530 - w, y_pos), amount, font=font, fill=0)
            return y_pos + 35

        # 取得等級資訊
        grade = get_grade(watched_percent)
        grade_name = GRADE_INFO[grade]['name']
        grade_desc_lines = GRADE_INFO[grade]['desc_lines']

        # 計算金額
        income_time = watch_seconds * 1000
        income_bonus = int(10000 * watched_percent / 100)
        subtotal = income_time + income_bonus
        deduction = subtotal
        net = 0

        y = 30

        # --- (A) 標題 ---
        text = "[ 注 意 力 有 限 公 司 ]"
        w = draw.textlength(text, font=font_title)
        draw.text(((WIDTH - w) / 2, y), text, font=font_title, fill=0)
        y += 60

        text = "薪 資 明 細 表"
        w = draw.textlength(text, font=font_header)
        draw.text(((WIDTH - w) / 2, y), text, font=font_header, fill=0)
        y += 45
        y = draw_line(y, "=")
        y += 10

        # --- (B) 職稱與描述 ---
        draw.text((25, y), f"職稱：{grade_name}", font=font_bold, fill=0)
        y += 40

        if len(grade_desc_lines) == 1:
            draw.text((25, y), f"『{grade_desc_lines[0]}』", font=font_body, fill=0)
            y += 32
        else:
            draw.text((25, y), f"『{grade_desc_lines[0]}", font=font_body, fill=0)
            y += 32
            for line in grade_desc_lines[1:-1]:
                draw.text((25, y), line, font=font_body, fill=0)
                y += 32
            draw.text((25, y), f"{grade_desc_lines[-1]}』", font=font_body, fill=0)
            y += 32
        y += 10

        # --- (C) 列印日期 ---
        now_str = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        draw.text((25, y), f"列印日期: {now_str}", font=font_body, fill=0)
        y += 35
        y = draw_line(y, "=")
        y += 10

        # --- (D) 注意力產出項目 ---
        text = "【 注 意 力 產 出 項 目 】"
        w = draw.textlength(text, font=font_bold)
        draw.text(((WIDTH - w) / 2, y), text, font=font_bold, fill=0)
        y += 35
        y = draw_line(y, "-")

        y = draw_row(y, f"總停留時數 ({watch_seconds} sec)", f"$  {income_time:,}")
        y = draw_row(y, f"互動完成率 ({watched_percent}%)", f"$  {income_bonus:,}")

        y = draw_line(y, "-")
        y = draw_row(y, "產值小計", f"$  {subtotal:,}", font=font_bold)
        y += 15

        # --- (E) 平台成本 ---
        text = "【 平 台 成 本 】"
        w = draw.textlength(text, font=font_bold)
        draw.text(((WIDTH - w) / 2, y), text, font=font_bold, fill=0)
        y += 35
        y = draw_line(y, "-")

        y = draw_row(y, "平台抽成比例 (100%)", f"$  {deduction:,}")

        y = draw_line(y, "-")
        y = draw_row(y, "扣除小計", f"$  {deduction:,}", font=font_bold)
        y += 20

        # --- (F) 實發金額 ---
        y = draw_line(y, "=")
        draw.text((25, y + 5), "實 發 金 額", font=font_header, fill=0)
        amt_str = f"$  {net}"
        w = draw.textlength(amt_str, font=font_big_money)
        draw.text((530 - w, y - 5), amt_str, font=font_big_money, fill=0)
        y += 65
        y = draw_line(y, "=")
        y += 15

        # --- (G) 備註 ---
        draw.text((25, y), "備註：", font=font_small, fill=0)
        y += 28
        notes = [
            "1. 本注意力產出已完成轉換與商業化流程。",
            "2. 相關資料將持續用於系統優化與預測模型訓練。",
            "3. 使用者無法要求刪除、回收或轉讓其產出內容。",
            "4. 本單據不構成僱傭關係證明。",
        ]
        for note in notes:
            draw.text((25, y), note, font=font_small, fill=0)
            y += 25
        y += 20

        # --- (H) 簽名檔 ---
        footer = "** 感 謝 您 的 專 注 投 入 **"
        w = draw.textlength(footer, font=font_bold)
        draw.text(((WIDTH - w) / 2, y), footer, font=font_bold, fill=0)
        y += 55

        sign = "_____________"
        w = draw.textlength(sign, font=font_body)
        draw.text(((WIDTH - w) / 2, y), sign, font=font_body, fill=0)
        y += 30

        sign_txt = "(簽收欄)"
        w = draw.textlength(sign_txt, font=font_small)
        draw.text(((WIDTH - w) / 2, y), sign_txt, font=font_small, fill=0)
        y += 40

        y = draw_line(y, "-")
        y += 20

        # ================= 繪圖結束，開始列印 =================
        final_image = image.crop((0, 0, WIDTH, y))
        final_image.save("last_print_preview.png")

        print(f"正在列印: 等級{grade} / {grade_name} / {watch_seconds}s / {watched_percent}%")
        p.image(final_image)
        p.cut()

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
    data = request.get_json(force=True)

    watch_seconds = data.get('watchSeconds', 0)
    watched_percent = data.get('watchedPercent', 0)

    try:
        watch_seconds = int(watch_seconds)
        watched_percent = float(watched_percent)
    except (ValueError, TypeError):
        watch_seconds = 0
        watched_percent = 0

    success, info = execute_print_job(watch_seconds, watched_percent)

    if success:
        return jsonify({"status": "success", "msg": "已加入佇列"})
    else:
        return jsonify({"status": "error", "msg": info}), 500

if __name__ == '__main__':
    # 預先連線

    get_printer()
    
    print("服務啟動中... Port: 4000")
    # 使用 Port 4000 (依照您的設定)
    app.run(host='0.0.0.0', port=4000, debug=False, threaded=True)

    # execute_print_job()