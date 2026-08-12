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
# 2. MESIN INDIKATOR & EMA
# ==========================================
def cek_status_cross(garis_cepat_skrg, garis_lambat_skrg, garis_cepat_kmrn, garis_lambat_kmrn):
    if garis_cepat_kmrn <= garis_lambat_kmrn and garis_cepat_skrg > garis_lambat_skrg:
        return "🔥 Golden Cross"
    elif garis_cepat_kmrn >= garis_lambat_kmrn and garis_cepat_skrg < garis_lambat_skrg:
        return "🩸 Death Cross"
    elif garis_cepat_skrg > garis_cepat_kmrn:
        return "📈 Meningkat"
    else:
        return "📉 Menurun"

def cek_pantulan_ema(c, h, l, c_prev, e20, e50, e200):
    for nama, ema in [("EMA 200", e200), ("EMA 50", e50), ("EMA 20", e20)]:
        if pd.isna(ema): continue
        if c_prev < ema and c > ema:
            return f"Harga melesat menembus ke atas {nama}."
        elif c_prev > ema and c < ema:
            return f"Harga anjlok menembus ke bawah {nama} (Tren patah)."
        elif l <= ema and c > ema:
            return f"Harga sempat turun namun berhasil memantul kuat di area support {nama}."
        elif h >= ema and c < ema:
            return f"Harga sempat naik namun tertolak turun oleh atap resisten {nama}."
    return ""

