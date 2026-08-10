import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import io
import os
import re
from datetime import datetime

# ==========================================
# 1. PENGATURAN BOT TELEGRAM (Mendukung GitHub Secrets)
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8909829324:AAGEaTwybmbTpRIiws_qOLkPGz0noFSUwwo")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "677263793")

def kirim_telegram(pesan):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": pesan, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Gagal mengirim pesan Telegram: {e}")

# ==========================================
# 2. SISTEM PENGAMBILAN DATA (FIX WIKIPEDIA)
# ==========================================
def dapatkan_watchlist_kompas100():
    print("Memuat daftar saham Kompas 100 dari internet...")
    try:
        url = 'https://id.wikipedia.org/wiki/Indeks_Kompas100'
        header_palsu = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        halaman_web = requests.get(url, headers=header_palsu).text
        
        tabel_semua = pd.read_html(io.StringIO(halaman_web))
        
        daftar_kode = []
        for tabel in tabel_semua:
            kolom_kode = next((col for col in tabel.columns if 'Kode' in str(col) or 'Ticker' in str(col)), None)
            if kolom_kode:
                daftar_kode = tabel[kolom_kode].tolist()
                break
                
        if daftar_kode:
            daftar_bersih = []
            for kode in daftar_kode:
                if pd.notna(kode):
                    # Membersihkan teks agar hanya mengambil huruf kapital/angka (Contoh: BEI: AALI -> AALI)
                    match = re.findall(r'[A-Z0-9]+', str(kode).upper())
                    if match:
                        # Ambil bagian string terpanjang yang murni huruf/angka
                        ticker = max(match, key=len)
                        if len(ticker) >= 4 and ticker != "KODE":
                            daftar_bersih.append(f"{ticker}.JK")
                            
            daftar_bersih = list(set(daftar_bersih))
            print(f"✅ Berhasil memuat {len(daftar_bersih)} saham.")
            return daftar_bersih
        else:
            raise ValueError("Tidak menemukan kolom 'Kode'.")
            
    except Exception as e:
        print(f"❌ Gagal memuat Wikipedia: {e}")
        return [
            "BBCA.JK", "BMRI.JK", "BBNI.JK", "BBRI.JK", "BRIS.JK", 
            "ASII.JK", "TLKM.JK", "ANTM.JK", "PGEO.JK", "GOTO.JK", 
            "AMMN.JK", "BREN.JK", "CUAN.JK", "BRPT.JK", "TPIA.JK"
        ]

