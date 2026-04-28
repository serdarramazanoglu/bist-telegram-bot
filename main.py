"""
BIST100 Bollinger Band — 4 Periyot Konfirmasyon Botu
=====================================================
Periyotlar: 30dk · 1 Saat · 2 Saat · 4 Saat
Strateji:
  🟢 AL  → 4 periyotun TAMAMINDA BB alt banda değdi / aşağı kırdı
  🔴 SAT → 4 periyotun TAMAMINDA BB üst banda değdi / yukarı kırdı
Tarama: 15 dakikada bir, 10:00 - 18:00
Değişiklik yoksa mesaj gönderilmez.
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
    {"key": "2h",  "ad": "2S",   "interval": "1h",  "period": "14d"},
    {"key": "4h",  "ad": "4S",   "interval": "1h",  "period": "30d"},
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
        prev  = df.iloc[-2]

        fiyat    = float(son['Close'])
        bb_ust   = float(bb.bollinger_hband().iloc[-1])
        bb_alt   = float(bb.bollinger_lband().iloc[-1])
        bb_mid   = float(bb.bollinger_mavg().iloc[-1])
        son_low  = float(son['Low'])
        son_high = float(son['High'])
        degisim  = (fiyat - float(prev['Close'])) / float(prev['Close']) * 100

        if son_low <= bb_alt or fiyat <= bb_alt:
            return {'sinyal':'AL','fiyat':round(fiyat,2),'bb_ust':round(bb_ust,2),
                    'bb_alt':round(bb_alt,2),'bb_mid':round(bb_mid,2),'degisim':round(degisim,2)}
        elif son_high >= bb_ust or fiyat >= bb_ust:
            return {'sinyal':'SAT','fiyat':round(fiyat,2),'bb_ust':round(bb_ust,2),
                    'bb_alt':round(bb_alt,2),'bb_mid':round(bb_mid,2),'degisim':round(degisim,2)}
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

# ── DURUM ─────────────────────────────────────────────────────────────────────
# Önceki tarama sonuçları — {ticker: 'AL'/'SAT'}
onceki_durum = {}
gun_al  = []
gun_sat = []

# ── ANA TARAMA ────────────────────────────────────────────────────────────────
def tarama():
    global onceki_durum

    now  = datetime.datetime.now()
    saat = now.hour + now.minute / 60
    if now.weekday() >= 5: log.info("Hafta sonu."); return
    if not (10.0 <= saat < 18.0):
        log.info(f"Borsa kapalı ({now.strftime('%H:%M')})."); return

    now_str = now.strftime("%d.%m.%Y %H:%M")
    log.info(f"🔍 Tarama — {now_str}")

    # ── 4 periyot konfirmasyon ──
    yeni_durum = {}  # {ticker: 'AL'/'SAT'} — sadece 4 periyot konfirmasyonu olanlar

    for ticker in BIST100:
        sonuclar = {}
        for pconf in PERIYOTLAR:
            r = bb_sinyal(ticker, pconf)
            sonuclar[pconf['key']] = r

        # 4 periyotun tamamında sinyal olmalı
        if not all(sonuclar[p['key']] is not None for p in PERIYOTLAR):
            continue

        yonler = [sonuclar[p['key']]['sinyal'] for p in PERIYOTLAR]

        if all(y == 'AL'  for y in yonler):
            yeni_durum[ticker] = {'yon': 'AL',  'data': sonuclar}
        elif all(y == 'SAT' for y in yonler):
            yeni_durum[ticker] = {'yon': 'SAT', 'data': sonuclar}

        time.sleep(0.1)

    # ── Değişiklik kontrolü ──
    yeni_al_set  = {t for t,v in yeni_durum.items() if v['yon'] == 'AL'}
    yeni_sat_set = {t for t,v in yeni_durum.items() if v['yon'] == 'SAT'}
    eski_al_set  = {t for t,v in onceki_durum.items() if v['yon'] == 'AL'}
    eski_sat_set = {t for t,v in onceki_durum.items() if v['yon'] == 'SAT'}

    degisiklik = (yeni_al_set != eski_al_set) or (yeni_sat_set != eski_sat_set)

    # Hiç sinyal yoksa ve önceki de yoksa → sessiz
    if not yeni_durum and not onceki_durum:
        log.info("Sinyal yok, değişiklik yok → sessiz.")
        return

    # Değişiklik yoksa → sessiz
    if not degisiklik:
        log.info(f"Değişiklik yok (AL:{len(yeni_al_set)} SAT:{len(yeni_sat_set)}) → mesaj gönderilmedi.")
        return

    # ── Değişiklik var — ne değişti? ──
    yeni_gelen_al  = yeni_al_set  - eski_al_set   # yeni eklenen AL
    yeni_gelen_sat = yeni_sat_set - eski_sat_set   # yeni eklenen SAT
    giden_al       = eski_al_set  - yeni_al_set    # AL listesinden çıkan
    giden_sat      = eski_sat_set - yeni_sat_set   # SAT listesinden çıkan
    al_sat_gecis   = yeni_al_set  & eski_sat_set   # SAT'tan AL'a geçen
    sat_al_gecis   = yeni_sat_set & eski_al_set    # AL'dan SAT'a geçen

    log.info(f"✅ Değişiklik var! AL:{len(yeni_al_set)} SAT:{len(yeni_sat_set)} | "
             f"+AL:{len(yeni_gelen_al)} +SAT:{len(yeni_gelen_sat)} "
             f"-AL:{len(giden_al)} -SAT:{len(giden_sat)}")

    # Gün içi kayıt
    gun_al.extend(list(yeni_al_set))
    gun_sat.extend(list(yeni_sat_set))

    # ── Mesaj ──
    msg = (
        f"🚨 <b>BB Konfirmasyon — Değişiklik Var!</b>\n"
        f"🕐 {now_str}  |  30dk+1S+2S+4S\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    # Mevcut AL listesi
    if yeni_al_set:
        msg += f"🟢 <b>AL ({len(yeni_al_set)} hisse)</b>\n"
        for ticker in sorted(yeni_al_set):
            ref = yeni_durum[ticker]['data']['4h']
            deg = f"+{ref['degisim']:.2f}%" if ref['degisim'] >= 0 else f"{ref['degisim']:.2f}%"
            etiket = " 🆕" if ticker in yeni_gelen_al else (" 🔄" if ticker in al_sat_gecis else "")
            msg += (
                f"  📌 <b>{ticker}</b>{etiket}  {ref['fiyat']:.2f}₺  {deg}\n"
                f"     BB Alt:{ref['bb_alt']:.2f}  Orta:{ref['bb_mid']:.2f}  Üst:{ref['bb_ust']:.2f}\n"
            )

    if yeni_al_set and yeni_sat_set:
        msg += "─────────────────────\n"

    # Mevcut SAT listesi
    if yeni_sat_set:
        msg += f"🔴 <b>SAT ({len(yeni_sat_set)} hisse)</b>\n"
        for ticker in sorted(yeni_sat_set):
            ref = yeni_durum[ticker]['data']['4h']
            deg = f"+{ref['degisim']:.2f}%" if ref['degisim'] >= 0 else f"{ref['degisim']:.2f}%"
            etiket = " 🆕" if ticker in yeni_gelen_sat else (" 🔄" if ticker in sat_al_gecis else "")
            msg += (
                f"  📌 <b>{ticker}</b>{etiket}  {ref['fiyat']:.2f}₺  {deg}\n"
                f"     BB Alt:{ref['bb_alt']:.2f}  Orta:{ref['bb_mid']:.2f}  Üst:{ref['bb_ust']:.2f}\n"
            )

    # Listeden çıkanlar
    cikanlar = []
    for t in giden_al:  cikanlar.append(f"{t}(AL çıktı)")
    for t in giden_sat: cikanlar.append(f"{t}(SAT çıktı)")
    if cikanlar:
        msg += f"─────────────────────\n"
        msg += f"⬜ <b>Listeden çıktı:</b> {', '.join(cikanlar)}\n"

    msg += "━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "<i>🆕 Yeni  🔄 Yön değiştirdi</i>\n"
    msg += "⚠️ <i>Yatırım tavsiyesi değildir.</i>"

    if len(msg) > 4000: msg = msg[:3990] + "\n..."
    tg(msg)

    # Durumu güncelle
    onceki_durum = yeni_durum

# ── GÜNLÜK ÖZET ───────────────────────────────────────────────────────────────
def gunluk_ozet():
    now   = datetime.datetime.now().strftime("%d.%m.%Y")
    al_u  = list(dict.fromkeys(gun_al))
    sat_u = list(dict.fromkeys(gun_sat))

    msg = (
        f"📋 <b>Günlük Özet — {now}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 AL sinyali veren: <b>{len(al_u)} hisse</b>\n"
    )
    if al_u:
        msg += "  " + "  ".join(f"<b>{t}</b>" for t in al_u) + "\n"
    msg += f"\n🔴 SAT sinyali veren: <b>{len(sat_u)} hisse</b>\n"
    if sat_u:
        msg += "  " + "  ".join(f"<b>{t}</b>" for t in sat_u) + "\n"
    msg += "\n🕐 Borsa kapandı. İyi akşamlar! 👋\n⚠️ <i>Yatırım tavsiyesi değildir.</i>"
    tg(msg)
    gun_al.clear(); gun_sat.clear()
    # Gün sonu durumu sıfırla
    global onceki_durum
    onceki_durum = {}

# ── GİRİŞ NOKTASI ─────────────────────────────────────────────────────────────
def main():
    log.info("🚀 BIST100 BB 4 Periyot Konfirmasyon Bot başlatıldı")
    tg(
        f"🤖 <b>BIST BB Konfirmasyon Botu Aktif</b>\n"
        f"📂 BIST100 ({len(BIST100)} hisse)\n"
        f"📊 30dk · 1S · 2S · 4S — 4 periyot konfirmasyon\n"
        f"🟢 AL:  4 periyotta BB alt kırılımı\n"
        f"🔴 SAT: 4 periyotta BB üst kırılımı\n"
        f"🔕 Değişiklik yoksa mesaj gönderilmez\n"
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
