# Сертификаты Минцифры (Russian Trusted CA)

Образ бэкенда доверяет сертификатам Национального удостоверяющего центра
Минцифры России (Russian Trusted Root CA), которыми подписан TLS-сертификат
`*.tbank.ru` — см. https://developer.tbank.ru/docs/tls-settings (T-Invest API,
«Установка сертификатов Минцифры»).

## Источник (официальный)

- Портальный раздел: https://www.gosuslugi.ru/crt
- Прямые ссылки (gu-st.ru / Госуслуги):
  - https://gu-st.ru/content/downloads/Russian_Trusted_Root_CA.cer
  - https://gu-st.ru/content/downloads/Russian_Trusted_Sub_CA.cer
  - https://gu-st.ru/content/downloads/Russian_Trusted_Sub_CA_2024.cer

## Файлы

| Файл | Сертификат | Серийный номер | SHA-256 |
| --- | --- | --- | --- |
| `russian_trusted_root_ca.pem` | Russian Trusted Root CA | 1000 | `D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31` |
| `russian_trusted_sub_ca.pem` | Russian Trusted Sub CA | 1002 | `BB:BD:E2:10:3E:79:0B:99:9E:C6:2B:D0:3C:F6:25:A5:A2:E7:C3:16:E1:0A:FE:6A:49:0E:ED:EA:D8:B3:FD:9B` |
| `russian_trusted_sub_ca_2024.pem` | Russian Trusted Sub CA (2024) | 1005 | `21:55:78:50:36:C9:00:DB:B5:F1:BB:2A:15:69:C8:0C:55:59:5B:D6:BF:94:86:7A:29:BB:DD:BC:7D:88:A3:F2` |

## Проверка подлинности

- Серийные номера и SHA-1 совпадают с сертификатами Russian Trusted CA в
  хранилище Windows (Cert:\CurrentUser\Root / \CA):
  Root — `8F:F9:15:CC:AB:7B:C1:6F:8C:5C:80:99:D5:3E:0E:11:5B:3A:EC:2F`,
  Sub CA — `33:5D:43:F5:34:51:B7:81:53:5F:F3:88:2D:F7:13:D3:C1:4F:8A:01`,
  Sub CA 2024 — `67:41:AB:02:CF:65:98:C0:96:52:DC:34:D2:DC:09:59:04:E3:2B:52`.
- Живая цепочка `invest-public-api.tbank.ru:443` (openssl s_client -showcerts):
  `*.tbank.ru` → Russian Trusted Sub CA (серийный 1005, он же Sub CA 2024)
  → Russian Trusted Root CA (1000). Файлы выше покрывают эту цепочку.

Формат PEM (уже текстовый, начинается с `-----BEGIN CERTIFICATE-----`),
подходит для `update-ca-certificates` (Debian/Ubuntu).

Проверка TLS **не отключается**: сертификаты добавляются в системное
хранилище образа, `verify=False`/`SSL_CERT_FILE`-обходы не используются.
