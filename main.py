"""
BIST100 Çoklu Periyot Telegram Sinyal Botu v3
==============================================
• BIST 100 hisseleri
• 3 periyot: 1 Saatlik · 4 Saatlik · Günlük
• Her periyot: TOP 5 AL + TOP 5 SAT
• SÜPER AL: En az 2 periyotta AL + Ort.Skor >= 90 → TOP 3
• SÜPER SAT: En az 2 periyotta SAT + Ort.Skor <= 25 → TOP 3
"""

import os, time, logging, schedule, datetime, warnings
warnings.filterwarnings("ignore")
import requests, pandas as pd, yfinance as yf

try:
    import ta
except ImportError:
    print("HATA: pip install ta"); exit(1)

# ── YAPILANDIRMA ──────────────────────────────────────────────────────────────
BOT_TOKEN  = os.environ.get("TELEGRAM_TOKEN",  "8100761185:AAF0bAFeCsjQ7H9gLSKuitcjA5Cv6G083g8")
CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID","6692644668")

SUPER_AL_SKOR    = 90
SUPER_SAT_SKOR   = 25
SUPER_MIN_PERIOD = 2
DAILY_SUMMARY    = "18:30"

PERIYOTLAR = [
    {"key": "1h", "ad": "1 Saatlik", "interval": "1h", "period": "7d",   "emoji": "⏱"},
    {"key": "4h", "ad": "4 Saatlik", "interval": "1h", "period": "30d",  "emoji": "🕓"},
    {"key": "1d", "ad": "Günlük",    "interval": "1d", "period": "180d", "emoji": "📅"},
]

BIST100 = list(dict.fromkeys([
    'THYAO','GARAN','AKBNK','EREGL','SISE','KCHOL','BIMAS','SAHOL','PGSUS','TUPRS',
    'FROTO','TOASO','ASELS','TCELL','EKGYO','ISCTR','HEKTS','MGROS','DOHOL','TAVHL',
    'ARCLK','ULKER','PETKM','CCOLA','ENKAI','KRDMD','VAKBN','SODA','TTKOM','AEFES',
    'OYAKC','ALARK','AKSEN','YKBNK','LOGO','MAVI','BERA','ENJSA','VESTL','CIMSA',
    'EGEEN','NETAS','KARSN','KONTR','IPEKE','ISGYO','GOLTS','GLYHO','KLNMA','AGHOL',
    'ANACM','BRSAN','BRYAT','BTCIM','DOAS','EUPWR','GESAN','GUBRF','HATEK','IMASM',
    'INDES','ISDMR','ISFIN','KAREL','KARTN','KERVT','KRSUS','MPARK','NTTUR','ODAS',
    'REEDR','RNPOL','RYSAS','SELEC','SKBNK','SOKM','TATGD','TKFEN','TKNSA','TMSN',
    'ALKIM','AYCES','BASGZ','BORSK','BUCIM','BURVA','CANTE','DERIM','DEVA','ECILC',
    'EDIP','EMKEL','ESCOM','FLAP','GSDHO','HLGYO','HTTBT','HUNER','IDGYO','VESTL',
]))

# ── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bist_telegram.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("BISTv3")

# ── ANALİZ (app.py ile birebir) ───────────────────────────────────────────────
def resample_4h(df):
    df = df.copy(); df.index = pd.to_datetime(df.index)
    return df.resample('4h').agg({
        'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'
    }).dropna()

