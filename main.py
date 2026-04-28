"""
BIST100 Bollinger Band — 4 Periyot Konfirmasyon Botu
=====================================================
Periyotlar: 30dk · 1 Saat · 2 Saat · 4 Saat
Strateji:
  🟢 AL  → 4 periyotun TAMAMINDA BB alt banda değdi / aşağı kırdı
  🔴 SAT → 4 periyotun TAMAMINDA BB üst banda değdi / yukarı kırdı
Tarama: 15 dakikada bir, 10:00 - 18:00
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
DAILY_SUMMARY = "18:30"
BB_WINDOW = 20
BB_DEV    = 2

PERIYOTLAR = [
    {"key": "30m", "ad": "30dk", "interval": "30m", "period": "5d"},
    {"key": "1h",  "ad": "1S",   "interval": "1h",  "period": "7d"},
    {"key": "2h",  "ad": "2S",   "interval": "1h",  "period": "14d"},  # resample
    {"key": "4h",  "ad": "4S",   "interval": "1h",  "period": "30d"},  # resample
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
    'EDIP','EMKEL','ESCOM','FLAP','GSDHO','HLGYO','HTTBT','HUNER','IDGYO',
]))

# ── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bist_bb.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("BIST_BB")

# ── VERİ & ANALİZ ─────────────────────────────────────────────────────────────
def resample(df, rule):
    df = df.copy(); df.index = pd.to_datetime(df.index)
    return df.resample(rule).agg({
        'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'
    }).dropna()

def bb_sinyal(ticker, pconf):
    """
    Tek periyot için BB sinyali döndürür.
    'AL' | 'SAT' | None
    """
    try:
        df = yf.download(
            ticker + '.IS',
            interval=pconf['interval'],
            period=pconf['period'],
            progress=False, auto_adjust=True
        )
        if df.empty or len(df) < BB_WINDOW + 5: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if pconf['key'] == '2h': df = resample(df, '2h')
        elif pconf['key'] == '4h': df = resample(df, '4h')
        if len(df) < BB_WINDOW + 5: return None

        close = df['Close'].squeeze()
        bb    = ta.volatility.BollingerBands(close, window=BB_WINDOW, window_dev=BB_DEV)
        son   = df.iloc[-1]

        fiyat    = float(son['Close'])
        bb_ust   = float(bb.bollinger_hband().iloc[-1])
        bb_alt   = float(bb.bollinger_lband().iloc[-1])
        bb_mid   = float(bb.bollinger_mavg().iloc[-1])
        son_low  = float(son['Low'])
        son_high = float(son['High'])
        prev     = df.iloc[-2]
        degisim  = (fiyat - float(prev['Close'])) / float(prev['Close']) * 100

        # AL: alt banda değdi veya aşağı kırdı
        if son_low <= bb_alt or fiyat <= bb_alt:
            return {
                'sinyal': 'AL', 'fiyat': round(fiyat, 2),
                'bb_ust': round(bb_ust, 2), 'bb_alt': round(bb_alt, 2),
                'bb_mid': round(bb_mid, 2), 'degisim': round(degisim, 2),
            }
        # SAT: üst banda değdi veya yukarı kırdı
        elif son_high >= bb_ust or fiyat >= bb_ust:
            return {
                'sinyal': 'SAT', 'fiyat': round(fiyat, 2),
                'bb_ust': round(bb_ust, 2), 'bb_alt': round(bb_alt, 2),
                'bb_mid': round(bb_mid, 2), 'degisim': round(degisim, 2),
            }
        return None

    except Exception as e:
        log.debug(f"{ticker}/{pconf['key']}: {e}"); return None

# ── TELEGRAM ──────────────────────────────────────────────────────────────────
def tg(mesaj):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": mesaj,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
        if r.status_code == 200: return True
        log.error(f"TG {r.status_code}: {r.text}"); return False
    except Exception as e:
        log.error(f"TG hata: {e}"); return False

# ── ANA TARAMA ────────────────────────────────────────────────────────────────
gun_al  = []
gun_sat = []

def tarama():
    now  = datetime.datetime.now()
    saat = now.hour + now.minute / 60
    if now.weekday() >= 5: log.info("Hafta sonu."); return
    if not (10.0 <= saat < 18.0):
        log.info(f"Borsa kapalı ({now.strftime('%H:%M')})."); return

    now_str = now.strftime("%d.%m.%Y %H:%M")
    log.info(f"🔍 Tarama başlıyor — {now_str}")

    konfirm_al  = []  # 4 periyotun tamamında AL
    konfirm_sat = []  # 4 periyotun tamamında SAT

    for ticker in BIST100:
        sonuclar = {}
        for pconf in PERIYOTLAR:
            r = bb_sinyal(ticker, pconf)
            sonuclar[pconf['key']] = r

        # 4 periyotun tamamında sinyal var mı?
        hepsi_var = all(sonuclar[p['key']] is not None for p in PERIYOTLAR)
        if not hepsi_var:
            continue

        # 4 periyotun tamamında AYNI yön mü?
        yonler = [sonuclar[p['key']]['sinyal'] for p in PERIYOTLAR]
        if all(y == 'AL' for y in yonler):
            # Son periyotun (4h) bb değerlerini al — en güvenilir
            ref = sonuclar['4h']
            konfirm_al.append({
                'ticker':  ticker,
                'fiyat':   ref['fiyat'],
                'degisim': ref['degisim'],
                'bb_ust':  ref['bb_ust'],
                'bb_alt':  ref['bb_alt'],
                'bb_mid':  ref['bb_mid'],
                'detay':   {p['key']: sonuclar[p['key']] for p in PERIYOTLAR},
            })
        elif all(y == 'SAT' for y in yonler):
            ref = sonuclar['4h']
            konfirm_sat.append({
                'ticker':  ticker,
                'fiyat':   ref['fiyat'],
                'degisim': ref['degisim'],
                'bb_ust':  ref['bb_ust'],
                'bb_alt':  ref['bb_alt'],
                'bb_mid':  ref['bb_mid'],
                'detay':   {p['key']: sonuclar[p['key']] for p in PERIYOTLAR},
            })

        time.sleep(0.1)

    log.info(f"✅ Tamamlandı: 🟢 AL:{len(konfirm_al)}  🔴 SAT:{len(konfirm_sat)}")

    # Sinyal yoksa sessiz kal
    if not konfirm_al and not konfirm_sat:
        log.info("Bu taramada 4 periyot konfirmasyon sinyali yok.")
        return

    # Gün içi kayıt
    gun_al.extend([r['ticker'] for r in konfirm_al])
    gun_sat.extend([r['ticker'] for r in konfirm_sat])

    # ── Mesaj ──
    msg = (
        f"🚨 <b>BB 4 Periyot Konfirmasyon Sinyali</b>\n"
        f"🕐 {now_str}\n"
        f"📊 30dk + 1S + 2S + 4S — 4 periyotun TAMAMINDA sinyal\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if konfirm_al:
        msg += f"🟢 <b>AL — {len(konfirm_al)} Hisse</b>\n"
        msg += "<i>Alt banda değdi / aşağı kırdı (tüm periyotlar)</i>\n"
        for r in konfirm_al:
            deg = f"+{r['degisim']:.2f}%" if r['degisim'] >= 0 else f"{r['degisim']:.2f}%"
            # Her periyotun fiyatını göster
            per_str = "  ".join([
                f"{p['key'].upper()}:{r['detay'][p['key']]['fiyat']:.2f}"
                for p in PERIYOTLAR
            ])
            msg += (
                f"\n  📌 <b>{r['ticker']}</b>  {r['fiyat']:.2f}₺  {deg}\n"
                f"  BB→  Alt:{r['bb_alt']:.2f}  Orta:{r['bb_mid']:.2f}  Üst:{r['bb_ust']:.2f}\n"
                f"  {per_str}\n"
            )

    if konfirm_al and konfirm_sat:
        msg += "━━━━━━━━━━━━━━━━━━━━━━━\n"

    if konfirm_sat:
        msg += f"🔴 <b>SAT — {len(konfirm_sat)} Hisse</b>\n"
        msg += "<i>Üst banda değdi / yukarı kırdı (tüm periyotlar)</i>\n"
        for r in konfirm_sat:
            deg = f"+{r['degisim']:.2f}%" if r['degisim'] >= 0 else f"{r['degisim']:.2f}%"
            per_str = "  ".join([
                f"{p['key'].upper()}:{r['detay'][p['key']]['fiyat']:.2f}"
                for p in PERIYOTLAR
            ])
            msg += (
                f"\n  📌 <b>{r['ticker']}</b>  {r['fiyat']:.2f}₺  {deg}\n"
                f"  BB→  Alt:{r['bb_alt']:.2f}  Orta:{r['bb_mid']:.2f}  Üst:{r['bb_ust']:.2f}\n"
                f"  {per_str}\n"
            )

    msg += "\n━━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <i>Yatırım tavsiyesi değildir.</i>"

    if len(msg) > 4000: msg = msg[:3990] + "\n..."
    tg(msg)

# ── GÜNLÜK ÖZET ───────────────────────────────────────────────────────────────
def gunluk_ozet():
    now   = datetime.datetime.now().strftime("%d.%m.%Y")
    al_u  = list(dict.fromkeys(gun_al))
    sat_u = list(dict.fromkeys(gun_sat))

    msg = (
        f"📋 <b>Günlük Özet — {now}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 AL konfirmasyon: <b>{len(al_u)} hisse</b>\n"
    )
    if al_u:
        msg += "  " + "  ".join(f"<b>{t}</b>" for t in al_u) + "\n"
    msg += f"\n🔴 SAT konfirmasyon: <b>{len(sat_u)} hisse</b>\n"
    if sat_u:
        msg += "  " + "  ".join(f"<b>{t}</b>" for t in sat_u) + "\n"
    msg += "\n🕐 Borsa kapandı. İyi akşamlar! 👋\n⚠️ <i>Yatırım tavsiyesi değildir.</i>"
    tg(msg)
    gun_al.clear(); gun_sat.clear()

# ── GİRİŞ NOKTASI ─────────────────────────────────────────────────────────────
def main():
    log.info("🚀 BIST100 BB 4 Periyot Konfirmasyon Bot başlatıldı")
    tg(
        f"🤖 <b>BIST BB Konfirmasyon Botu Aktif</b>\n"
        f"📂 BIST100 ({len(BIST100)} hisse)\n"
        f"📊 30dk · 1S · 2S · 4S — 4 periyot konfirmasyon\n"
        f"🟢 AL:  4 periyotta BB alt kırılımı\n"
        f"🔴 SAT: 4 periyotta BB üst kırılımı\n"
        f"⏰ Tarama: 15 dakikada bir (10:00-18:00)\n"
        f"📋 Günlük özet: {DAILY_SUMMARY}\n"
        f"🕐 {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"İlk tarama 10 sn içinde başlıyor..."
    )
    time.sleep(10)
    tarama()

    schedule.every().hour.at(":00").do(tarama)
    schedule.every().hour.at(":15").do(tarama)
    schedule.every().hour.at(":30").do(tarama)
    schedule.every().hour.at(":45").do(tarama)
    schedule.every().day.at(DAILY_SUMMARY).do(gunluk_ozet)

    log.info("📅 15 dakikada bir tarama + 18:30 günlük özet")
    while True:
        schedule.run_pending(); time.sleep(30)

if __name__ == "__main__":
    main()