# ==========================================
# 3. MESIN INDIKATOR & SMART MONEY
# ==========================================
def hitung_indikator(df):
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['STD20'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['SMA20'] + (df['STD20'] * 2)
    df['BB_Lower'] = df['SMA20'] - (df['STD20'] * 2)
    
    df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()
    df['Turnover'] = df['Close'] * df['Volume']
    df['Avg_Turnover_20D'] = df['Turnover'].rolling(window=20).mean()
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['Signal_Line']
    
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    raw_money_flow = typical_price * df['Volume']
    delta_tp = typical_price.diff()
    positive_flow = raw_money_flow.where(delta_tp > 0, 0).rolling(window=14).sum()
    negative_flow = raw_money_flow.where(delta_tp < 0, 0).rolling(window=14).sum()
    mfr = positive_flow / negative_flow
    df['MFI'] = 100 - (100 / (1 + mfr))
    
    arah_harga = np.sign(df['Close'].diff())
    df['OBV'] = (arah_harga * df['Volume']).fillna(0).cumsum()
    df['OBV_EMA20'] = df['OBV'].ewm(span=20, adjust=False).mean()
    
    return df

# ==========================================
# 4. LOGIKA 4 STRATEGI ANALISIS
# ==========================================
def proses_saham(kode_saham):
    try:
        saham = yf.Ticker(kode_saham)
        df = saham.history(period="6mo")
        if len(df) < 60: return
        
        df = hitung_indikator(df)
        hari_ini = df.iloc[-1]
        kemarin = df.iloc[-2]
        
        harga = hari_ini['Close']
        if harga < 100: return 
        rata_rata_turnover = hari_ini['Avg_Turnover_20D']
        if rata_rata_turnover < 5_000_000_000: return 

        ema20, ema50 = hari_ini['EMA20'], hari_ini['EMA50']
        volume, vol_ma = hari_ini['Volume'], hari_ini['Vol_MA20']
        rsi, mfi = hari_ini['RSI'], hari_ini['MFI']
        macd_hist = hari_ini['MACD_Hist']
        obv, obv_ema = hari_ini['OBV'], hari_ini['OBV_EMA20']
        bb_upper, bb_lower = hari_ini['BB_Upper'], hari_ini['BB_Lower']
        
        sinyal = None
        alasan = ""
        sl = tp1 = tp2 = 0

        # STRATEGI 1: BREAKOUT
        tertinggi_20h = df['High'].iloc[-21:-1].max()
        if (harga > tertinggi_20h) and (volume > vol_ma * 1.5) and (harga > ema20):
            if (macd_hist > 0) and (obv > obv_ema):
                sinyal = "🚀 BREAKOUT"
                alasan = "Tembus resisten 20 hari didukung tren akumulasi OBV & momentum MACD."
                sl = hari_ini['Low'] * 0.96
                tp1 = harga * 1.05
                tp2 = harga * 1.12

        # STRATEGI 2: BUY ON WEAKNESS
        elif (harga > ema50) and (harga <= bb_lower * 1.02):
            if (mfi < 30) and (macd_hist > kemarin['MACD_Hist']):
                sinyal = "📉 BUY ON WEAKNESS"
                alasan = "Sentuh batas bawah Bollinger. Indikator uang keluar (MFI) sangat jenuh."
                sl = bb_lower * 0.98
                tp1 = ema20 
                tp2 = bb_upper

        # STRATEGI 3: BULLISH DIVERGENCE
        elif (harga < ema20):
            low_baru = df['Low'].iloc[-5:].min()
            low_lama = df['Low'].iloc[-15:-5].min()
            rsi_baru = df['RSI'].iloc[-5:].min()
            rsi_lama = df['RSI'].iloc[-15:-5].min()
            macd_baru = df['MACD_Hist'].iloc[-5:].min()
            macd_lama = df['MACD_Hist'].iloc[-15:-5].min()
            
            harga_turun = low_baru < low_lama
            momentum_naik = (rsi_baru > rsi_lama + 5) and (macd_baru > macd_lama)
            candle_hijau = hari_ini['Close'] > hari_ini['Open']
            
            if harga_turun and momentum_naik and candle_hijau:
                sinyal = "👀 BULLISH DIVERGENCE"
                alasan = "Harga mencetak terendah baru, tetapi momentum RSI & MACD menanjak (penjual kehabisan tenaga)."
                sl = low_baru * 0.97
                tp1 = ema20
                tp2 = ema50

        # STRATEGI 4: REVERSAL
        elif (harga < ema50):
            engulfing = (harga > hari_ini['Open']) and (harga > kemarin['High'])
            obv_divergence = (obv > kemarin['OBV']) and (volume > vol_ma)
            
            if engulfing and (mfi < 40) and obv_divergence:
                sinyal = "🔥 CONFIRM REVERSAL"
                alasan = "Struktur candle kuat membalik tren, diiringi uang masuk (OBV naik) dari area bawah."
                sl = hari_ini['Low'] * 0.98
                jarak_sl = harga - sl
                if jarak_sl/harga < 0.03: sl = harga * 0.97
                tp1 = harga + ((harga - sl) * 2)
                tp2 = harga + ((harga - sl) * 3)

        if sinyal:
            pct_sl = ((harga - sl) / harga) * 100
            pct_tp1 = ((tp1 - harga) / harga) * 100
            pct_tp2 = ((tp2 - harga) / harga) * 100
            turnover_miliar = rata_rata_turnover / 1_000_000_000

            pesan = (
                f"🚨 **{sinyal}** | **{kode_saham.replace('.JK', '')}**\n\n"
                f"**Info:** {alasan}\n\n"
                f"📋 **TRADING PLAN**\n"
                f"• Entry: Rp {harga:,.0f}\n"
                f"• SL: Rp {sl:,.0f} (-{pct_sl:.1f}%)\n"
                f"• TP 1: Rp {tp1:,.0f} (+{pct_tp1:.1f}%)\n"
                f"• TP 2: Rp {tp2:,.0f} (+{pct_tp2:.1f}%)\n\n"
                f"📊 **INDIKATOR SMART MONEY**\n"
                f"• Likuiditas: Rp {turnover_miliar:.1f} M/hari\n"
                f"• OBV Trend: {'Naik (Akumulasi)' if obv > obv_ema else 'Turun'}\n"
                f"• MFI (Money Flow): {mfi:.1f}\n"
                f"• RSI: {rsi:.1f}"
            )
            kirim_telegram(pesan)
            print(f"Sinyal {sinyal} dikirim untuk emiten: {kode_saham}")

    except Exception:
        pass 

# ==========================================
# 5. EKSEKUSI UTAMA (UNTUK GITHUB ACTIONS)
# ==========================================
if __name__ == "__main__":
    print("Memulai pemindaian pasar harian...")
    daftar_pantauan_saham = dapatkan_watchlist_kompas100()
    
    print(f"Total saham dalam pantauan: {len(daftar_pantauan_saham)}. Memulai analisis...")
    for kode_emiten in daftar_pantauan_saham:
        proses_saham(kode_emiten)
        time.sleep(1) # Jeda agar aman dari batasan server Yahoo Finance
        
    print("Pemindaian selesai.")
