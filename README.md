# Majalah Bitcoin ₿
**Berita Bitcoin dalam Bahasa Melayu** — 100% percuma, auto-update setiap 4 jam.

## Cara Ia Berfungsi

```
GitHub Actions (setiap 4 jam — percuma)
  → Ambil berita terkini dari RSS CoinDesk, Cointelegraph, dll (percuma, tiada API key)
  → Hantar ke Gemini 2.0 Flash (percuma, 1,500 req/hari)
  → Gemini tulis 1 artikel ringkasan dalam Bahasa Melayu
  → Simpan ke data/news.json → commit ke repo
  → GitHub Pages hidangkan halaman terkini kepada pelawat
```

## Kos Bulanan: RM 0

| Komponen | Servis | Kos |
|----------|--------|-----|
| Hosting | GitHub Pages | Percuma |
| Cron job | GitHub Actions | Percuma (2,000 min/bulan) |
| AI (tulis artikel) | Gemini 2.0 Flash free tier | Percuma |
| Sumber berita | RSS feeds | Percuma |
| Domain | majalahbitcoin.com (anda dah ada) | — |

---

## Setup — Langkah demi Langkah

### Langkah 1 — Cipta repo di GitHub

1. Pergi ke https://github.com/new
2. Nama repo: `majalahbitcoin`
3. Set ke **Public**
4. Klik **Create repository** (jangan tambah README)

### Langkah 2 — Upload fail projek

Di terminal/command prompt:
```bash
cd majalahbitcoin        # folder yang anda unzip
git init
git add .
git commit -m "🚀 Launch MajalahBitcoin"
git remote add origin https://github.com/YOUR_USERNAME/majalahbitcoin.git
git branch -M main
git push -u origin main
```

### Langkah 3 — Dapatkan Gemini API Key (percuma)

1. Pergi ke https://aistudio.google.com
2. Log in dengan Google account
3. Klik **"Get API Key"** → **"Create API key"**
4. Salin key tersebut

### Langkah 4 — Simpan API Key di GitHub

1. GitHub repo anda → **Settings**
2. **Secrets and variables** → **Actions**
3. Klik **"New repository secret"**
4. Name: `GEMINI_API_KEY`
5. Value: key Gemini anda
6. Klik **Add secret**

### Langkah 5 — Aktifkan GitHub Pages

1. GitHub repo → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / folder: `(root)`
4. Klik **Save**

Selepas ~2 minit, site anda hidup di:
`https://YOUR_USERNAME.github.io/majalahbitcoin`

### Langkah 6 — Update username dalam index.html

Buka `index.html`, cari baris ~340:
```javascript
const REPO_OWNER = 'YOUR_GITHUB_USERNAME'; // ← tukar ini
const REPO_NAME  = 'majalahbitcoin';
```
Tukar kepada username GitHub anda, commit dan push.

### Langkah 7 — Uji imbasan pertama

1. GitHub repo → tab **Actions**
2. Klik **"Bitcoin News Scan (Every 4 Hours)"**
3. Klik **"Run workflow"** → **"Run workflow"**
4. Tunggu ~60 saat
5. Muat semula site → berita muncul! ✓

---

## Tuju Domain majalahbitcoin.com ke GitHub Pages

### Di GitHub:
1. Repo → **Settings** → **Pages**
2. Di bahagian **"Custom domain"**, taip: `majalahbitcoin.com`
3. Klik **Save**
4. Tandakan ✅ **"Enforce HTTPS"**

### Di Hostinger (DNS settings):
Log masuk Hostinger → Domain → majalahbitcoin.com → **DNS Zone**

Tambah rekod-rekod ini:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | @ | 185.199.108.153 | 3600 |
| A | @ | 185.199.109.153 | 3600 |
| A | @ | 185.199.110.153 | 3600 |
| A | @ | 185.199.111.153 | 3600 |
| CNAME | www | YOUR_USERNAME.github.io | 3600 |

Tunggu 10-30 minit untuk DNS merebak. Selepas itu, `majalahbitcoin.com` akan tuju terus ke site GitHub Pages anda, lengkap dengan HTTPS percuma.

---

## Tambah Artikel ke Pustaka

1. Pergi ke site anda → klik **Artikel**
2. Tampal URL artikel (CoinDesk, Bitcoin Magazine, dll)
3. Klik **Terjemah** → ikut arahan (buka GitHub Actions)
4. Dalam GitHub Actions → **"Translate Article"** → **Run workflow** → tampal URL → Run
5. Tunggu ~90 saat → artikel muncul dalam Pustaka

---

## Struktur Fail

```
majalahbitcoin/
├── index.html                     ← Seluruh frontend
├── CNAME                          ← Custom domain config
├── data/
│   ├── news.json                  ← Auto-dikemas kini setiap 4 jam
│   └── articles.json              ← Artikel terjemahan manual
├── scripts/
│   ├── scan_news.py               ← Logik imbasan + tulis artikel BM
│   └── translate_article.py      ← Terjemah artikel penuh ke BM
└── .github/workflows/
    ├── scan.yml                   ← Cron setiap 4 jam
    └── translate.yml              ← Manual trigger untuk artikel
```

---

## Tukar Kekerapan Imbasan

Edit `.github/workflows/scan.yml`:
```yaml
# Setiap 4 jam (lalai):
- cron: '0 0,4,8,12,16,20 * * *'

# Setiap 6 jam:
- cron: '0 0,6,12,18 * * *'

# Dua kali sehari (pagi & malam MYT):
- cron: '0 1,13 * * *'
```
