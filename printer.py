from escpos.printer import Usb
from PIL import Image, ImageDraw, ImageFont
import datetime

# --- 連線設定 (維持您的環境) ---
VID = 0x1fc9
PID = 0x2016
EP_OUT = 0x03
EP_IN = 0x81

def create_and_print_slip():
    # 1. 設定畫布 (寬度 576px 為 80mm 標準)
    WIDTH = 576
    HEIGHT = 1600 # 先開長一點，最後會裁切
    image = Image.new('RGB', (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    # 2. 載入字體 (使用微軟正黑體)
    try:
        font_path = "C:\\Windows\\Fonts\\msjh.ttc"
        # 設定不同大小的字體
        font_title = ImageFont.truetype(font_path, 42) # 公司名
        font_header = ImageFont.truetype(font_path, 32) # 表格標題
        font_body = ImageFont.truetype(font_path, 24)   # 一般內文
        font_bold = ImageFont.truetype(font_path, 26)   # 粗體/小計
        font_small = ImageFont.truetype(font_path, 20)  # 備註
        font_big_money = ImageFont.truetype(font_path, 48) # 實發金額
    except:
        print("找不到字體，請確認 C:\\Windows\\Fonts\\msjh.ttc")
        return

    # --- 繪圖輔助函式 ---
    def draw_line(y_pos, style="="):
        # 畫分隔線
        text = "=" * 46 if style == "=" else "-" * 46
        draw.text((20, y_pos), text, font=font_body, fill=0)
        return y_pos + 30

    def draw_row(y_pos, label, amount, font=font_body):
        # 畫左右對齊的行 (項目靠左，金額靠右)
        draw.text((25, y_pos), label, font=font, fill=0)
        
        # 計算金額寬度，讓它靠右對齊 (右邊界設在 530)
        w = draw.textlength(amount, font=font)
        draw.text((530 - w, y_pos), amount, font=font, fill=0)
        return y_pos + 35

    # ================= 繪製開始 =================
    y = 30

    # 1. 頁首
    text = "[ 注 意 力 有 限 公 司 ]"
    w = draw.textlength(text, font=font_title)
    draw.text(((WIDTH - w)/2, y), text, font=font_title, fill=0)
    y += 60

    text = "薪 資 明 細 表"
    w = draw.textlength(text, font=font_header)
    draw.text(((WIDTH - w)/2, y), text, font=font_header, fill=0)
    y += 40

    y = draw_line(y, "=")

    # 2. 基本資料
    labels = [
        "列印日期: 2025-12-10  10:30:25",
        "使用者代碼: A-111590001",
        "行為樣本名稱: 工作到死的綠色狗勾",
        "所屬模組: 注意力產出單元",
        "計算期間: 2025/11/01 - 11/30"
    ]
    for line in labels:
        draw.text((25, y), line, font=font_body, fill=0)
        y += 35

    y = draw_line(y, "=")
    y += 10

    # 3. 產出項目 (收入)
    draw.text((25, y), "【注 意 力 產 出 項 目】", font=font_bold, fill=0); y += 35
    y = draw_line(y, "-")

    # 項目清單
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
    y = draw_row(y, "產值小計", "$  39,650", font=font_bold)
    y += 20

    # 4. 成本扣除 (支出)
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
    y = draw_row(y, "扣除小計", "$  39,650", font=font_bold) # 剛好扣光光 XD
    y += 20

    # 5. 實際回饋 (重點!)
    y = draw_line(y, "=")
    
    # 這裡用大字體強調 $ 50
    draw.text((25, y+5), "實 際 回 饋 金 額", font=font_header, fill=0)
    
    amount_str = "$        50"
    w = draw.textlength(amount_str, font=font_big_money)
    draw.text((530 - w, y-5), amount_str, font=font_big_money, fill=0)
    y += 60

    y = draw_line(y, "=")
    y += 20

    # 6. 備註 (小字)
    draw.text((25, y), "備註:", font=font_small, fill=0); y += 25
    notes = [
        "1. 本注意力產出已完成轉換與商業化流程。",
        "2. 相關資料將持續用於系統優化與預測模型訓練。",
        "3. 使用者無法要求刪除、回收或轉讓其產出內容。",
        "4. 本單據不構成僱傭關係證明。",
        "5. 薪資旁邊地上請自行領取。"
    ]
    for note in notes:
        draw.text((25, y), note, font=font_small, fill=0)
        y += 25
    
    y += 20

    # 7. 頁尾感謝與簽收
    footer_text = "** 感 謝 您 的 專 注 投 入 **"
    w = draw.textlength(footer_text, font=font_bold)
    draw.text(((WIDTH - w)/2, y), footer_text, font=font_bold, fill=0)
    y += 60

    sign_line = "_____________"
    w = draw.textlength(sign_line, font=font_body)
    draw.text(((WIDTH - w)/2, y), sign_line, font=font_body, fill=0)
    y += 30

    sign_text = "(簽收欄)"
    w = draw.textlength(sign_text, font=font_small)
    draw.text(((WIDTH - w)/2, y), sign_text, font=font_small, fill=0)
    y += 60 # 底部留白

    # ================= 列印程序 =================
    
    # 裁切圖片
    final_image = image.crop((0, 0, WIDTH, y))
    
    # 儲存預覽 (方便除錯)
    final_image.save("attention_slip_preview.png")

    try:
        print("正在列印注意力薪資單...")
        # 這裡加入 profile="TM-T88II" 避免寬度警告
        p = Usb(idVendor=VID, idProduct=PID, timeout=0, in_ep=EP_IN, out_ep=EP_OUT, profile="TM-T88II")
        
        p.image(final_image)
        p.cut()
        p.close()
        print("列印完成！")
        
    except Exception as e:
        print(f"列印失敗: {e}")
        print("請檢查 USB 連線，或確認圖片是否已生成。")

if __name__ == "__main__":
    create_and_print_slip()