def hitung_indikator(df):
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['STD20'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['SMA20'] + (df['STD20'] * 2)
    df['BB_Lower'] = df['SMA20'] - (df['STD20'] * 2)
    df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()
    df['Turnover'] = df['Close'] * df['Volume']
    df['Avg_Turnover_20D'] = df['Turnover'].rolling(window=20).mean()
    
    df['TR'] = np.maximum(df['High'] - df['Low'], 
               np.maximum(abs(df['High'] - df['Close'].shift(1)), 
                          abs(df['Low'] - df['Close'].shift(1))))
    df['ATR'] = df['TR'].rolling(window=14).mean()
    df['Support_20'] = df['Low'].rolling(window=20).min()
    df['Resisten_20'] = df['High'].rolling(window=20).max()
    
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
    
    low_10 = df['Low'].rolling(window=10).min()
    high_10 = df['High'].rolling(window=10).max()
    df['%K_Raw'] = 100 * ((df['Close'] - low_10) / (high_10 - low_10))
    df['%K'] = df['%K_Raw'].rolling(window=5).mean()
    df['%D'] = df['%K'].rolling(window=5).mean()
    
    vol_aman = df['Volume'].replace(0, 1) 
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    raw_money_flow = typical_price * vol_aman
    delta_tp = typical_price.diff()
    
    uang_masuk = raw_money_flow.where(delta_tp > 0, 0).rolling(window=14).sum()
    uang_keluar = raw_money_flow.where(delta_tp < 0, 0).rolling(window=14).sum()
    uang_keluar = uang_keluar.replace(0, 1) 
    
    mfr = uang_masuk / uang_keluar
    df['MFI'] = 100 - (100 / (1 + mfr))
    
    arah_harga = np.sign(df['Close'].diff())
    df['OBV'] = (arah_harga * vol_aman).fillna(0).cumsum()
    df['OBV_EMA20'] = df['OBV'].ewm(span=20, adjust=False).mean()
    
    return df

# ==========================================
# 3. MANAJEMEN RIWAYAT & SPAM FILTER
# ==========================================
def dapatkan_riwayat_aktif():
    aktif = {}
    if os.path.exists('riwayat_sinyal.csv'):
        df = pd.read_csv('riwayat_sinyal.csv')
        for col in ['Strategi', 'TP2', 'Pernah_Warning', 'Status_TP']:
            if col not in df.columns:
                if col == 'TP2': df[col] = df['TP1'] * 1.05
                elif col == 'Status_TP': df[col] = ""
                elif col == 'Pernah_Warning': df[col] = False
                else: df[col] = ""
                
        df['Tanggal_DT'] = pd.to_datetime(df['Tanggal'], errors='coerce')
        batas_30 = datetime.now() - timedelta(days=30)
        df_aktif = df[df['Tanggal_DT'] >= batas_30]
        
        for _, row in df_aktif.iterrows():
            aktif[row['Kode']] = {
                'Strategi': row['Strategi'],
                'SL': row['SL'],
                'TP1': row['TP1'],
                'TP2': row['TP2'],
                'Pernah_Warning': row['Pernah_Warning'],
                'Status_TP': row['Status_TP']
            }
    return aktif

def set_pernah_warning(kode):
    if os.path.exists('riwayat_sinyal.csv'):
        df = pd.read_csv('riwayat_sinyal.csv')
        mask = df['Kode'] == kode
        df.loc[mask, 'Pernah_Warning'] = True
        df.to_csv('riwayat_sinyal.csv', index=False)

def evaluasi_sinyal_lama():
    if not os.path.exists('riwayat_sinyal.csv'): return
    df = pd.read_csv('riwayat_sinyal.csv')
    if df.empty: return
    
    for col in ['Strategi', 'TP2', 'Pernah_Warning', 'Status_TP']:
        if col not in df.columns:
            if col == 'TP2': df[col] = df['TP1'] * 1.05
            elif col == 'Status_TP': df[col] = ""
            elif col == 'Pernah_Warning': df[col] = False
            else: df[col] = ""
            
    rekap, sisa = [], []
    for _, row in df.iterrows():
        kode = row['Kode']
        sl, tp1, tp2 = float(row['SL']), float(row['TP1']), float(row['TP2'])
        status_tp = str(row['Status_TP'])
        
        try:
            hist = yf.download(kode, period="5d", threads=False)
            hist = hist.dropna(how='all')
            if hist.empty:
                sisa.append(row)
                continue
            
            tertinggi, terendah = float(hist['High'].iloc[-1]), float(hist['Low'].iloc[-1])
            emiten = kode.replace('.JK','')
            
            if terendah <= sl:
                kirim_telegram(f"❌ **STOP LOSS (SL)** | **{emiten}**\nMenyentuh batas grafik aktual: Rp {sl:,.0f}. Siklus pantau selesai.")
                row['Hasil'] = 'LOSS'
                rekap.append(row)
            elif tertinggi >= tp2:
                kirim_telegram(f"🚀 **TAKE PROFIT 2 (TP 2)** | **{emiten}**\nTarget maksimal tercapai: Rp {tp2:,.0f}. Siklus pantau selesai dengan sukses!")
                row['Hasil'] = 'WIN'
                rekap.append(row)
            elif tertinggi >= tp1 and status_tp != 'TP1':
                kirim_telegram(f"✅ **TAKE PROFIT 1 (TP 1)** | **{emiten}**\nTarget pertama tercapai: Rp {tp1:,.0f}. Sisa porsi ditahan menuju TP 2 (Rp {tp2:,.0f}).")
                row['Status_TP'] = 'TP1'
                sisa.append(row)
            else:
                sisa.append(row)
        except Exception:
            sisa.append(row)
        time.sleep(1)
        
    pd.DataFrame(sisa).to_csv('riwayat_sinyal.csv', index=False)
    
    if rekap:
        df_rekap = pd.DataFrame(rekap)
        if os.path.exists('rekap_bulanan.csv'):
            pd.concat([pd.read_csv('rekap_bulanan.csv'), df_rekap]).to_csv('rekap_bulanan.csv', index=False)
        else:
            df_rekap.to_csv('rekap_bulanan.csv', index=False)

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
                kirim_telegram(f"📊 **REKAP BULAN INI**\nTotal: {total} | ✅ Win: {win} | ❌ Loss: {loss}\n🏆 **Win Rate: {win_rate:.1f}%**")
            os.remove('rekap_bulanan.csv')

# ==========================================
# 4. OUTLOOK IHSG HARIAN
# ==========================================
def kirim_outlook_ihsg():
    try:
        ihsg = yf.Ticker("^JKSE")
        df = ihsg.history(period="1y") 
        if df.empty or len(df) < 200: return
        df = hitung_indikator(df)
        hari_ini, kemarin, lusa = df.iloc[-1], df.iloc[-2], df.iloc[-3]
        
        harga = hari_ini['Close']
        ema20 = hari_ini['EMA20']
        tren = "🟢 BULLISH" if harga > ema20 else "🔴 BEARISH"
        
        poin = harga - kemarin['Close']
        pct = (poin / kemarin['Close']) * 100
        simbol = "+" if poin > 0 else ""
        
        poin_str = f"{poin:.2f}".replace('.', ',')
        pct_str = f"{pct:.2f}".replace('.', ',')
        
        analisis_harga = ""
        if hari_ini['Close'] > hari_ini['Open'] and kemarin['Close'] < kemarin['Open'] and hari_ini['Close'] > kemarin['Open'] and hari_ini['Low'] < kemarin['Low']:
             analisis_harga = "🔥 **Pola Bullish Engulfing**. Daya beli menelan tekanan jual kemarin, potensi kuat pembalikan tren naik."
        elif hari_ini['Close'] < hari_ini['Open'] and kemarin['Close'] > kemarin['Open'] and hari_ini['Close'] < kemarin['Open'] and hari_ini['High'] > kemarin['High']:
             analisis_harga = "🩸 **Pola Bearish Engulfing**. Tekanan jual menelan daya beli kemarin, potensi berbalik turun."
        elif hari_ini['Close'] > kemarin['High']:
            analisis_harga = "🚀 **Struktur Kuat**. Ditutup di atas nilai tertinggi kemarin. Momentum naik masih berlanjut."
        elif hari_ini['Close'] < kemarin['Low']:
            analisis_harga = "⚠️ **Struktur Lemah**. Ditutup di bawah nilai terendah kemarin. Tekanan jual masih berlanjut."
        elif (hari_ini['High'] <= kemarin['High']) and (hari_ini['Low'] >= kemarin['Low']):
            analisis_harga = "⚖️ **Fase Konsolidasi (Inside Bar)**. Pasar sedang ragu-ragu menentukan arah (sideways)."
        else:
            if harga > kemarin['Close'] and kemarin['Close'] > lusa['Close']:
                analisis_harga = "📈 **Tren Terjaga**. Menguat 3 hari berturut-turut. Momentum aman."
            elif harga < kemarin['Close'] and kemarin['Close'] < lusa['Close']:
                analisis_harga = "📉 **Tren Menurun**. Melemah 3 hari berturut-turut."
            else:
                analisis_harga = "🟢 **Mencoba Bangkit**." if harga > kemarin['Close'] else "🔴 **Koreksi Wajar**."
        
        pesan_ema = cek_pantulan_ema(harga, hari_ini['High'], hari_ini['Low'], kemarin['Close'], hari_ini['EMA20'], hari_ini['EMA50'], hari_ini['EMA200'])
        if pesan_ema: analisis_harga += f" {pesan_ema}"

        status_macd = cek_status_cross(hari_ini['MACD'], hari_ini['Signal_Line'], kemarin['MACD'], kemarin['Signal_Line'])
        status_stoch = cek_status_cross(hari_ini['%K'], hari_ini['%D'], kemarin['%K'], kemarin['%D'])
        status_rsi = "📈 Meningkat" if hari_ini['RSI'] > kemarin['RSI'] else "📉 Menurun"
        status_mfi = "📈 Meningkat" if hari_ini['MFI'] > kemarin['MFI'] else "📉 Menurun"
        
        pesan = (
            f"🌐 **OUTLOOK PASAR (IHSG)**\n"
            f"Posisi: {harga:,.0f} ({simbol}{poin_str} poin / {simbol}{pct_str}%)\n"
            f"Tren Utama: {tren}\n\n"
            f"🕯️ **Aksi Harga (Price Action):**\n"
            f"{analisis_harga}\n\n"
            f"**Kondisi Indikator:**\n"
            f"• MACD: {status_macd}\n"
            f"• Stoch (10,5,5): {status_stoch}\n"
            f"• RSI (14): {status_rsi} ({hari_ini['RSI']:.1f})\n"
            f"• MFI (14): {status_mfi} ({hari_ini['MFI']:.1f})\n\n"
            f"*Sesuaikan porsi trading Anda dengan kondisi pasar hari ini.*"
        )
        kirim_telegram(pesan)
    except Exception:
        pass

# ==========================================
# 5. LOGIKA STRATEGI SAHAM
# ==========================================
def dapatkan_seluruh_saham_idx():
    try:
        data = pd.read_csv('saham.csv')
        daftar_kode = data['Code'].tolist()
        return list(set([f"{str(kode).strip()}.JK" for kode in daftar_kode if pd.notna(kode)]))
    except Exception:
        return ["BBCA.JK"] 

def proses_saham(kode_saham, df, dict_aktif, is_sesi_final):
    try:
        if len(df) < 200: return
        df = hitung_indikator(df)
        hari_ini, kemarin, lusa = df.iloc[-1], df.iloc[-2], df.iloc[-3]
        harga = hari_ini['Close']
        if harga < 50: return 
        rata_rata_turnover = hari_ini['Avg_Turnover_20D']
        if rata_rata_turnover < 5_000_000_000: return 

        volume, vol_ma = hari_ini['Volume'], hari_ini['Vol_MA20']
        ema20, ema50, ema200 = hari_ini['EMA20'], hari_ini['EMA50'], hari_ini['EMA200']
        bb_lower = hari_ini['BB_Lower']
        macd_hist = hari_ini['MACD_Hist']
        obv, obv_ema = hari_ini['OBV'], hari_ini['OBV_EMA20']
        mfi, atr, support, resisten = hari_ini['MFI'], hari_ini['ATR'], hari_ini['Support_20'], hari_ini['Resisten_20']
        emiten = kode_saham.replace('.JK', '')
        
        apakah_aktif = kode_saham in dict_aktif
        
        # ----------------------------------------------------
        # CEK PERINGATAN DARURAT (KATALIS MASIF NEGATIF)
        # ----------------------------------------------------
        cross_down_ema200 = (harga < ema200) and (kemarin['Close'] >= kemarin['EMA200'])
        cross_down_ema50 = (harga < ema50) and (kemarin['Close'] >= kemarin['EMA50'])
        distribusi_masif = (volume > vol_ma * 2.5) and (harga < hari_ini['Open'])
        anjlok = (harga <= kemarin['Close'] * 0.93)
        masif_negatif = cross_down_ema200 or cross_down_ema50 or distribusi_masif or anjlok
        
        if apakah_aktif:
            rek = dict_aktif[kode_saham]
            if masif_negatif and not rek['Pernah_Warning']:
                alasan_negatif = []
                if cross_down_ema200: alasan_negatif.append("Menembus ke bawah garis hidup EMA 200 (Tren Utama Patah)")
                elif cross_down_ema50: alasan_negatif.append("Menembus ke bawah EMA 50 (Tren Menengah Patah)")
                if distribusi_masif: alasan_negatif.append("Lonjakan volume jual > 250% (Distribusi Masif)")
                if anjlok: alasan_negatif.append(f"Harga anjlok tajam ({(harga-kemarin['Close'])/kemarin['Close']*100:.1f}%)")
                
                kirim_telegram(f"⚠️ **PERINGATAN DARURAT** | **{emiten}**\nPergerakan negatif masif:\n• {', '.join(alasan_negatif)}\n\nPerhatikan ketat area SL Anda.")
                set_pernah_warning(kode_saham)
                return 

        # ----------------------------------------------------
        # LOGIKA BELI (BUY STRATEGIES)
        # ----------------------------------------------------
        sinyal, alasan, sl, tp1, tp2 = None, "", 0, 0, 0
        
        tertinggi_20h = df['High'].iloc[-21:-1].max()
        if (harga > tertinggi_20h) and (volume > vol_ma * 1.5) and (harga > ema20):
            if (macd_hist > 0) and (obv > obv_ema):
                sinyal, alasan = "🚀 BREAKOUT", "Tembus resisten didukung volume kuat."
                sl, tp1, tp2 = kemarin['Low'] - (0.5 * atr), harga + (1.5 * atr), harga + (3.0 * atr)

        elif (harga > ema50) and (harga <= bb_lower * 1.02):
            if (mfi < 30) and (macd_hist > kemarin['MACD_Hist']):
                sinyal, alasan = "📉 BUY ON WEAKNESS", "Sentuh batas bawah dengan tekanan jual jenuh."
                sl, tp1, tp2 = support - (0.5 * atr), ema20, resisten                    

        elif (harga < ema20):
            low_baru, low_lama = df['Low'].iloc[-5:].min(), df['Low'].iloc[-15:-5].min()
            rsi_baru, rsi_lama = df['RSI'].iloc[-5:].min(), df['RSI'].iloc[-15:-5].min()
            macd_baru, macd_lama = df['MACD_Hist'].iloc[-5:].min(), df['MACD_Hist'].iloc[-15:-5].min()
            if (low_baru < low_lama) and ((rsi_baru > rsi_lama + 5) and (macd_baru > macd_lama)) and (hari_ini['Close'] > hari_ini['Open']):
                sinyal, alasan = "👀 BULLISH DIVERGENCE", "Harga turun, tetapi momentum naik."
                sl, tp1, tp2 = low_baru - (0.5 * atr), ema20, resisten

        elif (harga < ema50):
            if ((harga > hari_ini['Open']) and (harga > kemarin['High'])) and (mfi < 40) and ((obv > kemarin['OBV']) and (volume > vol_ma)):
                sinyal, alasan = "🔥 CONFIRM REVERSAL", "Lilin pembalikan didukung arus uang masuk."
                sl, tp1, tp2 = hari_ini['Low'] - (0.5 * atr), (ema20 if ema20 > harga else harga + (1.5 * atr)), (resisten if resisten > tp1 else harga + (3.0 * atr))

        # ----------------------------------------------------
        # CEK BLOKIR SPAM & KATALIS MASIF POSITIF
        # ----------------------------------------------------
        cross_up_ema200 = (harga > ema200) and (kemarin['Close'] <= kemarin['EMA200'])
        cross_up_ema50 = (harga > ema50) and (kemarin['Close'] <= kemarin['EMA50'])
        akumulasi_masif = (volume > vol_ma * 2.5) and (harga > hari_ini['Open'])
        terbang = (harga >= kemarin['Close'] * 1.07)
        masif_positif = cross_up_ema200 or cross_up_ema50 or akumulasi_masif or terbang

        if apakah_aktif:
            rek = dict_aktif[kode_saham]
            
            if masif_positif and not sinyal:
                sinyal = "🌟 KATALIS POSITIF MASIF"
                alasan = "Terdeteksi dorongan beli luar biasa di luar pola normal."
                sl, tp1, tp2 = rek['SL'], rek['TP1'], rek['TP2']

            if not is_sesi_final:
                if not masif_positif and (not sinyal or sinyal == rek['Strategi']):
                    return 
            else:
                if not masif_positif and (not sinyal or sinyal == rek['Strategi']):
                    return 
        else:
            if not is_sesi_final: return 
            if not sinyal: return
            
        # ----------------------------------------------------
        # FORMATTING PESAN
        # ----------------------------------------------------
        analisis_harga = ""
        if hari_ini['Close'] > hari_ini['Open'] and kemarin['Close'] < kemarin['Open'] and hari_ini['Close'] > kemarin['Open'] and hari_ini['Low'] < kemarin['Low']:
             analisis_harga = "Bullish Engulfing. Daya beli menelan tekanan jual kemarin."
        elif hari_ini['Close'] < hari_ini['Open'] and kemarin['Close'] > kemarin['Open'] and hari_ini['Close'] < kemarin['Open'] and hari_ini['High'] > kemarin['High']:
             analisis_harga = "Bearish Engulfing. (Hati-hati, tekanan jual tiba-tiba membesar)."
        elif hari_ini['Close'] > kemarin['High']:
            analisis_harga = "Struktur Breakout. Ditutup lebih tinggi dari nilai tertinggi kemarin."
        elif hari_ini['Close'] < kemarin['Low']:
            analisis_harga = "Struktur Breakdown. (Hati-hati, ditutup lebih rendah dari support kemarin)."
        elif (hari_ini['High'] <= kemarin['High']) and (hari_ini['Low'] >= kemarin['Low']):
            analisis_harga = "Inside Bar. Terjadi penyempitan rentang (konsolidasi)."
        else:
            if harga > kemarin['Close'] and kemarin['Close'] > lusa['Close']:
                analisis_harga = "Menguat 3 hari beruntun."
            elif harga < kemarin['Close'] and kemarin['Close'] < lusa['Close']:
                analisis_harga = "Melemah 3 hari beruntun."
            else:
                poin = harga - kemarin['Close']
                analisis_harga = f"Memantul naik (+{poin:,.0f} IDR)." if harga > kemarin['Close'] else f"Koreksi wajar ({poin:,.0f} IDR)."

        pesan_ema = cek_pantulan_ema(harga, hari_ini['High'], hari_ini['Low'], kemarin['Close'], ema20, ema50, ema200)
        if pesan_ema: analisis_harga += f" {pesan_ema}"

        turnover_miliar = rata_rata_turnover / 1_000_000_000
        obv_trend = "Naik (Akumulasi)" if obv > obv_ema else "Turun (Distribusi)"
        stat_macd = cek_status_cross(hari_ini['MACD'], hari_ini['Signal_Line'], kemarin['MACD'], kemarin['Signal_Line'])
        stat_stoch = cek_status_cross(hari_ini['%K'], hari_ini['%D'], kemarin['%K'], kemarin['%D'])
        stat_rsi = "📈 Meningkat" if hari_ini['RSI'] > kemarin['RSI'] else "📉 Menurun"
        stat_mfi = "📈 Meningkat" if hari_ini['MFI'] > kemarin['MFI'] else "📉 Menurun"
        
        pesan = (
            f"🚨 **{sinyal}** | **{emiten}**\n"
            f"{alasan}\n\n"
            f"🕯️ **AKSI HARGA (PRICE ACTION):**\n"
            f"• {analisis_harga}\n\n"
            f"📋 **TRADING PLAN**\n"
            f"• Entry: Rp {harga:,.0f}\n"
            f"• SL: Rp {sl:,.0f} (-{((harga - sl) / harga) * 100:.1f}%)\n"
            f"• TP 1: Rp {tp1:,.0f} (+{((tp1 - harga) / harga) * 100:.1f}%)\n"
            f"• TP 2: Rp {tp2:,.0f} (+{((tp2 - harga) / harga) * 100:.1f}%)\n\n"
            f"📊 **STATUS INDIKATOR**\n"
            f"• Likuiditas: Rp {turnover_miliar:.1f} M/hari\n"
            f"• OBV Trend: {obv_trend}\n"
            f"• MACD: {stat_macd}\n"
            f"• Stoch (10,5,5): {stat_stoch}\n"
            f"• RSI (14): {stat_rsi} ({hari_ini['RSI']:.1f})\n"
            f"• MFI (14): {stat_mfi} ({mfi:.1f})\n\n"
            f"📰 **LINK:** [G-News](https://www.google.com/search?tbm=nws&q=saham+{emiten}) | [Stockbit](https://stockbit.com/symbol/{emiten})"
        )
        kirim_telegram(pesan)
        
        baru = pd.DataFrame([{
            'Tanggal': datetime.now().strftime("%Y-%m-%d"), 
            'Kode': kode_saham, 
            'Strategi': sinyal,
            'Entry': harga, 
            'SL': sl, 
            'TP1': tp1,
            'TP2': tp2,
            'Pernah_Warning': False,
            'Status_TP': ""
        }])
        if os.path.exists('riwayat_sinyal.csv'):
            pd.concat([pd.read_csv('riwayat_sinyal.csv'), baru]).to_csv('riwayat_sinyal.csv', index=False)
        else:
            baru.to_csv('riwayat_sinyal.csv', index=False)
            
    except Exception:
        pass 

# ==========================================
# 6. EKSEKUSI UTAMA (SISTEM PEMBAGIAN WAKTU)
# ==========================================
if __name__ == "__main__":
    waktu_utc = datetime.utcnow()
    is_sesi_final = True 
    
    dict_aktif = dapatkan_riwayat_aktif()
    evaluasi_sinyal_lama()
    
    if is_sesi_final:
        cek_akhir_bulan()
        kirim_outlook_ihsg()
        daftar_pantauan = dapatkan_seluruh_saham_idx() 
    else:
        daftar_pantauan = list(dict_aktif.keys()) 
    
    if daftar_pantauan:
        for i in range(0, len(daftar_pantauan), 100):
            paket = daftar_pantauan[i:i+100]
            data_massal = yf.download(paket, period="1y", group_by='ticker', threads=True)
            for kode in paket:
                try:
                    df_saham = data_massal.copy() if len(paket) == 1 else data_massal[kode].copy()
                    df_saham = df_saham.dropna(how='all')
                    if not df_saham.empty:
                        proses_saham(kode, df_saham, dict_aktif, is_sesi_final)
                except Exception:
                    continue
            time.sleep(3)
