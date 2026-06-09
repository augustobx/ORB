document.addEventListener("DOMContentLoaded", () => {
    // Inicializar reloj NY
    updateClock();
    setInterval(updateClock, 1000);
    
    // Polling de logs cada 2 segundos
    fetchLogs();
    setInterval(fetchLogs, 2000);

    // Polling de status en vivo
    fetchLiveStatus();
    setInterval(fetchLiveStatus, 1000);

    // Polling de historial de trades cada 3 segundos
    fetchTradeHistory();
    setInterval(fetchTradeHistory, 3000);

    document.getElementById('clear-logs').addEventListener('click', () => {
        document.getElementById('error-console').innerHTML = '';
    });
});

function updateClock() {
    const now = new Date();
    // Convertir a hora NY
    const nyTime = new Date(now.toLocaleString("en-US", {timeZone: "America/New_York"}));
    const timeString = nyTime.toLocaleTimeString('en-US', { hour12: false });
    document.getElementById('ny-clock').textContent = `${timeString} NY`;
}

async function fetchLogs() {
    try {
        const response = await fetch('/errors.log?t=' + Date.now());
        if (!response.ok) return;

        const text = await response.text();
        if (!text) return;

        const lines = text.split('\n').filter(l => l.trim() !== '');
        
        // Tomamos solo las ultimas 100 lineas para no saturar el DOM
        const recentLines = lines.slice(-100);
        
        const consoleEl = document.getElementById('error-console');
        const isScrolledToBottom = consoleEl.scrollHeight - consoleEl.clientHeight <= consoleEl.scrollTop + 10;
        
        consoleEl.innerHTML = '';

        recentLines.forEach(line => {
            const div = document.createElement('div');
            div.className = 'log-line';
            
            // Parsear color basado en [LEVEL]
            if (line.includes('[ERROR]') || line.includes('[CRITICAL]')) {
                div.innerHTML = `<span class="log-error">${escapeHtml(line)}</span>`;
            } else if (line.includes('[WARNING]')) {
                div.innerHTML = `<span class="log-warning">${escapeHtml(line)}</span>`;
            } else if (line.includes('[INFO]')) {
                div.innerHTML = `<span class="log-info">${escapeHtml(line)}</span>`;
            } else {
                div.textContent = line;
            }
            
            consoleEl.appendChild(div);
        });

        // Autoscroll si ya estaba abajo
        if (isScrolledToBottom) {
            consoleEl.scrollTop = consoleEl.scrollHeight;
        }

    } catch (error) {
        console.error("Error fetching logs:", error);
    }
}

// Utility
function escapeHtml(unsafe) {
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

async function fetchLiveStatus() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');

    try {
        const response = await fetch('/dashboard/data/live_status.json?t=' + Date.now());
        if (!response.ok) throw new Error("Status API not found");

        const data = await response.json();
        
        // Comprobar latencia (si el archivo no se ha actualizado en los ultimos 5 segundos, el bot esta caido)
        const currentSeconds = Date.now() / 1000;
        const diff = currentSeconds - data.timestamp;

        if (diff > 5) {
            dot.className = "dot pulse-red";
            text.textContent = "Bot OFFLINE (No Heartbeat)";
            text.style.color = "#ef4444";
        } else {
            dot.className = "dot pulse-green";
            text.textContent = "System Online";
            text.style.color = "";
        }
        
        document.getElementById('live-vwap-dist').textContent = `${data.vwap_dist} pts`;
        document.getElementById('live-position').textContent = data.position;
        
        const pnlEl = document.getElementById('live-pnl');
        pnlEl.textContent = `$${data.pnl_usd.toFixed(2)}`;
        pnlEl.className = data.pnl_usd >= 0 ? 'metric-value highlight-green' : 'metric-value highlight-red';

    } catch (error) {
        // Silencioso si el bot no esta corriendo aun, pero marcamos como Offline
        dot.className = "dot pulse-red";
        text.textContent = "Bot OFFLINE (Not Running)";
        text.style.color = "#ef4444";
    }
}

