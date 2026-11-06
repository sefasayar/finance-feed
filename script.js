document.addEventListener("DOMContentLoaded", () => {
    const newsContainer = document.getElementById("news-container");
    const filterBar = document.getElementById("filter-bar");

    if (!newsContainer) return;

    fetch("./data/news.json?t=" + new Date().getTime())
        .then(response => {
            if (!response.ok) throw new Error("JSON dosyası okunamadı.");
            return response.json();
        })
        .then(data => {
            if (!data || !Array.isArray(data) || data.length === 0) {
                newsContainer.innerHTML = "<p>Şu an güncellenmiş haber bulunamadı.</p>";
                return;
            }
            renderNews(data);
            setupFilters(data);
        })
        .catch(error => {
            console.error("Haber yükleme hatası:", error);
            newsContainer.innerHTML = "<p class='error-text'>Haberler yüklenirken bir sorun oluştu.</p>";
        });

    function renderNews(items) {
        newsContainer.innerHTML = "";
        items.forEach(item => {
            const article = document.createElement("article");
            article.className = "news-card";

            const tag = item.tag || "MARKET";
            const sentiment = item.sentiment || "NEUTRAL";
            const title = item.title || "Financial News Update";
            const aiSummary = item.ai_summary || "";
            const marketImpact = item.market_impact || "Market Steady";
            const content = item.content || "<p>No content available.</p>";
            const originalLink = item.original_link || "#";

            let sentimentClass = "sentiment-neutral";
            if (sentiment === "BULLISH") sentimentClass = "sentiment-bullish";
            if (sentiment === "BEARISH") sentimentClass = "sentiment-bearish";

            article.innerHTML = `
                <div class="news-header-meta">
                    <span class="news-tag">${tag}</span>
                    <span class="sentiment-badge ${sentimentClass}">${sentiment}</span>
                </div>
                
                <h2 class="news-title">${title}</h2>
                
                ${aiSummary ? `
                    <div class="ai-summary-box">
                        <strong>AI Summary & Outlook:</strong> ${aiSummary}
                    </div>
                ` : ""}

                <div class="news-content">
                    ${content}
                </div>
                
                <div class="news-footer">
                    <a href="${originalLink}" target="_blank" rel="noopener noreferrer" class="source-link">
                        Read Original Source &rarr;
                    </a>
                    <span class="market-impact-tag">Impact: ${marketImpact}</span>
                </div>
            `;
            newsContainer.appendChild(article);
        });
    }

    function setupFilters(data) {
        if (!filterBar) return;
        const tags = ["ALL", ...new Set(data.map(item => item.tag || "MARKET"))];
        filterBar.innerHTML = "";
        tags.forEach(tag => {
            const btn = document.createElement("button");
            btn.className = "filter-btn" + (tag === "ALL" ? " active" : "");
            btn.textContent = tag;
            btn.onclick = () => {
                document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                renderNews(tag === "ALL" ? data : data.filter(i => (i.tag || "MARKET") === tag));
            };
            filterBar.appendChild(btn);
        });
    }
});
