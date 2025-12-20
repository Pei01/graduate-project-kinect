from escpos.printer import Usb
from PIL import Image, ImageDraw, ImageFont

# --- 連線設定 ---
VID = 0x1fc9
PID = 0x2016
EP_OUT = 0x03
EP_IN = 0x81

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

def print_doge_v2():
    # 80mm 紙張安全寬度大約 550px
    WIDTH = 550
    HEIGHT = 400 
    image = Image.new('RGB', (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    try:
        # --- 關鍵修正 1: 換字體 ---
        # Segoe UI Symbol 對特殊符號支援度最好
        font_path = "C:\\Windows\\Fonts\\seguisym.ttf"
        
        # --- 關鍵修正 2: 縮小字體 ---
        # 設為 24 應該剛好，不會太大
        font = ImageFont.truetype(font_path, 24)
    except:
        print("找不到 Segoe UI Symbol 字體，嘗試使用新細明體...")
        # 新細明體 (mingliu.ttc) 通常也支援這些符號
        font = ImageFont.truetype("C:\\Windows\\Fonts\\mingliu.ttc", 24)

    # 計算置中
    left, top, right, bottom = draw.textbbox((0, 0), DOGE_ART, font=font)
    text_width = right - left
    text_height = bottom - top
    
    x = (WIDTH - text_width) / 2
    y = 20

    # --- 關鍵修正 3: 調整行距 (spacing) ---
    # spacing 設為 4 或 0，讓圖案緊湊一點，不然狗會被拉很長
    draw.text((x, y), DOGE_ART, font=font, fill=(0, 0, 0), spacing=4)

    # 裁切圖片
    final_image = image.crop((0, 0, WIDTH, y + text_height + 50))
    
    # --- 強烈建議：先打開這張圖檢查 ---
    # 程式跑完後，請去資料夾點開這張圖，確認是不是狗勾，而不是方格
    final_image.save("doge_check.png") 

    try:
        print("正在列印修正版狗勾...")
        p = Usb(idVendor=VID, idProduct=PID, timeout=0, in_ep=EP_IN, out_ep=EP_OUT)
        p.image(final_image)
        p.cut()
        print("列印完成！請檢查是否還有方格。")
        
    except Exception as e:
        print(f"列印失敗: {e}")

if __name__ == "__main__":
    print_doge_v2()