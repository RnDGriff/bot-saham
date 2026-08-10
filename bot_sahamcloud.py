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
# 2. SISTEM EVALUASI SINYAL (TP / SL TERCAPAI)
# ==========================================
def evaluasi_sinyal_lama():
    if not os.path.exists('riwayat_sinyal.csv'): return
    
    df_riwayat = pd.read_csv('riwayat_sinyal.csv')
    if df_riwayat.empty: return
    
    rekap = []
    sisa = []
    
    print("Mengevaluasi sinyal aktif hari sebelumnya...")
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
                kirim_telegram(f"❌ **STOP LOSS (SL) TERSENTUH**\nSaham: {kode.replace('.JK','')}\nMenyentuh batas risiko struktur: Rp {sl:,.0f}.")
                row['Hasil'] = 'LOSS'
                rekap.append(row)
            elif tertinggi >= tp1:
                kirim_telegram(f"✅ **TAKE PROFIT (TP) TERCAPAI**\nSaham: {kode.replace('.JK','')}\nBerhasil menyentuh target grafik: Rp {tp1:,.0f}.")
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
# 3. SISTEM REKAP WIN RATE AKHIR BULAN
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
                
                pesan = f"📊 **REKAP WIN RATE BULAN INI**\n\nTotal Sinyal Dieksekusi: {total}\n✅ Menang (Cetak TP): {win}\n❌ Kalah (Kena SL): {loss}\n\n🏆 **Tingkat Kemenangan: {win_rate:.1f}%**"
                kirim_telegram(pesan)
            
            os.remove('rekap_bulanan.csv')

# ==========================================
# 4. MEMBACA DAFTAR SAHAM DARI FILE LOKAL
# ==========================================
def dapatkan_seluruh_saham_idx():
    print("Memuat daftar saham dari file lokal saham.csv...")
    try:
        data = pd.read_csv('saham.csv')
        daftar_kode = data['Code'].tolist()
        daftar_bersih = [f"{str(kode).strip()}.JK" for kode in daftar_kode if pd.notna(kode)]
        print(f"✅ Berhasil memuat {len(daftar_bersih)} saham BEI.")
        return list(set(daftar_bersih))
    except Exception as e:
        print(f"❌ Gagal membaca file saham.csv: {e}")
        return ["BBCA.JK"] 

# ==========================================
# 5. MESIN INDIKATOR
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
    mfr = raw_money_flow.where(delta_tp > 0, 0).rolling(window=14).sum() / raw_money_flow.where(delta_tp < 0, 0).rolling(window=14).sum()
    df['MFI'] = 100 - (100 / (1 + mfr))
    
    arah_harga = np.sign(df['Close'].diff())
    df['OBV'] = (arah_harga * df['Volume']).fillna(0).cumsum()
    df['OBV_EMA20'] = df['OBV'].ewm(span=20, adjust=False).mean()
    return df

# ==========================================
# 6. LOGIKA STRATEGI (SL DAN TP DINAMIS)
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
        rsi, mfi = hari_ini['RSI'], hari_ini['MFI']
        ema20, ema50 = hari_ini['EMA20'], hari_ini['EMA50']
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
                sl = df['Low'].iloc[-3:].min() * 0.98 
                jarak_sl = harga - sl
                tp1 = harga + (jarak_sl * 1.5) 
                tp2 = harga + (jarak_sl * 2.5) 

        # STRATEGI 2: BUY ON WEAKNESS
        elif (harga > ema50) and (harga <= bb_lower * 1.02):
            if (mfi < 30) and (macd_hist > kemarin['MACD_Hist']):
                sinyal = "📉 BUY ON WEAKNESS"
                alasan = "Sentuh batas bawah Bollinger. Indikator uang keluar (MFI) sangat jenuh."
                sl = bb_lower * 0.98 
                tp1 = ema20 
                tp2 = ema50 

        # STRATEGI 3: BULLISH DIVERGENCE
        elif (harga < ema20):
            low_baru, low_lama = df['Low'].iloc[-5:].min(), df['Low'].iloc[-15:-5].min()
            rsi_baru, rsi_lama = df['RSI'].iloc[-5:].min(), df['RSI'].iloc[-15:-5].min()
            macd_baru, macd_lama = df['MACD_Hist'].iloc[-5:].min(), df['MACD_Hist'].iloc[-15:-5].min()
            
            if (low_baru < low_lama) and ((rsi_baru > rsi_lama + 5) and (macd_baru > macd_lama)) and (hari_ini['Close'] > hari_ini['Open']):
                sinyal = "👀 BULLISH DIVERGENCE"
                alasan = "Harga mencetak terendah baru, tetapi momentum RSI & MACD menanjak."
                sl = low_baru * 0.98 
                tp1 = ema20
                tp2 = bb_upper

        # STRATEGI 4: REVERSAL
        elif (harga < ema50):
            if ((harga > hari_ini['Open']) and (harga > kemarin['High'])) and (mfi < 40) and ((obv > kemarin['OBV']) and (volume > vol_ma)):
                sinyal = "🔥 CONFIRM REVERSAL"
                alasan = "Struktur candle kuat membalik tren, diiringi uang masuk (OBV naik)."
                sl = hari_ini['Low'] * 0.98 
                jarak_sl = harga - sl
                tp1 = harga + (jarak_sl * 1.5)
                tp2 = harga + (jarak_sl * 2.5)

        if sinyal:
            pct_sl = ((harga - sl) / harga) * 100
            pct_tp1 = ((tp1 - harga) / harga) * 100
            pct_tp2 = ((tp2 - harga) / harga) * 100
            
            emiten = kode_saham.replace('.JK', '')
            turnover_miliar = rata_rata_turnover / 1_000_000_000
            
            pesan = (
                f"🚨 **{sinyal}** | **{emiten}**\n\n"
                f"**Info:** {alasan}\n\n"
                f"📋 **TRADING PLAN DINAMIS (GRAFIK)**\n"
                f"• Entry: Rp {harga:,.0f}\n"
                f"• SL: Rp {sl:,.0f} (-{pct_sl:.1f}%)\n"
                f"• TP 1: Rp {tp1:,.0f} (+{pct_tp1:.1f}%)\n"
                f"• TP 2: Rp {tp2:,.0f} (+{pct_tp2:.1f}%)\n\n"
                f"📊 **SMART MONEY**\n"
                f"• Likuiditas: Rp {turnover_miliar:.1f} M/hari\n"
                f"• OBV Trend: {'Naik (Akumulasi)' if obv > obv_ema else 'Turun'}\n"
                f"• MFI: {mfi:.1f} | RSI: {rsi:.1f}\n\n"
                f"📰 **CEK BERITA & SENTIMEN:**\n"
                f"• [Google News](https://www.google.com/search?tbm=nws&q=saham+{emiten})\n"
                f"• [Stockbit Stream](https://stockbit.com/symbol/{emiten})"
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
# 7. EKSEKUSI UTAMA
# ==========================================
if __name__ == "__main__":
    print("Sistem Dimulai.")
    
    evaluasi_sinyal_lama()
    cek_akhir_bulan()
    
    daftar_pantauan = dapatkan_seluruh_saham_idx()
    total = len(daftar_pantauan)
    print(f"Mulai menyaring {total} saham...")
    
    for i in range(0, total, 100):
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
        
    print("Selesai.")
