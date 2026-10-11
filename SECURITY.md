# Güvenlik

Gerçek `.env`, `*.connection.json`, `connection.bin`, Cloudflare/Wrangler oturumu,
müşteri belgeleri ve yerel veritabanı paylaşılmaz. `connection.example.json`
yalnızca şablondur. EXE ve herkese açık kaynak ZIP'i anahtar içermez.

Bağlantı JSON'u, o işletmenin PC bağlantısını devralabilen bir sırdır. Sızarsa
Cloudflare'da iki Worker'ın `GATEWAY_SECRET` değerini aynı yeni rastgele anahtarla
değiştirin; PC'de yeni JSON'u içe aktarın. Eski anahtarı geçersizleştirmeden Git
geçmişini temizlemek yeterli değildir.

Açık bildirimlerde anahtar, belge, gerçek müşteri adı veya tam yerel veri/log
dosyası eklemeyin. GitHub'ın private vulnerability reporting özelliği etkinse
Security sekmesinden özel rapor gönderin.

Uygulama aktarılan dosyaları otomatik açmaz. İçerik doğrulaması antivirüs değildir.
Güncel Windows, belge görüntüleyici ve antivirüs kullanın. Eski Windows 7/Python
çalışma ortamı uyumluluk içindir; güvenlik bakımına sahip yeni bir sistem tercih edilir.