def hesapla_indiktorler(df):
    if len(df) < 30: return None
    df = df.copy(); c,h,l,v = df['Close'],df['High'],df['Low'],df['Volume']
    df['RSI']       = ta.momentum.RSIIndicator(c, window=14).rsi()
    m               = ta.trend.MACD(c, window_slow=26, window_fast=12, window_sign=9)
    df['MACD']      = m.macd(); df['MACD_sig']=m.macd_signal(); df['MACD_hist']=m.macd_diff()
    bb              = ta.volatility.BollingerBands(c, window=20, window_dev=2)
    df['BB_upper']  = bb.bollinger_hband(); df['BB_lower']=bb.bollinger_lband(); df['BB_middle']=bb.bollinger_mavg()
    st              = ta.momentum.StochasticOscillator(h, l, c, window=14, smooth_window=3)
    df['STOCH_K']   = st.stoch(); df['STOCH_D']=st.stoch_signal()
    df['EMA20']     = ta.trend.EMAIndicator(c, window=20).ema_indicator()
    df['EMA50']     = ta.trend.EMAIndicator(c, window=50).ema_indicator()
    df['MFI']       = ta.volume.MFIIndicator(h, l, c, v, window=14).money_flow_index()
    return df

def skor_hesapla(row, close):
    skor=50; ind={}
    rsi=row.get('RSI')
    if pd.notna(rsi):
        ind['RSI']=round(float(rsi),1)
        if rsi<25:skor+=22
        elif rsi<35:skor+=14
        elif rsi<45:skor+=6
        elif rsi>75:skor-=22
        elif rsi>65:skor-=14
        elif rsi>55:skor-=6
    mh=row.get('MACD_hist'); mv=row.get('MACD')
    if pd.notna(mh):
        ind['MACD_yon']='↑' if mh>0 else '↓'
        if mh>0 and pd.notna(mv) and mv<0:skor+=18
        elif mh>0:skor+=10
        elif mh<0 and pd.notna(mv) and mv>0:skor-=18
        else:skor-=10
    bu=row.get('BB_upper'); bl=row.get('BB_lower'); bm=row.get('BB_middle')
    if pd.notna(bu) and pd.notna(bl) and close:
        bw=float(bu)-float(bl); bp=(close-float(bl))/bw if bw>0 else 0.5
        ind['BB_pct']=round(bp*100,1)
        if bp<0.10:skor+=20
        elif bp<0.25:skor+=12
        elif bp<0.35:skor+=5
        elif bp>0.90:skor-=20
        elif bp>0.75:skor-=12
        elif bp>0.65:skor-=5
    sk=row.get('STOCH_K')
    if pd.notna(sk):
        ind['Stoch_K']=round(float(sk),1)
        if sk<20:skor+=14
        elif sk<30:skor+=7
        elif sk>80:skor-=14
        elif sk>70:skor-=7
    e20=row.get('EMA20'); e50=row.get('EMA50')
    if pd.notna(e20) and pd.notna(e50) and close:
        v20,v50=float(e20),float(e50)
        if close>v20>v50: ind['EMA']='↑'; skor+=10
        elif close<v20<v50: ind['EMA']='↓'; skor-=10
        else: ind['EMA']='→'
    mfi=row.get('MFI')
    if pd.notna(mfi):
        ind['MFI']=round(float(mfi),1)
        if mfi<20:skor+=10
        elif mfi<30:skor+=5
        elif mfi>80:skor-=10
        elif mfi>70:skor-=5
    return max(0,min(100,round(skor))),ind

def skor_etiket(s):
    if s>=70: return 'GÜÇLÜ AL','🟢'
    if s>=55: return 'AL','🟩'
    if s>=40: return 'NÖTR','🟡'
    if s>=25: return 'SAT','🔴'
    return 'GÜÇLÜ SAT','⛔'

def analiz_et(ticker, pconf):
    try:
        df=yf.download(ticker+'.IS', interval=pconf['interval'], period=pconf['period'],
                       progress=False, auto_adjust=True)
        if df.empty or len(df)<30: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        if pconf['key']=='4h': df=resample_4h(df)
        df=hesapla_indiktorler(df)
        if df is None or len(df)<2: return None
        son=df.iloc[-1]; prev=df.iloc[-2]; close=float(son['Close'])
        skor,ind=skor_hesapla(son.to_dict(), close)
        return {
            'ticker': ticker, 'fiyat': close,
            'degisim': ((close-float(prev['Close']))/float(prev['Close']))*100,
            'skor': skor, 'ind': ind
        }
    except Exception as e:
        log.debug(f"{ticker}/{pconf['key']}: {e}"); return None

