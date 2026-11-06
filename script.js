document.addEventListener("DOMContentLoaded", () => {
    const newsContainer = document.getElementById("news-container");

    if (!newsContainer) return;

    fetch("./data/news.json?t=" + new Date().getTime())
        .then(response => response.json())
        .then(data => {
            newsContainer.innerHTML = "";

            if (!data || data.length === 0) {
                newsContainer.innerHTML = "<p>Şu an güncellenmiş haber bulunamadı.</p>";
                return;
            }

            data.forEach(item => {
                const article = document.createElement("article");
                article.className = "news-card";

                let sentimentClass = "sentiment-neutral";
                if (item.sentiment === "BULLISH") sentimentClass = "sentiment-bullish";
                if (item.sentiment === "BEARISH") sentimentClass = "sentiment-bearish";

                article.innerHTML = `
                    <div class="news-header-meta">
                        <span class="news-tag">${item.tag || "MARKET"}</span>
                        <span class="sentiment-badge ${sentimentClass}">${item.sentiment || "NEUTRAL"}</span>
                    </div>
                    
                    <h2 class="news-title">${item.title}</h2>
                    
                    ${item.ai_summary ? `
                        <div class="ai-summary-box">
                            <strong>AI Summary & Outlook:</strong> ${item.ai_summary}
                        </div>
                    ` : ""}

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
            console.error("Hata:", error);
            newsContainer.innerHTML = "<p class='error-text'>Haberler yüklenemedi.</p>";
        });
});
