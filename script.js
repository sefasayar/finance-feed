document.addEventListener("DOMContentLoaded", () => {
    const newsContainer = document.getElementById("news-container");

    if (!newsContainer) {
        console.error("Hata: news-container öğesi HTML içerisinde bulunamadı.");
        return;
    }

    // Tarayıcı önbelleğini (cache) kırmak için istek sonuna dinamik timestamp eklenir
    fetch("./data/news.json?t=" + new Date().getTime())
        .then(response => {
            if (!response.ok) {
                throw new Error("Veri dosyası yüklenemedi: " + response.statusText);
            }
            return response.json();
        })
        .then(data => {
            newsContainer.innerHTML = ""; // Yükleniyor yazısını temizle

            if (!data || data.length === 0) {
                newsContainer.innerHTML = "<p>Şu an güncellenmiş haber bulunamadı. Otomasyon bir sonraki döngüde haberleri ekleyecektir.</p>";
                return;
            }

            // JSON içerisindeki her bir haberi DOM kartı olarak ekle
            data.forEach(item => {
                const article = document.createElement("article");
                article.className = "news-card";

                article.innerHTML = `
                    <h2 class="news-title">${item.title}</h2>
                    <div class="news-content">
                        ${item.content}
                    </div>
                    <div class="news-footer">
                        <a href="${item.original_link}" target="_blank" rel="noopener noreferrer" class="source-link">
                            Read Original Source &rarr;
                        </a>
                    </div>
                `;

                newsContainer.appendChild(article);
            });
        })
        .catch(error => {
            console.error("Haber alma hatası:", error);
            newsContainer.innerHTML = "<p class='error-text'>Haberler yüklenirken bir sorun oluştu.</p>";
        });
});
