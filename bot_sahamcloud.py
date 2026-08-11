import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import os
from datetime import datetime, timedelta

# ==========================================
# 1. PENGATURAN BOT TELEGRAM
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def kirim_telegram(pesan):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": pesan, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass

# ==========================================
# 2. STATUS PERSILANGAN (ARAH KEMIRINGAN)
# ==========================================
def cek_status_cross(garis_cepat_skrg, garis_lambat_skrg, garis_cepat_kmrn, garis_lambat_kmrn):
    if garis_cepat_kmrn <= garis_lambat_kmrn and garis_cepat_skrg > garis_lambat_skrg:
        return "🔥 Golden Cross"
    elif garis_cepat_kmrn >= garis_lambat_kmrn and garis_cepat_skrg < garis_lambat_skrg:
        return "🩸 Death Cross"
    elif garis_cepat_skrg > garis_cepat_kmrn:
        return "📈 Menanjak Naik"
    else:
        return "📉 Menurun"

# ==========================================
# 3. MESIN INDIKATOR
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
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['Signal_Line']
    
    # Stochastic (10, 5, 5)
    low_10 = df['Low'].rolling(window=10).min()
    high_10 = df['High'].rolling(window=10).max()
    df['%K_Raw'] = 100 * ((df['Close'] - low_10) / (high_10 - low_10))
    df['%K'] = df['%K_Raw'].rolling(window=5).mean()
    df['%D'] = df['%K'].rolling(window=5).mean()
    
    # Money Flow Index
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    raw_money_flow = typical_price * df['Volume']
    delta_tp = typical_price.diff()
    mfr = raw_money_flow.where(delta_tp > 0, 0).rolling(window=14).sum() / raw_money_flow.where(delta_tp < 0, 0).rolling(window=14).sum()
    df['MFI'] = 100 - (100 / (1 + mfr))
    
    # On-Balance Volume
    arah_harga = np.sign(df['Close'].diff())
    df['OBV'] = (arah_harga * df['Volume']).fillna(0).cumsum()
    df['OBV_EMA20'] = df['OBV'].ewm(span=20, adjust=False).mean()
    
    return df

# ==========================================
# 4. OUTLOOK IHSG HARIAN
# ==========================================
def kirim_outlook_ihsg():
    try:
        df = yf.download("^JKSE", period="3mo", threads=False)
        df = df.dropna(how='all')
        if len(df) < 20: return
        
        df = hitung_indikator(df)
        hari_ini = df.iloc[-1]
        kemarin = df.iloc[-2]
        
        harga = hari_ini['Close']
        ema20 = hari_ini['EMA20']
        
        tren = "🟢 BULLISH (Aman)" if harga > ema20 else "🔴 BEARISH (Hati-hati)"
        
        status_macd = cek_status_cross(hari_ini['MACD'], hari_ini['Signal_Line'], kemarin['MACD'], kemarin['Signal_Line'])
        status_stoch = cek_status_cross(hari_ini['%K'], hari_ini['%D'], kemarin['%K'], kemarin['%D'])
        status_rsi = "📈 Menanjak Naik" if hari_ini['RSI'] > kemarin['RSI'] else "📉 Menurun"
        
        pesan = (
            f"🌐 **OUTLOOK PASAR (IHSG)**\n"
            f"Posisi: {harga:,.0f} | Tren: {tren}\n\n"
            f"**Kondisi Indikator:**\n"
            f"• MACD: {status_macd}\n"
            f"• Stoch (10,5,5): {status_stoch}\n"
            f"• RSI (14): {status_rsi} ({hari_ini['RSI']:.1f})\n\n"
            f"*Sesuaikan jumlah beli Anda dengan arah tren pasar hari ini.*"
        )
        kirim_telegram(pesan)
    except Exception:
        pass