# ── TELEGRAM ──────────────────────────────────────────────────────────────────
def tg(mesaj):
    try:
        r=requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id":CHAT_ID,"text":mesaj,"parse_mode":"HTML","disable_web_page_preview":True},
            timeout=10)
        if r.status_code==200: return True
        log.error(f"TG {r.status_code}: {r.text}"); return False
    except Exception as e: log.error(f"TG hata: {e}"); return False

# ── HISSE SATIRI ──────────────────────────────────────────────────────────────
def hisse_satiri(r, sira):
    et,em=skor_etiket(r['skor']); ind=r['ind']
    deg=f"+{r['degisim']:.2f}%" if r['degisim']>=0 else f"{r['degisim']:.2f}%"
    detay=" | ".join(filter(None,[
        f"RSI:{ind['RSI']:.0f}" if 'RSI' in ind else "",
        f"MACD:{ind.get('MACD_yon','')}" if 'MACD_yon' in ind else "",
        f"EMA:{ind.get('EMA','')}" if 'EMA' in ind else "",
        f"MFI:{ind['MFI']:.0f}" if 'MFI' in ind else "",
    ]))
    return (
        f"{sira}. {em} <b>{r['ticker']}</b>  {r['fiyat']:.2f}₺  {deg}\n"
        f"    Skor: <b>{r['skor']}</b> ({et})  {detay}\n"
    )

