"""
BIST100 Bollinger Band Sinyal Botu
===================================
Strateji:
  🟢 AL  → Fiyat BB alt bandına değdi veya altına indi (1 saatlik)
  🔴 SAT → Fiyat BB üst bandına değdi veya üstüne çıktı (1 saatlik)

Tarama: 30 dakikada bir, 10:00 - 18:00 arası
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

# BB parametreleri (app.py ile aynı)
BB_WINDOW = 20
BB_DEV    = 2

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

# ── ANALİZ ────────────────────────────────────────────────────────────────────
def bb_analiz(ticker):
    """
    1 saatlik mumlarla Bollinger Band hesapla.
    Dönüş: {'ticker', 'sinyal', 'fiyat', 'bb_ust', 'bb_alt', 'degisim', 'kirilim_pct'}
    sinyal: 'AL' | 'SAT' | None
    """
    try:
        df = yf.download(
            ticker + '.IS',
            interval='1h',
            period='7d',
            progress=False,
            auto_adjust=True
        )
        if df.empty or len(df) < BB_WINDOW + 5:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df['Close'].squeeze()
        high  = df['High'].squeeze()
        low   = df['Low'].squeeze()

        bb = ta.volatility.BollingerBands(close, window=BB_WINDOW, window_dev=BB_DEV)
        df['BB_upper']  = bb.bollinger_hband()
        df['BB_lower']  = bb.bollinger_lband()
        df['BB_middle'] = bb.bollinger_mavg()

        son  = df.iloc[-1]
        prev = df.iloc[-2]

        fiyat   = float(son['Close'])
        bb_ust  = float(son['BB_upper'])
        bb_alt  = float(son['BB_lower'])
        bb_mid  = float(son['BB_middle'])
        prev_close = float(prev['Close'])
        degisim = (fiyat - prev_close) / prev_close * 100

        # Mum low değeri (dip dokunuşu için)
        son_low  = float(son['Low'])
        son_high = float(son['High'])

        sinyal = None

        # 🟢 AL: Mum'un dibi alt banda değdiyse VEYA kapanış alt bandın altındaysa
        if son_low <= bb_alt or fiyat <= bb_alt:
            sinyal = 'AL'
            kirilim_pct = (bb_alt - fiyat) / bb_alt * 100  # ne kadar altında

        # 🔴 SAT: Mum'un tepesi üst banda değdiyse VEYA kapanış üst bandın üstündeyse
        elif son_high >= bb_ust or fiyat >= bb_ust:
            sinyal = 'SAT'
            kirilim_pct = (fiyat - bb_ust) / bb_ust * 100  # ne kadar üstünde

        else:
            return None  # Sinyal yok, listeye ekleme

        return {
            'ticker':       ticker,
            'sinyal':       sinyal,
            'fiyat':        round(fiyat, 2),
            'bb_ust':       round(bb_ust, 2),
            'bb_alt':       round(bb_alt, 2),
            'bb_mid':       round(bb_mid, 2),
            'degisim':      round(degisim, 2),
            'kirilim_pct':  round(abs(kirilim_pct), 3),
        }

    except Exception as e:
        log.debug(f"{ticker}: {e}")
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
        if r.status_code == 200:
            return True
        log.error(f"TG {r.status_code}: {r.text}")
        return False
    except Exception as e:
        log.error(f"TG hata: {e}"); return False

# ── TARAMA ────────────────────────────────────────────────────────────────────
gun_al_sinyalleri  = []
gun_sat_sinyalleri = []

def tarama():
    now  = datetime.datetime.now()
    saat = now.hour + now.minute / 60

    # Hafta sonu kontrolü
    if now.weekday() >= 5:
        log.info("Hafta sonu — tarama yok.")
        return

    # Saat kontrolü: 10:00 - 18:00
    if not (10.0 <= saat < 18.0):
        log.info(f"Borsa kapalı ({now.strftime('%H:%M')}) — tarama yok.")
        return

    log.info(f"🔍 BB taraması başlıyor... ({len(BIST100)} hisse, 1 saatlik)")

    al_sinyaller  = []
    sat_sinyaller = []

    for i, ticker in enumerate(BIST100):
        r = bb_analiz(ticker)
        if r:
            if r['sinyal'] == 'AL':
                al_sinyaller.append(r)
            elif r['sinyal'] == 'SAT':
                sat_sinyaller.append(r)
        if (i + 1) % 10 == 0:
            time.sleep(0.5)

    # Kırılım büyüklüğüne göre sırala (en güçlü sinyal başta)
    al_sinyaller.sort(key=lambda x: x['kirilim_pct'], reverse=True)
    sat_sinyaller.sort(key=lambda x: x['kirilim_pct'], reverse=True)

    # Gün içi listeye ekle
    gun_al_sinyalleri.extend([r['ticker'] for r in al_sinyaller])
    gun_sat_sinyalleri.extend([r['ticker'] for r in sat_sinyaller])

    log.info(f"✅ Tamamlandı: 🟢 AL:{len(al_sinyaller)}  🔴 SAT:{len(sat_sinyaller)}")

    # Hiç sinyal yoksa kısa mesaj
    if not al_sinyaller and not sat_sinyaller:
        tg(
            f"📊 <b>BB Taraması</b>  🕐 {now.strftime('%H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Bu taramada Bollinger Band sinyali üreten hisse bulunamadı."
        )
        return

    # ── Mesaj oluştur ──
    msg = (
        f"📊 <b>Bollinger Band Sinyalleri</b>\n"
        f"🕐 {now.strftime('%d.%m.%Y %H:%M')}  |  ⏱ 1 Saatlik\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if al_sinyaller:
        msg += f"🟢 <b>AL Sinyali ({len(al_sinyaller)} hisse)</b>\n"
        msg += "<i>Fiyat BB Alt Bandına değdi / altına indi</i>\n"
        for r in al_sinyaller:
            deg = f"+{r['degisim']:.2f}%" if r['degisim'] >= 0 else f"{r['degisim']:.2f}%"
            msg += (
                f"  • <b>{r['ticker']}</b>  {r['fiyat']:.2f}₺  {deg}\n"
                f"    BB Alt:{r['bb_alt']:.2f}  Orta:{r['bb_mid']:.2f}  Üst:{r['bb_ust']:.2f}\n"
            )

    if al_sinyaller and sat_sinyaller:
        msg += "━━━━━━━━━━━━━━━━━━━━━━━\n"

    if sat_sinyaller:
        msg += f"🔴 <b>SAT Sinyali ({len(sat_sinyaller)} hisse)</b>\n"
        msg += "<i>Fiyat BB Üst Bandına değdi / üstüne çıktı</i>\n"
        for r in sat_sinyaller:
            deg = f"+{r['degisim']:.2f}%" if r['degisim'] >= 0 else f"{r['degisim']:.2f}%"
            msg += (
                f"  • <b>{r['ticker']}</b>  {r['fiyat']:.2f}₺  {deg}\n"
                f"    BB Alt:{r['bb_alt']:.2f}  Orta:{r['bb_mid']:.2f}  Üst:{r['bb_ust']:.2f}\n"
            )

    msg += "━━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <i>Yatırım tavsiyesi değildir.</i>"

    # 4096 karakter sınırı
    if len(msg) > 4000:
        msg = msg[:3990] + "\n..."

    tg(msg)

# ── GÜNLÜK ÖZET ───────────────────────────────────────────────────────────────
def gunluk_ozet():
    now = datetime.datetime.now().strftime("%d.%m.%Y")
    al_unique  = list(dict.fromkeys(gun_al_sinyalleri))
    sat_unique = list(dict.fromkeys(gun_sat_sinyalleri))

    msg = (
        f"📋 <b>Günlük BB Özet — {now}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Gün içi AL sinyali veren: {len(al_unique)} hisse\n"
    )
    if al_unique:
        msg += "  " + ", ".join(f"<b>{t}</b>" for t in al_unique) + "\n"

    msg += f"\n🔴 Gün içi SAT sinyali veren: {len(sat_unique)} hisse\n"
    if sat_unique:
        msg += "  " + ", ".join(f"<b>{t}</b>" for t in sat_unique) + "\n"

    msg += "\n🕐 Borsa kapandı. İyi akşamlar! 👋\n⚠️ <i>Yatırım tavsiyesi değildir.</i>"
    tg(msg)

    gun_al_sinyalleri.clear()
    gun_sat_sinyalleri.clear()

# ── GİRİŞ NOKTASI ─────────────────────────────────────────────────────────────
def main():
    log.info("🚀 BIST100 Bollinger Band Bot başlatıldı")
    tg(
        f"🤖 <b>BIST BB Sinyal Botu Aktif</b>\n"
        f"📂 BIST100 ({len(BIST100)} hisse)\n"
        f"📊 Strateji: Bollinger Band kırılımı (1 saatlik)\n"
        f"⏱ Tarama: 30 dakikada bir (10:00 - 18:00)\n"
        f"🟢 AL: Fiyat BB Alt bandına değdi / altına indi\n"
        f"🔴 SAT: Fiyat BB Üst bandına değdi / üstüne çıktı\n"
        f"📋 Günlük özet: 18:30\n"
        f"🕐 {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"İlk tarama 10 sn içinde başlıyor..."
    )
    time.sleep(10)
    tarama()

    # Her 30 dakikada bir: :00 ve :30
    schedule.every().hour.at(":00").do(tarama)
    schedule.every().hour.at(":30").do(tarama)
    schedule.every().day.at(DAILY_SUMMARY).do(gunluk_ozet)

    log.info("📅 30 dakikada bir tarama + 18:30 günlük özet")
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()
