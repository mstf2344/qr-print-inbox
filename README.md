# QR File Inbox

Telefonunuzdaki dosyaları QR koduyla doğrudan Windows bilgisayarınıza aktarın.
QR'yi açın, dosyalarınızı seçin ve gönderin. Aktarım tamamlandığında gönderim
numarası görünür; dosyalar bilgisayarın **Masaüstü → Gelen Dosyalar → tarih →
gönderim numarası** klasöründe bulunur.

Kendi Cloudflare hesabınızı, adresinizi ve anahtarınızı kullanırsınız. Dosyalar
bulutta kalıcı olarak saklanmaz; Cloudflare üzerinden sınırlı RAM parçalarıyla
bilgisayara iletilir. Hedef PC açık, uyanık, internete bağlı ve kullanıcı oturumu
açık olmalıdır. PC çevrimdışıyken sayfa açılır ancak aktarım tamamlanamaz.

## Özellikler

- QR veya bağlantı ile telefondan dosya gönderme.
- PDF, DOCX, XLSX, PPTX, JPG ve PNG desteği.
- Dosya başına 25 MiB; gönderim başına 100 MiB / 10 dosya.
- Onaylanmış aktarımlara gönderim numarası; aynı dosya adlarına `_2` eki.
- Süresi dolan yarım aktarımların temizlenmesi; tarih klasörlerinin **14 gün
  sonra otomatik silinmesi**. Otomatik yedekleme yapılmaz.
- Kullanıcı hesabına Windows kurulumu ve oturum açılışında otomatik başlangıç.

## Kendi hesabınızla ilk kurulum

Kurulumu hazırlayan bilgisayara Git, Python **3.12+**, uv ve Node.js LTS kurun.
Cloudflare hesabınızda Workers & Pages üzerinden Workers alt alan adınızı açın.

```powershell
git clone https://github.com/mstf2344/qr-print-inbox.git
cd qr-print-inbox
uv sync --locked
npm --prefix worker ci
node worker/node_modules/wrangler/bin/wrangler.js login
```

Aşağıdaki örnek adları ve `HESABIM` alanını kendinize göre değiştirin. Gateway
ve relay adları farklı olmalıdır; `--public-url` sonuna `/desktop` eklemeyin:

```powershell
uv run python -m scripts.setup_public --public-url https://dosya-aktar.HESABIM.workers.dev --worker-name dosya-aktar --relay-name dosya-aktar-relay --deploy
```

Komut iki Worker dağıtır, ikisine aynı rastgele `GATEWAY_SECRET` değerini
kaydeder ve **dist/My-PC.connection.json** dosyasını oluşturur. Kişisel Wrangler
ayarları `*.local.jsonc` dosyalarında tutulur; Git'e eklenmez. `--deploy` olmadan
komut yalnız yerel hazırlık yapar. Aynı adresle tekrar çalıştırmak anahtarı korur.
Cloudflare hesap seçimini ve plan kotalarını dağıtım öncesinde kontrol edin.