# ── PERİYOT RAPORU — TOP5 AL + TOP5 SAT tek mesaj ────────────────────────────
def periyot_raporu(periyot, sonuclar):
    now=datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

    top5_al  = sorted([r for r in sonuclar if r['skor']>=55], key=lambda x:x['skor'], reverse=True)[:5]
    top5_sat = sorted([r for r in sonuclar if r['skor']<40],  key=lambda x:x['skor'])[:5]

    msg=(
        f"{periyot['emoji']} <b>BIST100 — {periyot['ad']}</b>  |  🕐 {now}\n"
        f"📊 AL:{sum(1 for r in sonuclar if r['skor']>=55)}  "
        f"NÖTR:{sum(1 for r in sonuclar if 40<=r['skor']<55)}  "
        f"SAT:{sum(1 for r in sonuclar if r['skor']<40)}  "
        f"({len(sonuclar)} hisse)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if top5_al:
        msg+="🟢 <b>TOP 5 AL</b>\n"
        for i,r in enumerate(top5_al,1):
            msg+=hisse_satiri(r,i)
    else:
        msg+="🟢 TOP 5 AL: Bu periyotta AL sinyali yok\n"

    msg+="━━━━━━━━━━━━━━━━━━━━━━━\n"

    if top5_sat:
        msg+="🔴 <b>TOP 5 SAT</b>\n"
        for i,r in enumerate(top5_sat,1):
            msg+=hisse_satiri(r,i)
    else:
        msg+="🔴 TOP 5 SAT: Bu periyotta SAT sinyali yok\n"

    msg+="⚠️ <i>Yatırım tavsiyesi değildir.</i>"
    tg(msg)

# ── SÜPER SİNYAL — TOP3 AL + TOP3 SAT tek mesaj ──────────────────────────────
def super_rapor(tum_sonuclar):
    now=datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    PE={'1h':'1S','4h':'4S','1d':'1G'}

    hisse_skorlari={}; hisse_fiyat={}; hisse_degisim={}; hisse_ind={}
    for pkey,sonuclar in tum_sonuclar.items():
        for r in sonuclar:
            t=r['ticker']
            if t not in hisse_skorlari: hisse_skorlari[t]={}
            hisse_skorlari[t][pkey]=r['skor']
            hisse_fiyat[t]=r['fiyat']
            hisse_degisim[t]=r['degisim']
            hisse_ind[t]=r['ind']

    super_al=[]; super_sat=[]
    for ticker,skorlar in hisse_skorlari.items():
        ort=sum(skorlar.values())/len(skorlar)
        al_p=[k for k,s in skorlar.items() if s>=55]
        sat_p=[k for k,s in skorlar.items() if s<40]
        if len(al_p)>=SUPER_MIN_PERIOD and ort>=SUPER_AL_SKOR:
            super_al.append({'ticker':ticker,'fiyat':hisse_fiyat[ticker],
                'degisim':hisse_degisim[ticker],'ort':round(ort,1),
                'al_p':al_p,'skorlar':skorlar,'ind':hisse_ind[ticker]})
        if len(sat_p)>=SUPER_MIN_PERIOD and ort<=SUPER_SAT_SKOR:
            super_sat.append({'ticker':ticker,'fiyat':hisse_fiyat[ticker],
                'degisim':hisse_degisim[ticker],'ort':round(ort,1),
                'sat_p':sat_p,'skorlar':skorlar,'ind':hisse_ind[ticker]})

    super_al.sort(key=lambda x:x['ort'],reverse=True)
    super_sat.sort(key=lambda x:x['ort'])
    top3_al=super_al[:3]; top3_sat=super_sat[:3]

    msg=(
        f"🚀 <b>SÜPER SİNYAL RAPORU</b> 🚀\n"
        f"🕐 {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    # TOP 3 AL
    if top3_al:
        msg+=f"⭐ <b>TOP 3 SÜPER AL</b>\n"
        msg+=f"(≥{SUPER_MIN_PERIOD} periyotta AL · Ort.Skor ≥ {SUPER_AL_SKOR})\n"
        for i,r in enumerate(top3_al,1):
            deg=f"+{r['degisim']:.2f}%" if r['degisim']>=0 else f"{r['degisim']:.2f}%"
            pstr=" · ".join([f"{PE[k]}:{r['skorlar'][k]}" for k in ['1h','4h','1d'] if k in r['skorlar']])
            al_str="+".join([PE[k] for k in r['al_p']])
            msg+=(f"{i}. 🟢 <b>{r['ticker']}</b>  {r['fiyat']:.2f}₺  {deg}\n"
                  f"    Ort.Skor:<b>{r['ort']}</b>  AL:{al_str}\n"
                  f"    {pstr}\n")
    else:
        msg+="⭐ <b>TOP 3 SÜPER AL:</b> Kriter karşılayan hisse yok\n"
        msg+=f"(Kriter: ≥{SUPER_MIN_PERIOD} periyotta AL · Ort.Skor ≥ {SUPER_AL_SKOR})\n"

    msg+="━━━━━━━━━━━━━━━━━━━━━━━\n"

    # TOP 3 SAT
    if top3_sat:
        msg+=f"💀 <b>TOP 3 SÜPER SAT</b>\n"
        msg+=f"(≥{SUPER_MIN_PERIOD} periyotta SAT · Ort.Skor ≤ {SUPER_SAT_SKOR})\n"
        for i,r in enumerate(top3_sat,1):
            deg=f"+{r['degisim']:.2f}%" if r['degisim']>=0 else f"{r['degisim']:.2f}%"
            pstr=" · ".join([f"{PE[k]}:{r['skorlar'][k]}" for k in ['1h','4h','1d'] if k in r['skorlar']])
            sat_str="+".join([PE[k] for k in r['sat_p']])
            msg+=(f"{i}. ⛔ <b>{r['ticker']}</b>  {r['fiyat']:.2f}₺  {deg}\n"
                  f"    Ort.Skor:<b>{r['ort']}</b>  SAT:{sat_str}\n"
                  f"    {pstr}\n")
    else:
        msg+="💀 <b>TOP 3 SÜPER SAT:</b> Kriter karşılayan hisse yok\n"
        msg+=f"(Kriter: ≥{SUPER_MIN_PERIOD} periyotta SAT · Ort.Skor ≤ {SUPER_SAT_SKOR})\n"

    msg+="━━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <i>Yatırım tavsiyesi değildir.</i>"
    tg(msg)

# ── ANA TARAMA ────────────────────────────────────────────────────────────────
gun_sinyalleri={}

def saatlik_tarama():
    log.info("⏰ Tarama başlıyor...")
    now=datetime.datetime.now(); saat=now.hour+now.minute/60
    if now.weekday()>=5: log.info("Hafta sonu."); return
    if not(9.5<=saat<=18.6): log.info(f"Borsa kapalı {now.strftime('%H:%M')}."); return

    tum_sonuclar={}
    for periyot in PERIYOTLAR:
        log.info(f"  → {periyot['ad']} ({len(BIST100)} hisse)...")
        sonuclar=[]
        for i,ticker in enumerate(BIST100):
            r=analiz_et(ticker, periyot)
            if r: sonuclar.append(r)
            if (i+1)%5==0: time.sleep(0.5)
        sonuclar.sort(key=lambda x:x['skor'], reverse=True)
        tum_sonuclar[periyot['key']]=sonuclar
        gun_sinyalleri[periyot['key']]=sonuclar
        log.info(f"  ✅ {periyot['ad']}: {len(sonuclar)} hisse")
        periyot_raporu(periyot, sonuclar)
        time.sleep(1)

    # Süper sinyal
    tg("🔄 3 periyot tamamlandı, süper sinyal hesaplanıyor...")
    time.sleep(1)
    super_rapor(tum_sonuclar)
    log.info("✅ Tüm tarama tamamlandı.")

def gunluk_ozet():
    if not gun_sinyalleri: return
    now=datetime.datetime.now().strftime("%d.%m.%Y")
    PE={'1h':'1 Saatlik','4h':'4 Saatlik','1d':'Günlük'}
    msg=f"📋 <b>Günlük Özet — {now}</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n"
    for pkey,sonuclar in gun_sinyalleri.items():
        if not sonuclar: continue
        en_iyi=sorted([r for r in sonuclar if r['skor']>=70],key=lambda x:x['skor'],reverse=True)[:3]
        msg+=f"\n{PE.get(pkey,pkey)} — En iyi 3 AL:\n"
        for r in en_iyi:
            et,em=skor_etiket(r['skor'])
            msg+=f"  {em} {r['ticker']}  Skor:{r['skor']}  {r['fiyat']:.2f}₺\n"
    msg+="\n🕐 Borsa kapandı. İyi akşamlar! 👋\n⚠️ <i>Yatırım tavsiyesi değildir.</i>"
    tg(msg); gun_sinyalleri.clear()

# ── GİRİŞ NOKTASI ─────────────────────────────────────────────────────────────
def main():
    log.info("🚀 BIST100 Bot v3 başlatıldı")
    tg(
        f"🤖 <b>BIST100 Sinyal Botu v3</b>\n"
        f"📂 BIST100 ({len(BIST100)} hisse)\n"
        f"⏱ 1 Saatlik · 4 Saatlik · Günlük\n"
        f"📊 Her periyot: TOP 5 AL + TOP 5 SAT\n"
        f"🚀 Süper AL/SAT: TOP 3\n"
        f"🕐 {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"İlk tarama 10 sn içinde başlıyor..."
    )
    time.sleep(10)
    saatlik_tarama()
    schedule.every().hour.at(":00").do(saatlik_tarama)
    schedule.every().day.at(DAILY_SUMMARY).do(gunluk_ozet)
    log.info(f"📅 Her saat başı + {DAILY_SUMMARY} günlük özet")
    while True: schedule.run_pending(); time.sleep(30)

if __name__=="__main__":
    main()