# ==========================================
# 5. SISTEM EVALUASI SINYAL LAMA
# ==========================================
def evaluasi_sinyal_lama():
    if not os.path.exists('riwayat_sinyal.csv'): return
    df_riwayat = pd.read_csv('riwayat_sinyal.csv')
    if df_riwayat.empty: return
    
    rekap = []
    sisa = []
    
    for _, row in df_riwayat.iterrows():
        kode = row['Kode']
        sl = float(row['SL'])
        tp1 = float(row['TP1'])
        
        try:
            df = yf.download(kode, period="5d", threads=False)
            df = df.dropna(how='all')
            if df.empty:
                sisa.append(row)
                continue
            
            tertinggi = float(df['High'].iloc[-1])
            terendah = float(df['Low'].iloc[-1])
            
            if terendah <= sl:
                kirim_telegram(f"❌ **STOP LOSS (SL)**\nSaham: {kode.replace('.JK','')}\nMenyentuh batas: Rp {sl:,.0f}.")
                row['Hasil'] = 'LOSS'
                rekap.append(row)
            elif tertinggi >= tp1:
                kirim_telegram(f"✅ **TAKE PROFIT (TP)**\nSaham: {kode.replace('.JK','')}\nMenyentuh target: Rp {tp1:,.0f}.")
                row['Hasil'] = 'WIN'
                rekap.append(row)
            else:
                sisa.append(row)
        except Exception:
            sisa.append(row)
        time.sleep(1)
        
    pd.DataFrame(sisa).to_csv('riwayat_sinyal.csv', index=False)
    
    if rekap:
        df_rekap = pd.DataFrame(rekap)
        if os.path.exists('rekap_bulanan.csv'):
            df_lama = pd.read_csv('rekap_bulanan.csv')
            pd.concat([df_lama, df_rekap]).to_csv('rekap_bulanan.csv', index=False)
        else:
            df_rekap.to_csv('rekap_bulanan.csv', index=False)

# ==========================================
# 6. REKAP WIN RATE BULANAN
# ==========================================
def cek_akhir_bulan():
    besok = datetime.now() + timedelta(days=1)
    hari_ini = datetime.now()
    
    if besok.month != hari_ini.month:
        if os.path.exists('rekap_bulanan.csv'):
            df = pd.read_csv('rekap_bulanan.csv')
            if not df.empty:
                total = len(df)
                win = len(df[df['Hasil'] == 'WIN'])
                loss = len(df[df['Hasil'] == 'LOSS'])
                win_rate = (win / total) * 100 if total > 0 else 0
                pesan = f"📊 **REKAP BULAN INI**\nTotal: {total} | ✅ Win: {win} | ❌ Loss: {loss}\n🏆 **Win Rate: {win_rate:.1f}%**"
                kirim_telegram(pesan)
            os.remove('rekap_bulanan.csv')

# ==========================================
# 7. MEMBACA DAFTAR SAHAM
# ==========================================
def dapatkan_seluruh_saham_idx():
    try:
        data = pd.read_csv('saham.csv')
        daftar_kode = data['Code'].tolist()
        return list(set([f"{str(kode).strip()}.JK" for kode in daftar_kode if pd.notna(kode)]))
    except Exception:
        return ["BBCA.JK"] 