Worker relay'i SQLite türü Durable Object bağlaması kullanır; uygulama burada
kalıcı dosya depolama çağrısı yapmaz. Ücretsiz hizmetlerin kota ve süre sınırları
vardır. [Cloudflare belgeleri](https://developers.cloudflare.com/durable-objects/)
ve [gizli değişkenler](https://developers.cloudflare.com/workers/configuration/secrets/).

Windows kurulum dosyasını ve kendi QR'nizi üretin:

```powershell
.\windows\Build-Exe.ps1
uv run python -m windows.verify_package
uv run python -m scripts.make_qr --url https://dosya-aktar.HESABIM.workers.dev --output dist/qr
```

`artifacts` görselleri örnek adrese aittir. Kendi adresiniz için `qr.png` ve
`qr-poster.png` üretin. QR'de public yükleme sayfası, bağlantı JSON'unda ise aynı
adresin `/desktop` yolu kullanılır.

## Windows bilgisayara kurma

1. **QRPrintInbox-Kurulum.exe** ve kendi **My-PC.connection.json** dosyanızı
   hedef bilgisayara taşıyın. Hedefte Python, Node veya uv gerekmez.
2. EXE'yi açıp **Kur** deyin. Başlat menüsündeki **QR File Inbox** panelinden
   **Bağlantı dosyasını seç → My-PC.connection.json → Başlat** adımlarını izleyin.
3. Alternatif: EXE ve JSON ile aynı klasöre `windows/Install-Here.cmd` dosyasını
   koyup çalıştırın; kurulum, bağlantı aktarımı ve başlatmayı birlikte yapar.
4. **Bağlantı hazır** durumunu bekleyin. Telefonun mobil verisiyle küçük bir
   dosya gönderip hedefteki **Gelen Dosyalar** klasörünü kontrol edin.

Paneli kapatmak arka plan aktarım servisini durdurmaz. **Başlat / Durdur**
düğmelerini kullanın. Aynı bağlantıya aynı anda yalnız bir PC bağlanabilir.

EXE ve bazı teknik dosya/dizin adları geriye uyumluluk için `QRPrintInbox`
adını korur; uygulamanın görünen adı **QR File Inbox**'tır.

## Windows uyumluluğu

| Sistem | Durum |
| --- | --- |
| Windows 10 x64 | x86 paket ve backend test edildi; .NET Framework 4.8+ gerekir. |
| Windows 11 x64 | Hedeflenir; fiziksel cihaz kabul testi yapılmadı. |
| Windows 7 SP1 x86 / x64 | Paketli Python 3.8.10 x86 ile uyumluluk hedeflenir; fiziksel cihaz kabul testi yapılmadı. .NET 4.8, TLS 1.2 ve kök sertifika güncellemeleri gerekir. |
| Windows 8.1 / Windows 10 x86 | Test edilmedi. |
| ARM / S modu / XP / Vista / Windows 8 | Doğrulanmış destek yoktur. |

Tüm Windows cihazları için koşulsuz uyumluluk garantisi yoktur. Test edilmemiş
sistemlerde önce küçük bir aktarımla kabul testi yapın. Uygulama kullanıcı
hesabına kurulur; .NET kurulumu yönetici yetkisi isteyebilir. EXE kod imzalı
değildir; yayımlanan SHA256 değeriyle dosyayı kontrol edin.

[Microsoft .NET gereksinimleri](https://learn.microsoft.com/en-us/dotnet/framework/get-started/system-requirements)
· [.NET 4.8 resmi kurulum](https://support.microsoft.com/help/4503548)

## Başka bilgisayara taşıma ve güncelleme

Eski PC'de **Durdur** deyin. Otomatik başlangıcı da kaldırmak için:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Disable-Local.ps1
```

Yeni PC'de aynı EXE + özel JSON ile kurulum yapın. Bulut adresiniz değişmezse QR
kodunuz da değişmez. Eski PC beklenmedik şekilde kapanırsa bağlantı kilidinin
sona ermesi yaklaşık 35 saniye sürebilir.

Yeni PC yeni yerel sayaçla başlar. Önceki dosyaları ve sayaçları da taşımak için
iki PC'de servisi durdurun; **Gelen Dosyalar** ile **veri alanını** birlikte
kopyalayın. Hedefteki mevcut verinin üzerine yazmayın.

- Program: `%LOCALAPPDATA%/Programs/QRPrintInbox`
- Şifreli bağlantı ayarı: `%LOCALAPPDATA%/QRPrintInbox/desktop/connection.bin`
- Veri alanı: `%LOCALAPPDATA%/QRPrintInbox/desktop/data`
- Masaüstü farklı sürücüdeyse veri alanı: `Masaüstü/.QRPrintInbox-data`

`connection.bin` Windows kullanıcı hesabına bağlıdır; başka PC'ye taşımayın,
özel JSON'u yeniden içe aktarın. Masaüstünün sürücüsünü değiştirirken mevcut veri
alanını da taşıyın. OneDrive Masaüstü yönlendirmesi izlenir; ağ paylaşımı ve
çıkarılabilir disk üzerinde test yapılmadı.

Güncelleme: **Durdur → yeni EXE'de Kur → gerekirse JSON'u yeniden seç → Başlat**.
Eski sürümden geçerken JSON'u yeniden seçin; yeni sürüm adresi de şifreli saklar.
Kaldırmak için önce kapatma betiğini çalıştırın, program klasörünü ve Başlat
menüsü kısayolunu kaldırın. Dosyalar/veritabanı ayrıca tutulur.

## Sorun giderme

- **503 / bağlantı bekleniyor:** PC, internet ve servisi kontrol edin. Eski PC'yi
  durdurup 35 saniye bekleyin. Cloudflare kotasını ve iki Worker'ın anahtarını kontrol edin.
- **403:** doğru JSON'u içe aktarın; adres ve anahtarın iki Worker ile eşleştiğini doğrulayın.
- **Başlatma hatası:** .NET 4.8, yazma izinleri ve boş alanı kontrol edin.
  Ayar klasöründeki `status.txt` ve `operation-error.txt` yardımcı olabilir.
- **Dosya reddi:** dosyanın desteklenen gerçek içerik türünde ve boyut sınırında
  olduğunu kontrol edin. İçerik doğrulama antivirüs taraması değildir.

## Geliştirme ve paylaşılabilir paket

```powershell
.\scripts\Test-All.ps1
.\windows\Build-Exe.ps1
.\windows\Test-Connection.ps1
.\windows\Test-Legacy.ps1
uv run python -m windows.verify_package
uv run python -m scripts.package_release
```

Yerel testler varsayılandır. İsteğe bağlı canlı testler kendi adresinizi açıkça
vermenizi gerektirir ve hedef PC'de test dosyaları oluşturur:

```powershell
.\scripts\Test-All.ps1 -Live -BaseUrl https://dosya-aktar.HESABIM.workers.dev
```

`-InterruptService` ayrıca servisi geçici durdurur; yalnız aktif aktarım yokken kullanın.
Kaynak test ortamı Python 3.12+, paketli runtime 3.8 x86'dır. Windows EXE üretimi
.NET Framework derleyicisi gerektirir. Runtime resmi Python arşivinden hash/imza
kontrolüyle, bağımlılıklar hash kilidiyle alınır; üçüncü taraf lisansları korunur.

Paketleme anahtarsız **QRPrintInbox-Public.zip**, Git'in izlediği dosyalardan
**qr-print-inbox-source.zip** ve **SHA256SUMS.txt** üretir. Yeni kaynakları önce
Git'e ekleyin. Yalnız genel EXE, genel ZIP, kaynak ZIP'i ve hash listesini paylaşın.

**Gerçek bağlantı JSON'u, .env, hesap oturumu, yerel veri, özel belgeler ve loglar
public repoya ya da Release'e yüklenmez.** `.gitignore` önceden commit edilmiş
sırları temizlemez; sızan anahtarı iptal edip yenisini üretin. Daha fazlası:
[SECURITY.md](SECURITY.md).

## Lisans

[MIT](LICENSE). Kaynak kodu kendi ihtiyaçlarınıza göre değiştirebilir ve dağıtabilirsiniz.
