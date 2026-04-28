"""
BIST100 Çoklu Periyot Bollinger Band Sinyal Botu
=================================================
Periyotlar: 30dk · 1 Saatlik · 2 Saatlik · 4 Saatlik
Strateji:
  🔴 SAT → Fiyat BB ALT bandına değdi veya aşağı kırdı
  🟢 AL  → Fiyat BB ÜST bandına değdi veya yukarı kırdı
Tarama: 15 dakikada bir, 10:00 - 18:00 arası
Süper Sinyal: En az 3 periyotta aynı yönde sinyal
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

# Süper sinyal: kaç periyotta aynı yönde sinyal olmalı
SUPER_MIN = 3

PERIYOTLAR = [
    {"key": "30m", "ad": "30 Dakika",  "interval": "30m", "period": "5d",  "emoji": "⏱"},
    {"key": "1h",  "ad": "1 Saat",     "interval": "1h",  "period": "7d",  "emoji": "🕐"},
    {"key": "2h",  "ad": "2 Saat",     "interval": "1h",  "period": "14d", "emoji": "🕑"},  # 1h çekip resample
    {"key": "4h",  "ad": "4 Saat",     "interval": "1h",  "period": "30d", "emoji": "🕓"},  # 1h çekip resample
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

# ── VERİ ÇEKME ────────────────────────────────────────────────────────────────
def resample(df, rule):
    df = df.copy(); df.index = pd.to_datetime(df.index)
    return df.resample(rule).agg({
        'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'
    }).dropna()

def veri_cek(ticker, pconf):
    try:
        df = yf.download(
            ticker + '.IS',
            interval=pconf['interval'],
            period=pconf['period'],
            progress=False,
            auto_adjust=True
        )
        if df.empty or len(df) < BB_WINDOW + 5:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        # 2h ve 4h için 1h veriyi resample et
        if pconf['key'] == '2h':
            df = resample(df, '2h')
        elif pconf['key'] == '4h':
            df = resample(df, '4h')
        if len(df) < BB_WINDOW + 5:
            return None
        return df
    except Exception as e:
        log.debug(f"{ticker}/{pconf['key']} veri hatası: {e}")
        return None

# ── BB ANALİZ ─────────────────────────────────────────────────────────────────
def bb_sinyal(ticker, pconf):
    """
    Bollinger Band kırılım analizi.
    🔴 SAT: Mum dibi alt banda değdi VEYA kapanış alt bandın altında
    🟢 AL:  Mum tepesi üst banda değdi VEYA kapanış üst bandın üstünde
    Dönüş: dict veya None (sinyal yoksa)
    """
    df = veri_cek(ticker, pconf)
    if df is None:
        return None
    try:
        close = df['Close'].squeeze()
        bb = ta.volatility.BollingerBands(close, window=BB_WINDOW, window_dev=BB_DEV)
        df['BB_upper']  = bb.bollinger_hband()
        df['BB_lower']  = bb.bollinger_lband()
        df['BB_middle'] = bb.bollinger_mavg()

        son  = df.iloc[-1]
        prev = df.iloc[-2]

        fiyat    = float(son['Close'])
        bb_ust   = float(son['BB_upper'])
        bb_alt   = float(son['BB_lower'])
        bb_mid   = float(son['BB_middle'])
        son_low  = float(son['Low'])
        son_high = float(son['High'])
        degisim  = (fiyat - float(prev['Close'])) / float(prev['Close']) * 100

        # 🟢 AL: Alt banda değdi veya aşağı kırdı (aşırı satım → geri dönüş)
        if son_low <= bb_alt or fiyat <= bb_alt:
            sapma = round((bb_alt - fiyat) / bb_alt * 100, 3)
            return {
                'ticker':  ticker,
                'sinyal':  'AL',
                'fiyat':   round(fiyat, 2),
                'bb_ust':  round(bb_ust, 2),
                'bb_alt':  round(bb_alt, 2),
                'bb_mid':  round(bb_mid, 2),
                'degisim': round(degisim, 2),
                'sapma':   sapma,
            }

        # 🔴 SAT: Üst banda değdi veya yukarı kırdı (aşırı alım → geri dönüş)
        elif son_high >= bb_ust or fiyat >= bb_ust:
            sapma = round((fiyat - bb_ust) / bb_ust * 100, 3)
            return {
                'ticker':  ticker,
                'sinyal':  'SAT',
                'fiyat':   round(fiyat, 2),
                'bb_ust':  round(bb_ust, 2),
                'bb_alt':  round(bb_alt, 2),
                'bb_mid':  round(bb_mid, 2),
                'degisim': round(degisim, 2),
                'sapma':   sapma,
            }

        return None  # Sinyal yok

    except Exception as e:
        log.debug(f"{ticker}/{pconf['key']} analiz hatası: {e}")
        return None

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

def tg_bol(mesaj):
    """4096 karakter sınırı için bölerek gönder."""
    limit = 4000
    while mesaj:
        if len(mesaj) <= limit:
            tg(mesaj); break
        k = mesaj[:limit].rfind('\n')
        if k == -1: k = limit
        tg(mesaj[:k]); mesaj = mesaj[k:].lstrip('\n')
        time.sleep(0.4)

# ── PERIYOT RAPORU ────────────────────────────────────────────────────────────
def periyot_satiri(r):
    deg = f"+{r['degisim']:.2f}%" if r['degisim'] >= 0 else f"{r['degisim']:.2f}%"
    return (
        f"  • <b>{r['ticker']}</b>  {r['fiyat']:.2f}₺  {deg}\n"
        f"    Alt:{r['bb_alt']:.2f}  Orta:{r['bb_mid']:.2f}  Üst:{r['bb_ust']:.2f}\n"
    )

def periyot_raporu_mesaj(periyot, al_list, sat_list, toplam):
    now = datetime.datetime.now().strftime("%H:%M")
    msg = (
        f"{periyot['emoji']} <b>{periyot['ad']}</b>  🕐 {now}\n"
        f"🟢 AL: {len(al_list)}  🔴 SAT: {len(sat_list)}  ({toplam} hisse tarandı)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if al_list:
        msg += f"🟢 <b>AL — BB Alt Kırılım</b>\n"
        msg += "<i>Fiyat alt banda değdi / aşağı kırdı → Geri dönüş beklenir</i>\n"
        for r in al_list:
            msg += periyot_satiri(r)
    if sat_list:
        if al_list: msg += "─────────────────────\n"
        msg += f"🔴 <b>SAT — BB Üst Kırılım</b>\n"
        msg += "<i>Fiyat üst banda değdi / yukarı kırdı → Geri dönüş beklenir</i>\n"
        for r in sat_list:
            msg += periyot_satiri(r)
    if not al_list and not sat_list:
        msg += "Bu periyotta BB kırılımı yok.\n"
    msg += "⚠️ <i>Yatırım tavsiyesi değildir.</i>"
    return msg

# ── SÜPER SİNYAL ──────────────────────────────────────────────────────────────
def super_sinyal_raporu(tum_sinyaller, now_str):
    """
    tum_sinyaller = {'30m': {ticker: 'AL'/'SAT'}, '1h': {...}, ...}
    En az SUPER_MIN periyotta aynı yönde sinyal → SÜPER AL / SÜPER SAT
    """
    hisse_yonleri = {}  # {ticker: {'AL': [periodlar], 'SAT': [periodlar]}}

    for pkey, sinyaller in tum_sinyaller.items():
        for ticker, yon in sinyaller.items():
            if ticker not in hisse_yonleri:
                hisse_yonleri[ticker] = {'AL': [], 'SAT': []}
            hisse_yonleri[ticker][yon].append(pkey)

    PERIOD_AD = {'30m':'30dk','1h':'1S','2h':'2S','4h':'4S'}

    super_al  = [(t, v['AL'])  for t,v in hisse_yonleri.items() if len(v['AL'])  >= SUPER_MIN]
    super_sat = [(t, v['SAT']) for t,v in hisse_yonleri.items() if len(v['SAT']) >= SUPER_MIN]

    if not super_al and not super_sat:
        return  # Süper sinyal yoksa mesaj gönderme

    msg = (
        f"🚨 <b>SÜPER SİNYAL ALARMI</b> 🚨\n"
        f"🕐 {now_str}  |  Kriter: {SUPER_MIN}+ periyotta aynı yön\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if super_al:
        msg += f"⭐ <b>SÜPER AL ({len(super_al)} hisse)</b>\n"
        msg += "<i>BB Alt bandı kırılımı — çoklu periyot</i>\n"
        for ticker, periodlar in sorted(super_al, key=lambda x: len(x[1]), reverse=True):
            pstr = " + ".join([PERIOD_AD.get(p,p) for p in periodlar])
            msg += f"  🟢 <b>{ticker}</b>  [{pstr}]\n"

    if super_al and super_sat:
        msg += "━━━━━━━━━━━━━━━━━━━━━━━\n"

    if super_sat:
        msg += f"💀 <b>SÜPER SAT ({len(super_sat)} hisse)</b>\n"
        msg += "<i>BB Üst bandı kırılımı — çoklu periyot</i>\n"
        for ticker, periodlar in sorted(super_sat, key=lambda x: len(x[1]), reverse=True):
            pstr = " + ".join([PERIOD_AD.get(p,p) for p in periodlar])
            msg += f"  🔴 <b>{ticker}</b>  [{pstr}]\n"

    msg += "━━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <i>Yatırım tavsiyesi değildir.</i>"
    tg(msg)

# ── ANA TARAMA ────────────────────────────────────────────────────────────────
gun_al  = []
gun_sat = []

def tarama():
    now  = datetime.datetime.now()
    saat = now.hour + now.minute / 60

    if now.weekday() >= 5:
        log.info("Hafta sonu."); return
    if not (10.0 <= saat < 18.0):
        log.info(f"Borsa kapalı ({now.strftime('%H:%M')})."); return

    now_str = now.strftime("%d.%m.%Y %H:%M")
    log.info(f"🔍 BB taraması — {now_str} ({len(BIST100)} hisse × 4 periyot)")

    tum_sinyaller = {}  # {pkey: {ticker: 'AL'/'SAT'}}

    for periyot in PERIYOTLAR:
        al_list  = []
        sat_list = []
        sinyal_map = {}

        for i, ticker in enumerate(BIST100):
            r = bb_sinyal(ticker, periyot)
            if r:
                if r['sinyal'] == 'AL':
                    al_list.append(r)
                    sinyal_map[ticker] = 'AL'
                elif r['sinyal'] == 'SAT':
                    sat_list.append(r)
                    sinyal_map[ticker] = 'SAT'
            if (i + 1) % 10 == 0:
                time.sleep(0.3)

        # Sapma büyüklüğüne göre sırala
        al_list.sort(key=lambda x: x['sapma'], reverse=True)
        sat_list.sort(key=lambda x: x['sapma'], reverse=True)

        tum_sinyaller[periyot['key']] = sinyal_map

        # Gün içi kayıt
        gun_al.extend([r['ticker'] for r in al_list])
        gun_sat.extend([r['ticker'] for r in sat_list])

        log.info(f"  {periyot['ad']}: AL:{len(al_list)} SAT:{len(sat_list)}")

        # Periyot raporunu gönder (sinyal varsa)
        if al_list or sat_list:
            msg = periyot_raporu_mesaj(periyot, al_list, sat_list, len(BIST100))
            tg_bol(msg)
            time.sleep(0.5)

    # Tüm periyotlar bitti → Süper sinyal kontrolü
    super_sinyal_raporu(tum_sinyaller, now_str)
    log.info("✅ Tarama tamamlandı.")

# ── GÜNLÜK ÖZET ───────────────────────────────────────────────────────────────
def gunluk_ozet():
    now = datetime.datetime.now().strftime("%d.%m.%Y")
    al_u  = list(dict.fromkeys(gun_al))
    sat_u = list(dict.fromkeys(gun_sat))

    msg = (
        f"📋 <b>Günlük BB Özet — {now}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Gün içi AL sinyali: <b>{len(al_u)} hisse</b>\n"
    )
    if al_u:
        msg += "  " + "  ".join(f"<b>{t}</b>" for t in al_u) + "\n"

    msg += f"\n🔴 Gün içi SAT sinyali: <b>{len(sat_u)} hisse</b>\n"
    if sat_u:
        msg += "  " + "  ".join(f"<b>{t}</b>" for t in sat_u) + "\n"

    msg += "\n🕐 Borsa kapandı. İyi akşamlar! 👋\n⚠️ <i>Yatırım tavsiyesi değildir.</i>"
    tg(msg)
    gun_al.clear(); gun_sat.clear()

# ── GİRİŞ NOKTASI ─────────────────────────────────────────────────────────────
def main():
    log.info("🚀 BIST100 BB Çoklu Periyot Bot başlatıldı")
    tg(
        f"🤖 <b>BIST BB Sinyal Botu Aktif</b>\n"
        f"📂 BIST100 ({len(BIST100)} hisse)\n"
        f"⏱ Periyotlar: 30dk · 1S · 2S · 4S\n"
        f"🔴 SAT: BB Alt bandı kırılımı\n"
        f"🟢 AL:  BB Üst bandı kırılımı\n"
        f"🚨 Süper Sinyal: {SUPER_MIN}+ periyotta aynı yön\n"
        f"⏰ Tarama: 15 dakikada bir (10:00-18:00)\n"
        f"📋 Günlük özet: {DAILY_SUMMARY}\n"
        f"🕐 {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"İlk tarama 10 sn içinde başlıyor..."
    )
    time.sleep(10)
    tarama()

    # 15 dakikada bir: :00 :15 :30 :45
    schedule.every().hour.at(":00").do(tarama)
    schedule.every().hour.at(":15").do(tarama)
    schedule.every().hour.at(":30").do(tarama)
    schedule.every().hour.at(":45").do(tarama)
    schedule.every().day.at(DAILY_SUMMARY).do(gunluk_ozet)

    log.info(f"📅 15 dakikada bir tarama + {DAILY_SUMMARY} günlük özet")
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()