# ==========================================
# 8. LOGIKA STRATEGI SAHAM
# ==========================================
def proses_saham(kode_saham, df):
    try:
        if len(df) < 60: return
        
        df = hitung_indikator(df)
        hari_ini = df.iloc[-1]
        kemarin = df.iloc[-2]
        
        harga = hari_ini['Close']
        if harga < 50: return 
        rata_rata_turnover = hari_ini['Avg_Turnover_20D']
        if rata_rata_turnover < 5_000_000_000: return 

        volume, vol_ma = hari_ini['Volume'], hari_ini['Vol_MA20']
        ema20, ema50 = hari_ini['EMA20'], hari_ini['EMA50']
        bb_upper, bb_lower = hari_ini['BB_Upper'], hari_ini['BB_Lower']
        macd_hist = hari_ini['MACD_Hist']
        obv, obv_ema = hari_ini['OBV'], hari_ini['OBV_EMA20']
        mfi = hari_ini['MFI']
        
        sinyal = None
        alasan = ""
        sl = tp1 = tp2 = 0

        # Strategi 1: Breakout
        tertinggi_20h = df['High'].iloc[-21:-1].max()
        if (harga > tertinggi_20h) and (volume > vol_ma * 1.5) and (harga > ema20):
            if (macd_hist > 0) and (obv > obv_ema):
                sinyal = "🚀 BREAKOUT"
                alasan = "Tembus resisten didukung volume kuat."
                sl = df['Low'].iloc[-3:].min() * 0.98 
                jarak_sl = harga - sl
                tp1 = harga + (jarak_sl * 1.5) 
                tp2 = harga + (jarak_sl * 2.5) 

        # Strategi 2: Buy on Weakness
        elif (harga > ema50) and (harga <= bb_lower * 1.02):
            if (mfi < 30) and (macd_hist > kemarin['MACD_Hist']):
                sinyal = "📉 BUY ON WEAKNESS"
                alasan = "Sentuh batas bawah dengan tekanan jual jenuh."
                sl = bb_lower * 0.98 
                tp1 = ema20 
                tp2 = ema50 

        # Strategi 3: Bullish Divergence
        elif (harga < ema20):
            low_baru, low_lama = df['Low'].iloc[-5:].min(), df['Low'].iloc[-15:-5].min()
            rsi_baru, rsi_lama = df['RSI'].iloc[-5:].min(), df['RSI'].iloc[-15:-5].min()
            macd_baru, macd_lama = df['MACD_Hist'].iloc[-5:].min(), df['MACD_Hist'].iloc[-15:-5].min()
            
            if (low_baru < low_lama) and ((rsi_baru > rsi_lama + 5) and (macd_baru > macd_lama)) and (hari_ini['Close'] > hari_ini['Open']):
                sinyal = "👀 BULLISH DIVERGENCE"
                alasan = "Harga turun, tetapi momentum naik."
                sl = low_baru * 0.98 
                tp1 = ema20
                tp2 = bb_upper

        # Strategi 4: Reversal
        elif (harga < ema50):
            if ((harga > hari_ini['Open']) and (harga > kemarin['High'])) and (mfi < 40) and ((obv > kemarin['OBV']) and (volume > vol_ma)):
                sinyal = "🔥 CONFIRM REVERSAL"
                alasan = "Lilin pembalikan didukung arus uang masuk."
                sl = hari_ini['Low'] * 0.98 
                jarak_sl = harga - sl
                tp1 = harga + (jarak_sl * 1.5)
                tp2 = harga + (jarak_sl * 2.5)

        if sinyal:
            # PEMBATASAN RISIKO (Maksimal Kerugian 8%)
            batas_sl_maks = harga * 0.92
            if sl < batas_sl_maks:
                sl = batas_sl_maks
                jarak_sl_baru = harga - sl
                tp1 = harga + (jarak_sl_baru * 1.5)
                tp2 = harga + (jarak_sl_baru * 2.5)

            pct_sl = ((harga - sl) / harga) * 100
            pct_tp1 = ((tp1 - harga) / harga) * 100
            pct_tp2 = ((tp2 - harga) / harga) * 100
            
            emiten = kode_saham.replace('.JK', '')
            
            # Status Indikator untuk Saham
            stat_macd = cek_status_cross(hari_ini['MACD'], hari_ini['Signal_Line'], kemarin['MACD'], kemarin['Signal_Line'])
            stat_stoch = cek_status_cross(hari_ini['%K'], hari_ini['%D'], kemarin['%K'], kemarin['%D'])
            stat_rsi = "📈 Menanjak Naik" if hari_ini['RSI'] > kemarin['RSI'] else "📉 Menurun"
            
            pesan = (
                f"🚨 **{sinyal}** | **{emiten}**\n"
                f"{alasan}\n\n"
                f"📋 **TRADING PLAN**\n"
                f"• Entry: Rp {harga:,.0f}\n"
                f"• SL: Rp {sl:,.0f} (-{pct_sl:.1f}%)\n"
                f"• TP 1: Rp {tp1:,.0f} (+{pct_tp1:.1f}%)\n"
                f"• TP 2: Rp {tp2:,.0f} (+{pct_tp2:.1f}%)\n\n"
                f"📊 **STATUS INDIKATOR**\n"
                f"• MACD: {stat_macd}\n"
                f"• Stoch (10,5,5): {stat_stoch}\n"
                f"• RSI (14): {stat_rsi} ({hari_ini['RSI']:.1f})\n\n"
                f"📰 **LINK:** [G-News](https://www.google.com/search?tbm=nws&q=saham+{emiten}) | [Stockbit](https://stockbit.com/symbol/{emiten})"
            )
            kirim_telegram(pesan)
            
            baru = pd.DataFrame([{'Tanggal': datetime.now().strftime("%Y-%m-%d"), 'Kode': kode_saham, 'Entry': harga, 'SL': sl, 'TP1': tp1}])
            if os.path.exists('riwayat_sinyal.csv'):
                pd.concat([pd.read_csv('riwayat_sinyal.csv'), baru]).to_csv('riwayat_sinyal.csv', index=False)
            else:
                baru.to_csv('riwayat_sinyal.csv', index=False)
                
    except Exception:
        pass 

# ==========================================
# 9. EKSEKUSI UTAMA
# ==========================================
if __name__ == "__main__":
    evaluasi_sinyal_lama()
    cek_akhir_bulan()
    
    kirim_outlook_ihsg()
    
    daftar_pantauan = dapatkan_seluruh_saham_idx()
    for i in range(0, len(daftar_pantauan), 100):
        paket = daftar_pantauan[i:i+100]
        data_massal = yf.download(paket, period="6mo", group_by='ticker', threads=True)
        for kode in paket:
            try:
                df_saham = data_massal.copy() if len(paket) == 1 else data_massal[kode].copy()
                df_saham = df_saham.dropna(how='all')
                if not df_saham.empty:
                    proses_saham(kode, df_saham)
            except Exception:
                continue
        time.sleep(3)