async function fetchTradeHistory() {
    try {
        const response = await fetch('/trades_vwap.csv?t=' + Date.now());
        if (!response.ok) return;

        const text = await response.text();
        if (!text) return;

        const lines = text.split('\n').filter(l => l.trim() !== '');
        if (lines.length <= 1) return; // Solo tiene el header

        // Parse CSV
        const parsedTrades = lines.slice(1).map(line => {
            const cols = line.split(',');
            return {
                ticket: cols[0],
                symbol: cols[1],
                type: cols[2],
                lots: parseFloat(cols[3]),
                entryTime: cols[4],
                entryPrice: parseFloat(cols[5]),
                exitTime: cols[6],
                exitPrice: parseFloat(cols[7]),
                pnl: parseFloat(cols[8]),
                roi: parseFloat(cols[9]),
                reason: cols[10],
                balance: parseFloat(cols[11])
            };
        });

        // Deduplicate trades by ticket
        const tradesMap = new Map();
        parsedTrades.forEach(t => {
            if (!tradesMap.has(t.ticket)) {
                tradesMap.set(t.ticket, t);
            } else {
                let existing = tradesMap.get(t.ticket);
                if (!existing.reason.includes(t.reason)) {
                    existing.reason += " / " + t.reason;
                }
                // Keep the later exit time if applicable, or just rely on the existing one
            }
        });

        const trades = Array.from(tradesMap.values());

        const totalTrades = trades.length;
        const winningTrades = trades.filter(t => t.pnl > 0).length;
        const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;
        const totalPnl = trades.reduce((acc, t) => acc + (isNaN(t.pnl) ? 0 : t.pnl), 0);
        const avgRoi = totalTrades > 0 ? trades.reduce((acc, t) => acc + (isNaN(t.roi) ? 0 : t.roi), 0) / totalTrades : 0;

        document.getElementById('hist-total-trades').textContent = totalTrades;
        document.getElementById('hist-win-rate').textContent = `${winRate.toFixed(1)}%`;
        
        const pnlEl = document.getElementById('hist-total-pnl');
        pnlEl.textContent = `$${totalPnl.toFixed(2)}`;
        pnlEl.className = totalPnl >= 0 ? 'highlight-green' : 'highlight-red';

        document.getElementById('hist-avg-roi').textContent = `${avgRoi.toFixed(2)}%`;

        const tbody = document.getElementById('trade-history-body');
        tbody.innerHTML = '';

        // Mostramos del más reciente al más antiguo
        trades.reverse().forEach(t => {
            const tr = document.createElement('tr');
            
            const typeClass = t.type === 'BUY' ? 'type-buy' : 'type-sell';
            const pnlClass = t.pnl >= 0 ? 'highlight-green' : 'highlight-red';
            
            tr.innerHTML = `
                <td><span class="ticket-id">${t.ticket}</span></td>
                <td><span class="symbol-badge">${t.symbol}</span></td>
                <td><span class="badge-type ${typeClass}">${t.type}</span></td>
                <td>${t.lots.toFixed(2)}</td>
                <td><div class="time-cell"><span>${t.entryTime}</span></div></td>
                <td>${t.entryPrice.toFixed(2)}</td>
                <td><div class="time-cell"><span>${t.exitTime}</span></div></td>
                <td>${t.exitPrice.toFixed(2)}</td>
                <td class="${pnlClass} font-bold">$${t.pnl.toFixed(2)}</td>
                <td class="${pnlClass}">${t.roi.toFixed(2)}%</td>
                <td><span class="reason-badge">${t.reason}</span></td>
                <td><span class="balance-cell">$${t.balance.toFixed(2)}</span></td>
            `;
            tbody.appendChild(tr);
        });

    } catch (error) {
        console.error("Error fetching trade history:", error);
    }
}

