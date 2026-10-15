"""tester_defs.py - статические определения тестера (аудит #5).

Хосты/домены/тайминги/датаклассы прогонов вынесены из core/tester.py, чтобы
модули проб/процессов/скоринга пользовались ими без циклических импортов.
core.tester ре-экспортирует эти имена (внешние модули исторически импортируют
их оттуда).
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── Уровни хостов ──────────────────────────────────────────────────

# Реалистичные браузерные заголовки - иначе CDN отвечают 403 на bot-подобные
# запросы без User-Agent.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0"
)
BROWSER_HEADERS = [
    "-H", f"User-Agent: {BROWSER_USER_AGENT}",
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "-H", "Accept-Language: en-US,en;q=0.5",
    "-H", "Accept-Encoding: identity",
]

# Домены, которые идут в network_rate - ОБЯЗАНЫ быть покрыты нашими
# hostlist'ами (иначе блок вне контроля пресета исказит скор стратегии).
RATED_HOSTS = [
    "discord.com", "gateway.discord.gg", "cdn.discordapp.com", "updates.discord.com",
    "www.youtube.com", "youtu.be", "i.ytimg.com", "redirector.googlevideo.com",
    "github.com", "raw.githubusercontent.com", "storage.googleapis.com",
]

# QUIC-класс (§15/§17): браузер ходит к этим хостам через QUIC, а тестер -
# «чужим» TLS-клиентом (curl): google-блок (fake+multisplit) рвёт сторонний
# ClientHello → 000 ПРИ работающем браузере. Измеряют «чужого клиента», а не
# стратегию: из network_rate исключены, статус при 000 - QUIC (не BLOCKED).
QUIC_QUIRK_DOMAINS = frozenset({
    "www.youtube.com", "youtu.be", "i.ytimg.com",
    "redirector.googlevideo.com", "storage.googleapis.com",
})

# QUIC-проба (12.10): реальный H3 вместо эвристики. niquests+qh3 - опциональная
# зависимость сборки; без неё - прежний нейтральный статус QUIC. Контракт:
# forced-H3, ассерт http_version==30, свежая сессия, внешний wall-clock дедлайн.
H3_WALL_DEADLINE = 12.0

# Пробуются, но НЕ в network_rate: excluded/непокрытые хосты показывают сырую
# сеть без искажения сравнения стратегий. Чистка 2026-09-11: убраны мёртвые
# (telegram/x/fb/inst/linkedin/whatsapp/fcm/apple - глубокий IP-блок, не лечится
# движком, только шум и +50с к прогону); оставлены живые канарейки и РФ-домены
# (vk/ya/gosuslugi - «сеть жива»).
CONTROL_HOSTS = [
    "www.google.com", "www.gstatic.com",
    "www.cloudflare.com", "cdnjs.cloudflare.com",
    "vk.ru", "ya.ru", "www.gosuslugi.ru",
]

TEST_HOSTS = RATED_HOSTS + CONTROL_HOSTS
CONTROL_DOMAINS = frozenset(CONTROL_HOSTS)


def is_control(domain: str) -> bool:
    """control-хост и его www-алиас (из _expand_with_www) не должны искажать
    network_rate: например www.x.com из control-хоста x.com.

    Публичная (аудит #10): server.py раньше держал инлайн-копии этой логики."""
    base = domain[4:] if domain.startswith("www.") else ""
    return base in CONTROL_DOMAINS

# Тип теста по домену: "http" = curl GET (HTTP-код), "tls" = только handshake.
HOST_TEST: dict[str, str] = {
    "discord.com":              "http",
    "gateway.discord.gg":       "tls",
    "cdn.discordapp.com":       "tls",
    "updates.discord.com":      "tls",
    "www.youtube.com":          "http",
    "youtu.be":                 "http",
    "i.ytimg.com":              "tls",
    "redirector.googlevideo.com": "tls",
    "github.com":               "http",
    "raw.githubusercontent.com": "http",
    "storage.googleapis.com":   "tls",
    "www.google.com":           "http",
    "www.gstatic.com":          "tls",
    "www.cloudflare.com":       "http",
    "cdnjs.cloudflare.com":     "tls",
    "vk.ru":                    "http",
    "ya.ru":                    "http",
    "www.gosuslugi.ru":         "http",
}

# Пинги - только DNS-канарейки (IP): доменные пинги убраны 2026-09-13 -
# ICMP к discord/открытым сервисам всегда блокирован и краснил рабочие хосты.
PING_HOSTS: list[str] = [
    "1.1.1.1", "1.0.0.1",
    "8.8.8.8", "8.8.4.4",
    "9.9.9.9",
]

# Хосты голого теста (без защиты) перед прогоном профилей: если все стратегии
# дают тот же результат - winws2 не перехватывает трафик или DPI экстремальный.
# 2026-09-12: расширен до полного RATED-набора (без www-алиасов) - «Голый тест
# N/4» был слишком узким для same_as_naked; QUIC-класс НЕ включён (их TCP-проба
# в голую всегда 000), www.google.com - канарейка «сеть жива».
NAKED_BASELINE_HOSTS: list[str] = [
    "discord.com", "gateway.discord.gg", "cdn.discordapp.com", "updates.discord.com",
    "github.com", "raw.githubusercontent.com",
    "www.google.com",
]

# Размер тела TCP 16-20 теста: 64 КБ случайных данных - stateful DPI режет поток в середине передачи.
TCP1620_BODY = 64 * 1024

# CDN-хосты теста (опционально, через галочку)
CDN_HOSTS = [
    "hyperion-cs.github.io", "www.mobil.com.se", "cdn.apple-mapkit.com",
    "amplifon.com", "optout.aboutads.info", "cdn.eso.org",
    "go.coveo.com", "justice.gov", "img.wzstats.gg", "esm.sh",
    "antoniotartaglia.it", "status.moow.info", "ui-arts.com",
    "app.thecuriositylibrary.com", "admin.survey54.com", "ssl.p.jwpcdn.com",
    "www.jetblue.com", "buyvm.net", "dmvideo.download",
    "gcore.com", "api.usercentrics.eu", "widgets.reputation.com",
    "king.hr", "mail.server.apaone.com", "nioges.com",
    "5fd8bdae.nip.io", "net4u.de", "elecane.com",
    "store.takeda.com", "sh00065.hostgator.com", "ged.com.sg",
    "www.adwin.fr", "www.emca.be", "www.velivole.fr",
    "askit-app.de", "us.rudder.qntmnet.com",
]
CDN_PROVIDERS: dict[str, str] = {
    "hyperion-cs.github.io": "Self",
    "www.mobil.com.se": "Akamai",
    "cdn.apple-mapkit.com": "Akamai",
    "amplifon.com": "AWS",
    "optout.aboutads.info": "AWS",
    "cdn.eso.org": "CDN77",
    "go.coveo.com": "Cloudflare",
    "justice.gov": "Cloudflare",
    "img.wzstats.gg": "Cloudflare",
    "esm.sh": "Cloudflare",
    "antoniotartaglia.it": "Contabo",
    "status.moow.info": "Contabo",
    "ui-arts.com": "DigitalOcean",
    "app.thecuriositylibrary.com": "DigitalOcean",
    "admin.survey54.com": "DigitalOcean",
    "ssl.p.jwpcdn.com": "Fastly",
    "www.jetblue.com": "Fastly",
    "buyvm.net": "FT/BuyVM",
    "dmvideo.download": "FT/BuyVM",
    "gcore.com": "Gcore",
    "api.usercentrics.eu": "GCP",
    "widgets.reputation.com": "GCP",
    "king.hr": "Hetzner",
    "mail.server.apaone.com": "Hetzner",
    "nioges.com": "Hetzner",
    "5fd8bdae.nip.io": "Hetzner",
    "net4u.de": "Hetzner",
    "elecane.com": "Melbicom",
    "store.takeda.com": "Azure",
    "sh00065.hostgator.com": "Oracle",
    "ged.com.sg": "Oracle",
    "www.adwin.fr": "OVH",
    "www.emca.be": "OVH",
    "www.velivole.fr": "Scaleway",
    "askit-app.de": "Vultr",
    "us.rudder.qntmnet.com": "Vultr",
}

WINDIVERT_CLEANUP_DELAY = 0.5


@dataclass
class TestResult:
    domain: str
    test_type: str
    status: str
    status_code: int = 0
    time_ms: float = 0.0
    error: str = ""


@dataclass
class ProfileTestResult:
    profile_name: str
    results: list[TestResult] = field(default_factory=list)
    ok_count: int = 0
    fail_count: int = 0
    total_time: float = 0.0
    success_rate: float = 0.0
    # Скор стратегии ТОЛЬКО по сетевым тестам (curl/TLS, пинги исключены):
    # пинги меряют голую связность, их включение даёт лживый «partial».
    net_ok_count: int = 0
    net_fail_count: int = 0
    net_total: int = 0
    network_rate: float = 0.0
    ping_ok_count: int = 0
    ping_total: int = 0
    tier: str = "full"
    provider_hop: int = 0      # первый хоп вне локальной сети (TTL-проба)
    provider_ip: str = ""       # IP этого хопа


class _TestAbort(Exception):
    def __init__(self, result=None): self.result = result


@dataclass
class CdnScanVerdict:
    domain: str
    provider: str
    alive: str            # "A" - жив под защитой, "x" - мёртв
    dpi: str              # "DET" - stateful DPI режет, "ok" - не режет, "-" - не проверялось
    naked: str            # "A"/"x"/"-" - живой/мёртвый без защиты (- если не проверялось)
    verdict: str          # fix / ok / break / dead / unknown / hard / covered
    ips: list[str] = field(default_factory=list)   # IP кандидата (для ipset-включений)
    covered: bool = False  # все IP уже внутри ipset-all - наложения нет
    ipset: str = "-"       # A/B: чинит | ломает | - (эффект IP-обхода для хоста)


@dataclass
class CdnScanResult:
    verdicts: list[CdnScanVerdict] = field(default_factory=list)
    naked_done: bool = False
    z2_was: bool = False
    z1_was: bool = False
    error: str = ""
    ipset_mode: bool = False
    protection_touched: bool = False  # скан сам перезапускал защиту - рестор обязателен
    ab_done: bool = False             # A/B-прогон (второй режим ipset) состоялся
    ab_fixed: int = 0                 # хостов, которые чинит IP-обход
    ab_broken: int = 0                # хостов, которые IP-обход ломает
